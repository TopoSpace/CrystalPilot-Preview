"""Crystallographic skill layer: dynamic expert knowledge as data, not code.

A *skill* is one markdown file under ENGINE_ROOT/knowledge/ - YAML-ish
frontmatter for retrieval (description, alert codes, tool names, tags) plus
a free-form body (decision rules, operating sequences, numeric chains with
sources). Skills are the designated home for externally-acquired expert
knowledge: tools compute facts, skills guide judgement. Because skills are
files, a mentor or the agent itself can add/refresh one mid-campaign and it
takes effect immediately - no engine restart, no code change, full git
history.

Write path: these tools run in the MCP server process (engine root), which
is deliberately OUTSIDE the codex sandbox - the agent cannot edit the
knowledge tree via shell, only through save_skill/delete_skill where the
change is validated, attributed and audit-logged.

Categories = subdirectories of knowledge/ (skills/, expert-cases/, ...).
save_skill defaults to skills/; expert-cases stays a curated category and
both are served by the same index.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from ..tools.base import Tool, ToolContext, ToolResult

ENGINE_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = ENGINE_ROOT / "knowledge"
DEFAULT_CATEGORY = "skills"
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


# --------------------------------------------------------------------------
def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Tolerant frontmatter parse (subset of YAML: scalars + flow lists).

    Accepts both the new skill schema and the legacy expert-cases card
    schema (symptom/alerts/tools/tags/source). Returns (meta, body).
    """
    m = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}, text
    meta: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip() != line:   # nested keys: skip
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if v.startswith("[") and v.endswith("]"):
            items = [x.strip().strip("'\"") for x in v[1:-1].split(",")]
            meta[k] = [x for x in items if x]
        else:
            meta[k] = v.strip("'\"")
    return meta, text[m.end():]


def _skill_files() -> list[Path]:
    if not KNOWLEDGE_DIR.is_dir():
        return []
    return sorted(p for p in KNOWLEDGE_DIR.rglob("*.md")
                  if p.name.upper() != "README.MD")


def _entry(p: Path) -> dict[str, Any]:
    meta, body = parse_frontmatter(
        p.read_text(encoding="utf-8", errors="replace"))
    rel = p.relative_to(KNOWLEDGE_DIR)
    return {
        "name": p.stem,
        "category": rel.parts[0] if len(rel.parts) > 1 else "",
        "description": (meta.get("description") or meta.get("symptom")
                        or body.strip().splitlines()[0][:120] if body.strip()
                        else ""),
        "alerts": meta.get("alerts") or [],
        "tools": meta.get("tools") or [],
        "tags": meta.get("tags") or [],
        "aliases": meta.get("aliases") or [],
        "source": meta.get("source") or "",
        "confidence": meta.get("confidence") or "",
        "created_by": meta.get("created_by") or "",
        "n_lines": body.count("\n") + 1,
        "path": str(rel).replace("\\", "/"),
    }


def skill_index() -> list[dict[str, Any]]:
    out = []
    for p in _skill_files():
        try:
            out.append(_entry(p))
        except OSError:
            continue
    return out


def skills_for_alerts(codes: list[str]) -> list[dict[str, str]]:
    """Match skills whose frontmatter alerts overlap the given checkCIF
    codes ('097', 'PLAT097' and 'RINTA01' forms all normalize)."""
    want = {re.sub(r"^PLAT", "", str(c).upper()).strip() for c in codes}
    hits = []
    for e in skill_index():
        have = {re.sub(r"^PLAT", "", str(a).upper()).strip()
                for a in e["alerts"]}
        inter = want & have
        if inter:
            hits.append({"skill": e["name"],
                         "matched_alerts": sorted(inter),
                         "description": e["description"]})
    return hits


def _resolve(name: str) -> Path | None:
    """Find a skill by stem anywhere under knowledge/ (unique stems)."""
    cands = [p for p in _skill_files() if p.stem == name]
    return cands[0] if len(cands) == 1 else (cands[0] if cands else None)


