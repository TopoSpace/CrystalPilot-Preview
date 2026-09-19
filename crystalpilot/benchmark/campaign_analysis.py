"""Mine campaign log bundles for what went wrong and where.

A grade says whether a delivery was good. It never says whether the agent
spent forty minutes retrying one tool, changed approach because of a
misleading error message, or read a file it should not have. Those live in
the codex rollout, which records the agent's private reasoning, every tool
call with its full arguments, every result, and every shell command.

Eight things get extracted, chosen because each corresponds to a distinct
thing we could FIX:

  tool error rates      a tool the agent cannot call correctly is a schema
                        or a message problem, not an agent problem.
  schema errors         calls the MCP layer rejected BEFORE the tool ran
                        ("Input validation error: 'a' is a required
                        property"). The tool never saw them, so it can
                        report nothing about them; they are pure
                        call-surface defects and the sharpest available
                        answer to "which tools are hard to call".
  spin (repeat calls)   the same call with the same arguments, twice, is
                        the agent failing to learn from a result - usually
                        because the result did not say what changed.
  polling               the same call with the same arguments, on a
                        DETACHED JOB, is the documented way to wait: the
                        tool's own `next` field says "poll
                        run_shelxt(job_status='job_...') again in 60-120
                        s". Counting that as spin punished the one
                        behaviour the tool contract asks for, so polls are
                        separated out and reported as polls per job plus
                        the wall clock they cover.
  argument churn        the same tool with slightly different arguments,
                        repeatedly, is the agent guessing at a schema.
  shell hazards         known-bad Windows idioms. Not hypothetical: r21
                        made 50 `Get-Content` calls, none with -Encoding,
                        which is how mojibake enters a transcript.
  abandoned tools       from the MCP server's own log, not the rollout:
                        a tool still computing when the server lost its
                        client. The rollout cannot show this - it holds
                        the invocation and no result, because no result
                        was ever produced.
  pivots                the agent abandoning an approach, linked back to
                        the tool error that preceded it. This is the r25
                        shape: a bare "shelxt timed out" made the agent
                        conclude SHELXT could not handle the cell and fall
                        back to charge flipping, when in fact phasing had
                        already succeeded and only the space-group search
                        was killed.

Plus a leakage audit, which is a gate rather than a metric. The agent runs
under codex's workspace-write sandbox: writes are confined, READS ARE NOT.
So a blind case cannot be prevented from reading mentor-side answers, only
detected - and a benchmark that cannot detect it is not blind, it is just
untested. Any case that touched a mentor path outside its own staging
directory is reported separately and excluded from the outcome table.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[2]

#: Windows shell idioms that have each produced a real failure in a past
#: campaign. Kept as (label, pattern, why) so the report can say what the
#: consequence was rather than just flagging a string.
SHELL_HAZARDS: list[tuple[str, re.Pattern[str], str]] = [
    ("get-content-no-encoding",
     re.compile(r"Get-Content(?!.*-Encoding)", re.I),
     "PowerShell 5.1 reads BOM-less UTF-8 as cp936; this is how mojibake "
     "enters a transcript (r21: 50 calls, 0 with -Encoding)"),
    ("multiline-python-c",
     re.compile(r"python(?:\.exe)?\s+-c\s+[\"'][^\"']*\n"),
     "a multi-line `python -c` is split by the shell shim on this host and "
     "fails with IndentationError; use a temp .py file"),
    ("taskkill-by-name",
     re.compile(r"taskkill[^\n]*/(?:IM|im)\s", re.I),
     "killing by image name can hit the user's own interpreters; the "
     "project rule is to verify the parent chain first"),
    ("rmdir-recursive-outside-project",
     re.compile(r"(?:Remove-Item[^\n]*-Recurse|rmdir\s+/s)", re.I),
     "recursive delete; check the target was inside the project"),
]

#: reasoning-summary phrases that mark a change of approach. English only:
#: the rollout's summary_text is emitted in English regardless of the
#: brief's language, which is convenient here and worth not forgetting.
PIVOT_MARKERS = re.compile(
    r"\b(fall(?:ing)? back|instead(?:,| of)|give up|giving up|abandon|"
    r"another approach|different approach|switch to|pivot|"
    r"doesn't work|didn't work|not working|failed again|"
    r"timed out|timeout|workaround|"
    # "unavailable" earned its place: r25's agent wrote "the unavailable
    # SHELXT" after two timeouts and moved to charge flipping. SHELXT was
    # not unavailable - it had already phased the structure and was killed
    # during the space-group search. A vocabulary that missed that word
    # missed the most consequential pivot in the campaign.
    r"unavailable|not available|can(?:no|')t use|unable to use|"
    r"no longer viable|rule out)\b", re.I)

#: argument names that mark a call as "ask a detached job how it is
#: doing" rather than "do something". A long tool (run_shelxt,
#: run_shelxl, solve_charge_flipping) returns a job id from its
#: detach=true call and then tells the agent, in the result itself, to
#: poll `<same tool>(job_status='<job>')` every 60-120 s. Same tool, same
#: arguments, many times over - identical in shape to spin and the exact
#: opposite in meaning.
POLL_ARG_KEYS: tuple[str, ...] = ("job_status",)

#: what the MCP layer answers when the arguments fail the tool's JSON
#: schema. The call is rejected before the tool runs, so the envelope is
#: `Ok` and its text is NOT json - which is why a miner that only reads
#: `{"ok": false}` bodies never saw these at all.
SCHEMA_ERROR_RE = re.compile(r"input validation error\s*:?\s*", re.I)

#: jsonschema phrasings, in the order they name the offending parameter.
#: The first two carry the parameter name; the rest carry the offending
#: VALUE, and the name is recovered by looking that value up in the
#: arguments the agent actually sent.
_SCHEMA_REQUIRED = re.compile(r"'([^']+)' is a required property")
_SCHEMA_UNEXPECTED = re.compile(
    r"[Aa]dditional properties are not allowed \(([^)]*?)"
    r"\s+(?:was|were) unexpected\)")
_SCHEMA_QUOTED = re.compile(r"'([^']*)'")
_SCHEMA_VALUE_KINDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(.*?) is not of type\b"), "wrong_type"),
    (re.compile(r"^(.*?) is (?:greater than the maximum|less than the "
                r"minimum|too long|too short)\b"), "out_of_range"),
    (re.compile(r"^(.*?) is not one of\b"), "not_in_enum"),
    (re.compile(r"^(.*?) does not match\b"), "bad_format"),
)

#: refusals that are the tool's PROTOCOL, not a failure: the first call is
#: meant to be refused and answered with reasons (WP5 finalize_delivery -
#: "NOT finalized: ... blocking items"). reg1-ext2 counted five of them as
#: tool errors and they topped the usability table. Prefix-matched on the
#: error text, per tool.
EXPECTED_REFUSALS: dict[str, tuple[str, ...]] = {
    "finalize_delivery": ("NOT finalized",),
}


def is_expected_refusal(tool: str, error: str | None) -> bool:
    if not error:
        return False
    return any(str(error).lstrip().startswith(pfx)
               for pfx in EXPECTED_REFUSALS.get(tool, ()))


#: mentor-side roots a blind case must never read from. The case's own
#: staging directory is passed in and subtracted.
MENTOR_ROOTS = (
    re.compile(r"H:[/\\]CrystalPilotData", re.I),
    re.compile(r"benchmark[/\\]data", re.I),
    re.compile(r"[/\\]refs?[/\\]", re.I),
    re.compile(r"e-survey", re.I),
)


# --------------------------------------------------------------- rollout io
def read_rollout(path: Path) -> list[dict[str, Any]]:
    """Rollout lines, skipping ones that do not parse.

    A truncated final line is normal when a run was interrupted, and it is
    not a reason to lose the other 600 records."""
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return out


def _ts(rec: dict[str, Any]) -> float | None:
    t = rec.get("timestamp")
    if not isinstance(t, str):
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _payload(rec: dict[str, Any]) -> dict[str, Any]:
    p = rec.get("payload")
    return p if isinstance(p, dict) else {}


def tool_calls(recs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten every tool invocation into one comparable shape.

    Three transports carry them - MCP tools, the exec harness, and plain
    function calls - and they matter equally for "what did the agent
    actually do", so they are normalised rather than reported separately.

    Each call also carries `poll` (the detached job id it is asking about,
    or None) and `schema_error` (the parsed MCP rejection, or None), both
    decided here so every consumer classifies a call the same way.
    """
    calls: list[dict[str, Any]] = []
    for rec in recs:
        p = _payload(rec)
        kind = p.get("type")
        if kind == "mcp_tool_call_end":
            inv = p.get("invocation") or {}
            res = p.get("result") or {}
            args = inv.get("arguments")
            ok, err, schema = _mcp_outcome(res, args)
            dur = p.get("duration") or {}
            calls.append({
                "t": _ts(rec), "transport": "mcp",
                "tool": inv.get("tool") or "?",
                "args": args,
                "ok": ok, "error": err, "schema_error": schema,
                "poll": poll_job(args),
                "secs": (float(dur.get("secs") or 0)
                         + float(dur.get("nanos") or 0) / 1e9),
            })
        elif kind == "custom_tool_call":
            calls.append({"t": _ts(rec), "transport": "custom",
                          "tool": p.get("name") or "?",
                          "args": p.get("input"), "ok": None,
                          "error": None, "schema_error": None,
                          "poll": poll_job(p.get("input")), "secs": None})
        elif kind == "function_call":
            calls.append({"t": _ts(rec), "transport": "function",
                          "tool": p.get("name") or "?",
                          "args": p.get("arguments"), "ok": None,
                          "error": None, "schema_error": None,
                          "poll": poll_job(p.get("arguments")),
                          "secs": None})
    return calls


