"""Delivery tools: local/IUCr checkCIF and the publication bundle
(write_outputs with mask/disorder obligation lists, a delivery status,
final.fab) plus finalize_delivery (promotion to `final`).

Two gates guard the bundle:

* SHELXL-job pairing (JOB_MATCH_CONDITIONS / _job_match_legs): the
  publication CIF comes from the newest completed run_shelxl job whose
  MODEL is the active node's - R1, atom/H/FVAR counts and values, non-H
  labels and element types, ZERR-Z, mask state. Keyed on content only:
  no timestamps, no experiment block, so metadata-only changes
  (set_experiment) after the job never demand a rerun; final.cif is the
  job's model plus the session's metadata at write time. A refusal
  spells out the conditions with the numbers seen (job_match).
* label/element gate (label_element_audit): every non-H label must
  announce its scatterer's element by the SHELX convention (chem/labels);
  a mismatch or a surviving Q label is a blocking coherence issue with
  the one-call fix, unless write_outputs(accept_label_mismatch=true,
  reason=...) records a deliberate exception (never for Q labels).
  finalize_delivery re-runs the gate on the delivered files.

Split out of tools_extra (r12 module split); registration stays in
tools_extra.register_refine_tools.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from ..procutil import NO_WINDOW
from ..tools.base import ToolContext, ToolResult
from .toolbase import _ProjectTool
from .provenance import delivery_source_issue, next_delivery_revision, validation_source

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SHELXL = REPO_ROOT / "vendor" / "shelx" / "shelxl.exe"

from .tools_shelxl import (_res_zerr_z, _shelx_atom_rows,  # noqa: F401
                           _shelx_atom_stats)


def _checkcif_delta(job: Path, alerts: list[dict[str, Any]],
                    kind: str) -> dict[str, Any] | None:
    """New/resolved alert codes vs the latest previous run of the SAME
    target kind (publication vs node) - comparing a minimal node CIF
    against a publication CIF would only report their built-in noise
    difference."""
    cur = {}
    for a in alerts:
        cur[a["code"]] = max(cur.get(a["code"], ""), a["level"])
    for pj in sorted(job.parent.glob("job_*/checkcif.json"), reverse=True):
        if pj.parent == job:
            continue
        try:
            prev_rep = json.loads(pj.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - a corrupt old job is not our problem
            continue
        if not str(prev_rep.get("target", "")).startswith(kind):
            continue
        if (prev_rep.get("execution_status", "completed") != "completed"
                or prev_rep.get("report_status", "complete") != "complete"
                or prev_rep.get("ok") is False):
            continue
        prev = {}
        for a in prev_rep.get("alerts", []):
            prev[a["code"]] = max(prev.get(a["code"], ""), a["level"])
        delta: dict[str, Any] = {
            "vs": pj.parent.name,
            "new": sorted(f"{c}({lv})" for c, lv in cur.items()
                          if c not in prev),
            "resolved": sorted(f"{c}({lv})" for c, lv in prev.items()
                               if c not in cur),
        }
        changed = sorted(f"{c} {prev[c]}->{lv}" for c, lv in cur.items()
                         if c in prev and prev[c] != lv)
        if changed:
            delta["level_changed"] = changed
        return delta
    return None


def _fcf_recreation_note(platon_out: Path, shelxl_exposed: bool
                         ) -> dict[str, Any] | None:
    """Why PLATON could not rebuild the .fcf (the substance behind 995_B),
    read from platon.out - the file four pa1 agents grepped by hand. None
    when PLATON raised no such complaint."""
    if not platon_out.exists():
        return None
    try:
        txt = platon_out.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    hits: list[str] = []
    for ln in txt.splitlines():
        if re.search(r"(?i)recreate\s+fcf|executable\s+required|SHLEXE", ln):
            s = ln.strip(" *\t").strip()
            if s and s not in hits:
                hits.append(s)
    if not hits:
        return None
    env_problem = any(re.search(r"(?i)executable|SHLEXE", h) for h in hits)
    if env_problem:
        hint = ("environmental: PLATON did not find a SHELXL executable "
                + ("even though SHLEXE was set - check the vendor shelxl.exe"
                   if shelxl_exposed else
                   "(no vendor shelxl.exe to expose via SHLEXE)")
                + "; not evidence against the embedded res/hkl/fab")
    else:
        hint = ("PLATON re-ran SHELXL on the embedded res/hkl(/fab) and the "
                "result did not match the embedded fcf - check that "
                "final.res carries ABIN and final.fab is the job's .fab "
                "(write_outputs writes both) or that the fcf is from the "
                "same job as the res")
    return {"problem": "; ".join(hits)[:300], "hint": hint}


def _slim_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Wire-size discipline: A/B keep everything incl. the KB annotation;
    C drops the KB and truncates; G collapses to code+count. The full
    list always lives in checkcif.json (r18/r22 re-ran checkCIF because
    the untrimmed result blew past the transcript tail)."""
    out = [a for a in alerts if a["level"] in "AB"]
    out += [{"code": a["code"], "level": "C", "text": a["text"][:90]}
            for a in alerts if a["level"] == "C"]
    g_counts: dict[str, int] = {}
    for a in alerts:
        if a["level"] == "G":
            g_counts[a["code"]] = g_counts.get(a["code"], 0) + 1
    out += [{"code": c, "level": "G", "count": n}
            for c, n in sorted(g_counts.items())]
    return out


def _alerts_scaffold(report: dict[str, Any], alerts: list[dict[str, Any]],
                     delta: dict[str, Any] | None) -> str:
    """checkcif_alerts.md for the delivery directory: one section per
    A/B/C alert with the KB annotation and an empty explanation slot."""
    lines = ["# checkCIF alerts - " + time.strftime("%Y-%m-%d %H:%M"),
             "", f"target: {report['target']}",
             "counts: " + "  ".join(f"{lv}={n}" for lv, n
                                    in report["counts"].items())]
    if delta:
        lines.append(f"delta vs {delta['vs']}: "
                     f"new {delta['new'] or '[]'}, "
                     f"resolved {delta['resolved'] or '[]'}")
    for lv, title in (("A", "A alerts (must fix or justify)"),
                      ("B", "B alerts"), ("C", "C alerts")):
        sel = [a for a in alerts if a["level"] == lv]
        if not sel:
            continue
        lines += ["", f"## {title}"]
        for a in sel:
            lines += ["", f"### {a['code']}_ALERT_{a['type']}_{lv}  "
                          f"{a['text']}"]
            kb = a.get("kb") or {}
            for k in ("meaning", "causes", "remedy"):
                if kb.get(k):
                    lines.append(f"- {k}: {kb[k]}")
            lines.append("- explanation: (fill in: fixed, or the "
                         "evidence-based justification for VALIDATION.md)")
    g = [a for a in alerts if a["level"] == "G"]
    if g:
        codes: dict[str, int] = {}
        for a in g:
            codes[a["code"]] = codes.get(a["code"], 0) + 1
        lines += ["", "## G notes (codes only)",
                  ", ".join(f"{c} x{n}" for c, n in sorted(codes.items()))]
    return "\n".join(lines) + "\n"