# domain zh<->en synonym rings: campaign transcripts show ~25 empty
# list_skills queries, mostly a Chinese query against an English card (or
# vice versa) - "孪晶警示征" found nothing although twin cards existed
_SYNONYMS: list[set[str]] = [
    {"孪晶", "双晶", "twin", "twinning"},
    {"无序", "disorder", "disordered", "part"},
    {"掩膜", "溶剂掩膜", "mask", "squeeze", "solvent"},
    {"氢", "加氢", "hydrogen", "riding"},
    {"权重", "weight", "weights", "wght"},
    {"空间群", "定群", "space", "group"},
    {"吸收", "absorption", "sadabs", "twinabs"},
    {"完整度", "completeness"},
    {"分辨率", "截断", "resolution", "cutoff"},
    {"警报", "alert", "checkcif"},
    {"超胞", "supercell", "复合", "composite"},
    {"赝对称", "伪对称", "pseudo-symmetry", "pseudosymmetry", "ncs"},
    {"约束", "restraint", "restraints", "限制"},
    {"客体", "guest", "溶剂客体"},
    {"骨架", "framework", "mof"},
    {"精修", "refine", "refinement", "shelxl"},
    {"求解", "solve", "solution", "shelxt", "电荷翻转", "charge-flipping"},
    {"交付", "delivery", "deliver", "发表", "publication"},
    {"元素", "element", "指认", "assignment"},
    {"占有率", "occupancy", "fvar"},
    {"对映", "手性", "flack", "absolute", "绝对结构"},
    {"消光", "extinction", "systematic", "absence", "absences"},
]


def _expand_word(w: str) -> set[str]:
    wl = w.lower()
    out = {wl}
    for ring in _SYNONYMS:
        if wl in ring:
            out |= ring
    return out


def _word_hits(word: str, hay: str) -> bool:
    return any(v in hay for v in _expand_word(word))


def _haystack(e: dict[str, Any]) -> str:
    return (e["name"] + " " + e["description"] + " "
            + " ".join(map(str, e["tags"])) + " "
            + " ".join(map(str, e.get("aliases") or []))).lower()