def _args_dict(args: Any) -> dict[str, Any]:
    """Arguments as a mapping, whichever transport carried them.

    MCP hands them over already decoded; the function-call transport
    carries the same object as a JSON string."""
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            loaded = json.loads(args)
        except ValueError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def poll_job(args: Any) -> str | None:
    """The detached job this call is asking about, or None if it is not a
    poll. `run_shelxt(job_status='job_20260903_155917')` -> the job id."""
    d = _args_dict(args)
    for key in POLL_ARG_KEYS:
        v = d.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _schema_error(text: str, args: Any) -> dict[str, Any]:
    """One `Input validation error: ...` message, parsed.

    The parameter is what makes the finding actionable - "compare_nodes
    is hard to call" is a shrug, "compare_nodes was called with `nodes`
    when it wanted `a`" is a rename. jsonschema names the parameter
    directly for the two structural failures and only quotes the offending
    VALUE for the rest, so for those the name is recovered by looking the
    value up in the arguments the agent actually sent."""
    body = SCHEMA_ERROR_RE.sub("", text.strip(), count=1).strip()
    msg = body or text.strip()
    m = _SCHEMA_REQUIRED.search(msg)
    if m:
        return {"param": m.group(1), "kind": "missing_required",
                "message": msg[:300]}
    m = _SCHEMA_UNEXPECTED.search(msg)
    if m:
        names = _SCHEMA_QUOTED.findall(m.group(1))
        return {"param": names[0] if names else None,
                "kind": "unknown_param", "message": msg[:300]}
    for pat, kind in _SCHEMA_VALUE_KINDS:
        m = pat.search(msg)
        if m:
            return {"param": _param_holding(m.group(1).strip(), args),
                    "kind": kind, "message": msg[:300]}
    return {"param": None, "kind": "invalid_arguments", "message": msg[:300]}