@contextlib.contextmanager
def _checkcif_publish_lock(path: Path):
    """Serialize only validation-artifact publication, not project/model writes."""
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        until = time.monotonic() + 5
        while True:
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= until:
                    raise TimeoutError("checkCIF artifact publication lock timed out") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _persist_checkcif(job: Path, delivery: Path | None, report: dict[str, Any]) -> bool:
    """Persist attempts, including failures, without resurrecting an older success."""
    def atomic(path: Path, text: str) -> None:
        tmp = path.with_name(path.name + "." + report["attempt_id"] + ".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    payload = json.dumps(report, indent=2, ensure_ascii=False)
    atomic(job / "checkcif.json", payload)
    if delivery is None:
        return False
    with _checkcif_publish_lock(job.parent / ".publish.lock"):
        target = delivery / "checkcif.json"
        try:
            current = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        if isinstance(current, dict) and str(current.get("attempt_id", "")) > report["attempt_id"]:
            return False
        atomic(target, payload)
        if report["execution_status"] != "completed":
            scaffold = ("# checkCIF execution incomplete\n\n"
                        f"State: {report['execution_status']}; counts unknown, not zero.\n\n"
                        f"{report.get('error') or 'Validation is running.'}\n\n"
                        f"Diagnostics: {job}\\checkcif.json\n")
        else:
            scaffold = _alerts_scaffold(report, report["alerts"], report.get("delta"))
        atomic(job / "checkcif_alerts.md", scaffold)
        atomic(delivery / "checkcif_alerts.md", scaffold)
    return True


class RunCheckcif(_ProjectTool):
    name = "run_checkcif"
    description = (
        "Run PLATON checkCIF (independent IUCr-style validation). Default "
        "target = the ACTIVE node's minimal CIF (metadata alerts are retained "
        "and the limited scope is disclosed). PREFERRED after write_outputs: pass "
        "cif='<output_dir>/final.cif' to validate the PUBLICATION CIF - full "
        "structure-factor checks; A/B alerts come back structured with a "
        "knowledge-base annotation (meaning/causes/remedy), and the delivery "
        "directory automatically receives checkcif.json plus a "
        "checkcif_alerts.md scaffold (one section per alert with an "
        "explanation slot for VALIDATION.md) - no manual copying. Repeat "
        "runs report a delta (new/resolved alert codes vs the previous run "
        "of the same kind). C/G alerts are trimmed in the reply; the full "
        "list is always in checkcif.json. BUDGET: bounded timeout_s (default "
        "420 s, maximum 3600 s), live progress and cancellation. The owned "
        "PLATON/SHELXL process tree is cleaned up on every exit. Failures "
        "persist diagnostics and source versions with unknown alert counts; "
        "inspect failure_reason and logs before retrying. A complete local "
        "report is not a scientific pass or official IUCr validation.")
    params_schema = {
        "type": "object",
        "properties": {
            "cif": {"type": "string",
                    "description": "project-relative path of a CIF to "
                                   "validate (e.g. the write_outputs "
                                   "final.cif); omit for the active node"},
            "timeout_s": {"type": "integer", "default": 420, "minimum": 1, "maximum": 3600},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from datetime import datetime
        from uuid import uuid4
        from ..tools.budget import Budget
        from .checkcif_runner import OUTPUTS, parse_alerts, run_platon

        timeout = params.get("timeout_s", 420)
        if type(timeout) is not int or not 1 <= timeout <= 3600:
            return ToolResult.failure("timeout_s must be an integer from 1 to 3600 seconds")
        budget = Budget.for_tool(ctx, self.name, params)
        exe = Path(os.environ.get("CRYSTALPILOT_PLATON",
                                  str(REPO_ROOT / "vendor" / "shelx" / "platon.exe")))
        st = self.project.nodes.state()
        node = st["active_node"]
        publication = bool(params.get("cif"))
        if publication:
            cif = (self.project.dir / str(params["cif"])).resolve()
            if self.project.dir.resolve() not in cif.parents:
                return ToolResult.failure("cif must stay inside the project")
            if not cif.exists():
                return ToolResult.failure(f"no such CIF: {params['cif']}")
            from .data_versions import is_protected
            if is_protected(self.project.dir, cif):
                return ToolResult.failure("Archived inputs/nodes are read-only: omit cif to validate the active node, or validate an exported copy outside the archive")
        else:
            if node is None:
                return ToolResult.failure("no node to validate")
            cif = self.project.nodes.node_dir(node) / "model.cif"
            if not cif.exists():
                return ToolResult.failure(f"node {node} has no model.cif")
        attempt = datetime.now().strftime("job_%Y%m%d_%H%M%S_%f_") + uuid4().hex[:8]
        job = self.project.dir / ".crystalpilot" / "refine" / "checkcif" / attempt
        job.mkdir(parents=True, exist_ok=False)
        source = validation_source(
            cif, node=None if publication else node,
            revision=(self.project.nodes.node_meta(node).get("revision")
                      if node is not None and not publication else None))
        report: dict[str, Any] = {
            "schema_version": 2, "attempt_id": attempt,
            "target": ("publication:" + str(params.get("cif")) if publication
                       else f"node:{node} (minimal cif)"),
            "cif": str(cif), "source": source,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "execution_status": "running", "report_status": "missing",
            "ok": False, "counts": None, "alerts": [], "job_dir": str(job),
        }
        artifacts = {"checkcif_json": str(job / "checkcif.json")}
        if publication:
            artifacts["delivery_checkcif_json"] = str(cif.parent / "checkcif.json")
        _persist_checkcif(job, cif.parent if publication else None, report)
        try:
            from .storage import is_stripped, restore_embedded_hkl
            staged_text = cif.read_text(encoding="utf-8", errors="replace")
            if is_stripped(staged_text):
                # a stripped intermediate job.cif: PLATON needs the data
                (job / "model.cif").write_text(
                    restore_embedded_hkl(staged_text, cif.parent), encoding="utf-8")
            else:
                shutil.copy2(cif, job / "model.cif")
            # External structure factors / mask coefficients must stay paired.
            for suffix in (".fcf", ".res", ".hkl", ".fab"):
                sibling = cif.with_suffix(suffix)
                if sibling.is_file():
                    shutil.copy2(sibling, job / ("model" + suffix))
            cif_text = (job / "model.cif").read_text(encoding="utf-8", errors="replace")
            report["delivery_status"] = read_status_header(cif_text)
            shelxl = Path(os.environ.get("CRYSTALPILOT_SHELXL", str(DEFAULT_SHELXL)))
            outcome = run_platon(job, exe, shelxl, budget)
        except Exception as error:
            outcome = {"execution_status": "failed", "report_status": "missing",
                       "failure_reason": "input_error", "error": f"{type(error).__name__}: {error}"}
        report.update(outcome)
        # Do not publish success if cancellation arrived during process cleanup.
        if budget.cancelled():
            report.update(execution_status="cancelled", failure_reason="cancelled",
                          report_status="partial", error="checkCIF cancelled before publication")
        for name in OUTPUTS:
            if (job / name).is_file():
                artifacts[name] = str(job / name)
        chk = job / "model.chk"

        def failed_result() -> ToolResult:
            report.update(ok=False, counts=None, alerts=[])
            _persist_checkcif(job, cif.parent if publication else None, report)
            return ToolResult(ok=False, summary={**report, "no_state_change": True,
                              "timeout": report["execution_status"] == "timeout",
                              "cancelled": report["execution_status"] == "cancelled"},
                              artifacts=artifacts, error=report.get("error", "PLATON did not complete"))

        if report["execution_status"] != "completed":
            return failed_result()
        text = chk.read_text(encoding="utf-8", errors="replace")
        alerts = parse_alerts(text)
        metadata_alerts = sum(a["type"] == 1 for a in alerts)
        counts = {lv: sum(1 for a in alerts if a["level"] == lv)
                  for lv in "ABCG"}
        # skill layer: surface expert playbooks whose frontmatter names any
        # of the raised alert codes (read_skill for the full text)
        related_skills: list[dict[str, str]] = []
        from .registry import knowledge_mode
        if knowledge_mode() != "tools_only":   # ka1: no skill pointers
            try:
                from .tools_skills import skills_for_alerts
                related_skills = skills_for_alerts(
                    [a["code"] for a in alerts if a["level"] in "AB"])
            except Exception:  # noqa: BLE001 - advisory only, never block
                pass
        delta = _checkcif_delta(job, alerts,
                                "publication" if publication else "node")
        # the structured reason when PLATON could not rebuild the .fcf
        # (995_B): SHELXL not found vs a genuine res/hkl/fab mismatch
        fcf_note = _fcf_recreation_note(job / "platon.out", outcome.get("shelxl_exposed", False))
        report.update(ok=True, counts=counts, alerts=alerts)
        if delta:
            report["delta"] = delta
        if fcf_note:
            report["fcf_recreation"] = fcf_note
        if budget.cancelled():
            report.update(execution_status="cancelled", failure_reason="cancelled",
                          report_status="partial", error="checkCIF cancelled before publication")
            return failed_result()
        published = _persist_checkcif(job, cif.parent if publication else None, report)
        # counts LAST so a truncated result_tail still carries them
        summary: dict[str, Any] = {
            "execution_status": report["execution_status"],
            "report_status": report["report_status"],
            "attempt_id": attempt,
            "elapsed_s": report["elapsed_s"],
            "exit_code": report["exit_code"],
            "cleanup_complete": report["cleanup_complete"],
            "target": report["target"],
            "source": source,
            "checked_at": report["checked_at"],
            "alerts": _slim_alerts(alerts),
            "job_dir": str(job),
            "no_state_change": True,
        }
        if fcf_note:
            summary["fcf_recreation"] = fcf_note
        if related_skills:
            summary["related_skills"] = related_skills[:8]
        artifacts["chk"] = str(chk)
        if publication and published:
            # the delivery directory carries its own validation record: the
            # structured result plus an alert-by-alert scaffold with the KB
            # annotations and an empty explanation slot each - the file four
            # campaigns hand-wrote (r16 make_reports.py, r17 x4) and then
            # hand-copied (r10 x9). VALIDATION.md quotes from it.
            dst = cif.parent
            scaffold = dst / "checkcif_alerts.md"
            artifacts["delivery_checkcif_json"] = str(dst / "checkcif.json")
            artifacts["alerts_scaffold"] = str(scaffold)
            summary["delivered_to"] = [str(dst / "checkcif.json"),
                                       str(scaffold)]
            summary["note"] = (
                "publication-CIF validation with embedded reflection data. "
                "EVERY A/B/C alert must be either fixed or given an evidence-"
                "based explanation in your validation report - "
                "checkcif_alerts.md in the delivery directory is the "
                "scaffold (KB annotation + explanation slot per alert); A "
                "alerts block the 'publication' grade unless they stem from "
                "a disclosed data limitation.")
        elif not publication:
            summary["n_metadata_alerts"] = metadata_alerts
            summary["note"] = (
                "type-1 metadata alerts retained (expected for the minimal "
                "node CIF); 023/029 resolution/completeness artifacts come "
                "from having no embedded reflection data, and PLATON guesses "
                "elements from LABELS. For real validation run write_outputs "
                "then run_checkcif with cif=<output>/final.cif.")
        if delta:
            summary["delta"] = delta
        summary["counts"] = counts
        return ToolResult(ok=True, summary=summary, artifacts=artifacts)


# ==========================================================================
class SubmitIucrCheckcif(_ProjectTool):
    name = "submit_iucr_checkcif"
    description = (
        "Submit a CIF to the OFFICIAL IUCr checkCIF web service "
        "(checkcif.iucr.org) - the authoritative validation journals use. "
        "UPLOADS STRUCTURE DATA TO IUCR: disabled unless the user has enabled "
        "'allow_iucr_upload' in the project settings; ask the user before "
        "using it. Prefer run_checkcif (local PLATON, data never leaves the "
        "machine) for iteration; use this once for the final pre-submission "
        "check. The CIF should embed reflection data (write_outputs "
        "publication CIF does) for full structure-factor validation. BUDGET: "
        "the HTTP exchange is abandoned at timeout_s (default 300 s) and the "
        "tool returns ok=false; the upload may still have reached IUCr, so "
        "check the service rather than resubmitting blindly, and iterate "
        "with run_checkcif locally in the meantime.")
    params_schema = {
        "type": "object",
        "properties": {
            "cif": {"type": "string",
                    "description": "project-relative CIF path (final.cif)"},
            "validation_type": {
                "type": "string",
                "enum": ["checkcif_with_hkl", "checkcif_only"],
                "default": "checkcif_with_hkl"},
            "timeout_s": {"type": "integer", "default": 300},
        },
        "required": ["cif"],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        # explicit per-project opt-in (default OFF): outward-facing upload
        state_file = self.project.dir / ".crystalpilot-workbench.json"
        allowed = False
        if state_file.exists():
            try:
                allowed = bool(json.loads(
                    state_file.read_text(encoding="utf-8"))
                    .get("settings", {}).get("allow_iucr_upload"))
            except (OSError, json.JSONDecodeError):
                allowed = False
        if not allowed:
            return ToolResult.failure(
                "IUCr upload is DISABLED for this project. The user must "
                "enable settings.allow_iucr_upload in "
                ".crystalpilot-workbench.json (or the workbench settings UI) "
                "first - structure data would leave this machine. Use the "
                "local run_checkcif meanwhile.")
        cif = (self.project.dir / str(params["cif"])).resolve()
        if self.project.dir.resolve() not in cif.parents or not cif.exists():
            return ToolResult.failure(f"no such project CIF: {params['cif']}")
        import requests
        job = (self.project.dir / ".crystalpilot" / "refine" / "checkcif" /
               time.strftime("iucr_%Y%m%d_%H%M%S"))
        job.mkdir(parents=True, exist_ok=True)
        try:
            resp = requests.post(
                "https://checkcif.iucr.org/cgi-bin/checkcif_hkl.pl",
                files={"filecif": (cif.name, cif.read_bytes())},
                data={"from_index": "from_index", "runtype": "symmonly",
                      "referer": "checkcif_server", "outputtype": "HTML",
                      "validtype": params.get("validation_type",
                                              "checkcif_with_hkl"),
                      "valout": "vrfabc", "duplic": "duplicno",
                      "UPLOAD": "Send CIF for checking"},
                timeout=int(params.get("timeout_s", 300)))
        except requests.RequestException as e:
            return ToolResult.failure(f"IUCr submission failed: {e}")
        if resp.status_code != 200:
            return ToolResult.failure(f"IUCr returned HTTP {resp.status_code}")
        html = resp.text
        (job / "iucr_report.html").write_text(html, encoding="utf-8",
                                              errors="replace")
        from ..report.checkcif_kb import annotate
        alerts = []
        for m in re.finditer(
                r"(?:PLAT)?(\d{3}|[A-Z]{2,6}\d{2})_ALERT_(\d)_([ABCG])"
                r"\s+([^<\n]*)", html):
            entry: dict[str, Any] = {"code": m.group(1),
                                     "type": int(m.group(2)),
                                     "level": m.group(3),
                                     "text": m.group(4).strip()}
            kb = annotate(m.group(1))
            if kb:
                entry["kb"] = kb
            alerts.append(entry)
        counts = {lv: sum(1 for a in alerts if a["level"] == lv)
                  for lv in "ABCG"}
        pv = re.search(r"PLATON version[^<\n]*", html)
        return ToolResult(ok=True, summary={
            "service": "checkcif.iucr.org (official)",
            "cif": str(params["cif"]),
            "counts": counts, "alerts": alerts,
            "platon_version": pv.group(0) if pv else None,
            "report_html": str(job / "iucr_report.html"),
            "note": ("compare with the local run_checkcif result; explain "
                     "every A/B/C alert in VALIDATION.md"),
            "no_state_change": True,
        }, artifacts={"html": str(job / "iucr_report.html")})


# ==========================================================================

def _mask_obligations(mask_rec: dict | None, moiety: str | None,
                      final_cif_text: str | None) -> list[str]:
    """Reporting duties a MASKED delivery owes (专家纪律 SQUEEZE discipline,
    automated at the write_outputs moment). Facts + duty pointers only -
    the chemical judgment stays in the skills."""
    if not mask_rec:
        return []
    duties: list[str] = []
    if not moiety:
        duties.append(
            "formula_moiety 未提供：掩膜交付的 _chemical_formula_moiety 应包含"
            "客体估计（掩膜电子数 ÷ 候选溶剂电子数换算，如 ', 4(H2O)'）；"
            "确定客体后重新 write_outputs 并传 formula_moiety。")
    duties.append(
        "交付叙述义务（VALIDATION.md）：报告掩膜体积与每胞电子数、把电子数指认"
        "到合成溶剂/客体的化学依据（read_skill mof-guest-evidence-rule）、"
        "以及为何掩膜而非建模（read_skill mof-solvent-mask-discipline）。")
    for enc in mask_rec.get("coordination_encroachment") or []:
        duties.append(
            f"掩膜孔 {enc.get('void')} 侵入金属 {enc.get('metal')} 的配位球"
            f"（≤{enc.get('within_A')} Å），配位溶剂绝不遮掩：要么在该位置"
            "显式建模被配位的溶剂，要么在 VALIDATION.md 给出该金属位点"
            "确实空置的差值密度证据。")
    if final_cif_text is not None and "_platon_squeeze" not in final_cif_text:
        duties.append(
            "final.cif 缺 _platon_squeeze 记录，掩膜信息未进入发表 CIF"
            "（检查活动节点是否在掩膜生效的会话内提交）。")
    return duties


def _disorder_obligations(meta: dict) -> list[str]:
    """Disclosure duty for disordered deliveries: reviewers expect a full
    _refine_special_details description per disorder group (Nat. Chem.
    referee template, skill refine-special-details-templates)."""
    groups = meta.get("disorder_groups") or []
    parts_extra = meta.get("parts_extra") or {}
    n = len(groups) if groups else (1 if parts_extra else 0)
    if n == 0:
        return []
    return [
        f"无序披露义务：模型含 {n} 组 PART 无序，按模板为每处无序写"
        f"精修描述（对象与取向数/占有率收敛值/几何限制/ADP 限制逐条，"
        f"read_skill refine-special-details-templates），并入交付说明与"
        f"VALIDATION.md。"]


# ==========================================================================
# delivery status (provisional / diagnostic / final)
#
# pa1 cage-l2-r1: SUMMARY.md rejected the I2/a model in words while
# final.cif WAS that model; hex-l3-r3 delivered an unmasked 0.185 model
# with a 0.080 masked node in the tree. The honesty lived in prose only -
# nothing machine-readable said what the delivered files claim. The status
# is a comment header in final.cif (legal CIF, survives every parser) and a
# field in REPORT.json / MANIFEST.json; only finalize_delivery writes
# `final`, after the completeness checks in delivery_audit().

DELIVERY_STATUSES = ("provisional", "diagnostic", "final")
STATUS_MEANING = {
    "provisional": ("written by write_outputs and not yet promoted: the "
                    "structure claim stands, but run_checkcif / VALIDATION.md "
                    "/ finalize_delivery have not confirmed the delivery"),
    "diagnostic": ("NOT a structure claim: a model kept for diagnosis "
                   "(rejected space group, trial element, incomplete "
                   "framework, unmasked comparison) - finalize_delivery "
                   "can still SEAL this record for a complete audit trail "
                   "(status stays diagnostic; blocking items are listed, "
                   "not waived) but never promotes it; deliver the claimed "
                   "model with status=provisional to publish"),
    "final": ("promoted by finalize_delivery: complete file set, checkCIF "
              "run on this very CIF, every blocking item resolved or waived "
              "with a reason recorded in REPORT.json finalized.waivers"),
}
_STATUS_LINE_PREFIX = "# CrystalPilot delivery "
_STATUS_PREFIX = _STATUS_LINE_PREFIX + "status: "


def _status_header(status: str, node: str | None, stamp: str,
                   meaning: str | None = None, grade: str | None = None) -> str:
    lines = [
        f"{_STATUS_PREFIX}{status}",
        f"{_STATUS_LINE_PREFIX}meaning: {meaning or STATUS_MEANING[status]}",
        f"{_STATUS_LINE_PREFIX}written: {stamp} from node {node} "
        f"(REPORT.json and MANIFEST.json carry the same status)",
    ]
    if grade:
        # what KIND of CIF this is, in the file itself: a SHELXL ACTA CIF
        # (esds, geometry, reflection statistics) or a model CIF that
        # carries coordinates and whatever statistics were measured for
        # this exact model - usertest 2026-09-08 found out in Olex2
        lines.append(f"{_STATUS_LINE_PREFIX}cif: {grade}")
    return "\n".join(lines) + "\n"


def _grade_line(cif_grade: dict[str, Any] | None) -> str | None:
    """`<grade> - <note>` for the header: the grade word first so a reader
    (or a test) can key on it, the note after it says what that means."""
    if not cif_grade or not cif_grade.get("grade"):
        return None
    note = cif_grade.get("note")
    return f"{cif_grade['grade']}" + (f" - {note}" if note else "")


def strip_status_header(text: str) -> str:
    """Remove only the status comments rewritten when a delivery is finalized."""
    return "".join(ln for ln in text.splitlines(keepends=True)
                   if not ln.startswith(_STATUS_LINE_PREFIX))


def read_status_header(text: str) -> str | None:
    for ln in text.splitlines():
        if ln.startswith(_STATUS_PREFIX):
            return ln[len(_STATUS_PREFIX):].strip()
    return None


def with_status_header(text: str, status: str, node: str | None,
                       stamp: str, meaning: str | None = None,
                       grade: str | None = None) -> str:
    """meaning overrides STATUS_MEANING[status] verbatim - used by
    finalize_delivery to say exactly how many blocking items a `final`
    promotion waived, instead of the generic claim that every one of
    them was resolved (pa-cage: 23 disclosure waivers promoted a
    self-declared unpublishable model to `final` behind that generic
    text)."""
    return (_status_header(status, node, stamp, meaning, grade)
            + strip_status_header(text))


def write_manifest(out: Path, files: list[str], *, scope: str,
                   status: str | None, generated: str | None = None,
                   extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Inventory of delivered files; no content digest or integrity gate."""
    manifest: dict[str, Any] = {
        "schema_version": 2,
        "generated": generated or time.strftime("%Y-%m-%d %H:%M:%S"),
        "scope": scope, "status": status, "files": {}}
    for fname in files:
        fp = out / fname
        if fp.is_file():
            manifest["files"][fname] = {"bytes": fp.stat().st_size}
    if extra:
        manifest.update(extra)
    (out / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


# ==========================================================================
# final.fab + ABIN: a masked refinement is only reproducible with its
# Fourier coefficients. pa1: 17 masked final.res files without an ABIN
# card, 11 deliveries without any .fab, >=5 agents hand-copying job.fab
# with the shell, 4 grepping platon.out for the 995_B reason.

def _res_with_abin(res_text: str) -> tuple[str, bool]:
    """Insert an ABIN card (before WGHT/FVAR, i.e. still in the
    instruction block) unless one is present. Returns (text, inserted)."""
    if re.search(r"^\s*ABIN\b", res_text, re.M | re.I):
        return res_text, False
    lines = res_text.splitlines(keepends=True)
    idx = len(lines)
    for i, ln in enumerate(lines):
        toks = ln.split()
        if toks and toks[0].upper() in ("WGHT", "FVAR", "HKLF"):
            idx = i
            break
    # two REM lines, each under SHELXL's hard 80-character line limit: the
    # original 96-character REM made SHELXL abort on every masked
    # final.res ("INPUT INSTRUCTION ... IS LONGER THAN 80 CHARACTERS"),
    # which silently killed the grader's model-transplant arm (pa3)
    lines.insert(idx, "REM CrystalPilot: solvent-mask Fourier coefficients "
                      "in final.fab\n"
                      "REM (the same .fab file the SHELXL job used)\n"
                      "ABIN\n")
    return "".join(lines), True


def _fab_from_mask(out: Path, node_dir: Path, session) -> str | None:
    """final.fab from the node's cached f_mask (or the live session's) in
    exactly the form run_shelxl exports (P1-complete + Bijvoet mates, see
    tools_shelxl) - the fallback when no matching SHELXL job holds a
    job.fab. Returns a source description, None when no mask is at hand."""
    f_mask = None
    source = None
    pkl = node_dir / "f_mask.pkl"
    if pkl.exists():
        try:
            from libtbx import easy_pickle
            f_mask = easy_pickle.load(str(pkl))["f_mask"]
            source = "node f_mask snapshot (f_mask.pkl)"
        except Exception:  # noqa: BLE001 - fall through to the session
            f_mask = None
    if f_mask is None and session is not None:
        f_mask = (getattr(session, "flags", None) or {}).get("f_mask")
        if f_mask is not None:
            source = "live session f_mask"
    if f_mask is None:
        return None
    from ..io.shelx_writer import write_fab
    write_fab(f_mask.expand_to_p1().generate_bijvoet_mates(),
              out / "final.fab")
    return source


# ==========================================================================
# what the delivered node descends from, and the key facts of the CIF
# (25/28 pa1 runs read REPORT.json back with the shell to write SUMMARY.md)

def _ancestry(nodes, node_id: str | None, limit: int = 1000
              ) -> list[tuple[str, str]]:
    """[(node_id, tool)] from the root to node_id via the parent links."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    cur = node_id
    while cur and cur not in seen and len(out) < limit:
        seen.add(cur)
        try:
            meta = nodes.node_meta(cur)
        except Exception:  # noqa: BLE001 - a pruned ancestor ends the walk
            break
        out.append((cur, str(meta.get("tool") or "")))
        cur = meta.get("parent")
    out.reverse()
    return out


def solution_provenance(ancestry: list[tuple[str, str]],
                        session=None) -> dict[str, Any]:
    """How the delivered model was solved, from the LAST solver node in
    its ancestry (a re-solve in another space group supersedes the first).
    No solver in the lineage = the model was imported with atoms and the
    method is unknown -> '?' with a caveat (never SHELXL's default SHELXT
    claim, never the old forced 'charge flipping')."""
    from ..report.publication import SOLVER_PROVENANCE
    solver = None
    for nid, tool in ancestry:
        if tool in SOLVER_PROVENANCE:
            solver = (nid, tool)
    if solver is None:
        root = ancestry[0] if ancestry else ("?", "?")
        return {"computing": None, "primary": None, "solver_node": None,
                "caveat": (f"结构求解方法未知：模型沿袭自导入的起始模型（节点 "
                           f"{root[0]} {root[1]}），谱系里没有求解器节点，"
                           f"_computing_structure_solution 写为 '?'（SHELXL "
                           f"默认的 SHELXT 声明已去除）；若知道起始模型的求解"
                           f"方法请在 SUMMARY.md 说明。")}
    nid, tool = solver
    computing, primary = SOLVER_PROVENANCE[tool]
    if tool == "interpret_peaks":
        # the solvers themselves commit no node; the live session still
        # knows which engine produced the peaks when the process survived
        info = getattr(session, "cf_info", None) or {}
        if info.get("engine") == "superflip":
            computing = SOLVER_PROVENANCE["solve_superflip"][0]
        elif info:
            computing = SOLVER_PROVENANCE["solve_charge_flipping"][0]
    return {"computing": computing, "primary": primary,
            "solver_node": nid, "solver_tool": tool}


_KEY_FACT_TAGS = {
    "r1_gt": "_refine_ls_R_factor_gt", "r1_all": "_refine_ls_R_factor_all",
    "wr2": "_refine_ls_wR_factor_ref", "goof": "_refine_ls_goodness_of_fit_ref",
    "n_reflns": "_refine_ls_number_reflns",
    "n_params": "_refine_ls_number_parameters",
    "n_restraints": "_refine_ls_number_restraints",
    "diff_density_max": "_refine_diff_density_max",
    "diff_density_min": "_refine_diff_density_min",
    "formula_sum": "_chemical_formula_sum",
    "formula_moiety": "_chemical_formula_moiety",
    "z": "_cell_formula_units_Z", "space_group": "_space_group_name_H-M_alt",
    "temperature_K": "_diffrn_ambient_temperature",
    "wavelength": "_diffrn_radiation_wavelength",
    "radiation_type": "_diffrn_radiation_type",
    "theta_max": "_diffrn_reflns_theta_max",
    "completeness_full": "_diffrn_measured_fraction_theta_full",
    "rint": "_diffrn_reflns_av_R_equivalents",
    "hydrogen_treatment": "_refine_ls_hydrogen_treatment",
    "flack": "_refine_ls_abs_structure_Flack",
}


def cif_key_facts(text: str) -> dict[str, str]:
    """The numbers a SUMMARY.md / VALIDATION.md needs, read from the CIF
    text (values on the same line or, as SHELXL writes the formula, on the
    next line). '?' and '.' are omitted."""
    lines = text.splitlines()
    facts: dict[str, str] = {}
    for key, tag in _KEY_FACT_TAGS.items():
        for i, ln in enumerate(lines):
            if not ln.startswith(tag + " ") and ln.strip() != tag:
                continue
            rest = ln[len(tag):].strip()
            if not rest:
                nxt = next((l.strip() for l in lines[i + 1:] if l.strip()),
                           "")
                rest = "" if (nxt.startswith("_") or nxt.startswith("loop_")
                              or nxt.startswith(";")) else nxt
            if rest and rest not in ("?", "."):
                facts[key] = rest.strip("'")
            break
    return facts


# ==========================================================================
# finalize_delivery support

#: every delivery must carry these before it can be `final` (hex-l2-r3
#: shipped without SUMMARY/VALIDATION and nothing objected)
REQUIRED_DELIVERY_FILES = ("final.cif", "final.fcf", "final.res",
                           "REPORT.json", "checkcif.json", "SUMMARY.md",
                           "VALIDATION.md")


def find_newest_delivery(project_dir: Path) -> Path | None:
    """Newest write_outputs directory: `CrystalPilot Results/<task>/` (the
    grader's layout), one level deeper as a fallback (pa1 cu-l2-r2 wrote
    into <task>/deliverables/), then any REPORT.json+final.cif pair up to
    two levels below the project."""
    root = project_dir / "CrystalPilot Results"
    cands = list(root.glob("*/REPORT.json")) + list(root.glob("*/*/REPORT.json"))
    if not cands:
        cands = [p for p in (list(project_dir.glob("*/REPORT.json"))
                             + list(project_dir.glob("*/*/REPORT.json")))
                 if ".crystalpilot" not in p.parts]
    cands = [p for p in cands if p.with_name("final.cif").exists()]
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime).parent


# ==========================================================================
# SHELXL-job pairing: which run_shelxl job is the active node's job
#
# Keyed on MODEL CONTENT only - the job's R1 / atom rows / FVAR / Z / mask
# state against the node's metrics and model.res. No timestamps, no
# experiment block: a metadata-only change (set_experiment) after the job
# leaves the pairing intact, and final.cif is the job's model plus the
# session's metadata at write time. pa2/pa3: the refusal said "no matching
# job" without the conditions or the numbers, so agents re-ran run_shelxl
# blindly (or after set_experiment, needlessly) or gave up.

JOB_MATCH_R1_TOL = 0.005
JOB_MATCH_FVAR_TOL = 0.02
JOB_MATCH_SITE_TOL = 1e-5
JOB_MATCH_CONDITIONS = (
    f"(1) R1: the job's _refine_ls_R_factor_gt is within {JOB_MATCH_R1_TOL} "
    "of the node's r1_strong",
    "(2) model: job.res and the node's model.res have the same atom count, "
    f"H count and FVAR count (each FVAR within {JOB_MATCH_FVAR_TOL}), and "
    "the same non-H labels with the same element types; all atomic coordinates "
    f"(including H) agree within {JOB_MATCH_SITE_TOL} fractional after integer translations",
    "(3) bookkeeping: the same ZERR Z, the job refined with ABIN/.fab "
    "exactly when the node carries a solvent mask, and the job has its "
    ".ok completion marker",
)
JOB_MATCH_ACTION = (
    "run_shelxl(mode='adopt') on the active node (mode='check' when the "
    "node already IS the SHELXL model), then write_outputs again. If you "
    "only changed metadata (set_experiment: experiment / instrument / "
    "chemistry) no rerun is needed - the pairing is keyed on the model, "
    "and final.cif takes the job's model plus the session's metadata at "
    "write time.")


def _nonh_rows(rows: list[tuple[str, str]]) -> dict[str, str]:
    """{LABEL: element} of the non-hydrogen atoms of a SHELX atom list."""
    from ..chem.labels import normalize_element
    out: dict[str, str] = {}
    for label, el in rows:
        e = normalize_element(el)
        if e == "H":
            continue
        out[str(label).upper()] = e or str(el)
    return out


def _shelx_sites(text: str) -> dict[str, tuple[float, float, float]]:
    labels = {label.upper() for label, _ in _shelx_atom_rows(text)}
    sites = {}
    for line in text.splitlines():
        fields = line.split()
        if fields and fields[0].upper() in ("HKLF", "END"):
            break
        if len(fields) >= 7 and fields[0].upper() in labels:
            try:
                sites[fields[0].upper()] = tuple(float(x) for x in fields[2:5])
            except ValueError:
                continue
    return sites


def _node_match_facts(node_id: str | None, r1: float | None,
                      node_res: str | None, masked: Any) -> dict[str, Any]:
    """What the active node looks like to the pairing legs."""
    facts: dict[str, Any] = {"node": node_id, "r1": r1, "atoms": None,
                             "h": None, "n_fvar": None, "fvar": [],
                             "z": None, "masked": bool(masked), "rows": {}, "sites": {}}
    if node_res is not None:
        from .shelx_cards import instruction_cards_of
        nn, nh, nf = _shelx_atom_stats(node_res)
        facts.update(atoms=nn, h=nh, n_fvar=len(nf), fvar=nf,
                     z=_res_zerr_z(node_res),
                     rows=_nonh_rows(_shelx_atom_rows(node_res)),
                     sites=_shelx_sites(node_res),
                     cards=instruction_cards_of(node_res))
    return facts


def _fmt_match_facts(f: dict[str, Any]) -> str:
    r1 = f.get("r1")
    r1s = f"{r1:.4f}" if isinstance(r1, (int, float)) else "?"

    def s(v: Any) -> str:
        return "?" if v is None else str(v)

    return (f"R1 {r1s}, {s(f.get('atoms'))} atoms / {s(f.get('h'))} H / "
            f"{s(f.get('n_fvar'))} FVAR, Z {s(f.get('z'))}, "
            f"{'masked' if f.get('masked') else 'unmasked'}")


def _job_match_legs(job_name: str, job_cif_text: str,
                    job_res_text: str | None, job_masked: bool,
                    node: dict[str, Any],
                    riding_h_tolerant: bool = False) -> dict[str, Any]:
    """One completed job against the node facts -> candidate record with
    EVERY failed leg listed (nothing short-circuits: the agent sees the
    whole picture, not the first miss).

    riding_h_tolerant: the job is the one the node RECORDS as its own
    measurement (metrics_source.job of a run_shelxl adopt). adopt takes
    SHELXL's heavy atoms verbatim but re-derives the riding H in-process
    (replay_riding_h), so the node's H sit a few thousandths off SHELXL's
    idealized positions; that is the tool's own doing, not a model
    change, and it must not un-pair the node from its job (usertest
    test3-1 18:25 / test3-2 18:31: 'coordinates (including H) ... differ'
    right after an adopt, minimal CIF delivered). Non-H legs stay strict."""
    cand: dict[str, Any] = {"job": job_name, "completed": True, "r1": None,
                            "atoms": None, "h": None, "n_fvar": None,
                            "z": None, "masked": bool(job_masked),
                            "failed": []}
    failed: list[str] = cand["failed"]
    m = re.search(r"_refine_ls_R_factor_gt\s+([0-9.]+)", job_cif_text)
    if not m:
        failed.append("no _refine_ls_R_factor_gt in job.cif")
    else:
        job_r1 = float(m.group(1))
        cand["r1"] = job_r1
        if node["r1"] is not None and abs(job_r1 - node["r1"]) > JOB_MATCH_R1_TOL:
            failed.append(f"R1 {job_r1:.4f} vs node {float(node['r1']):.4f} "
                          f"(tolerance {JOB_MATCH_R1_TOL})")
    if job_res_text is not None and node.get("atoms") is not None:
        # model legs vs the node model: atom count, H count, FVAR count and
        # values, ZERR-Z. The Z leg kills the r21 stale-ACTA trap: after a
        # Z fix (set_z / re-ingest) an OLD adopt job still matched on
        # R1+atoms+FVAR and delivered the wrong formula/Z metadata.
        jn, jh, jf = _shelx_atom_stats(job_res_text)
        cand.update(atoms=jn, h=jh, n_fvar=len(jf))
        if jn != node["atoms"]:
            failed.append(f"atoms {jn} vs node {node['atoms']}")
        if jh != node["h"]:
            failed.append(f"H {jh} vs node {node['h']}")
        nf = node["fvar"]
        if len(jf) != len(nf):
            failed.append(f"FVAR count {len(jf)} vs node {len(nf)} (a free "
                          "variable was added or removed after the job)")
        elif any(abs(a - b) > JOB_MATCH_FVAR_TOL for a, b in zip(jf, nf)):
            failed.append("FVAR moved > 0.02 (check job refined free "
                          "variables the node never adopted - "
                          "run_shelxl(mode='adopt') first)")
        jz = _res_zerr_z(job_res_text)
        cand["z"] = jz
        if jz is not None and node["z"] is not None and jz != node["z"]:
            failed.append(f"Z {jz} vs node {node['z']} (stale job from "
                          "before a Z fix - re-run run_shelxl)")
        # WP2 (informational leg, never fails the pairing: nodes from
        # before effective_state carry no cards): do the job's constraint
        # cards match the node's? The delivery's restartable flag reads it.
        from .shelx_cards import CONSTRAINT_CARD_KEYWORDS, card_keyword, \
            instruction_cards_of
        jc = [c for c in instruction_cards_of(job_res_text)
              if card_keyword(c) in CONSTRAINT_CARD_KEYWORDS]
        nc = [c for c in (node.get("cards") or [])
              if card_keyword(c) in CONSTRAINT_CARD_KEYWORDS]
        cand["constraint_cards"] = {"job": jc, "node": nc,
                                    "agree": set(jc) == set(nc)}
        if jn == node["atoms"]:
            # label/element leg: a retype (edit_atoms reassign) or a rename
            # after the job keeps every count and the copied R1, yet the
            # job's CIF would deliver the OLD labels/types (pa2/pa3 N62/C1)
            jrows = _nonh_rows(_shelx_atom_rows(job_res_text))
            nrows = node["rows"]
            only_job = sorted(set(jrows) - set(nrows))
            only_node = sorted(set(nrows) - set(jrows))
            if only_job or only_node:
                failed.append(f"labels: job has {only_job[:6]} the node "
                              f"lacks, node has {only_node[:6]} the job "
                              "lacks (atoms relabelled after the job - "
                              "re-run run_shelxl)")
            retyped = [f"{lb} job {jrows[lb]} vs node {nrows[lb]}"
                       for lb in sorted(set(jrows) & set(nrows))
                       if jrows[lb] != nrows[lb]]
            if retyped:
                failed.append("element types: " + ", ".join(retyped[:6])
                              + (f" (+{len(retyped) - 6} more)"
                                 if len(retyped) > 6 else "")
                              + " (atoms retyped after the job - re-run "
                                "run_shelxl)")
        job_sites = _shelx_sites(job_res_text)
        node_sites = node.get("sites") or {}
        job_nonh = set(_nonh_rows(_shelx_atom_rows(job_res_text)))
        job_h = set(job_sites) - job_nonh
        node_h = set(node_sites) - set(node["rows"])
        compare = set(job_sites) & set(node_sites)
        if riding_h_tolerant:
            compare -= job_h | node_h
        moved = [label for label in sorted(compare)
                 if any(abs(a - b - round(a - b)) > JOB_MATCH_SITE_TOL
                        for a, b in zip(job_sites[label], node_sites[label]))]
        if moved:
            failed.append(("coordinates: " if riding_h_tolerant
                           else "coordinates (including H): ")
                          + ", ".join(moved[:8])
                          + " differ from the node; adopt the matching model "
                            "before delivery")
        if riding_h_tolerant:
            drifted = [label for label in sorted((job_h & node_h))
                       if any(abs(a - b - round(a - b)) > JOB_MATCH_SITE_TOL
                              for a, b in zip(job_sites[label], node_sites[label]))]
            cand["riding_h_tolerance"] = {
                "h_not_compared": True,
                "n_h_drifted": len(drifted),
                "note": ("this job is the node's recorded measurement; "
                         "riding H are re-derived in-process on adopt, so "
                         "their coordinates are not a pairing leg")}
        if job_h != node_h:
            failed.append(f"H labels: job {sorted(job_h - node_h)[:6]} vs "
                          f"node {sorted(node_h - job_h)[:6]}")
    elif job_res_text is None:
        cand["note"] = "job.res absent: model legs not checked"
    # the solvent mask. A job.fab means the job refined with ABIN; the
    # node's mask record must agree, otherwise final.cif (job) and
    # final.res/REPORT (node) would describe different models (pa1 hex:
    # masked 0.08 nodes next to unmasked 0.185 ones in one tree)
    if bool(job_masked) != bool(node["masked"]):
        failed.append(
            f"mask: job {'with' if job_masked else 'without'} "
            f"ABIN/.fab vs node {'with' if node['masked'] else 'without'} "
            f"solvent mask - re-run run_shelxl on this node")
    return cand


def _job_match_refusal(node: dict[str, Any],
                       candidates: list[dict[str, Any]], n_jobs: int) -> str:
    """The explicit refusal: the conditions with the numbers seen, which
    leg the newest job failed, and the action."""
    head = (f"no SHELXL job matches the active node {node.get('node')} "
            f"(node: {_fmt_match_facts(node)}). A job matches when ALL of: "
            + "; ".join(JOB_MATCH_CONDITIONS) + ". ")
    if n_jobs == 0 or not candidates:
        body = "No run_shelxl job exists in this project yet. "
    else:
        newest = candidates[0]
        if not newest.get("completed"):
            body = (f"Newest job {newest['job']} never completed (no .ok "
                    "marker: SHELXL failed or was killed). ")
        else:
            body = (f"Newest job {newest['job']} "
                    f"({_fmt_match_facts(newest)}) failed on: "
                    + "; ".join(newest.get("failed") or ["?"]) + ". ")
        older = [c for c in candidates[1:] if c.get("failed")]
        if older:
            body += (f"{len(older)} older job(s) rejected too (see "
                     "job_match.candidates). ")
    return head + body + "Action: " + JOB_MATCH_ACTION


# ==========================================================================
# label/element gate: does every delivered label announce its element?
#
# pa2/pa3: SHELXT's placeholder composition left mu3-O/OH atoms labelled
# N62 / C1; the agent retyped some of them (type O, label still N62) and
# never retyped the others. checkCIF, the viewer, the grader and every
# human read the LABEL - nothing at delivery time said so.

_CIF_TOKEN = re.compile(r"'[^']*'|\"[^\"]*\"|\S+")


def _cif_tokens(line: str) -> list[str]:
    out: list[str] = []
    for tok in _CIF_TOKEN.findall(line):
        if tok.startswith("#"):
            break
        if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "'\"":
            tok = tok[1:-1]
        out.append(tok)
    return out


def cif_atom_sites(text: str) -> list[tuple[str, str | None]]:
    """(label, type_symbol) of every _atom_site_ row, read from the CIF
    text alone (no iotbx: nodes.py records iotbx.cif segfaulting on our
    own files, and finalize_delivery runs this on files it did not
    write). type_symbol is None when the loop has no such column."""
    lines = text.splitlines()
    n = len(lines)
    i = 0
    while i < n:
        if lines[i].strip().lower() != "loop_":
            i += 1
            continue
        i += 1
        tags: list[str] = []
        while i < n and lines[i].strip().startswith("_"):
            tags.append(lines[i].strip().split()[0])
            i += 1
        if "_atom_site_label" not in tags:
            continue
        li = tags.index("_atom_site_label")
        ti = (tags.index("_atom_site_type_symbol")
              if "_atom_site_type_symbol" in tags else None)
        tokens: list[str] = []
        while i < n:
            s = lines[i].strip()
            low = s.lower()
            if (s.startswith("_") or low.startswith("loop_")
                    or low.startswith("data_")):
                break
            if s.startswith(";"):
                i += 1
                while i < n and not lines[i].startswith(";"):
                    i += 1
                i += 1
                tokens.append("")
                continue
            if s and not s.startswith("#"):
                tokens.extend(_cif_tokens(s))
            i += 1
        ncol = len(tags)
        rows: list[tuple[str, str | None]] = []
        for k in range(0, len(tokens) - ncol + 1, ncol):
            row = tokens[k:k + ncol]
            rows.append((row[li], row[ti] if ti is not None else None))
        return rows
    return []


def label_element_audit(res_text: str | None,
                        cif_text: str | None) -> dict[str, Any]:
    """The label/element gate over the delivered files (final.res atom
    list + final.cif _atom_site loop). H atoms are skipped (riding labels
    follow the carrier). Returns
    {mismatches: [{label, label_element, type, where}], peak_labels: [..],
     type_conflicts: ['N62: final.res O vs final.cif N'], n_checked}."""
    from ..chem.labels import normalize_element, parse_label
    sources: list[tuple[str, list]] = []
    if res_text:
        sources.append(("final.res", _shelx_atom_rows(res_text)))
    if cif_text:
        sources.append(("final.cif", cif_atom_sites(cif_text)))
    mismatches: list[dict[str, Any]] = []
    index: dict[tuple[str, str], dict[str, Any]] = {}
    peaks: list[str] = []
    maps: dict[str, dict[str, str]] = {}
    for where, rows in sources:
        emap: dict[str, str] = {}
        for label, typ in rows:
            el = normalize_element(typ) if typ else None
            if el == "H":
                continue
            pl = parse_label(label)
            if pl.kind == "peak":
                if str(label).upper() not in {q.upper() for q in peaks}:
                    peaks.append(str(label))
                continue
            if el is None:
                continue                  # unreadable type: nothing to compare
            emap[str(label).upper()] = el
            if pl.element != el:
                key = (str(label).upper(), el)
                rec = index.get(key)
                if rec is None:
                    rec = {"label": str(label), "label_element": pl.element,
                           "type": el, "where": [where]}
                    index[key] = rec
                    mismatches.append(rec)
                elif where not in rec["where"]:
                    rec["where"].append(where)
        maps[where] = emap
    conflicts: list[str] = []
    if "final.res" in maps and "final.cif" in maps:
        a, b = maps["final.res"], maps["final.cif"]
        for lb in sorted(set(a) & set(b)):
            if a[lb] != b[lb]:
                conflicts.append(f"{lb}: final.res {a[lb]} vs final.cif {b[lb]}")
    n_checked = len({lb for emap in maps.values() for lb in emap})
    return {"mismatches": mismatches, "peak_labels": peaks,
            "type_conflicts": conflicts, "n_checked": n_checked}


def _suggest_label(label: str, element: str) -> str:
    """'N62' typed O -> 'O62'; 'C1' typed Cu -> 'CU1' (SHELX uppercases)."""
    from ..chem.labels import parse_label
    rest = label[len(parse_label(label).prefix):]
    return element.upper() + (rest or "1")


def _label_gate_messages(audit: dict[str, Any], accepted: bool) -> list[str]:
    """Blocking coherence messages of the label gate: Q labels always,
    mismatches unless accepted, res/cif type conflicts always."""
    out: list[str] = []
    q = audit.get("peak_labels") or []
    if q:
        out.append(
            f"peak labels in the delivery (never accepted): {', '.join(q[:8])}"
            + (f" (+{len(q) - 8} more)" if len(q) > 8 else "")
            + " - a Q peak is not an atom: delete it (edit_atoms delete) or "
              "give it an element (edit_atoms reassign) AND a label "
              "(rename_atoms(mode='map')), then run_shelxl and write_outputs "
              "again")
    mm = audit.get("mismatches") or []
    if mm and not accepted:
        shown = mm[:8]
        listing = "; ".join(
            f"{m['label']} is labelled {m['label_element'] or 'no element'} "
            f"but typed {m['type']}" for m in shown)
        rename_map = ", ".join(
            f"'{m['label']}': '{_suggest_label(m['label'], m['type'])}'"
            for m in shown)
        reassign = ", ".join(f"{m['label']} -> {m['label_element']}"
                             for m in shown if m["label_element"])
        out.append(
            f"label/element mismatch on {len(mm)} atom(s) - readers, "
            f"checkCIF and the grader take the element from the LABEL: "
            f"{listing}"
            + (f" (+{len(mm) - 8} more)" if len(mm) > 8 else "")
            + f". One call fixes it: rename_atoms(mode='map', "
              f"map={{{rename_map}}}) when the TYPE is right (adjust a "
              "label that is already taken), or edit_atoms(operations="
              "[{'action': 'reassign', 'atoms': [...], 'element': ...}]) "
              "when the LABEL is right"
            + (f" ({reassign})" if reassign else "")
            + "; then run_shelxl and write_outputs again. A deliberately "
              "unconventional labelling passes with write_outputs("
              "accept_label_mismatch=true, reason='...') - the reason is "
              "recorded in REPORT.json / MANIFEST.json")
    tc = audit.get("type_conflicts") or []
    if tc:
        out.append(
            "element type differs between final.res and final.cif for "
            + "; ".join(tc[:8])
            + (f" (+{len(tc) - 8} more)" if len(tc) > 8 else "")
            + " (a stale SHELXL job or model.cif) - re-run run_shelxl on "
              "the active node, then write_outputs again")
    return out


def _label_gate_fatal(out: Path, report: dict[str, Any]) -> list[str]:
    """finalize_delivery's re-run of the gate on the delivered files;
    mismatches write_outputs recorded as accepted (with a reason) pass."""
    cif_p, res_p = out / "final.cif", out / "final.res"
    if not cif_p.exists():
        return []
    try:
        audit = label_element_audit(
            res_p.read_text(encoding="utf-8", errors="replace")
            if res_p.exists() else None,
            cif_p.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:  # noqa: BLE001 - an unreadable delivery IS the finding
        return [f"label/element audit could not read the delivery: {e}"]
    acc = report.get("label_mismatch_accepted") or {}
    accepted = {(str(m.get("label", "")).upper(), m.get("type"))
                for m in acc.get("mismatches") or []}
    audit["mismatches"] = [m for m in audit["mismatches"]
                           if (m["label"].upper(), m["type"]) not in accepted]
    return _label_gate_messages(audit, accepted=False)


def delivery_audit(out: Path) -> dict[str, Any]:
    """Completeness audit of a delivery directory.

    fatal    - cannot be waived: missing files, a checkCIF run that did
               not see this final.cif, coherence issues
    blocking - must be resolved or waived WITH a reason to reach 'final';
               for a 'diagnostic' delivery these are sealed as open_items
               INSTEAD of being waived (the audit trail IS the point of a
               diagnostic record - it is not a structure claim): every
               A-level checkCIF alert and every REPORT.json `unresolved`
               entry
    """
    fatal: list[str] = []
    blocking: list[dict[str, str]] = []
    report: dict[str, Any] = {}
    rp = out / "REPORT.json"
    if rp.exists():
        try:
            report = json.loads(rp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            fatal.append(f"REPORT.json unreadable: {e}")
    status = report.get("status")
    # A 'diagnostic' record is sealed for its audit trail, not promoted:
    # what it LACKS (no fcf because no SHELXL job matched, no checkCIF,
    # no VALIDATION.md) is listed as an open item, never a reason to leave
    # SUMMARY/REPORT/final.res outside any inventory (usertest test3-2: the
    # user's diagnostic delivery was refused three times and never sealed).
    # Missing final.cif / final.res / REPORT.json stay fatal for both.
    soft_for_diagnostic = {"final.fcf", "checkcif.json", "VALIDATION.md"}
    for fname in REQUIRED_DELIVERY_FILES:
        if not (out / fname).exists():
            hint = {"final.fcf": " (no matching run_shelxl job at "
                                 "write_outputs time - run run_shelxl then "
                                 "write_outputs again)",
                    "checkcif.json": " (run_checkcif(cif=<dir>/final.cif) "
                                     "has not been run on this delivery)",
                    "SUMMARY.md": " (the Chinese summary the project "
                                  "convention requires)",
                    "VALIDATION.md": " (alert-by-alert explanation; "
                                     "checkcif_alerts.md is the scaffold)",
                    }.get(fname, "")
            if status == "diagnostic" and fname in soft_for_diagnostic:
                blocking.append({"item": f"file:{fname}",
                                 "text": f"missing {fname}{hint}"})
            else:
                fatal.append(f"missing {fname}{hint}")
    # the hand-over set: a person continues from ins + hkl (+ fab); their
    # absence blocks a `final` promotion and is an open item of a
    # diagnostic seal. p4p is an input - reported, never blocking.
    for fname in ("final.ins", "final.hkl"):
        if not (out / fname).exists():
            blocking.append({"item": f"file:{fname}",
                             "text": f"missing {fname} (write_outputs writes it; "
                                     "re-run write_outputs on this node)"})
    missing_inputs: list[dict[str, str]] = []
    if not (out / "final.p4p").exists():
        p4p_note = ((report.get("files") or {}).get("final.p4p") or {}).get("note")
        missing_inputs.append({"item": "file:final.p4p",
                               "text": "final.p4p not delivered (instrument cell "
                                       "record, an input): "
                                       + str(p4p_note or "not on record")})
    if report.get("mask") and not (out / "final.fab").exists():
        fatal.append("missing final.fab for a masked delivery (write_outputs "
                     "writes it from the SHELXL job / node mask - re-run "
                     "write_outputs)")
    for ci in report.get("coherence_issues") or []:
        fatal.append(f"coherence issue recorded at write time: {ci}")
    # the label/element gate, re-run on the files as they are NOW (hand
    # edits, deliveries written before the gate existed); a message the
    # write-time record already carries is not repeated
    for msg in _label_gate_fatal(out, report):
        if not any(msg in f for f in fatal):
            fatal.append(msg)
    cif_p = out / "final.cif"
    cc_p = out / "checkcif.json"
    alerts_a: list[dict[str, Any]] = []
    counts = None
    if cif_p.exists() and cc_p.exists():
        cc: dict[str, Any] | None
        try:
            cc = json.loads(cc_p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            cc = None
            fatal.append(f"checkcif.json unreadable: {e}")
        if cc is not None:
            from ..report.checkcif import report_issue
            execution_issue = report_issue(cc)
            if execution_issue:
                fatal.append(execution_issue)
            else:
                counts = cc.get("counts")
                alerts_a = [a for a in cc["alerts"] if a.get("level") == "A"]
            if isinstance(cc, dict):
                source_issue = delivery_source_issue(out, report, cc)
                if source_issue:
                    fatal.append(source_issue)
    seen: set[str] = set()
    for a in alerts_a:
        key = f"alert:{a.get('code')}_A"
        if key in seen:
            continue
        seen.add(key)
        blocking.append({"item": key, "text": str(a.get("text", ""))[:100]})
    for i, u in enumerate(report.get("unresolved") or [], 1):
        blocking.append({"item": f"unresolved#{i}", "text": str(u)[:160]})
    return {"fatal": fatal, "blocking": blocking, "report": report,
            "status": status, "checkcif_counts": counts,
            "missing_inputs": missing_inputs}


class WriteOutputs(_ProjectTool):
    name = "write_outputs"
    description = (
        "Write the final deliverables from the ACTIVE node into an output "
        "directory: final.res (SHELX), final.cif (PUBLICATION-grade when a "
        "matching run_shelxl job exists: SHELXL ACTA backbone with esds + "
        "experiment metadata + solvent-mask documentation), final.fcf "
        "(structure factors), REPORT.json (metrics, node lineage, restraints, "
        "synthesis priors, CIF caveats). PAIRING SEMANTICS: the publication "
        "CIF is assembled from the newest COMPLETED run_shelxl job whose "
        "MODEL is the active node's - R1 within 0.005, same atom/H/FVAR "
        "counts (FVARs within 0.02), same non-H labels and element types, "
        "same ZERR-Z and mask state (the chosen job is returned as "
        "shelxl_job; every rejection reason is listed in job_mismatches, "
        "and a refusal spells out the conditions with the numbers seen in "
        "job_match). So run run_shelxl FIRST, and re-run it after anything "
        "that changes the MODEL (edits, renames, retypes, set_z, "
        "set_weights, mask on/off) - otherwise the newest matching job is "
        "stale or absent and you get a minimal CIF. Metadata-only changes "
        "(set_experiment: experiment / instrument / chemistry) need NO "
        "rerun: final.cif takes the job's model plus the session's "
        "metadata at write time. List "
        "unresolved issues honestly in 'unresolved'. Masked deliveries "
        "also get final.fab (the job's ABIN coefficients; final.res gains "
        "the ABIN card) and return mask_obligations - the reporting duties "
        "(moiety with guest estimate, electron-count chemistry in "
        "VALIDATION.md) the delivery still owes; settle them before "
        "finishing. STATUS: every delivery carries a machine-readable "
        "status (comment header of final.cif + REPORT.json): "
        "'provisional' (default; a structure claim awaiting checkCIF / "
        "VALIDATION.md), 'diagnostic' (NOT a structure claim - a rejected "
        "space group, trial element or unmasked comparison kept for the "
        "record; finalize_delivery can still SEAL it into an audited "
        "MANIFEST without ever promoting it), 'final' (only "
        "finalize_delivery grants it). The reply "
        "returns key_facts (R1/wR2/GooF/formula/Z/mask numbers) and "
        "cif_missing_metadata (each '?' slot with the checkCIF alert it "
        "raises and the set_experiment key that fills it) - no need to "
        "read REPORT.json back with the shell. SETTING: the reply's "
        "setting_change says which setting of the space group the "
        "delivery stands in; when it is not the ITA reference setting "
        "(an origin-shifted SHELXT solution, say) the symmetry NAMES are "
        "written true for the operator loop (Hall symbol carries the "
        "origin, H-M '?' when no tabulated symbol fits) and cb_op is the "
        "change of basis that WOULD reach the reference setting - "
        "reported, never applied (applied=false), because final.res/.fcf/"
        ".fab are the refinement's own files. Journals expect the "
        "reference setting: to deliver there, apply cb_op at the solution "
        "end and refine again. LABEL GATE: every non-H "
        "label must announce its scatterer's element by the SHELX "
        "convention (leading one/two letters: CL1 = Cl, OW1 = O, ZR1 = Zr) "
        "because checkCIF, the viewer, the grader and every reader type "
        "atoms from LABELS; a mismatch (N62 typed O, C1 typed Zr) or a "
        "surviving Q peak label is a blocking coherence issue that names "
        "the one-call fix (rename_atoms(mode='map') when the type is "
        "right, edit_atoms reassign when the label is right). A knowingly "
        "unconventional labelling passes with accept_label_mismatch=true "
        "plus reason (recorded in REPORT.json / MANIFEST.json); Q labels "
        "never pass.")
    params_schema = {
        "type": "object",
        "properties": {
            "output_dir": {"type": "string",
                           "description": "relative to the project directory"},
            "accept_label_mismatch": {
                "type": "boolean", "default": False,
                "description": "let a KNOWINGLY unconventional labelling "
                               "through the label/element gate (label "
                               "prefix != scatterer element); requires "
                               "`reason`; the mismatches and the reason "
                               "are recorded in REPORT.json "
                               "label_mismatch_accepted and MANIFEST.json. "
                               "Q (peak) labels are never accepted"},
            "reason": {
                "type": "string",
                "description": "with accept_label_mismatch: why the "
                               "labelling is intended (>= 12 chars, e.g. "
                               "'OW/OH labels follow the group's water "
                               "convention, documented in SUMMARY.md')"},
            "summary_note": {"type": "string", "default": ""},
            "unresolved": {"type": "array", "items": {"type": "string"},
                           "default": [],
                           "description": "honest list of remaining issues"},
            "formula_moiety": {
                "type": "string",
                "description": "optional _chemical_formula_moiety, e.g. "
                               "'C34 H18 O16 Zr6, 4(OH)'"},
            "status": {
                "type": "string",
                "enum": list(DELIVERY_STATUSES),
                "default": "provisional",
                "description": "provisional (default) | diagnostic (model "
                               "kept for diagnosis, not a structure claim) "
                               "| final (recorded as provisional: only "
                               "finalize_delivery can promote, after "
                               "run_checkcif on the written CIF)"},
            "pair_with_shelxl": {
                "type": "boolean", "default": True,
                "description": "when no SHELXL job matches the active node, "
                               "run a zero-cycle SHELXL job on it (L.S. 0: "
                               "nothing moves) so final.fcf and the R "
                               "factors in final.cif are THIS model's; "
                               "false = deliver the model CIF with the "
                               "node's own records only"},
            "shelxl_timeout_s": {"type": "integer", "default": 180,
                                 "description": "budget of that zero-cycle job"},
        },
        "required": ["output_dir"],
    }

    def _zero_cycle_job(self, ctx: ToolContext,
                        params: dict[str, Any]) -> dict[str, Any]:
        """A SHELXL job whose model IS the active node: L.S. 0 computes the
        R factors and writes the .fcf without moving an atom (SHELXL still
        refuses ACTA at zero cycles, so no job.cif - the model CIF carries
        these numbers instead). Nothing is committed. usertest test3-2
        (18:29-18:35): without this the agent moved atoms and ran one
        unconverged cycle (max shift/su 40.7) just to obtain a CIF."""
        import os
        from .tools_shelxl import DEFAULT_SHELXL, RunShelxl
        exe = Path(os.environ.get("CRYSTALPILOT_SHELXL", str(DEFAULT_SHELXL)))
        if not exe.exists():
            return {"skipped": f"shelxl.exe not available at {exe}"}
        if getattr(ctx, "session", None) is None:
            return {"skipped": "no live session to run SHELXL on"}
        try:
            r = RunShelxl(self.project).run(
                ctx, mode="check", l_s=0,
                timeout_s=int(params.get("shelxl_timeout_s", 180)))
        except Exception as e:  # noqa: BLE001 - the delivery goes on without it
            return {"error": f"{type(e).__name__}: {e}"}
        if not r.ok:
            return {"error": r.error}
        job = Path(str(r.summary.get("job_dir") or ""))
        fcf = job / "job.fcf"
        return {"job": job.name, "job_dir": str(job),
                "shelxl": r.summary.get("shelxl") or {},
                "fcf": fcf if fcf.exists() else None,
                "note": "zero-cycle SHELXL job on the delivered node: R "
                        "factors and final.fcf of this exact model; no "
                        "refinement, no node"}

    def _publication_cif(self, node_meta: dict, out: Path,
                         moiety: str | None,
                         solution: dict[str, Any] | None = None
                         ) -> dict[str, Any]:
        """Assemble final.cif from the newest MATCHING shelxl job; returns a
        status dict. Falls back to the minimal viewer CIF on any mismatch.
        A masked job's job.fab is copied to final.fab - the very
        coefficients that produced the delivered R1.

        The pairing is keyed on model content only (JOB_MATCH_CONDITIONS,
        _job_match_legs): nothing here reads timestamps or the experiment
        block, so a metadata-only change after the job keeps the match
        and the CIF carries the session's metadata as of THIS call."""
        p = self.project
        node_id = (node_meta.get("id") or node_meta.get("node")
                   or p.nodes.state()["active_node"])
        jobs = sorted((p.dir / ".crystalpilot" / "refine" / "shelxl").glob(
            "job_*/job.cif"), reverse=True)
        metrics = node_meta.get("metrics") or {}
        node_res = None
        node_dir = p.nodes.node_dir(node_id)
        if (node_dir / "model.res").exists():
            node_res = (node_dir / "model.res").read_text(
                encoding="utf-8", errors="replace")
        node = _node_match_facts(node_id, metrics.get("r1_strong"), node_res,
                                 node_meta.get("mask"))
        node_public = {k: node[k] for k in ("node", "r1", "atoms", "h",
                                            "n_fvar", "z", "masked")}
        mismatches: list[str] = []
        candidates: list[dict[str, Any]] = []
        # the job the node itself names as its measurement comes first: a
        # run_shelxl adopt records metrics_source.job, and that job IS the
        # node's model by construction (heavy atoms verbatim; riding H
        # re-derived - see _job_match_legs riding_h_tolerant)
        ms = node_meta.get("metrics_source") or {}
        linked = (str(ms["job"]) if node_meta.get("metrics_current")
                  and ms.get("engine") == "SHELXL" and ms.get("job") else None)
        if linked:
            jobs = ([j for j in jobs if j.parent.name == linked]
                    + [j for j in jobs if j.parent.name != linked])
        for cif_path in jobs:
            job_name = cif_path.parent.name
            # a failed SHELXL run leaves the previous job.cif in an older
            # dir - only jobs run_shelxl marked complete are trusted
            if not (cif_path.parent / ".ok").exists():
                mismatches.append(f"{job_name}: no completion "
                                  "marker (failed or pre-marker job)")
                candidates.append({"job": job_name, "completed": False,
                                   "failed": ["no completion marker"]})
                continue
            text = cif_path.read_text(encoding="utf-8", errors="replace")
            # an intermediate job.cif keeps only a marker where SHELXL wrote
            # the reflection list; the publication CIF must carry the data
            from .storage import restore_embedded_hkl
            try:
                text = restore_embedded_hkl(text, cif_path.parent)
            except FileNotFoundError as e:
                mismatches.append(f"{job_name}: {e}")
                candidates.append({"job": job_name, "completed": True,
                                   "failed": ["reflection block not restorable"]})
                continue
            job_res_p = cif_path.with_name("job.res")
            job_res_text = (job_res_p.read_text(encoding="utf-8",
                                                errors="replace")
                            if job_res_p.exists() else None)
            cand = _job_match_legs(job_name, text, job_res_text,
                                   cif_path.with_name("job.fab").exists(),
                                   node, riding_h_tolerant=(job_name == linked))
            candidates.append(cand)
            if cand["failed"]:
                mismatches.append(f"{job_name}: " + "; ".join(cand["failed"]))
                continue
            from ..report.publication import assemble_publication_cif
            mask_info = (node_meta.get("mask") or {}).get("info")
            mask_params = (node_meta.get("mask") or {}).get("params")
            assembled, rep = assemble_publication_cif(
                text, experiment=p.experiment() if hasattr(p, "experiment")
                else {}, mask_info=mask_info, moiety=moiety,
                solution=solution, mask_params=mask_params)
            (out / "final.cif").write_text(assembled, encoding="utf-8")
            fcf = cif_path.with_name("job.fcf")
            if fcf.exists():
                shutil.copy(fcf, out / "final.fcf")
            fab = cif_path.with_name("job.fab")
            fab_source = None
            if fab.exists():
                shutil.copy(fab, out / "final.fab")
                fab_source = f"SHELXL job {job_name} job.fab"
            return {"publication": True, "shelxl_job": job_name,
                    "shelxl_r1": cand["r1"], "n_filled": len(rep["filled"]),
                    "remaining_placeholders": rep["remaining_placeholders"],
                    "missing_metadata": rep.get("missing_metadata") or [],
                    "symmetry_names_corrected":
                        rep.get("symmetry_names_corrected") or [],
                    "caveats": rep["caveats"], "fcf": fcf.exists(),
                    "fab": fab.exists(), "fab_source": fab_source,
                    "job_match": {"matched": True, "job": job_name,
                                  "node": node_public,
                                  "linked_job": linked,
                                  "via": ("node metrics_source" if job_name == linked
                                          else "model content scan"),
                                  **({"riding_h_tolerance": cand["riding_h_tolerance"]}
                                     if cand.get("riding_h_tolerance") else {}),
                                  "conditions": list(JOB_MATCH_CONDITIONS)},
                    **({"job_mismatches": mismatches[:6]}
                       if mismatches else {})}
        refusal = _job_match_refusal(node_public, candidates, len(jobs))
        return {"publication": False,
                "job_mismatches": mismatches[:6],
                "job_match": {
                    "matched": False, "node": node_public,
                    "linked_job": linked,
                    "conditions": list(JOB_MATCH_CONDITIONS),
                    "n_jobs_seen": len(jobs),
                    "newest_job": candidates[0]["job"] if candidates else None,
                    "newest_job_failed_on": (candidates[0].get("failed")
                                             if candidates else None),
                    "candidates": candidates[:6],
                    "action": JOB_MATCH_ACTION,
                    "refusal": refusal},
                "fab": False, "fab_source": None,
                "caveats": ["final.cif 是极简结构 CIF（无匹配的 run_shelxl 作业"
                            "，请先 run_shelxl 再 write_outputs 以获得发表级 "
                            "CIF + fcf）"]
                + ([f"最近作业被拒绝的原因：{mismatches[0]}"]
                   if mismatches else [])
                + [refusal]}

    @staticmethod
    def _delivery_coherence(out: Path, report: dict[str, Any],
                            publication: bool,
                            restart: dict[str, Any] | None = None) -> list[str]:
        """Same-source assertions across the files JUST written: the
        r15 near-miss (final.cif paired with the wrong ACTA job) and the
        2-8 min hand-run Select-String loops every campaign ended with
        become one structured check."""
        issues: list[str] = []
        rn = rz = None
        res_p = out / "final.res"
        if res_p.exists():
            res_text = res_p.read_text(encoding="utf-8", errors="replace")
            rn, _rh, _rf = _shelx_atom_stats(res_text)
            rz = _res_zerr_z(res_text)
        cif_p = out / "final.cif"
        if not cif_p.exists():
            return ["final.cif was not written"]
        try:
            import iotbx.cif
            cif = iotbx.cif.reader(input_string=cif_p.read_text(
                encoding="utf-8", errors="replace")).model()
            block = next(iter(cif.values()))
        except Exception as e:  # noqa: BLE001 - unparseable IS the finding
            return [f"final.cif does not parse as CIF: {e}"]

        def _num(key, cast=float):
            v = block.get(key)
            if v is None:
                return None
            try:
                return cast(str(v).split("(")[0])
            except ValueError:
                return None

        # the space-group NAMES must be true for the operator loop beside
        # them, in every setting: an origin-shifted SHELXT solution
        # published as the reference-setting symbol is a file cctbx refuses
        # outright (CifBuilderError) and PLATON flags with alert 120
        from ..io.cif_symmetry import check_cif_symmetry, conflict_summary
        try:
            sym = check_cif_symmetry(cif_p.read_text(encoding="utf-8",
                                                     errors="replace"))
        except Exception as e:  # noqa: BLE001 - report, never crash
            sym = {"checked": False, "error": f"{type(e).__name__}: {e}"}
        if sym.get("consistent") is False:
            issues.append("final.cif symmetry: " + conflict_summary(sym))

        n_cif = len(block.get("_atom_site_label") or [])
        if rn is not None and n_cif and rn != n_cif:
            issues.append(f"atom count: final.res {rn} vs final.cif {n_cif}")
        cz = _num("_cell_formula_units_Z", int)
        if rz is not None and cz is not None and rz != cz:
            issues.append(f"Z: final.res ZERR {rz} vs final.cif {cz}")
        if publication:
            cif_r1 = _num("_refine_ls_R_factor_gt")
            node_r1 = (report.get("metrics") or {}).get("r1_strong")
            if (cif_r1 is not None and node_r1 is not None
                    and abs(cif_r1 - node_r1) > 0.005):
                issues.append(f"R1: final.cif {cif_r1} vs node metrics "
                              f"{node_r1} (REPORT.json)")
        # WP2: the delivered .res must carry the instruction cards the
        # paired job refined with, or a restart refines another model
        if restart and not restart.get("restartable", True):
            issues.append(
                "instruction cards: final.res lacks "
                + ", ".join(restart.get("missing_constraints") or [])
                + (" and carries " + ", ".join(
                    c for c in (restart.get("extra_in_res") or []))
                   if restart.get("extra_in_res") else "")
                + " - not restartable as the paired SHELXL job")
        return issues

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        p = self.project
        out = (p.dir / str(params["output_dir"])).resolve()
        if p.dir.resolve() not in out.parents and out != p.dir.resolve():
            return ToolResult.failure("output_dir must stay inside the project")
        from .data_versions import is_protected
        if is_protected(p.dir, out):
            return ToolResult.failure("Archived inputs/nodes are read-only; choose an output directory outside the archive")
        status = str(params.get("status") or "provisional")
        if status not in DELIVERY_STATUSES:
            return ToolResult.failure(
                f"status must be one of {list(DELIVERY_STATUSES)}")
        accept_labels = bool(params.get("accept_label_mismatch"))
        accept_reason = str(params.get("reason") or "").strip()
        if accept_labels and len(accept_reason) < 12:
            return ToolResult.failure(
                "accept_label_mismatch=true needs a real reason (>= 12 "
                "chars): it is recorded in REPORT.json / MANIFEST.json as "
                "the disclosure that the labelling is deliberately "
                "unconventional (peak Q labels are never accepted). Nothing "
                "was written.")
        status_note = None
        if status == "final":
            # `final` is a verdict on the WHOLE delivery (checkCIF run on
            # this CIF, VALIDATION.md, waivers) - nothing write_outputs can
            # know at write time; only finalize_delivery grants it
            status = "provisional"
            status_note = ("status 'final' is granted by finalize_delivery "
                           "only (checkCIF must run on the written CIF "
                           "first) - written as 'provisional'")
        out.mkdir(parents=True, exist_ok=True)
        delivery_revision = next_delivery_revision(out)
        st = p.nodes.state()
        node = st["active_node"]
        if node is None:
            return ToolResult.failure("no node to export")
        meta = p.nodes.node_meta(node)
        ndir = p.nodes.node_dir(node)
        session = getattr(ctx, "session", None) or getattr(p, "session", None)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        ancestry = _ancestry(p.nodes, node)
        solution = solution_provenance(ancestry, session)
        pub = self._publication_cif(meta, out,
                                    params.get("formula_moiety") or None,
                                    solution=solution)
        from . import deliver_files as _df
        zero_cycle: dict[str, Any] | None = None
        cif_grade: dict[str, Any]
        if pub["publication"]:
            cif_grade = {"grade": "shelxl-acta",
                         "note": f"SHELXL ACTA CIF of job {pub.get('shelxl_job')} "
                                 "(esds, geometry tables, reflection statistics)"}
        else:
            if (ndir / "model.cif").exists():
                shutil.copy(ndir / "model.cif", out / "final.cif")
            if params.get("pair_with_shelxl", True):
                zero_cycle = self._zero_cycle_job(ctx, params)
            if (out / "final.cif").exists():
                text0 = (out / "final.cif").read_text(encoding="utf-8",
                                                      errors="replace")
                text1, cif_grade = _df.enrich_model_cif(
                    text0, meta, zero_cycle if zero_cycle
                    and zero_cycle.get("shelxl") else None)
                (out / "final.cif").write_text(text1, encoding="utf-8")
            else:
                cif_grade = {"grade": "model", "added": [],
                             "note": "no model.cif for this node"}
            if zero_cycle and zero_cycle.get("fcf"):
                shutil.copy(zero_cycle["fcf"], out / "final.fcf")
                pub["fcf"] = True
                pub["fcf_source"] = f"zero-cycle SHELXL job {zero_cycle['job']}"
            if zero_cycle:
                pub["zero_cycle_job"] = {k: v for k, v in zero_cycle.items()
                                         if k != "fcf"}
        # final.fab: the job's own file when a job matched, else the node's
        # cached mask in the same P1 form; final.res then carries ABIN so
        # res + hkl + fab reproduce the delivered R1
        masked = bool(meta.get("mask"))
        fab_caveat = None
        if masked and not pub.get("fab"):
            try:
                src = _fab_from_mask(out, ndir, session)
            except Exception as e:  # noqa: BLE001 - report, never block
                src = None
                fab_caveat = f"final.fab could not be written: {e}"
            if src:
                pub["fab"], pub["fab_source"] = True, src
            elif fab_caveat is None:
                fab_caveat = ("final.fab not written: the node carries a mask "
                              "but neither a matching SHELXL job.fab nor an "
                              "f_mask snapshot is available - checkout the "
                              "node (mask restored) and write_outputs again")
        res_text = (ndir / "model.res").read_text(encoding="utf-8",
                                                  errors="replace")
        abin_added = False
        if pub.get("fab"):
            res_text, abin_added = _res_with_abin(res_text)
        (out / "final.res").write_text(res_text, encoding="utf-8")
        if fab_caveat:
            pub.setdefault("caveats", []).append(fab_caveat)
        # the hand-over set (res / cif / ins / hkl / p4p): each file with the
        # source it was made from, in REPORT.json files / MANIFEST.json
        provenance: dict[str, Any] = {
            "final.res": {"from": f"node {node} model.res"
                                  + (" + ABIN card" if abin_added else "")},
            "final.cif": dict(cif_grade),
        }
        provenance["final.cif"]["from"] = (
            f"SHELXL job {pub.get('shelxl_job')} job.cif + session metadata"
            if pub.get("publication") else f"node {node} model.cif + statistics block")
        if pub.get("fcf"):
            provenance["final.fcf"] = {"from": pub.get("fcf_source")
                                       or f"SHELXL job {pub.get('shelxl_job')} job.fcf"}
        if pub.get("fab"):
            provenance["final.fab"] = {"from": pub.get("fab_source")}
        # final.ins: the deck that reproduces the delivered numbers
        job_ins_p = (p.dir / ".crystalpilot" / "refine" / "shelxl"
                     / str(pub.get("shelxl_job") or "") / "job.ins")
        if pub.get("publication") and pub.get("shelxl_job") and job_ins_p.exists():
            shutil.copy(job_ins_p, out / "final.ins")
            provenance["final.ins"] = {
                "from": f"SHELXL job {pub['shelxl_job']} job.ins (the deck "
                        "that produced final.cif/final.fcf)"}
        else:
            ins_text, ins_info = _df.restart_ins_text(res_text)
            (out / "final.ins").write_text(ins_text, encoding="utf-8")
            provenance["final.ins"] = {"from": f"final.res + {ins_info['note']}",
                                       "inserted_cards": ins_info["inserted"]}
        # final.hkl: the observations the node is bound to, byte-preserved
        hkl_src = getattr(p, "hkl_path", None)
        if hkl_src is not None and Path(hkl_src).exists():
            try:
                hkl_info = _df.copy_hkl_for_handover(Path(hkl_src), out / "final.hkl")
                hkl_info["data_revision"] = meta.get("data_revision")
                provenance["final.hkl"] = {"from": hkl_info.pop("source"), **hkl_info}
            except Exception as e:  # noqa: BLE001 - report, never block
                provenance["final.hkl"] = {"error": f"{type(e).__name__}: {e}"}
        else:
            provenance["final.hkl"] = {"error": "project has no reflection file "
                                                "path (unbound node?)"}
        # final.p4p: the instrument's cell record captured at ingest - copied
        # when known, its absence written down when not (never fabricated)
        p4p = _df.find_vendor_sidecar(p, meta, ".p4p")
        if p4p.get("path"):
            shutil.copy(p4p["path"], out / "final.p4p")
            provenance["final.p4p"] = {"from": p4p["source"]}
        else:
            provenance["final.p4p"] = {"absent": True, "note": p4p.get("note")}
        # WP2: can final.res be restarted as the job that made the numbers?
        pub["restartable"] = None
        if pub.get("publication") and pub.get("shelxl_job"):
            from .shelx_cards import card_coherence
            job_ins = (p.dir / ".crystalpilot" / "refine" / "shelxl"
                       / str(pub["shelxl_job"]) / "job.ins")
            if job_ins.exists():
                cc = card_coherence(res_text, job_ins.read_text(
                    encoding="utf-8", errors="replace"))
                pub["restartable"] = cc["restartable"]
                pub["restart_cards"] = cc
                if not cc["restartable"]:
                    pub.setdefault("caveats", []).append(
                        "final.res 不可等价重启：" + cc["note"])
        if (out / "final.cif").exists():
            cif_p = out / "final.cif"
            cif_p.write_text(with_status_header(
                cif_p.read_text(encoding="utf-8", errors="replace"),
                status, node, stamp, grade=_grade_line(cif_grade)),
                encoding="utf-8")
        # Which SETTING of its space group does this delivery stand in?
        # Read back from the file that was just written, so the answer is
        # the same for the SHELXL publication CIF and for the minimal one.
        # DECISION (see crystalpilot/io/cif_symmetry): the setting is KEPT
        # and named truthfully; the change of basis is reported, never
        # applied - final.res/.fcf/.fab are the refinement's own files and
        # only a re-refinement could honestly produce them in another
        # basis. `applied` says so, so nobody reads `cb_op` as a transform
        # that has already happened to the delivered coordinates.
        setting_change = None
        if (out / "final.cif").exists():
            from ..io.cif_symmetry import describe, space_group_from_cif_text
            try:
                sg_delivered = space_group_from_cif_text(
                    (out / "final.cif").read_text(encoding="utf-8",
                                                  errors="replace"))
                if sg_delivered is not None:
                    d = describe(sg_delivered)
                    setting_change = {
                        "cb_op": d["cb_op"],
                        "hkl_reindexed": d["hkl_reindexed"],
                        "applied": False,
                        "setting": d["setting"],
                        "reference_setting": d["reference_setting"],
                        "is_reference_setting": d["is_reference_setting"],
                        "hall": d["hall"], "hm": d["hm"],
                        "note": ("delivered in the ITA reference setting"
                                 if d["is_reference_setting"] else
                                 f"delivered in {d['setting']}, NOT the ITA "
                                 f"reference setting. cb_op {d['cb_op']} "
                                 "would take it there; it was NOT applied - "
                                 "final.cif/.res/.fcf/.fab all describe the "
                                 "refined setting and stay mutually "
                                 "coherent. Journals and checkCIF expect the "
                                 "reference setting: to deliver there, apply "
                                 "the cb_op at the SOLUTION end and refine "
                                 "again"
                                 + ("" if not d["hkl_reindexed"] else
                                    " (this cb_op also reindexes hkl)"))}
            except Exception as e:  # noqa: BLE001 - reporting must not block
                setting_change = {"error": f"{type(e).__name__}: {e}"}
        listing = p.nodes.list_nodes(limit=200)
        report = {
            "status": status,
            "status_meaning": STATUS_MEANING[status],
            "status_history": [{"status": status, "at": stamp,
                                "by": "write_outputs"}],
            "final_node": node,
            "source_state": {"node": node, "revision": meta.get("revision")},
            "delivery_revision": delivery_revision,
            "branch": st.get("active_branch"),
            "metrics": meta.get("metrics"),
            "metrics_current": meta.get("metrics_current"),
            "model": meta.get("model"),
            "restraints": meta.get("restraints"),
            "hydrogens": meta.get("hydrogens"),
            "mask": (meta.get("mask") or {}).get("info") if meta.get("mask") else None,
            "mask_params": (meta.get("mask") or {}).get("params")
            if meta.get("mask") else None,
            "solution": solution,
            "synthesis_priors": (p.context.get("chemistry") or {}),
            "experiment": p.experiment() if hasattr(p, "experiment") else {},
            "publication_cif": pub,
            "unresolved": params.get("unresolved") or [],
            "summary_note": params.get("summary_note", ""),
            "lineage": listing["nodes"],
            "generated": stamp,
        }
        if status_note:
            report["status_note"] = status_note
        files = ["final.res", "final.cif", "final.ins", "REPORT.json"]
        if (out / "final.hkl").exists():
            files.append("final.hkl")
        if (out / "final.p4p").exists():
            files.append("final.p4p")
        if pub.get("fcf"):
            files.append("final.fcf")
        if pub.get("fab"):
            files.append("final.fab")
        coherence_issues = self._delivery_coherence(
            out, report, bool(pub.get("publication")),
            restart=pub.get("restart_cards"))
        final_cif_text = None
        if (out / "final.cif").exists():
            final_cif_text = (out / "final.cif").read_text(
                encoding="utf-8", errors="replace")
        # SHELXL's bond table against the model's own bonding (a listed
        # metal-X row that is not a bond becomes a coordination number in
        # every viewer)
        bond_audit: dict[str, Any] | None = None
        if pub.get("publication") and final_cif_text and session is not None \
                and getattr(session, "model", None) is not None:
            try:
                from .nodes import part_connectivity_kwargs
                bond_audit = _df.geom_bond_audit(
                    final_cif_text, session.model,
                    part_connectivity_kwargs(session.flags,
                                             list(session.model.scatterers())))
            except Exception as e:  # noqa: BLE001 - an audit never blocks
                bond_audit = {"checked": False, "suspects": [],
                              "note": f"audit failed: {type(e).__name__}: {e}"}
        manual = _df.manual_continuation(out, provenance, masked)
        report["files"] = provenance
        report["cif_grade"] = cif_grade
        # which SHELXL job the CIF came from and HOW it was paired (the
        # node's linked job / a content scan / no match and why)
        report["job_match"] = pub.get("job_match")
        report["manual_continuation"] = manual
        if bond_audit is not None:
            report["bond_table_audit"] = bond_audit
        # the label/element gate over the files just written; a knowing
        # exception is recorded (REPORT.json + MANIFEST.json), never silent
        label_audit = label_element_audit(res_text, final_cif_text)
        label_accepted_rec = None
        if accept_labels and label_audit["mismatches"]:
            label_accepted_rec = {
                "reason": accept_reason, "at": stamp,
                "mismatches": [{"label": m["label"],
                                "label_element": m["label_element"],
                                "type": m["type"]}
                               for m in label_audit["mismatches"]],
                "note": ("these labels announce a different element than "
                         "the scatterer type; accepted knowingly by the "
                         "agent - checkCIF, the viewer and the grader read "
                         "labels, so VALIDATION.md must say the same")}
        coherence_issues.extend(_label_gate_messages(
            label_audit, accepted=label_accepted_rec is not None))
        obligations = _mask_obligations(
            meta.get("mask"), params.get("formula_moiety") or None,
            final_cif_text)
        disorder_duties = _disorder_obligations(meta)
        key_facts = cif_key_facts(final_cif_text) if final_cif_text else {}
        mask_info = report["mask"] or {}
        if mask_info:
            for k in ("total_solvent_electrons_per_cell", "solvent_volume_A3",
                      "solvent_volume_pct_of_cell", "n_voids_masked",
                      "solvent_mask_converged"):
                if mask_info.get(k) is not None:
                    key_facts[f"mask_{k}"] = mask_info[k]
        # everything the summary says is also on disk: 25/28 pa1 runs read
        # REPORT.json back with the shell because the result and the file
        # disagreed on what they carried
        from .nodes import better_nodes as _better_nodes
        better = _better_nodes(listing["nodes"], node,
                               (meta.get("metrics") or {}).get("r1_strong"))
        report["better_nodes"] = better
        report["coherence_issues"] = coherence_issues
        report["label_audit"] = {
            "n_checked": label_audit["n_checked"],
            "mismatches": label_audit["mismatches"],
            "peak_labels": label_audit["peak_labels"],
            "type_conflicts": label_audit["type_conflicts"]}
        if label_accepted_rec:
            report["label_mismatch_accepted"] = label_accepted_rec
        report["mask_obligations"] = obligations
        report["disorder_obligations"] = disorder_duties
        report["setting_change"] = setting_change
        report["key_facts"] = key_facts
        report["cif_missing_metadata"] = pub.get("missing_metadata") or []
        (out / "REPORT.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
        # A readable inventory; scientific checks remain separate.
        write_manifest(out, files, generated=stamp, status=status,
                       scope="write_outputs deliverables (later files - "
                             "VALIDATION.md, checkcif - are added by "
                             "finalize_delivery)",
                       extra={"source_state": report["source_state"],
                              "delivery_revision": delivery_revision,
                              "cif_grade": cif_grade.get("grade"),
                              "provenance": provenance,
                              "manual_continuation": manual,
                              **({"label_mismatch_accepted": label_accepted_rec}
                                 if label_accepted_rec else {})})
        files.append("MANIFEST.json")
        summary = {
            "output_dir": str(out),
            "status": status,
            "files": files,
            "final_node": node,
            "source_state": report["source_state"],
            "delivery_revision": delivery_revision,
            "metrics": meta.get("metrics"),
            "metrics_current": meta.get("metrics_current"),
            "publication_cif": pub.get("publication"),
            "shelxl_job": pub.get("shelxl_job"),
            "restartable": pub.get("restartable"),
            "key_facts": key_facts,
            "cif_caveats": pub.get("caveats"),
            "n_unresolved": len(params.get("unresolved") or []),
        }
        summary["cif_grade"] = cif_grade.get("grade")
        summary["cif_grade_note"] = cif_grade.get("note")
        summary["manual_continuation"] = manual
        summary["file_provenance"] = {k: (v.get("from") or v.get("note") or v.get("error"))
                                      for k, v in provenance.items()}
        if zero_cycle:
            summary["zero_cycle_job"] = {k: v for k, v in zero_cycle.items()
                                         if k not in ("fcf", "shelxl")}
            if zero_cycle.get("shelxl"):
                z = zero_cycle["shelxl"]
                summary["zero_cycle_job"]["r1_strong"] = z.get("r1_strong")
                summary["zero_cycle_job"]["wr2"] = z.get("wr2")
        if bond_audit is not None:
            summary["bond_table_audit"] = {
                "checked": bond_audit.get("checked"),
                "n_suspects": len(bond_audit.get("suspects") or []),
                "suspects": bond_audit.get("suspects"),
                "note": bond_audit.get("note")}
            if bond_audit.get("suspects"):
                summary.setdefault("warnings", []).append(
                    "bond table: " + "; ".join(
                        f"{s['a']}-{s['b']} {s['distance']} A is not a bond in the "
                        f"model ({s['free_card']})" for s in bond_audit["suspects"][:6])
                    + " - readers count these as coordination; add the FREE "
                      "card(s) via run_shelxl extra_cards and write_outputs again")
        if setting_change:
            # the reference-setting case is the boring one: keep the reply
            # short and leave the full record in REPORT.json
            summary["setting_change"] = (
                {k: setting_change[k] for k in
                 ("setting", "cb_op", "hkl_reindexed", "applied")
                 if k in setting_change}
                if setting_change.get("is_reference_setting")
                else setting_change)
        if status_note:
            summary["status_note"] = status_note
        if better:
            summary["better_nodes"] = better
            summary["better_nodes_note"] = (
                f"{len(better)} node(s) in this tree refine to a lower R1 "
                f"than the delivered node (best {better[0]['id']} R1 "
                f"{better[0]['r1']}, {'masked' if better[0]['masked'] else 'unmasked'}"
                f", delta {better[0]['delta_r1']:+.4f}). Delivering a worse "
                "node can be right (mask withdrawn for a reason, diagnostic "
                "branch, chemistry that does not hold) but it must be a "
                "stated decision: name the node and the reason in "
                "summary_note / SUMMARY.md, or checkout the better node and "
                "deliver that. The grader reads the same table.")
        if masked:
            summary["final_fab"] = ({"written": True,
                                     "source": pub.get("fab_source"),
                                     "abin_in_final_res": True}
                                    if pub.get("fab") else
                                    {"written": False, "reason": fab_caveat})
        if abin_added:
            summary["final_res_note"] = ("ABIN card added to final.res "
                                         "(final.res + final.hkl + final.fab "
                                         "reproduce the refinement)")
        if pub.get("missing_metadata"):
            summary["cif_missing_metadata"] = pub["missing_metadata"]
            summary["metadata_note"] = (
                "each entry is a '?' slot a journal CIF needs, with the "
                "checkCIF alert it raises and the set_experiment key (or "
                "argument) that fills it - record known facts with "
                "set_experiment (provenance required) and ask the user for "
                "the rest; never invent values")
        if obligations:
            summary["mask_obligations"] = obligations
        if disorder_duties:
            summary["disorder_obligations"] = disorder_duties
        if label_accepted_rec:
            summary["label_mismatch_accepted"] = label_accepted_rec
        elif accept_labels:
            summary["label_note"] = ("accept_label_mismatch given but no "
                                     "label/element mismatch was found - "
                                     "nothing recorded")
        if label_audit["mismatches"] or label_audit["peak_labels"]:
            summary["label_audit"] = {
                "n_checked": label_audit["n_checked"],
                "mismatches": [f"{m['label']}: label {m['label_element']} "
                               f"/ type {m['type']}"
                               for m in label_audit["mismatches"][:12]],
                "peak_labels": label_audit["peak_labels"][:12]}
        if not pub.get("publication") and pub.get("job_match"):
            jm = dict(pub["job_match"])
            jm["candidates"] = (jm.get("candidates") or [])[:3]
            summary["job_match"] = jm
        if coherence_issues:
            summary["coherence_issues"] = coherence_issues
            summary["coherence_note"] = (
                "the files just written DISAGREE with each other - do NOT "
                "deliver this directory until resolved (usually: re-run "
                "run_shelxl so a fresh matching job exists, then "
                "write_outputs again; label/element mismatches: "
                "rename_atoms(mode='map') or edit_atoms reassign first, as "
                "listed)")
        else:
            summary["coherence"] = ("final.res / final.cif / REPORT.json "
                                    "agree (atoms, Z, R1, labels/elements)")
        summary["next"] = (
            "run_checkcif(cif='<output_dir>/final.cif') -> explain every "
            "A/B/C alert in VALIDATION.md, write SUMMARY.md -> "
            "finalize_delivery (promotes this directory to status 'final'; "
            "A alerts and unresolved items must be fixed or waived with a "
            "reason)" if status == "provisional" else
            "diagnostic delivery: not a structure claim. run_checkcif + "
            "SUMMARY.md/VALIDATION.md, then finalize_delivery can still "
            "seal this directory for a complete audit trail (status stays "
            "'diagnostic', open items listed in MANIFEST.json open_items - "
            "no waivers needed); it will never promote a diagnostic to "
            "'final' - deliver the model you actually claim with "
            "status='provisional' for that")
        return ToolResult(ok=True, summary=summary,
                          artifacts={"final_res": str(out / "final.res"),
                      "final_cif": str(out / "final.cif"),
                      "final_ins": str(out / "final.ins"),
                      **({"final_hkl": str(out / "final.hkl")}
                         if (out / "final.hkl").exists() else {}),
                      **({"final_p4p": str(out / "final.p4p")}
                         if (out / "final.p4p").exists() else {}),
                      "report": str(out / "REPORT.json"),
                      **({"final_fcf": str(out / "final.fcf")}
                         if pub.get("fcf") else {}),
                      **({"final_fab": str(out / "final.fab")}
                         if pub.get("fab") else {})})


# ==========================================================================
class FinalizeDelivery(_ProjectTool):
    name = "finalize_delivery"
    description = (
        "Record a write_outputs delivery in a readable MANIFEST.json "
        "after a completeness check: final.cif + "
        "final.fcf + final.res + REPORT.json + SUMMARY.md + VALIDATION.md "
        "present, final.fab for a masked model, checkcif.json produced by "
        "run_checkcif linked to this node and delivery revision, no coherence "
        "issues, and the label/element gate re-run on the delivered files "
        "(a non-H label announcing a different element than its type, or "
        "a Q label, is fatal unless write_outputs recorded "
        "label_mismatch_accepted with a reason; Q labels never pass). TWO "
        "OUTCOMES depending on the delivery's status: a 'provisional' "
        "delivery is PROMOTED to 'final' - every blocking item (each "
        "A-level checkCIF alert, each REPORT.json 'unresolved' entry) "
        "must be gone or explicitly waived, each with its own reason "
        "(recorded in REPORT.json finalized.waivers and MANIFEST.json "
        "waived; a waiver is a disclosure, not a fix - the CIF header "
        "then names how many blocking items were waived instead of "
        "implying every one was resolved). A 'diagnostic' delivery (NOT a "
        "structure claim) is instead SEALED as-is - status stays "
        "'diagnostic', no waivers are needed or accepted, and every "
        "unresolved blocking item is listed in REPORT.json/MANIFEST.json "
        "open_items; it is never promoted to 'final'. Either way this "
        "rewrites the status header of final.cif, updates REPORT.json and "
        "rebuilds MANIFEST.json over every file in the directory "
        "(SUMMARY/VALIDATION/checkcif included). Default target = the "
        "newest delivery under 'CrystalPilot Results/'. A failed call "
        "changes nothing and lists what is missing.")
    params_schema = {
        "type": "object",
        "properties": {
            "output_dir": {
                "type": "string",
                "description": "delivery directory (project-relative); "
                               "omit for the newest delivery"},
            "waivers": {
                "type": "array",
                "items": {"type": "object",
                          "properties": {"item": {"type": "string"},
                                         "reason": {"type": "string"}},
                          "required": ["item", "reason"]},
                "default": [],
                "description": "blocking items to waive, by id as listed "
                               "in a failed call ('alert:183_A', "
                               "'unresolved#2'), each with a real reason "
                               "(the evidence, or the data limitation, and "
                               "where VALIDATION.md discusses it); only "
                               "used to promote a 'provisional' delivery "
                               "to 'final' - a 'diagnostic' delivery seals "
                               "with its blocking items listed as "
                               "open_items instead, no waivers needed"},
            "note": {"type": "string", "default": "",
                     "description": "optional closing note for REPORT.json"},
            "unmet_goals": {
                "type": "array", "items": {"type": "string"}, "default": [],
                "description": "diagnostic deliveries only: what this study "
                               "did NOT achieve, one line each (written into "
                               "open_items). Not needed when set_investigation "
                               "already records the unmet tiers and the open "
                               "directions - those are written automatically"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        p = self.project
        if params.get("output_dir"):
            out = (p.dir / str(params["output_dir"])).resolve()
            if p.dir.resolve() not in out.parents:
                return ToolResult.failure("output_dir must stay inside the "
                                          "project")
            if not (out / "REPORT.json").exists():
                return ToolResult.failure(
                    f"{params['output_dir']} is not a write_outputs delivery "
                    "(no REPORT.json)")
        else:
            out = find_newest_delivery(p.dir)
            if out is None:
                return ToolResult.failure(
                    "no delivery found (write_outputs has not written a "
                    "REPORT.json + final.cif under 'CrystalPilot Results/')")
        from .data_versions import is_protected
        if is_protected(p.dir, out):
            return ToolResult.failure("Archived inputs/nodes are read-only; finalize an exported copy outside the archive")
        audit = delivery_audit(out)
        is_diagnostic = audit["status"] == "diagnostic"
        waivers = params.get("waivers") or []
        waived: dict[str, str] = {}
        bad_waivers: list[str] = []
        valid_ids = {b["item"] for b in audit["blocking"]}
        for w in waivers:
            if not isinstance(w, dict):
                bad_waivers.append(f"{w!r}: not an object")
                continue
            item = str(w.get("item") or "").strip()
            reason = str(w.get("reason") or "").strip()
            if item not in valid_ids:
                bad_waivers.append(f"{item!r}: not a blocking item of this "
                                   f"delivery")
            elif len(reason) < 12:
                bad_waivers.append(f"{item!r}: reason too short to be a "
                                   f"disclosure")
            else:
                waived[item] = reason
        unwaived = [b for b in audit["blocking"] if b["item"] not in waived]
        # a 'diagnostic' delivery is sealed AS-IS: unwaived blocking items
        # become open_items in the MANIFEST/REPORT.json rather than a
        # reason to refuse - the audited record of a model that is NOT a
        # structure claim is the point (cage-full-r1 chose the honest
        # 'diagnostic' status and finalize_delivery refused to seal it at
        # all, so SUMMARY.md/VALIDATION.md/checkcif.json never entered a
        # delivery inventory)
        blocks_finalize = [] if is_diagnostic else unwaived
        open_items = list(unwaived) if is_diagnostic else []
        # inputs nobody here can produce (the instrument's p4p): recorded
        # beside the seal, neither waived nor blocking
        missing_inputs = list(audit.get("missing_inputs") or [])
        # round-3 WP7: a diagnostic delivery must say what it did NOT
        # achieve - the unmet goal tiers and the untried directions from the
        # investigation record (or an explicit unmet_goals list) become
        # open_items; the seal is refused only when neither exists. A final
        # promotion is not gated by this (the live-demo Zr-MOF twice ended
        # in a diagnostic seal that read like a failed task instead of a
        # study stopped short of a stated goal)
        inv_block = None
        unmet_param = [str(g).strip() for g in (params.get("unmet_goals") or [])
                       if str(g).strip()]
        if is_diagnostic and not audit["fatal"] and not bad_waivers:
            from . import investigation as _inv
            inv = _inv.load(p.dir)
            if not _inv.is_set(inv) and not unmet_param:
                return ToolResult.failure(
                    f"NOT finalized: {out}\n"
                    "a 'diagnostic' delivery must say what it did NOT "
                    "achieve: record the investigation first "
                    "(set_investigation(goal=..., tiers={...}, "
                    "open_directions=[...]) - its unmet tiers and open "
                    "directions are written into open_items automatically) "
                    "or pass unmet_goals=['...'] here\n"
                    "nothing was changed")
            if _inv.is_set(inv):
                open_items.extend(_inv.open_items_for_delivery(inv))
                inv_block = _inv.summary_block(inv)
            for i, g in enumerate(unmet_param, 1):
                open_items.append({"item": f"unmet_goal#{i}", "text": g})
        if audit["fatal"] or blocks_finalize or bad_waivers:
            lines = [f"NOT finalized: {out}"]
            if audit["fatal"]:
                lines.append("fatal (cannot be waived): "
                             + " | ".join(audit["fatal"]))
            if blocks_finalize:
                lines.append("blocking (fix, or waive by id with a reason): "
                             + " | ".join(f"{b['item']}: {b['text']}"
                                          for b in blocks_finalize))
            if bad_waivers:
                lines.append("rejected waivers: " + " | ".join(bad_waivers))
            lines.append("nothing was changed")
            return ToolResult.failure("\n".join(lines))

        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        report = audit["report"]
        final_status = "diagnostic" if is_diagnostic else "final"
        n_waived = len(waived)
        header_meaning = None
        if not is_diagnostic and n_waived:
            header_meaning = (
                f"final - {n_waived} blocking item"
                f"{'s' if n_waived != 1 else ''} waived with reasons (see "
                "MANIFEST.json) - not every blocking item was resolved "
                "outright")
        cif_p = out / "final.cif"
        cif_p.write_text(with_status_header(
            cif_p.read_text(encoding="utf-8", errors="replace"),
            final_status, report.get("final_node"), stamp,
            meaning=header_meaning,
            grade=_grade_line(report.get("cif_grade"))), encoding="utf-8")
        report["status"] = final_status
        report["status_meaning"] = header_meaning or STATUS_MEANING[final_status]
        report.setdefault("status_history", []).append(
            {"status": final_status, "at": stamp, "by": "finalize_delivery"})
        waivers_list = [{"item": k, "reason": v,
                         "text": next((b["text"] for b in audit["blocking"]
                                       if b["item"] == k), "")}
                        for k, v in waived.items()]
        report["finalized"] = {
            "at": stamp,
            "promoted": not is_diagnostic,
            "waivers": waivers_list,
            "waived_count": n_waived,
            "open_items": open_items,
            "missing_inputs": missing_inputs,
            "checkcif_counts": audit.get("checkcif_counts"),
            "note": str(params.get("note") or ""),
            **({"investigation": inv_block} if inv_block else {}),
        }
        (out / "REPORT.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
        files = sorted(f.name for f in out.iterdir()
                       if f.is_file() and f.name != "MANIFEST.json")
        subdirs = sorted(d.name for d in out.iterdir() if d.is_dir())
        from . import deliver_files as _df
        manual = _df.manual_continuation(out, report.get("files") or {},
                                         bool(report.get("mask")))
        report["manual_continuation"] = manual
        (out / "REPORT.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
        write_manifest(out, files, status=final_status, generated=stamp,
                       scope="finalize_delivery: every file in the delivery "
                             "directory at finalize time",
                       extra={"subdirectories_not_listed": subdirs,
                              "source_state": report.get("source_state"),
                              "delivery_revision": report.get("delivery_revision"),
                              "cif_grade": (report.get("cif_grade") or {}).get("grade"),
                              "provenance": report.get("files") or {},
                              "manual_continuation": manual,
                              "finalized": stamp,
                              "promoted": not is_diagnostic,
                              "waived": waivers_list,
                              "waived_count": n_waived,
                              "open_items": open_items,
                              "missing_inputs": missing_inputs})
        if is_diagnostic:
            note = ("diagnostic delivery SEALED for a complete audit trail "
                    "(final.cif header, REPORT.json, MANIFEST.json all "
                    "still say 'diagnostic' - this is NOT a structure "
                    "claim); open_items lists what was never resolved or "
                    "waived, because a diagnostic record needs neither")
        elif n_waived:
            note = (f"delivery promoted to 'final' with {n_waived} blocking "
                    f"item{'s' if n_waived != 1 else ''} waived, not "
                    "resolved (final.cif header, REPORT.json, "
                    "MANIFEST.json); waivers are disclosures the user will "
                    "read - make sure VALIDATION.md says the same")
        else:
            note = ("delivery promoted to 'final' with every blocking item "
                    "resolved, no waivers (final.cif header, REPORT.json, "
                    "MANIFEST.json)")
        return ToolResult(ok=True, summary={
            "output_dir": str(out),
            "status": final_status,
            "sealed": True,
            "promoted": not is_diagnostic,
            "files": files + ["MANIFEST.json"],
            "waived": waivers_list,
            "waived_count": n_waived,
            "open_items": open_items,
            "missing_inputs": missing_inputs,
            "checkcif_counts": audit.get("checkcif_counts"),
            "n_unresolved": len(report.get("unresolved") or []),
            "cif_grade": (report.get("cif_grade") or {}).get("grade"),
            "manual_continuation": manual,
            **({"label_mismatch_accepted": report["label_mismatch_accepted"]}
               if report.get("label_mismatch_accepted") else {}),
            "note": note,
        }, artifacts={"final_cif": str(cif_p),
                      "report": str(out / "REPORT.json"),
                      "manifest": str(out / "MANIFEST.json")})


# ==========================================================================