# --------------------------------------------------------------------------
class ListSkills(Tool):
    name = "list_skills"
    description = (
        "Browse the crystallographic skill library (expert knowledge as "
        "retrievable units: decision rules, thresholds with sources, case "
        "playbooks). Filter by checkCIF alert code, tool name, or free-text "
        "query over name/description/tags. Start here when facing a "
        "situation you suspect the experts have seen: disorder calls, "
        "twin suspicion, alert triage, resolution cutoffs.")
    params_schema = {
        "type": "object",
        "properties": {
            "alert": {"type": "string",
                      "description": "checkCIF code(s), e.g. 'PLAT097', "
                                     "'097' or a batch '097,220,306' - one "
                                     "call, not one per code"},
            "tool": {"type": "string",
                     "description": "tool/command name, e.g. 'model_disorder' "
                                    "or 'PART'"},
            "query": {"type": "string",
                      "description": "words over name+description+tags+"
                                     "aliases; multiple words AND-match, "
                                     "zh/en domain synonyms expand "
                                     "automatically (孪晶 finds twin cards)"},
            "category": {"type": "string",
                         "description": "subdirectory filter, e.g. 'skills' "
                                        "or 'expert-cases'"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        idx = skill_index()
        alert = params.get("alert")
        matched_alerts: dict[str, list[str]] = {}
        if alert:
            # batch form: '097,220 306' - r11_d fired 12 single-code calls
            want = {re.sub(r"^PLAT", "", c).strip()
                    for c in re.split(r"[\s,;]+", str(alert).upper())
                    if c.strip()}
            kept = []
            for e in idx:
                have = {re.sub(r"^PLAT", "", str(a).upper()).strip()
                        for a in e["alerts"]}
                inter = want & have
                if inter:
                    kept.append(e)
                    matched_alerts[e["name"]] = sorted(inter)
            idx = kept
        tool = params.get("tool")
        if tool:
            t = str(tool).lower()
            idx = [e for e in idx
                   if any(t == str(x).lower() for x in e["tools"])]
        cat = params.get("category")
        if cat:
            idx = [e for e in idx if e["category"] == cat]
        q = params.get("query")
        words = [w for w in re.split(r"\s+", str(q))
                 if w.strip()] if q else []
        pre_query = idx
        if words:
            idx = [e for e in idx
                   if all(_word_hits(w, _haystack(e)) for w in words)]
        summary: dict[str, Any] = {
            "n_skills": len(idx),
            "skills": [{k: e[k] for k in
                        ("name", "category", "description", "alerts",
                         "tools", "n_lines")} for e in idx[:40]],
            "note": ("read_skill(name=...) for the full text; save_skill to "
                     "capture a new reusable judgement rule"),
        }
        if matched_alerts and idx:
            summary["matched_alerts"] = {
                e["name"]: matched_alerts[e["name"]]
                for e in idx if e["name"] in matched_alerts}
        if not idx and words:
            # empty result: per-word nearest instead of a dead end (the
            # campaign pattern was rephrase-and-retry, 25 blank calls)
            near = {}
            for w in words:
                hits = [e["name"] for e in pre_query
                        if _word_hits(w, _haystack(e))]
                near[w] = {"n": len(hits), "top": hits[:3]}
            summary["near_misses_per_word"] = near
            summary["note"] = (
                "no skill matches ALL the words together; per-word nearest "
                "cards above - drop the word with n=0, or filter by "
                "tool=/alert= instead of free text")
        return ToolResult(ok=True, summary=summary)


_HEADING = re.compile(r"^(#{1,4})[ \t]+(.+?)[ \t]*$", re.M)


def skill_sections(text: str) -> list[dict[str, Any]]:
    """Markdown headings with the span each one governs (its own text plus
    every deeper heading until the next heading of its level or higher).
    `i` is 1-based so it can be quoted back as read_skill(section=i)."""
    heads = [(m.start(), len(m.group(1)), m.group(2).strip())
             for m in _HEADING.finditer(text)]
    out: list[dict[str, Any]] = []
    for n, (start, level, heading) in enumerate(heads):
        end = len(text)
        for s2, l2, _ in heads[n + 1:]:
            if l2 <= level:
                end = s2
                break
        out.append({"i": n + 1, "level": level, "heading": heading,
                    "offset": start, "end": end})
    return out


def find_section(sections: list[dict[str, Any]], key: str
                 ) -> dict[str, Any] | None:
    """By 1-based index, exact heading, or the shortest heading containing
    the key (case-insensitive) - 'A12' finds '### A12. PART 分组…'."""
    k = str(key).strip()
    if not k:
        return None
    if k.isdigit():
        i = int(k)
        return next((s for s in sections if s["i"] == i), None)
    kl = k.lower()
    exact = [s for s in sections if s["heading"].lower() == kl]
    if exact:
        return exact[0]
    hits = [s for s in sections if kl in s["heading"].lower()]
    if not hits:
        return None
    return min(hits, key=lambda s: len(s["heading"]))


class ReadSkill(Tool):
    name = "read_skill"
    description = (
        "Read one skill (frontmatter + body), or ONE SECTION of it with "
        "section=<heading text or index>. Call it directly with the name "
        "when you already know the card (AGENTS.md names them); list_skills "
        "is for browsing, not a prerequisite. Every result carries the "
        "card's `sections` table: for a long card read the section you "
        "need instead of paging the whole card - pa1 agents re-read the "
        "108k-char review ruleset four pages at a time, 13 reads per run. "
        "Paging still exists (offset=next_offset while truncated=true) and "
        "a truncated page is never the full card. Skills are advice with "
        "sources, not commands: when following one, cite it in your "
        "reasoning; when the data contradicts it, say so.")
    params_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string",
                     "description": "skill name (file stem) from list_skills"},
            "section": {"type": "string",
                        "description": "read one section only: a heading's "
                                       "text (case-insensitive substring, "
                                       "e.g. 'A12' or 'R 因子') or its index "
                                       "from `sections`; subsections are "
                                       "included"},
            "offset": {"type": "integer", "default": 0,
                       "description": "character offset to continue reading "
                                      "a long skill or section (use "
                                      "next_offset from the previous page)"},
        },
        "required": ["name"],
    }

    # One page per call keeps MCP results bounded; r23 collab audit found
    # the old hard cap silently cost agents the tails of the two longest
    # rulesets (both truncated at exactly 20015 chars, misread as full).
    PAGE = 20000

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        p = _resolve(str(params["name"]))
        if p is None:
            return ToolResult.failure(
                f"no skill named {params['name']!r} - list_skills to browse")
        text = p.read_text(encoding="utf-8", errors="replace")
        secs = skill_sections(text)
        toc = [{"i": s["i"], "level": s["level"], "heading": s["heading"],
                "n_chars": s["end"] - s["offset"]} for s in secs][:120]
        section = params.get("section")
        hit = None
        if section is not None and str(section).strip():
            hit = find_section(secs, str(section))
            matched_by = "heading"
            if hit is None:
                # reg1-ext2 cuox: read_skill(section='PLAT196') on a
                # ruleset whose headings are topics, not alert codes - the
                # token lives INSIDE a section. Fall back to the section
                # whose body mentions it most, and say so.
                tok = str(section).strip().lower()
                low = text.lower()
                scored = []
                for s in secs:
                    # count in the section's OWN text: a parent section
                    # spans its children, so counting the whole span would
                    # always hand the match to the top-level heading
                    own = low[s["offset"]:s["end"]]
                    for c in secs:
                        if (c["level"] > s["level"] and c["offset"] >= s["offset"]
                                and c["end"] <= s["end"]):
                            child = low[c["offset"]:c["end"]]
                            own = own.replace(child, "", 1)
                    n = own.count(tok)
                    if n > 0:
                        scored.append((n, s["level"], s))
                if scored:
                    # most mentions; ties go to the deeper (more specific)
                    hit = max(scored, key=lambda x: (x[0], x[1]))[2]
                    matched_by = "content"
            if hit is None:
                return ToolResult.failure(
                    f"no section matching {section!r} in {p.stem} (neither "
                    "a heading nor a mention in any section body); "
                    "sections: " + "; ".join(
                        f"{s['i']}: {s['heading']}" for s in secs[:80]))
            body = text[hit["offset"]:hit["end"]]
        else:
            body = text
        offset = max(0, int(params.get("offset") or 0))
        chunk = body[offset:offset + self.PAGE]
        truncated = offset + len(chunk) < len(body)
        summary: dict[str, Any] = {
            "name": p.stem,
            "path": str(p.relative_to(KNOWLEDGE_DIR)).replace("\\", "/"),
            "text": chunk,
            **({"section_matched_by": matched_by,
                "section_heading": hit["heading"]}
               if section is not None and str(section).strip() and hit
               else {}),
            "n_chars_total": len(text),
            "offset": offset,
            "truncated": truncated,
            "sections": toc,
        }
        if hit is not None:
            summary["section"] = {"i": hit["i"], "heading": hit["heading"],
                                  "n_chars": len(body)}
        if truncated:
            summary["next_offset"] = offset + len(chunk)
            sec_arg = (f", section={str(section)!r}" if hit is not None
                       else "")
            summary["note"] = (f"page ends at char {offset + len(chunk)} of "
                              f"{len(body)}; call read_skill(name=..."
                              f"{sec_arg}, offset={offset + len(chunk)}) for "
                              f"the rest")
            if hit is None and len(secs) > 1:
                summary["note"] += (
                    f" - or read just the section you need: this card has "
                    f"{len(secs)} sections (see `sections`), "
                    f"section=<heading or index>")
        return ToolResult(ok=True, summary=summary)