def _param_holding(value_text: str, args: Any) -> str | None:
    """Which argument carried this value, if any.

    `600 is greater than the maximum of 500` names no parameter; the call
    that produced it did, and it is the only place the name survives."""
    if not value_text:
        return None
    try:
        wanted: Any = json.loads(value_text)
    except ValueError:
        wanted = value_text.strip("'\"")
    for key, val in _args_dict(args).items():
        if val == wanted or str(val) == str(wanted):
            return str(key)
    return None


def _mcp_outcome(res: Any, args: Any = None
                 ) -> tuple[bool | None, str | None, dict[str, Any] | None]:
    """(succeeded?, error text, schema rejection) for one MCP result.

    Three kinds of failure, and only one of them is visible to the
    transport. `Err` is a protocol-level failure. A CrystalPilot tool that
    could not do its job returns a perfectly successful envelope carrying
    `{"ok": false, "error": "..."}` - which is the shape of every
    interesting runtime failure. Counting only `Err` reports every tool as
    flawless: r25's two `run_shelxt` timeouts, the ones that sent the whole
    campaign down a charge-flipping detour, are both `Ok` envelopes.

    And a call the MCP layer REJECTED against the tool's JSON schema comes
    back as an `Ok` envelope too, carrying a bare non-json string ("Input
    validation error: 'a' is a required property"). The old json-only
    parse skipped it as unparseable and scored the call a success, so the
    two `compare_nodes` rejections in ka1-cage - the clearest evidence in
    the whole campaign of a tool the model cannot call - counted as two
    clean calls. They are failures, and they are additionally reported as
    their own category because nothing about the tool's behaviour is
    implicated: only its call surface.
    """
    if not isinstance(res, dict):
        return None, None, None
    if "Err" in res:
        err = res["Err"]
        return False, (err if isinstance(err, str) else
                       json.dumps(err, ensure_ascii=False,
                                  default=str))[:400], None
    ok = res.get("Ok")
    if ok is None:
        return None, None, None
    for item in (ok.get("content") or []) if isinstance(ok, dict) else []:
        text = item.get("text") if isinstance(item, dict) else None
        if not isinstance(text, str):
            continue
        try:
            body = json.loads(text)
        except ValueError:
            # not json at all. A rejected call is the one thing that
            # arrives this way, and the marker is only trusted here: a
            # TOOL that mentions validation inside its own json result is
            # reporting, not being rejected.
            if SCHEMA_ERROR_RE.search(text):
                return False, text.strip()[:400], _schema_error(text, args)
            continue
        if isinstance(body, str) and SCHEMA_ERROR_RE.search(body):
            return False, body.strip()[:400], _schema_error(body, args)
        if isinstance(body, dict) and body.get("ok") is False:
            return False, str(body.get("error") or text)[:400], None
    return True, None, None