class SaveSkill(Tool):
    name = "save_skill"
    description = (
        "Create or update a crystallographic skill - the designated place "
        "for reusable expert judgement (decision rules, threshold recipes, "
        "case playbooks). Save when you learn something that would help a "
        "FUTURE project: a diagnosis pattern that worked, a parameter "
        "recipe for a structure class, a mentor correction. Do NOT save "
        "project-specific facts (those belong in the project report) or "
        "anything you have not verified. Every skill needs a source "
        "(campaign/case/corpus link) and honest confidence. Updates "
        "overwrite; git history preserves every version.")
    params_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string",
                     "description": "kebab-case slug, e.g. "
                                    "'twin-ghost-vs-disorder'"},
            "description": {"type": "string",
                            "description": "one-line retrieval key "
                                           "(symptom/situation it covers)"},
            "body": {"type": "string",
                     "description": "markdown body: the rule(s), numeric "
                                    "chains, operating sequence, per-rule "
                                    "sources"},
            "alerts": {"type": "array", "items": {"type": "string"},
                       "description": "related checkCIF codes (PLAT097...)"},
            "tools": {"type": "array", "items": {"type": "string"},
                      "description": "related tool/command names"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "source": {"type": "string",
                       "description": "where this came from (campaign id, "
                                      "CCDC number, corpus tid, 'mentor')"},
            "confidence": {"type": "string",
                           "enum": ["high", "medium", "low"],
                           "description": "high = multiple confirmations; "
                                          "low = single observation"},
            "reason": {"type": "string",
                       "description": "why this is worth keeping (goes to "
                                      "the audit log)"},
        },
        "required": ["name", "description", "body", "source", "reason"],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        name = str(params["name"]).strip().lower()
        if not _SLUG.match(name):
            return ToolResult.failure(
                "name must be kebab-case ([a-z0-9-], 2-64 chars)")
        body = str(params["body"]).strip()
        if len(body) < 40:
            return ToolResult.failure(
                "body too short to be a skill - state the rule, the "
                "numbers and the source")
        desc = str(params["description"]).strip().replace("\n", " ")

        def _lst(key: str) -> list[str]:
            return [str(x).strip() for x in (params.get(key) or [])
                    if str(x).strip()]

        target = KNOWLEDGE_DIR / DEFAULT_CATEGORY / f"{name}.md"
        existing = _resolve(name)
        if existing is not None and existing != target:
            # updating a card living in another category (expert-cases):
            # edit it in place rather than shadowing it
            target = existing
        target.parent.mkdir(parents=True, exist_ok=True)
        prev = target.read_text(encoding="utf-8", errors="replace") \
            if target.exists() else None

        fm = ["---", f"name: {name}", f"description: {desc}"]
        for key in ("alerts", "tools", "tags"):
            vals = _lst(key)
            if vals:
                fm.append(f"{key}: [{', '.join(vals)}]")
        fm.append(f"source: {str(params['source']).strip()}")
        fm.append(f"confidence: {params.get('confidence') or 'medium'}")
        fm.append(f"created_by: {params.get('_actor') or 'agent'}")
        fm.append(f"updated: {time.strftime('%Y-%m-%d')}")
        fm.append("---")
        target.write_text("\n".join(fm) + "\n\n" + body + "\n",
                          encoding="utf-8")
        return ToolResult(ok=True, summary={
            "saved": str(target.relative_to(KNOWLEDGE_DIR)).replace("\\", "/"),
            "action": "updated" if prev is not None else "created",
            "reason": str(params["reason"]),
            "note": ("skill is live immediately for every project; "
                     "git history keeps prior versions"),
        })


class DeleteSkill(Tool):
    name = "delete_skill"
    description = (
        "Delete a skill that turned out to be wrong or was superseded. "
        "Requires the reason (audit-logged). Prefer save_skill with a "
        "correction over deletion when the skill is partially right - "
        "deleting erases the retrieval entry, git keeps the content.")
    params_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "reason": {"type": "string",
                       "description": "why it must go (wrong? superseded "
                                      "by which skill?)"},
        },
        "required": ["name", "reason"],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        p = _resolve(str(params["name"]))
        if p is None:
            return ToolResult.failure(f"no skill named {params['name']!r}")
        try:
            p.relative_to(KNOWLEDGE_DIR)
        except ValueError:
            return ToolResult.failure("refusing to delete outside knowledge/")
        p.unlink()
        return ToolResult(ok=True, summary={
            "deleted": p.stem, "reason": str(params["reason"]),
            "note": "recoverable from git history"})


def register_skills_tools(reg, project) -> None:
    for tool in (ListSkills(), ReadSkill(), SaveSkill(), DeleteSkill()):
        reg.register(tool)