def reasoning_texts(recs: Iterable[dict[str, Any]]
                    ) -> list[tuple[float | None, str]]:
    """Deduplicated reasoning summaries.

    The same summary arrives twice - once as a `response_item/reasoning`
    and once as an `event_msg/agent_reasoning`. Keeping both would double
    every pivot count and make a run look twice as confused as it was."""
    out: list[tuple[float | None, str]] = []
    seen: set[str] = set()
    for rec in recs:
        p = _payload(rec)
        if p.get("type") not in ("reasoning", "agent_reasoning"):
            continue
        texts = ([p["text"]] if isinstance(p.get("text"), str) else
                 [s["text"] for s in (p.get("summary") or [])
                  if isinstance(s, dict) and isinstance(s.get("text"), str)])
        for t in texts:
            key = t.strip()[:400]
            if key in seen:
                continue
            seen.add(key)
            out.append((_ts(rec), t))
    return out


def shell_commands(calls: list[dict[str, Any]]) -> list[str]:
    """Command text from whichever transport carried it."""
    out: list[str] = []
    for c in calls:
        a = c.get("args")
        if isinstance(a, str):
            out.append(a)
        elif isinstance(a, dict):
            for k in ("command", "cmd", "script", "input", "code"):
                if isinstance(a.get(k), str):
                    out.append(a[k])
    return out


# ------------------------------------------------------------------ metrics
def _norm_args(args: Any) -> str:
    """Argument fingerprint. Sorted keys so key order never fakes a change;
    truncated so a giant inline payload does not dominate the hash."""
    try:
        return json.dumps(args, sort_keys=True, ensure_ascii=False,
                          default=str)[:600]
    except (TypeError, ValueError):
        return str(args)[:600]


#: harness plumbing, not crystallography. `wait` polling the same cell
#: repeatedly is how you wait for a long tool, not evidence of spinning.
CONTROL_TOOLS = {"wait", "exec"}


def find_spin(calls: list[dict[str, Any]], window: int = 12
              ) -> list[dict[str, Any]]:
    """Identical (tool, args) issued more than once inside a short window.

    Window rather than whole-run: calling `situation_report` at the start
    and the end of a two-hour session is good practice, calling it three
    times in eight consecutive actions is spinning.

    Polls are not spin and are dropped here (see find_polling): the tool
    that started a detached job answers with "poll
    run_shelxt(job_status='job_...') again in 60-120 s", so an agent that
    does exactly that scored eleven repeats of one identical call in ka1
    for following instructions."""
    seen: list[tuple[str, str]] = []
    hits: Counter[tuple[str, str]] = Counter()
    for c in calls:
        if c["tool"] in CONTROL_TOOLS or c.get("poll"):
            continue
        key = (c["tool"], _norm_args(c.get("args")))
        if key in seen[-window:]:
            hits[key] += 1
        seen.append(key)
    return [{"tool": t, "args": a[:200], "repeats": n}
            for (t, a), n in hits.most_common(30)]


def find_polling(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detached-job polls, grouped by the job each one asked about.

    Reported as polls per job plus the wall clock the polls span, because
    that is the number that answers the question polling raises: not "did
    the agent repeat itself" but "how long did it sit waiting, and did it
    wait at the cadence the tool asked for". `secs` is what the polls
    themselves cost, which is ~0 - a poll is a status read, and saying so
    keeps a long wait from being read as an expensive tool."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for c in calls:
        job = c.get("poll")
        if job:
            groups[(c["tool"], job)].append(c)
    out: list[dict[str, Any]] = []
    for (tool, job), hits in groups.items():
        ts = sorted(t for t in (h.get("t") for h in hits) if t is not None)
        span = round(ts[-1] - ts[0], 1) if len(ts) >= 2 else None
        out.append({
            "tool": tool, "job": job, "polls": len(hits),
            "first_t": ts[0] if ts else None,
            "last_t": ts[-1] if ts else None,
            "span_s": span,
            "mean_interval_s": (round(span / (len(ts) - 1), 1)
                                if span and len(ts) >= 2 else None),
            "secs": round(sum(h.get("secs") or 0 for h in hits), 1),
        })
    return sorted(out, key=lambda d: -d["polls"])[:30]


def find_error_chains(calls: list[dict[str, Any]], min_len: int = 2
                      ) -> list[dict[str, Any]]:
    """Runs of consecutive failures of the same tool.

    This is the expensive kind of stuck: each retry costs a full tool
    timeout, and the agent has no new information after any of them."""
    chains: list[dict[str, Any]] = []
    cur_tool: str | None = None
    cur: list[dict[str, Any]] = []

    def flush() -> None:
        if cur_tool and len(cur) >= min_len:
            chains.append({"tool": cur_tool, "length": len(cur),
                           "secs": round(sum(c.get("secs") or 0
                                             for c in cur), 1),
                           "first_error": (cur[0].get("error") or "")[:300]})
    for c in calls:
        if c.get("ok") is False:
            if c["tool"] == cur_tool:
                cur.append(c)
            else:
                flush()
                cur_tool, cur = c["tool"], [c]
        else:
            flush()
            cur_tool, cur = None, []
    flush()
    return sorted(chains, key=lambda d: -d["length"])[:20]


def find_arg_churn(calls: list[dict[str, Any]], min_variants: int = 3
                   ) -> list[dict[str, Any]]:
    """Consecutive runs of one tool with a different argument set each
    time. With errors in the run it is the signature of guessing at a
    schema; without any it is browsing (reg3-rz: five successful
    read_skill calls on four cards/sections were reported as "hard to
    call"). `n_errors` lets the report tell the two apart."""
    out: list[dict[str, Any]] = []
    calls = [c for c in calls if c["tool"] not in CONTROL_TOOLS]
    i = 0
    while i < len(calls):
        j, variants = i, {_norm_args(calls[i].get("args"))}
        while j + 1 < len(calls) and calls[j + 1]["tool"] == calls[i]["tool"]:
            j += 1
            variants.add(_norm_args(calls[j].get("args")))
        if len(variants) >= min_variants and (j - i + 1) >= min_variants:
            run = calls[i:j + 1]
            out.append({"tool": calls[i]["tool"], "calls": j - i + 1,
                        "distinct_args": len(variants),
                        "n_errors": sum(1 for c in run
                                        if c.get("ok") is False
                                        or c.get("schema_error"))})
        i = j + 1
    return sorted(out, key=lambda d: (-(d["n_errors"] > 0),
                                      -d["distinct_args"]))[:20]


def find_shell_hazards(cmds: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for label, pat, why in SHELL_HAZARDS:
        hits = [c for c in cmds if pat.search(c)]
        if hits:
            out.append({"hazard": label, "count": len(hits), "why": why,
                        "example": hits[0][:220]})
    return out


def find_pivots(reasons: list[tuple[float | None, str]],
                calls: list[dict[str, Any]], within_s: float = 180.0
                ) -> list[dict[str, Any]]:
    """Approach changes, each linked to the tool error that preceded it.

    The link is the point. "The agent gave up on SHELXT" is an anecdote;
    "the agent gave up on SHELXT 40 s after run_shelxt returned a bare
    timeout string" is a fixable message-design defect."""
    fails = [c for c in calls if c.get("ok") is False and c.get("t")]
    out: list[dict[str, Any]] = []
    for t, text in reasons:
        m = PIVOT_MARKERS.search(text)
        if not m:
            continue
        prior = None
        if t is not None:
            cands = [c for c in fails if c["t"] <= t and t - c["t"] <= within_s]
            if cands:
                prior = max(cands, key=lambda c: c["t"])
        out.append({
            "marker": m.group(0).lower(),
            "excerpt": _around(text, m.start()),
            "after_tool_error": (prior or {}).get("tool"),
            "tool_error": ((prior or {}).get("error") or "")[:300] or None,
        })
    return out


def failure_consequences(calls: list[dict[str, Any]],
                         reasons: list[tuple[float | None, str]]
                         ) -> list[dict[str, Any]]:
    """For each tool failure, what the agent thought immediately after.

    The reverse direction from find_pivots, and the more direct
    instrument: it asks "what did THIS error message make the agent do",
    which is the question that turns a failure count into a message-design
    fix. The r25 case is the archetype - `run_shelxt` returned the bare
    string "shelxt timed out", and the next reasoning step concluded
    SHELXT could not handle the cell, when phasing had in fact already
    succeeded and only the space-group search was killed.
    """
    stamped = sorted([(t, x) for t, x in reasons if t is not None])
    out: list[dict[str, Any]] = []
    for c in calls:
        if c.get("ok") is not False or c.get("t") is None:
            continue
        nxt = next(((t, x) for t, x in stamped if t >= c["t"]), None)
        out.append({
            "tool": c["tool"],
            "error": (c.get("error") or "")[:300],
            "cost_s": round(c.get("secs") or 0, 1),
            "gap_s": (round(nxt[0] - c["t"], 1) if nxt else None),
            "next_reasoning": (nxt[1][:600].replace("\n", " ")
                               if nxt else None),
            "pivoted": bool(nxt and PIVOT_MARKERS.search(nxt[1])),
        })
    return out


def _around(text: str, at: int, span: int = 160) -> str:
    lo, hi = max(0, at - span), min(len(text), at + span)
    return ("…" if lo else "") + text[lo:hi].replace("\n", " ") + ("…" if hi < len(text) else "")


def audit_leakage(cmds: list[str], reasons: list[tuple[float | None, str]],
                  allowed: Iterable[str]) -> list[dict[str, Any]]:
    """Mentor-side paths touched outside the case's own staging directory."""
    allow = [re.escape(str(a)).replace("/", "[/\\\\]").replace("\\\\\\\\", "[/\\\\]")
             for a in allowed if a]
    allow_pats = [re.compile(a, re.I) for a in allow]
    hits: list[dict[str, Any]] = []
    for where, blobs in (("shell", cmds),
                         ("reasoning", [t for _, t in reasons])):
        for blob in blobs:
            for pat in MENTOR_ROOTS:
                for m in pat.finditer(blob):
                    ctx = _around(blob, m.start(), 120)
                    if any(p.search(ctx) for p in allow_pats):
                        continue          # the case's own staging dir
                    hits.append({"where": where, "match": m.group(0),
                                 "context": ctx})
    # dedupe on context; one path mentioned ten times is one finding
    seen, out = set(), []
    for h in hits:
        if h["context"] in seen:
            continue
        seen.add(h["context"])
        out.append(h)
    return out[:40]


def audit_path_tokens(reasons: list[tuple[float | None, str]],
                      tokens: Iterable[str]) -> list[dict[str, Any]]:
    """Folder names the agent reasoned FROM.

    pa1: four "blind" cu runs cited the project folder `cu-l0-r2` as their
    reason to expect copper; the data path is a prior the experiment never
    meant to give. Reports every reasoning passage that mentions a case /
    project / data-directory token (anonymised `p<8 hex>` names count too:
    a mention is harmless then, but the count still says whether the
    agent reads paths for hints)."""
    toks = sorted({t for t in tokens if t and len(t) >= 4}, key=len,
                  reverse=True)
    if not toks:
        return []
    pat = re.compile("|".join(re.escape(t) for t in toks), re.I)
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, text in reasons:
        for m in pat.finditer(text):
            ctx = _around(text, m.start(), 120)
            if ctx in seen:
                continue
            seen.add(ctx)
            hits.append({"token": m.group(0), "context": ctx})
    return hits[:40]


# ------------------------------------------------------------------ per case
def read_server_log(path: Path) -> list[dict[str, Any]]:
    """`<project>/.crystalpilot/mcp_server.jsonl` as the bundle copied it.

    One line per MCP process event. Lines written before the `event` key
    existed are startup lines, and older bundles are full of them, so a
    missing key means startup rather than unknown."""
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    rec.setdefault("event", "startup")
                    out.append(rec)
    except OSError:
        return []
    return out


def find_abandoned_tools(server_log: Iterable[dict[str, Any]]
                         ) -> list[dict[str, Any]]:
    """Tools still computing when the MCP server lost its client.

    The server's transport watchdog writes one line when codex goes away
    while a tool is mid-run. It is the end of the story the rollout cannot
    tell: the rollout's last record for that call is the invocation, with
    no result, because no result was ever produced. A tool that is still
    running when the case ends is the strongest form of "the model could
    not bound this call" - it did not misread a result, it never got
    one."""
    out: list[dict[str, Any]] = []
    for rec in server_log:
        if rec.get("action") != "exit_abandoning_tool":
            continue
        out.append({"tool": rec.get("running_tool"),
                    "elapsed_s": rec.get("elapsed_s"),
                    "budget_s": rec.get("budget_s")})
    return out


def analyse_case(logs_dir: Path, staging_allow: Iterable[str] = ()
                 ) -> dict[str, Any]:
    manifest = _load(logs_dir / "MANIFEST.json") or {}
    recs = read_rollout(logs_dir / "rollout.jsonl")
    calls = tool_calls(recs)
    cmds = shell_commands(calls)
    reasons = reasoning_texts(recs)
    server_log = read_server_log(logs_dir / "mcp_server.jsonl")

    by_tool: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "errors": 0, "schema_errors": 0, "polls": 0,
                 "expected_refusals": 0, "secs": 0.0})
    for c in calls:
        c["expected_refusal"] = (c.get("ok") is False
                                 and is_expected_refusal(c["tool"], c.get("error")))
    for c in calls:
        row = by_tool[c["tool"]]
        row["calls"] += 1
        row["secs"] += c.get("secs") or 0.0
        if c.get("expected_refusal"):
            row["expected_refusals"] += 1
        elif c.get("ok") is False:
            row["errors"] += 1
        # a schema rejection IS an error (the call did not happen), and is
        # counted inside `errors` as well as on its own line
        if c.get("schema_error"):
            row["schema_errors"] += 1
        if c.get("poll"):
            row["polls"] += 1
    for row in by_tool.values():
        row["secs"] = round(row["secs"], 1)
        row["error_rate"] = (round(row["errors"] / row["calls"], 3)
                             if row["calls"] else 0.0)

    leak = audit_leakage(cmds, reasons, staging_allow)
    polling = find_polling(calls)
    schema_errors = [{"tool": c["tool"], **c["schema_error"]}
                     for c in calls if c.get("schema_error")]
    abandoned = find_abandoned_tools(server_log)
    path_tokens = audit_path_tokens(reasons, [
        manifest.get("case") or "",
        Path(str(manifest.get("project_dir") or "")).name,
        Path(str(manifest.get("data_dir") or "")).name,
        *[Path(str(a)).name for a in staging_allow]])
    return {
        "case": manifest.get("case") or logs_dir.parent.name,
        "arm": manifest.get("arm"),
        "crystal": manifest.get("crystal"),
        "campaign": manifest.get("campaign"),
        "wall_s": manifest.get("wall_s"),
        "lanes_busy": manifest.get("lanes_busy"),
        "usage": manifest.get("usage"),
        "log_errors": manifest.get("errors") or [],
        "rollout_records": len(recs),
        "n_tool_calls": len(calls),
        "n_tool_errors": sum(1 for c in calls
                             if c.get("ok") is False and not c.get("expected_refusal")),
        # protocol refusals (EXPECTED_REFUSALS): the tool did its job by
        # saying no; listed, never counted as errors
        "expected_refusals": [{"tool": c["tool"], "error": c["error"],
                               "t": c.get("t")}
                              for c in calls if c.get("expected_refusal")][:60],
        "n_expected_refusals": sum(1 for c in calls if c.get("expected_refusal")),
        "n_reasoning": len(reasons),
        "failures": [{"tool": c["tool"], "error": c["error"],
                      "secs": round(c.get("secs") or 0, 1)}
                     for c in calls
                     if c.get("ok") is False and not c.get("expected_refusal")][:60],
        "tools": dict(sorted(by_tool.items(),
                             key=lambda kv: -kv[1]["calls"])),
        # schema rejections are a SUBSET of n_tool_errors, broken out
        # because they name a call-surface defect and nothing else
        "schema_errors": schema_errors[:60],
        "n_schema_errors": len(schema_errors),
        # correct waiting, kept out of `spin` (see find_polling)
        "polling": polling,
        "n_polls": sum(p["polls"] for p in polling),
        "polled_wall_s": round(sum(p["span_s"] or 0 for p in polling), 1),
        # from mcp_server.jsonl, not the rollout: tools still running when
        # the server lost its client
        "server_abandoned_tools": abandoned,
        "spin": find_spin(calls),
        "error_chains": find_error_chains(calls),
        "arg_churn": find_arg_churn(calls),
        "shell_hazards": find_shell_hazards(cmds),
        "pivots": find_pivots(reasons, calls),
        "failure_consequences": failure_consequences(calls, reasons),
        "leakage": leak,
        "leak_clean": not leak,
        "path_tokens": path_tokens,
        "path_token_cited": bool(path_tokens),
    }


def _load(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("logs", nargs="+",
                    help="case logs/ directories, or campaign workdirs")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    dirs: list[Path] = []
    for raw in args.logs:
        p = Path(raw)
        dirs.extend([p] if (p / "rollout.jsonl").exists()
                    else sorted(p.glob("*/logs")))
    out = [analyse_case(d) for d in dirs]
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if args.json:
        args.json.write_text(text, encoding="utf-8")
        print(f"wrote {args.json} ({len(out)} case(s))")
    else:
        print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
