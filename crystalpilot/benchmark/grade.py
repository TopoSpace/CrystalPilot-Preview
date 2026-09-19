"""Unified mentor-side grader: score a CrystalPilot delivery, with or
without a reference answer.

Boundary (fixed by design):
  * agent SELF-audit  = reference-free consistency checks INSIDE the
    product (delivery-self-audit skill, write_outputs three-way
    fingerprint, run_checkcif). Needs no reference and never sees one.
  * mentor GRADING    = reference-based scoring OUTSIDE the product
    (this module). Reference answers never enter the MCP tool surface,
    the project directory, or campaign prompts - which is why this module
    is deliberately NOT registered as an MCP tool, and why grade output
    goes to the repo workdir, not the project.

Three layers:
  1. self-consistency (always runs; the no-reference fallback mode):
     CIF field extraction, fcf-recomputed R1 vs claimed R1, REPORT.json vs
     CIF agreement, independent local checkCIF + per-alert explanations
     (evaluate_refinement._checkcif_gate), unresolved-issues disclosure,
     and a peek report (reference files inside the project / suspicious
     lookups in the transcript).
  2. reference layer (when a reference .cif/.res is given): emma structure
     match with solvent fairness (benchmark.evaluate), Niggli cell check,
     sgtbx space-group-type equality, composition/Z, R1 delta.
     reference_kind='literature' means same phase but a different
     measurement: R1 is reported, not scored.
  3. grade: publication / acceptable / below_bar (with reference) or
     self_consistent_pass / self_consistent_fail (fallback).

CLI:  python -m crystalpilot.benchmark.grade <project_dir>
          [--ref <cif|res>] [--ref-kind exact|literature] [--out <dir>]
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]

#: transcript / filesystem patterns whose presence suggests the agent saw
#: the answer (report-level evidence, never an automatic verdict)
_PEEK_PATTERNS = (
    r"ccdc\.cam\.ac\.uk", r"crystallography\.net", r"codbase",
    # 'reference' only counts as a PATH (reference/ or reference\ followed
    # by a word char - the backslash form is how JSONL escapes a Windows
    # path) or a FILE (reference.cif, reference_COD_1234567.cif,
    # reference-answer.res). The earlier bare `reference_` / `reference-`
    # branch fired on identifiers: every one of the 16 pa1 peek hits
    # (cage-l2-r1 x10, cage-l2-r2 x6) was the e-statistics field name
    # `reference_centric` / `reference_acentric` in the agent's own script
    # and its printed output, and prose like "reference-free" would fire
    # the same way. The JSONL-escaped key \"reference\" (r11) stays exempt.
    r"reference(?:[/\\]+(?=\w)|(?:[_-][\w-]*)?\.(?:cif|res|ins|hkl|fcf)\b)",
    r"[/\\]refs?[/\\]", r"cod_\d{7}",
)


# --------------------------------------------------------------------------- #
# CIF field helpers (lifted from workdir/compare_cif_p770.py, now retired)
# --------------------------------------------------------------------------- #

def _read_cif_block(p: Path):
    """Parse the first data block, tolerating non-ASCII text values.

    CIF 1.1 is ASCII-only; a stray UTF-8 α/λ/Å in a text field (e.g. a
    vendor-source string carried in via set_experiment) makes iotbx's C++
    lexer emit an error message that slices the multi-byte char in half -
    the resulting UnicodeDecodeError killed r13 grading. Grade must judge
    the crystallography, not crash on the encoding, so parse from a
    sanitized in-memory copy (numeric fields are unaffected; the ASCII
    hygiene of the CIF itself is publication.py's job and checked there).
    """
    import iotbx.cif

    from .evaluate import tolerant_cif_text
    cif = iotbx.cif.reader(input_string=tolerant_cif_text(p)).model()
    return next(iter(cif.values()))


def _val(block, key: str, cast=float):
    v = block.get(key)
    if v is None:
        return None
    s = str(v).split("(")[0]
    try:
        return cast(s)
    except ValueError:
        return str(v)


def _num(block, key: str) -> float | None:
    """`_val` when it really is a number. A looped or '?' field comes back
    from `_val` as a string, and a resolution derived from one would be a
    fiction."""
    v = _val(block, key)
    return float(v) if isinstance(v, (int, float)) else None


def _cif_d_min(block) -> float | None:
    """The refinement's resolution limit in A, or None.

    `_reflns_d_resolution_high` when the CIF states it outright; otherwise
    Bragg from the measured theta max, d_min = lambda / (2 sin theta_max),
    from the pair SHELXL always writes (`_diffrn_reflns_theta_max` +
    `_diffrn_radiation_wavelength`; `_reflns_theta_max` is accepted as the
    refinement-side spelling). There is no `_refine_ls_d_res_high` in core
    CIF, so nothing here reads one. A .res/.ins reference carries no such
    field at all - unknown resolution is a normal answer."""
    import math
    d = _num(block, "_reflns_d_resolution_high")
    if d is not None and d > 0:
        return round(d, 4)
    lam = _num(block, "_diffrn_radiation_wavelength")
    theta = _num(block, "_diffrn_reflns_theta_max")
    if theta is None:
        theta = _num(block, "_reflns_theta_max")
    if lam is None or theta is None or not 0.0 < theta < 90.0:
        return None
    sin_t = math.sin(math.radians(theta))
    return round(lam / (2.0 * sin_t), 4) if sin_t > 0 else None


def _cell(block) -> list[float | None]:
    return [_val(block, f"_cell_length_{x}") for x in "abc"] + \
           [_val(block, f"_cell_angle_{x}") for x in
            ("alpha", "beta", "gamma")]


def _niggli(cell6):
    from cctbx import crystal
    cs = crystal.symmetry(unit_cell=cell6, space_group_symbol="P 1")
    return list(cs.niggli_cell().unit_cell().parameters())


def _formula_counts(formula: str | None) -> dict[str, float]:
    if not formula:
        return {}
    out: dict[str, float] = {}
    for el, n in re.findall(r"([A-Z][a-z]?)\s*([\d.]*)", str(formula)):
        out[el] = out.get(el, 0.0) + (float(n) if n else 1.0)
    return out


def _cif_symmetry_check(p: Path) -> dict[str, Any]:
    """Do the delivered CIF's space-group NAMES agree with its own
    operator loop? (reg1-ext2 hsl shipped 'P 21 21 21' beside the
    operators of an origin-shifted setting.)"""
    from ..io.cif_symmetry import check_cif_symmetry
    try:
        return check_cif_symmetry(Path(p).read_text(encoding="utf-8",
                                                    errors="replace"))
    except Exception as e:  # noqa: BLE001 - never block grading
        return {"checked": False, "error": f"{type(e).__name__}: {e}"}


def _cif_fields(p: Path) -> dict[str, Any]:
    b = _read_cif_block(p)
    dg = b.get("_atom_site_disorder_group")
    twin = (b.get("_twin_individual_mass_fraction_refined")
            or ("TWIN" if "twin" in
                str(b.get("_refine_special_details") or "").lower()
                else None))
    return {
        "cell": _cell(b),
        "space_group": (b.get("_space_group_name_H-M_alt")
                        or b.get("_symmetry_space_group_name_H-M")),
        "formula": b.get("_chemical_formula_sum"),
        "z": _val(b, "_cell_formula_units_Z", int),
        "r1_gt": _val(b, "_refine_ls_R_factor_gt"),
        "wr2": _val(b, "_refine_ls_wR_factor_ref"),
        "goof": _val(b, "_refine_ls_goodness_of_fit_ref"),
        "n_params": _val(b, "_refine_ls_number_parameters", int),
        "n_atoms": len(b.get("_atom_site_label") or []),
        "n_disorder_marked": (sum(1 for x in dg if str(x) not in (".", "?"))
                              if dg is not None else 0),
        "twin_marker": twin,
        "flack": _val(b, "_refine_ls_abs_structure_Flack"),
        "d_min": _cif_d_min(b),
    }


# --------------------------------------------------------------------------- #
# delivery location + self-consistency layer
# --------------------------------------------------------------------------- #

def find_delivery(project_dir: Path) -> Path | None:
    """Newest publication delivery: final.cif with final.fcf beside it
    (same rule as evaluate_refinement._checkcif_gate).

    The standard layout is `CrystalPilot Results/<task>/final.cif`; a
    delivery one level deeper still counts (pa1 cu-l2-r2 wrote a complete
    final.cif/fcf/res + checkCIF into `<task>/deliverables/` and was graded
    no_delivery) - grade_delivery records the layout so a non-standard one
    is visible as a process defect instead of a missing structure."""
    root = project_dir / "CrystalPilot Results"
    outs = sorted(root.glob("*/final.cif"), key=lambda p: p.stat().st_mtime,
                  reverse=True)
    hit = next((p for p in outs if p.with_name("final.fcf").exists()), None)
    if hit is not None:
        return hit
    deeper = sorted(root.glob("*/*/final.cif"),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    return next((p for p in deeper if p.with_name("final.fcf").exists()),
                None)


def delivery_layout(project_dir: Path, final_cif: Path) -> str:
    return ("standard" if final_cif.parent.parent ==
            project_dir / "CrystalPilot Results" else "nonstandard")


def _self_consistency(project_dir: Path, final_cif: Path,
                      run_checkcif: bool = True) -> dict[str, Any]:
    from ..refine.tools_analysis import _audit_fcf

    out: dict[str, Any] = {"delivery": str(final_cif.parent)}
    fields = _cif_fields(final_cif)
    out["cif"] = fields

    # (s2) the CIF's claimed R1 must be reproducible from its own fcf
    fcf = final_cif.with_name("final.fcf")
    audit = _audit_fcf(fcf)
    rec = audit.get("r1_from_file_fo2_gt_2sig")
    out["fcf_recomputed_r1_gt"] = rec
    out["fcf_nonconstant_fc2_groups"] = audit.get(
        "groups_with_nonconstant_fc2")
    if fields["r1_gt"] is not None and rec is not None:
        out["s2_cif_matches_fcf"] = bool(abs(fields["r1_gt"] - rec) <= 0.005)
        out["s2_delta"] = round(fields["r1_gt"] - rec, 5)
    else:
        out["s2_cif_matches_fcf"] = None

    # (s3) REPORT.json metrics must agree with the delivered CIF
    rep_path = final_cif.with_name("REPORT.json")
    if rep_path.exists():
        rep = json.loads(rep_path.read_text(encoding="utf-8"))
        rr1 = (rep.get("metrics") or {}).get("r1_strong")
        out["report_r1"] = rr1
        out["s3_report_matches_cif"] = (
            bool(abs(rr1 - fields["r1_gt"]) <= 0.002)
            if rr1 is not None and fields["r1_gt"] is not None else None)
        out["unresolved_disclosed"] = rep.get("unresolved")
        out["report_model_atoms"] = (rep.get("model") or {}).get("n_atoms")
        # WP2 (report-level): does final.res carry the instruction cards
        # of the paired job? None = no paired job / pre-WP2 delivery
        out["restartable"] = (rep.get("publication_cif") or {}).get("restartable")
    else:
        out["s3_report_matches_cif"] = None
        out["note_report"] = "no REPORT.json beside the delivery"

    # (s4) independent local checkCIF + per-alert explanation requirement
    if run_checkcif:
        from .evaluate_refinement import _checkcif_gate
        out["checkcif"] = _checkcif_gate(project_dir)
    else:
        out["checkcif"] = {"available": False, "note": "skipped by caller"}

    # (gate-e) peek report: reference material inside the project, or
    # answer-looking lookups in the transcript. Report-level ONLY.
    peek: dict[str, Any] = {"suspect_files": [], "transcript_hits": []}
    for pat in ("reference*", "*_ref.*", "cod_*.cif", "ccdc_*.cif"):
        for f in project_dir.glob(f"CrystalPilot Results/*/{pat}"):
            peek["suspect_files"].append(str(f.relative_to(project_dir)))
        for f in project_dir.glob(pat):
            peek["suspect_files"].append(str(f.relative_to(project_dir)))
    tr = final_cif.with_name("transcript.jsonl")
    if tr.exists():
        # line-wise (JSONL = one event per line) so our own knowledge base
        # is exempt: read_skill/list_skills results quote skill cards whose
        # citation lists legitimately mention CCDC/COD teaching URLs (r13
        # false hit on framework-restraint-idioms' reference list). A hit
        # hidden on a skill-event line would evade this, but the gate is
        # report-level and the tutor reads the transcript regardless.
        counts: dict[str, int] = {}
        with tr.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"read_skill"' in line or '"list_skills"' in line:
                    continue
                for pat in _PEEK_PATTERNS:
                    n = len(re.findall(pat, line, re.I))
                    if n:
                        counts[pat] = counts.get(pat, 0) + n
        for pat in _PEEK_PATTERNS:
            if counts.get(pat):
                peek["transcript_hits"].append(
                    {"pattern": pat, "count": counts[pat]})
    peek["clean"] = not peek["suspect_files"] and not peek["transcript_hits"]
    out["peek_report"] = peek

    cc_gate = (out["checkcif"] or {}).get("gate_d_pass")
    out["self_consistent"] = bool(
        out.get("s2_cif_matches_fcf") is not False
        and out.get("s3_report_matches_cif") is not False
        and cc_gate is not False)
    return out


# --------------------------------------------------------------------------- #
# mentor-side checks the pa1 post-mortem found missing (PA1-FINAL-ANALYSIS
# §9): A-alert split, SHELXL reproducibility, node tree vs delivery,
# porosity, chemistry sanity, delivery file set
# --------------------------------------------------------------------------- #

#: checkCIF A alerts that report a MISSING CIF item rather than a model
#: defect. Every code here was verified in the pa1 checkCIF outputs, where
#: the same five fired on 16-27 of the 26 deliveries regardless of model
#: quality: 183/184/185 _cell_measurement_{reflns_used,theta_min,theta_max},
#: 660 _diffrn_radiation_type, 699 _exptl_crystal_description. PLAT051 (Mu
#: ratio) is type-1 as well but reports an inconsistency the agent WROTE,
#: so it stays model-side.
_METADATA_ALERT_CODES = frozenset({"183", "184", "185", "660", "699"})
#: A alerts that describe the DATA, not the model: 020 R_int > 0.12, 023
#: resolution below sin(theta)/lambda 0.6, 026 observed/unique ratio, 029
#: measured fraction of theta_full. On the pa1/pa2 hex data (R_int 0.57,
#: cut at 1.0 A) 020 and 023 fire on every delivery - and would on the
#: group's manual structure too. They must be explained in VALIDATION.md
#: (the explanation gate keeps that) but they cannot block publication,
#: or the yardstick demotes every model of a weak dataset forever.
_DATA_QUALITY_ALERT_CODES = frozenset({"020", "023", "026", "029"})
_DATA_QUALITY_WORDS = re.compile(
    r"Value of Rint|Resolution \(too\) Low|Ratio Observed / Unique|"
    r"measured_fraction_theta", re.I)
_CIF_TAG = re.compile(r"_[A-Za-z][\w/.-]*")
_MISSING_WORDS = re.compile(
    r"\b(?:missing|no valid|not (?:given|reported|specified|provided)|"
    r"absent|please do)\b", re.I)


def classify_a_alert(code: str, text: str = "") -> str:
    """'metadata_missing' (a required CIF item absent / '?'),
    'data_quality' (R_int / resolution / completeness of the DATA) or
    'model_quality' (everything else).

    pa1 §9: the publication gate mixed the two. PLAT213/215/374 (ADP,
    geometry) rightly held cu-l3-r2 - the best model of the batch - at
    acceptable, but the same gate demotes a flawless model for an unfilled
    _exptl_crystal_description. Text rule beyond the verified code list: a
    CIF tag together with a missing-word ("Missing _cell_measurement_
    theta_max Value", "No Valid _diffrn_radiation_type Value Reported");
    "Missing FCF Refl" (PLAT911) carries no tag and stays data-side."""
    code = str(code).strip()
    if code in _METADATA_ALERT_CODES:
        return "metadata_missing"
    if code in _DATA_QUALITY_ALERT_CODES:
        return "data_quality"
    t = text or ""
    if _CIF_TAG.search(t) and _MISSING_WORDS.search(t):
        return "metadata_missing"
    if _DATA_QUALITY_WORDS.search(t):
        return "data_quality"
    return "model_quality"


def _a_alerts_from_gate(cc: dict) -> tuple[list[dict], list[dict]]:
    """(all A alerts, blocking A alerts) from a _checkcif_gate result,
    whose entries are the strings 'A 185 text' / '185 text'."""
    all_a: list[dict] = []
    blocking: list[dict] = []
    for s in cc.get("alerts_abc") or []:
        m = re.match(r"\s*A\s+(\d{3})\s*(.*)", str(s))
        if m:
            all_a.append({"code": m.group(1), "text": m.group(2)})
    for s in cc.get("blocking_a") or []:
        m = re.match(r"\s*(\d{3})\s*(.*)", str(s))
        if m:
            blocking.append({"code": m.group(1), "text": m.group(2)})
    return all_a, blocking


def _a_alerts_from_delivered(final_cif: Path) -> list[dict] | None:
    """A alerts from the agent's own checkcif.json beside the delivery
    (run_checkcif output: {"alerts": [{code, type, level, text}, ...]}).
    Used only when no independent PLATON rerun is available."""
    p = final_cif.with_name("checkcif.json")
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    return [{"code": str(a.get("code")), "text": str(a.get("text") or "")}
            for a in (d.get("alerts") or [])
            if isinstance(a, dict) and str(a.get("level")) == "A"]


def checkcif_a_split(cc: dict | None, final_cif: Path) -> dict[str, Any]:
    """Split the A alerts into metadata_missing / model_quality and name
    the ones that block publication (model-quality only).

    Source is the independent PLATON rerun when it ran; otherwise the
    delivered checkcif.json (clearly labelled - it is the agent's own run).
    With the rerun, `blocking_a` already dropped type-1 alerts the
    VALIDATION.md explains; an unexplained metadata alert still fails the
    explanation gate (gate_d -> self_consistent), it just no longer counts
    as a model defect."""
    cc = cc or {}
    if cc.get("available"):
        all_a, blocking = _a_alerts_from_gate(cc)
        source = "platon rerun"
    else:
        found = _a_alerts_from_delivered(final_cif)
        if found is None:
            return {"source": None,
                    "note": "no checkCIF result (no PLATON rerun and no "
                            "checkcif.json beside the delivery)"}
        all_a, blocking, source = found, list(found), "delivered checkcif.json"

    def _kind(a: dict) -> str:
        return classify_a_alert(a["code"], a["text"])

    def _fmt(rows: list[dict]) -> list[str]:
        seen: list[str] = []
        for a in rows:
            s = f"{a['code']} {a['text'][:44]}".strip()
            if s not in seen:
                seen.append(s)
        return seen

    meta = [a for a in all_a if _kind(a) == "metadata_missing"]
    data = [a for a in all_a if _kind(a) == "data_quality"]
    model = [a for a in all_a if _kind(a) == "model_quality"]
    model_blocking = sorted({a["code"] for a in blocking
                             if _kind(a) == "model_quality"})
    return {"source": source, "n_a": len(all_a),
            "metadata_missing": _fmt(meta),
            "data_quality": _fmt(data),
            "model_quality": _fmt(model),
            "blocking_model_quality": model_blocking}


def _embedded_shelx_block(cif_text: str, tag: str) -> str | None:
    """Body of a `;`-delimited text field (SHELXL embeds res/hkl/fab this
    way); SHELX lines never start with ';' so the first such line ends it."""
    m = re.search(rf"^{tag}[ \t]*\n;[ \t]*\n(.*?)\n;[ \t]*$", cif_text,
                  re.S | re.M)
    return m.group(1) if m else None


def _shelxl_exe() -> Path:
    import os
    from ..refine.tools_shelxl import DEFAULT_SHELXL
    return Path(os.environ.get("CRYSTALPILOT_SHELXL", str(DEFAULT_SHELXL)))


def _run_shelxl_job(job: Path, exe: Path, timeout_s: int) -> dict[str, Any]:
    """The single SHELXL spawn of the reproduce arm (tests replace it).
    stdin=DEVNULL like every vendor spawn since the pa1 bisect (procutil):
    a child inheriting a pipe someone else is reading blocks at start-up."""
    import subprocess
    from ..procutil import NO_WINDOW
    proc = subprocess.run([str(exe), "job"], cwd=str(job),
                          stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, errors="replace", timeout=timeout_s,
                          creationflags=NO_WINDOW)
    return {"returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-600:]}


def _job_r1(job: Path) -> tuple[float | None, int | None, list[str]]:
    """R1 for Fo > 4sig from job.lst (job.res REM as fallback), plus
    SHELXL's own '**' error lines when there is none."""
    errs: list[str] = []
    for name in ("job.lst", "job.res"):
        p = job / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"R1 =\s*([\d.]+) for\s*(\d+)", text)
        if m:
            return float(m.group(1)), int(m.group(2)), []
        if name == "job.lst":
            errs = [ln.strip() for ln in text.splitlines() if "**" in ln][:4]
    return None, None, errs


def _reproduce_refinement(final_cif: Path,
                          timeout_s: int = 60) -> dict[str, Any]:
    """Does the delivered model give the CIF's R1? Extract the embedded
    _shelx_res_file / _shelx_hkl_file (/ _shelx_fab_file) and run SHELXL
    with zero cycles: structure factors of the model AS DELIVERED, nothing
    refined, so the claimed R1(gt) has to fall out to within 0.002.

    pa1 §9: the s2 gate only recomputes R1 from the fcf, which the same
    process wrote. Seventeen masked pa1 deliveries had a final.res without
    an ABIN card (eleven without a final.fab at all) - res+hkl alone give
    hex-l1-r1 0.18, not the 0.0817 the CIF claims (PLAT995 territory).
    When that exact shape shows up (fab embedded, no ABIN) the arm reruns
    once with ABIN added so the report can say whether the model or the
    packaging is at fault. Report-level: never raises, never grades."""
    import shutil
    import subprocess
    import tempfile

    text = final_cif.read_text(encoding="utf-8", errors="replace")
    res = _embedded_shelx_block(text, "_shelx_res_file")
    hkl = _embedded_shelx_block(text, "_shelx_hkl_file")
    fab = _embedded_shelx_block(text, "_shelx_fab_file")
    if res is None or hkl is None:
        return {"skipped": "final.cif embeds no _shelx_res_file + "
                           "_shelx_hkl_file pair"}
    exe = _shelxl_exe()
    if not exe.exists():
        return {"skipped": f"no SHELXL at {exe}"}
    m = re.search(r"^_refine_ls_R_factor_gt\s+([\d.]+)", text, re.M)
    r1_cif = float(m.group(1)) if m else None
    res_lines = res.splitlines()
    has_abin = any(ln.strip().upper().startswith("ABIN") for ln in res_lines)

    def _ins(add_abin: bool, source_res: str) -> str:
        out: list[str] = []
        zero_cycles = False
        for ln in source_res.splitlines():
            u = ln.strip().upper()
            if u.startswith(("L.S.", "CGLS")):
                if not zero_cycles:
                    out.append("L.S. 0")
                    zero_cycles = True
            elif u.startswith(("ACTA", "LIST")):
                continue                    # no cif/fcf writing: speed
            else:
                if u.startswith("HKLF") and not zero_cycles:
                    out.append("L.S. 0")    # canonical node RES may omit L.S.
                    zero_cycles = True
                out.append(ln)
                if add_abin and u.startswith("UNIT"):
                    out.append("ABIN")
        return "\n".join(out) + "\n"

    def _run(add_abin: bool, source_res: str = res,
             source_fab: str | None = fab) -> dict[str, Any]:
        job = Path(tempfile.mkdtemp(prefix="cp_repro_"))
        try:
            (job / "job.ins").write_text(_ins(add_abin, source_res), encoding="utf-8")
            (job / "job.hkl").write_text(hkl + "\n", encoding="utf-8")
            if source_fab is not None:
                (job / "job.fab").write_text(source_fab + "\n", encoding="utf-8")
            try:
                run = _run_shelxl_job(job, exe, timeout_s)
            except subprocess.TimeoutExpired:
                return {"error": f"shelxl timed out after {timeout_s} s"}
            r1, n, errs = _job_r1(job)
            if r1 is None:
                return {"error": "SHELXL produced no R1: "
                        + ("; ".join(errs) or run.get("stdout_tail") or
                           f"exit {run.get('returncode')}")}
            return {"r1": r1, "n_strong": n}
        finally:
            shutil.rmtree(job, ignore_errors=True)

    out: dict[str, Any] = {"r1_cif": r1_cif, "fab_embedded": fab is not None,
                           "res_has_abin": has_abin, "shelxl": str(exe)}
    # the embedded res is SHELXL's own cross-check job; the FILE the agent
    # delivered as final.res is what a reader would rerun - pa1 shipped 17
    # masked deliveries whose final.res had no ABIN (quality.md §5.4)
    final_res = final_cif.with_name("final.res")
    if final_res.exists():
        delivered_res = final_res.read_text(encoding="utf-8", errors="replace")
        delivered_fab_path = final_cif.with_name("final.fab")
        delivered_fab = (delivered_fab_path.read_text(encoding="utf-8", errors="replace")
                         if delivered_fab_path.exists() else None)
        out["delivered_res_has_abin"] = any(
            ln.strip().upper().startswith("ABIN") for ln in delivered_res.splitlines())
        delivered = _run(False, delivered_res, delivered_fab)
        out["delivered_res_replay"] = delivered
        if "r1" in delivered and r1_cif is not None:
            out["delivered_res_delta"] = round(delivered["r1"] - r1_cif, 4)
            out["delivered_res_reproducible"] = abs(out["delivered_res_delta"]) <= 0.002
        else:
            out["delivered_res_reproducible"] = None
        if fab is not None and not out["delivered_res_has_abin"]:
            out["packaging_note"] = ("delivered final.res carries no ABIN "
                                     "card although the CIF embeds a .fab: "
                                     "final.res + hkl alone will not "
                                     "reproduce the masked R1")
    first = _run(add_abin=False)
    if "error" in first:
        out["error"] = first["error"]
        return out
    out["reproduced_r1"] = first["r1"]
    out["n_strong"] = first["n_strong"]
    if r1_cif is None:
        out["note"] = "CIF carries no _refine_ls_R_factor_gt to compare"
        return out
    out["delta"] = round(first["r1"] - r1_cif, 4)
    out["reproducible"] = abs(out["delta"]) <= 0.002
    if not out["reproducible"] and fab is not None and not has_abin:
        second = _run(add_abin=True)
        if "error" not in second:
            out["reproduced_r1_with_abin"] = second["r1"]
            out["reproducible_with_abin"] = bool(
                abs(second["r1"] - r1_cif) <= 0.002)
            out["note"] = ("final.res carries no ABIN card although the CIF "
                           "embeds a .fab: res+hkl alone do not give the "
                           "CIF R1"
                           + (", they do once ABIN is added (packaging "
                              "defect, not a model defect)"
                              if out["reproducible_with_abin"] else
                              ", and neither does res+hkl+fab"))
    return out


def _load_project_nodes(project_dir: Path) -> dict[str, dict]:
    """{node id: node.json} from <project>/.crystalpilot/refine/nodes/."""
    nodes: dict[str, dict] = {}
    root = project_dir / ".crystalpilot" / "refine" / "nodes"
    for p in sorted(root.glob("*/node.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict):
            nodes[str(d.get("id") or p.parent.name)] = d
    return nodes


#: a node may carry at most this many times the delivered model's
#: parameters before its lower R1 stops being a comparison. An R1 always
#: falls when parameters are added, so a P1 descent (every atom set free)
#: undercuts the symmetric model it came from by construction - that is a
#: known trial, not a better answer.
BETTER_NODE_PARAM_RATIO = 1.5


def _node_sg_number(sg: Any) -> int | None:
    """IT number of a recorded space-group string, so settings of one group
    (P 21/n and P 21/c) compare equal and P1 vs P-1 do not."""
    if not sg:
        return None
    try:
        from cctbx import sgtbx
        return int(sgtbx.space_group_info(symbol=str(sg)).type().number())
    except Exception:  # noqa: BLE001 - an unreadable symbol proves nothing
        return None


def _node_facts(node: dict) -> dict[str, Any]:
    m = node.get("metrics") if isinstance(node.get("metrics"), dict) else {}
    n_params = m.get("n_params")
    if not isinstance(n_params, int) or n_params <= 0:
        n_params = None                  # run_shelxl adopt nodes record -1
    return {"sg": (node.get("data") or {}).get("space_group"),
            "n_params": n_params,
            "n_atoms": (node.get("model") or {}).get("n_atoms"),
            "branch": node.get("branch"), "tool": node.get("tool"),
            "label": (m or {}).get("label")}


def _node_comparable(cand: dict[str, Any],
                     delivered: dict[str, Any]) -> str | None:
    """None when `cand` is a fair comparison for the delivered model, else
    the reason it is not. Unknown facts never disqualify: a node is only
    skipped on evidence, never on a gap."""
    c_sg, d_sg = _node_sg_number(cand["sg"]), _node_sg_number(delivered["sg"])
    if c_sg is not None and d_sg is not None and c_sg != d_sg:
        return (f"space group {cand['sg']} differs from the delivered "
                f"{delivered['sg']} - a lower-symmetry trial refines more "
                "parameters against the same data")
    c_n, d_n = cand["n_params"], delivered["n_params"]
    what = "parameters"
    if c_n is None or d_n is None:
        c_n, d_n, what = cand["n_atoms"], delivered["n_atoms"], "atoms"
    if isinstance(c_n, int) and isinstance(d_n, int) and d_n > 0 \
            and c_n > BETTER_NODE_PARAM_RATIO * d_n:
        return (f"{c_n} {what} vs the delivered {d_n} (> "
                f"{BETTER_NODE_PARAM_RATIO}x): a bigger model buys a lower "
                "R1 by construction")
    return None


def node_tree_report(nodes: dict[str, dict], delivered_r1: float | None,
                     delivered_node_id: str | None = None,
                     delivered_sg: str | None = None,
                     delivered_n_params: int | None = None,
                     delivered_n_atoms: int | None = None) -> dict[str, Any]:
    """Best COMPARABLE node R1 in the tree vs the R1 that was delivered.

    pa1 hex-l3-r3 delivered R1 0.1851 (no mask) while its own tree held
    n0034 at 0.080 and n0044 at 0.092 with the mask - nobody noticed
    because the grader only ever read the delivery. A node's R1 comes
    from its `metrics.r1_strong` (None for import/edit nodes). Report-level:
    a better node may be a worse model (fewer atoms, another cut), so the
    delta is a reason, not a demotion.

    Comparable means: the same space-group TYPE as the delivered model and
    no more than BETTER_NODE_PARAM_RATIO times its parameters. reg1-ext2
    nm was told "a better node existed: n0012 R1 0.0807 vs delivered
    0.0948" - n0012 was the P1 descent, 74 atoms / 414 parameters against
    the delivered P-1 model's 37 / 207. Rejecting it was correct, and a
    grader that calls that an oversight teaches the wrong lesson. Every
    lower-R1 node that is skipped is listed with its reason in
    `better_nodes_skipped`, so nothing is hidden."""
    scored = [(nid, n["metrics"]["r1_strong"], n) for nid, n in nodes.items()
              if isinstance(n.get("metrics"), dict)
              and isinstance(n["metrics"].get("r1_strong"), (int, float))]
    out: dict[str, Any] = {"n_nodes": len(nodes), "n_scored": len(scored),
                           "delivered_node_id": delivered_node_id}
    if not scored:
        out["note"] = "no node in the tree carries an R1"
        return out
    dn = nodes.get(delivered_node_id or "")
    delivered = _node_facts(dn) if dn else {"sg": None, "n_params": None,
                                            "n_atoms": None}
    # the delivery's own facts (final.cif / REPORT.json) fill what the
    # delivered node does not carry - a set_z or rename node has no metrics
    for key, val in (("sg", delivered_sg), ("n_params", delivered_n_params),
                     ("n_atoms", delivered_n_atoms)):
        if delivered.get(key) in (None, "") and val not in (None, ""):
            delivered[key] = val
    out["delivered_model"] = {"space_group": delivered["sg"],
                              "n_params": delivered["n_params"],
                              "n_atoms": delivered["n_atoms"]}
    out["comparability_rule"] = (
        "only nodes of the delivered space-group type and within "
        f"{BETTER_NODE_PARAM_RATIO}x its parameter count count as 'better'")

    if dn and isinstance(dn.get("metrics"), dict) and isinstance(
            dn["metrics"].get("r1_strong"), (int, float)):
        out["delivered_node_r1"] = dn["metrics"]["r1_strong"]
        out["delivered_r1_source"] = "node metrics"
    else:
        out["delivered_node_r1"] = delivered_r1
        out["delivered_r1_source"] = "final.cif"
    d_r1 = out["delivered_node_r1"]

    comparable: list[tuple[str, float, dict]] = []
    skipped: list[dict[str, Any]] = []
    for nid, r1, n in scored:
        if nid == delivered_node_id:
            continue
        reason = _node_comparable(_node_facts(n), delivered)
        if reason is None:
            comparable.append((nid, r1, n))
        elif d_r1 is None or r1 < d_r1:
            skipped.append({"node": nid, "r1": r1, "reason": reason})
    skipped.sort(key=lambda r: r["r1"])
    out["n_comparable"] = len(comparable)
    if skipped:
        out["better_nodes_skipped"] = skipped

    if not comparable:
        out["note"] = ("no node in the tree is a fair comparison for the "
                       "delivered model" if skipped else
                       "no other scored node in the tree")
        out["better_node_existed"] = False
        return out
    best_id, best_r1, best = min(comparable, key=lambda t: t[1])
    out.update({"best_node_id": best_id, "best_node_r1": best_r1,
                "best_node_label": (best.get("metrics") or {}).get("label"),
                "best_node_masked": best.get("mask") is not None,
                "best_node_atoms": (best.get("model") or {}).get("n_atoms")})
    if d_r1 is not None:
        out["delivery_vs_best_delta"] = round(d_r1 - best_r1, 4)
        out["better_node_existed"] = out["delivery_vs_best_delta"] > 0.01
    return out


#: above this many P1 atoms the mask / neighbour searches are skipped
CHEM_MAX_P1_ATOMS = 2000

#: PLATON alert codes that assert a solvent-accessible void exists.
#: Meanings are PLATON's own, quoted from the repo's alert dictionary
#: crystalpilot/report/checkcif_kb_auto.json:
#:   601 "Test for (Unreported) solvent accessible voids"
#:   602 "Test for TOO LARGE (Unreported) solvent accessible voids"
#:   604 "Test for TOO Many VOIDS"
#:   605 "Test for (Reported) solvent accessible voids"
#: 603 ("TOO LARGE Unit Cell for VOID search") and 607 ("Skipped VOID
#: Test") are deliberately absent: they say PLATON did not look, not that
#: a void is there. P11 - the porosity verdict is PLATON's own rule table,
#: read from its output; this grader must not re-encode it as a fraction.
PLATON_VOID_ALERT_CODES = frozenset({"601", "602", "604", "605"})


def _non_h(xs):
    from .evaluate import _select_elements
    return _select_elements(xs, lambda e: e not in ("H", "D"))


def _platon_void_alerts(checkcif: dict | None,
                        final_cif: Path) -> tuple[list[dict], str | None]:
    """(void alerts, source) as PLATON reported them: the mentor's
    independent rerun first, the delivered checkcif.json second,
    ([], None) when neither exists.

    The rerun keeps its A/B/C alerts as the strings 'A 602 text'
    (`alerts_abc`, already narrowed by explanation_gate to codes the
    agent's own run also raised) plus `rerun_only_codes` - bare codes the
    rerun raised and the agent's run did not, which carry no level or text
    but are still PLATON saying 'void'. Both are read. G-level alerts
    never survive into the gate's output, so a void PLATON graded G is
    invisible here: that under-reports a void, it never invents one."""
    cc = checkcif or {}
    if cc.get("available"):
        out: list[dict] = []
        for row in cc.get("alerts_abc") or []:
            m = re.match(r"\s*([ABC])\s+(\d{3})\s*(.*)", str(row))
            if m and m.group(2) in PLATON_VOID_ALERT_CODES:
                out.append({"code": m.group(2), "level": m.group(1),
                            "text": m.group(3)})
        seen = {a["code"] for a in out}
        for c in cc.get("rerun_only_codes") or []:
            if str(c) in PLATON_VOID_ALERT_CODES and str(c) not in seen:
                out.append({"code": str(c), "level": None,
                            "text": "raised by the mentor's PLATON rerun "
                                    "only (level/text not retained)"})
        return out, "platon rerun"
    p = final_cif.with_name("checkcif.json")
    if not p.exists():
        return [], None
    try:
        d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return [], None
    # the agent's own run: every level counts, because a void alert is a
    # statement that the void is there, not a severity we re-grade
    return ([{"code": str(a.get("code")), "level": str(a.get("level") or ""),
              "text": str(a.get("text") or "")}
             for a in (d.get("alerts") or [])
             if isinstance(a, dict)
             and str(a.get("code")) in PLATON_VOID_ALERT_CODES],
            "delivered checkcif.json")


def _porosity_flag(out: dict[str, Any], n_guests: int | None
                   ) -> dict[str, Any]:
    """Fill `porous_unmasked_unmodelled` + `porosity_check` on `out` from
    PLATON's verdict and what the delivery does about it, and return it.
    `n_guests` is None when the structure would not load or was skipped.

    None ("not_checked") is a first-class answer: without a PLATON result
    we do not know whether this void is one PLATON would report, and the
    grader must say so rather than fall back on a constant of its own."""
    source, alerts = out["platon_source"], out["platon_void_alerts"]
    why = None
    if source is None:
        flag, why = None, ("no PLATON result (neither an independent rerun "
                           "nor a checkcif.json beside the delivery)")
    elif not alerts or out["mask_block_in_cif"]:
        flag = False          # PLATON saw no void, or the CIF already masks
    elif n_guests is None:
        flag, why = None, ("PLATON reports a void but the model could not "
                           "be read, so modelled guests are uncounted")
    else:
        flag = n_guests == 0
    out["porous_unmasked_unmodelled"] = flag
    out["porosity_check"] = "not_checked" if flag is None else "platon"
    if why:
        out["note"] = why
    return out


def porosity_report(final_cif: Path, xs,
                    checkcif: dict | None = None) -> dict[str, Any]:
    """PLATON's void verdict against what the delivery does about it - a
    mask block in the CIF, or modelled guest fragments - with the smtbx
    solvent-accessible volume (probe 1.2 A) reported alongside as fact.

    pa1: four hex deliveries at R1 0.185 were the bare framework in a 79 %
    void - the mask tool's silent "0 e" had been read as "the data do not
    support a mask" - and the cage deliveries modelled nothing in their
    pores either. Whether a void is worth reporting is PLATON's call
    (601/602/604/605, see PLATON_VOID_ALERT_CODES) read back from its
    output, never a fraction re-encoded here; the smtbx numbers size the
    void PLATON named, and with no PLATON result at all the check reports
    itself not_checked instead of guessing."""
    text = final_cif.read_text(encoding="utf-8", errors="replace")
    has_mask = bool(re.search(r"_(?:platon_squeeze|smtbx_masks)_void_",
                              text))
    alerts, source = _platon_void_alerts(checkcif, final_cif)
    out: dict[str, Any] = {"mask_block_in_cif": has_mask,
                           "probe_radius": 1.2,
                           "platon_void_alerts": alerts,
                           "platon_source": source}
    if xs is None:
        out["skipped"] = "structure not loadable"
        return _porosity_flag(out, None)
    heavy = _non_h(xs)
    n_p1 = heavy.scatterers().size() * heavy.space_group().order_z()
    out["n_p1_atoms"] = n_p1
    if heavy.scatterers().size() == 0:
        out["skipped"] = "no non-H atoms"
        return _porosity_flag(out, None)
    if n_p1 > CHEM_MAX_P1_ATOMS:
        out["skipped"] = f"{n_p1} P1 atoms > {CHEM_MAX_P1_ATOMS}"
        return _porosity_flag(out, None)
    from smtbx import masks

    from ..chem.connectivity import analyze_connectivity
    sav = masks.solvent_accessible_volume(
        heavy, solvent_radius=1.2, shrink_truncation_radius=1.2,
        grid_step=0.4)
    vol = float(heavy.unit_cell().volume())
    frac = float(sav.solvent_accessible_volume) / vol if vol else 0.0
    conn = analyze_connectivity(heavy)
    guests = [f for f in conn.fragments[1:] if f["n_atoms"] >= 2]
    singles = [f for f in conn.fragments[1:] if f["n_atoms"] == 1]
    out.update({
        "void_fraction": round(frac, 3),
        "void_volume_A3": round(float(sav.solvent_accessible_volume), 1),
        "n_voids": int(sav.n_voids()),
        "n_guest_fragments": len(guests),
        "n_single_atom_fragments": len(singles),
    })
    return _porosity_flag(out, len(guests))


def _p1_neighbour_table(xs, cutoff: float):
    """P1 expansion + every pair within `cutoff` over the 27 cell images.
    nbrs[i] = [(j, shift, d)]: atom j translated by `shift` sits d A from
    atom i in the home cell."""
    import itertools

    import numpy as np
    p1 = xs.expand_to_p1()
    scs = list(p1.scatterers())
    elements = ["".join(c for c in sc.scattering_type if c.isalpha())[:2]
                .capitalize() for sc in scs]
    labels = [sc.label for sc in scs]
    frac = np.array([[x % 1.0 for x in sc.site] for sc in scs])
    ortho = np.array(p1.unit_cell().orthogonalization_matrix()).reshape(3, 3)
    cart0 = frac @ ortho.T
    nbrs: list[list[tuple[int, tuple, float]]] = [[] for _ in scs]
    for shift in itertools.product((-1, 0, 1), repeat=3):
        cart_s = (frac + np.array(shift)) @ ortho.T
        d2 = ((cart0[:, None, :] - cart_s[None, :, :]) ** 2).sum(axis=2)
        ii, jj = np.where((d2 < cutoff ** 2) & (d2 > 0.01))
        for i, j in zip(ii.tolist(), jj.tolist()):
            nbrs[i].append((j, tuple(shift), float(np.sqrt(d2[i, j]))))
    return labels, elements, frac, ortho, nbrs


def chemistry_flags(xs) -> dict[str, Any]:
    """Reference-free chemistry sanity of the delivered model.

    Four checks the pa1 deliveries needed (§9 "化学合理性门"):
      (a) metal coordination number outside the element's plausible window
          (knowledge.METAL_PROFILES) - hex-l1-r1's Zn at CN 8 was warned
          twice by validate and delivered anyway;
      (b) an atom labelled N in a carboxylate-shaped X-C(-C)-X' group with
          X...X' ~2.2 A - the cu runs' N1 (N-C 1.25, N...N' 2.23 A) is the
          third carboxylate arm's O - only fires when that N is terminal
          (its only heavy-atom neighbour is the carboxyl-like C): an
          amide or imide N keeps its acyl C plus >= 1 more heavy
          neighbour (org-full-r1's AHL amide N, N-C 1.34, N...O 2.24 A,
          has two) and is exempt;
      (c) an N in a planar six-membered ring that carries a C substituent
          (cu-l1-r1 N2: ring atom bonded to the carboxylate C at 1.50 A)
          - an aromatic C labelled N, unless the ring is a pyridinium:
          reported as low confidence;
      (d) a metal with >= 5 C at 1.9-2.1 A (no chemistry) - while >= 5 C
          at 2.4-2.6 A is an eta-bound ring (cage Cp3Zr3) and is noted so
          nobody reads it as ghosts again;
      (e) pa2: the metal-bonded light-atom audit (chem.metal_bonded_audit,
          the same function validate_structure runs) - metal CN counts an
          eta-ring as ONE ligand (3 sites) so an eta5-Cp is no longer "CN=5",
          and every C/N at a metal without a carbon skeleton, carboxylate O
          under a C/N label, N-N / carbonyl-length C-C bond outside
          azide/azole/alkyne chemistry is a `metal_bonded_light_atoms` /
          `suspect_bonds` flag (high severity) or note (medium).
    Flags are reasons, never a demotion below acceptable."""
    import numpy as np

    from ..chem.connectivity import _bond_cutoff
    from ..chem.knowledge import is_metal, profile_for
    from ..chem.metal_bonded_audit import audit_metal_bonded_light_atoms
    out: dict[str, Any] = {"flags": [], "notes": [], "metal_coordination": []}
    if xs is None:
        out["skipped"] = "structure not loadable"
        return out
    heavy = _non_h(xs)
    n_p1 = heavy.scatterers().size() * heavy.space_group().order_z()
    out["n_p1_atoms"] = n_p1
    if n_p1 == 0:
        out["skipped"] = "no non-H atoms"
        return out
    if n_p1 > CHEM_MAX_P1_ATOMS:
        out["skipped"] = f"{n_p1} P1 atoms > {CHEM_MAX_P1_ATOMS}"
        return out
    labels, el, frac, ortho, nbrs = _p1_neighbour_table(heavy, 3.0)
    flags, notes = out["flags"], out["notes"]
    try:
        mba = audit_metal_bonded_light_atoms(heavy)
    except Exception as e:  # noqa: BLE001 - evidence arm never blocks
        mba = None
        notes.append(f"metal-bonded light-atom audit did not run: "
                     f"{type(e).__name__}: {e}")
    env_of = {e["metal"]: e for e in (mba["metal_environments"] if mba else [])}

    def _cart(j: int, shift) -> "np.ndarray":
        return (frac[j] + np.array(shift)) @ ortho.T

    def _dist(i: int, j: int, shift) -> float:
        return float(np.linalg.norm(_cart(j, shift) - _cart(i, (0, 0, 0))))

    seen_metal: set[str] = set()
    seen_n: set[str] = set()
    for i, e in enumerate(el):
        # ---- (a) + (d): metals ------------------------------------------
        if is_metal(e) and labels[i] not in seen_metal:
            seen_metal.add(labels[i])
            prof = profile_for(e)
            env = env_of.get(labels[i])
            if env is not None:
                # audit CN: eta-ring = one ligand (3 sites), H excluded,
                # chelate skeleton carbons never donors
                cn = env["cn_sites"]
                row = {"atom": labels[i], "element": e, "cn": cn,
                       "cn_atoms": env["cn_atoms"],
                       "cn_ligands": env["cn_ligands"],
                       "cn_sites": env["cn_sites"], "donors": env["donors"],
                       "expected_cn": list(prof.cn_range) if prof else None}
                cn_note = (f" (donor atoms {env['cn_atoms']}, ligands "
                           f"{env['cn_ligands']}; eta-ring = 3 sites, H excluded)")
            else:
                donors = [(j, d) for j, s, d in nbrs[i]
                          if d >= 0.9 and not is_metal(el[j])
                          and d <= _bond_cutoff(e, el[j])]
                cn = len(donors)
                row = {"atom": labels[i], "element": e, "cn": cn,
                       "expected_cn": list(prof.cn_range) if prof else None}
                cn_note = ""
            out["metal_coordination"].append(row)
            if prof and not prof.cn_range[0] <= cn <= prof.cn_range[1]:
                flags.append(f"{labels[i]} ({e}) CN={cn} outside the "
                             f"plausible {list(prof.cn_range)} for {e}{cn_note}")
            c_eta = [d for j, s, d in nbrs[i] if el[j] == "C"
                     and 2.35 <= d <= 2.65]
            c_short = [d for j, s, d in nbrs[i] if el[j] == "C"
                       and 1.85 <= d <= 2.15]
            if len(c_eta) >= 5:
                notes.append(f"{labels[i]} ({e}) has {len(c_eta)} C at "
                             f"2.4-2.6 A: an eta-bound ring (Cp-like), "
                             "not ghosts or short contacts")
            if len(c_short) >= 5:
                # 5 C at ~2.0 A is a metallocene on a 3d metal (ferrocene
                # Fe-C 2.05 A) but impossible on a Zr-class metal whose
                # M-O window already starts at 2.0 A
                if prof and prof.m_o_range[0] >= 2.0:
                    flags.append(
                        f"{labels[i]} ({e}) has {len(c_short)} C at "
                        f"1.9-2.1 A: no {e} coordination chemistry looks "
                        "like this (misassigned type or mislabelled ring?)")
                else:
                    notes.append(f"{labels[i]} ({e}) has {len(c_short)} C "
                                 "at 1.9-2.1 A: metallocene-type eta-bound "
                                 "ring")
            continue
        if e != "N" or labels[i] in seen_n:
            continue
        seen_n.add(labels[i])
        # ---- (b): carboxylate-shaped N -----------------------------------
        carboxy = _carboxylate_shaped(i, nbrs, el, _dist)
        if carboxy:
            d1, dxx = carboxy
            # element-generic exemption: a carboxylate O is terminal (its
            # only heavy neighbour is the carboxyl-like C); an amide or
            # imide N keeps its acyl C plus >= 1 more heavy substituent
            # (org-full-r1's amide N, N-C 1.34, N...O 2.24 A, has two and
            # must not be flagged)
            n_heavy = sum(1 for j, s, d in nbrs[i]
                          if d >= 0.9 and d <= _bond_cutoff(e, el[j]))
            if n_heavy == 1:
                flags.append(f"{labels[i]} is labelled N but sits in a "
                             f"carboxylate-shaped X-C(-C)-X' group (N-C "
                             f"{d1:.2f}, X...X' {dxx:.2f} A, terminal N): "
                             "carboxylate O mislabelled as N?")
        # ---- (c): ring N carrying a C substituent ------------------------
        bonded = [(j, s, d) for j, s, d in nbrs[i]
                  if el[j] in ("C", "N") and 1.20 <= d <= 1.65]
        if len(bonded) < 3:
            continue
        ring = _six_ring_through(i, nbrs, el)
        if ring is None:
            continue
        ring_members = {(j, s) for j, s in ring}
        exo = [(j, s, d) for j, s, d in bonded
               if (j, s) not in ring_members and el[j] == "C"
               and 1.40 <= d <= 1.60]
        if exo:
            pts = np.array([_cart(j, s) for j, s in ring])
            dev = np.linalg.svd(pts - pts.mean(axis=0))[1][-1] / len(pts) ** 0.5
            if dev <= 0.15:
                flags.append(
                    f"{labels[i]} is a planar six-ring atom carrying a C "
                    f"substituent at {exo[0][2]:.2f} A: aromatic C "
                    "labelled N? (a pyridinium N-C looks the same; low "
                    "confidence)")
    # ---- (e): metal-bonded light atoms + suspect bonds ---------------------
    if mba is not None:
        susp = mba["suspect_elements"]
        bonds = mba["suspect_bonds"]
        high = [s for s in susp if s["severity"] == "high"]
        hb = [b for b in bonds if b["severity"] == "high"]

        def _atom(s: dict) -> str:
            return (f"{s['label']} ({s['element']}) {s['d']:.2f} A from "
                    f"{s['metal']} -> {s['candidates'][0]}")

        def _bond(b: dict) -> str:
            return f"{b['a']}-{b['b']} {b['d']:.2f} A ({b['kind']})"

        out["metal_bonded_light_atoms"] = {
            "n": len(susp), "n_high": len(high),
            "atoms": [{k: s.get(k) for k in ("label", "element", "metal", "d",
                                              "severity", "kind", "candidates")}
                      for s in susp[:5]],
            "n_suspect_bonds": len(bonds), "n_suspect_bonds_high": len(hb),
            "bonds": [{k: b[k] for k in ("a", "b", "d", "kind", "severity")}
                      for b in bonds[:5]],
            "n_pi_ligands": len(mba["pi_ligands"]),
            "pi_ligands": [f"eta{r['hapticity']}-{r['ring_size']} "
                           f"[{', '.join(r['ring_labels'])}] on {r['metal']}"
                           + ("" if r["ring_closed"] else " (open fragment)")
                           for r in mba["pi_ligands"][:6]],
            "summary": mba["summary"], "note": mba["note"],
        }
        if high:
            flags.append(f"metal_bonded_light_atoms: {len(susp)} ({len(high)} "
                         "high) - " + "; ".join(_atom(s) for s in high[:5])
                         + ("; ..." if len(high) > 5 else ""))
        elif susp:
            notes.append(f"metal_bonded_light_atoms: {len(susp)} medium-severity "
                         "label(s) to check - " + "; ".join(_atom(s) for s in susp[:5])
                         + ("; ..." if len(susp) > 5 else ""))
        if hb:
            flags.append(f"suspect_bonds: {len(bonds)} N-N / carbonyl-length C-C "
                         f"bond(s) outside azide/azole/alkyne chemistry ({len(hb)} "
                         "high) - " + "; ".join(_bond(b) for b in hb[:5])
                         + ("; ..." if len(hb) > 5 else ""))
        elif bonds:
            notes.append(f"suspect_bonds: {len(bonds)} medium-severity N-N / C-C "
                         "bond(s) to check - " + "; ".join(_bond(b) for b in bonds[:5])
                         + ("; ..." if len(bonds) > 5 else ""))
    return out


def _carboxylate_shaped(i: int, nbrs, el, dist) -> tuple[float, float] | None:
    """(N-C, X...X') when atom i (labelled N) is one X of an X-C(-C)-X'
    group with X...X' 2.10-2.40 A - the carboxylate O...O separation."""
    import numpy as np
    for c, s1, d1 in nbrs[i]:
        if el[c] != "C" or not 1.15 <= d1 <= 1.40:
            continue
        partners = []
        has_ring_c = False
        for x, s2, d2 in nbrs[c]:
            shift = tuple(int(v) for v in np.add(s1, s2))
            if el[x] == "C" and 1.40 <= d2 <= 1.65:
                has_ring_c = True
            elif (el[x] in ("O", "N") and 1.15 <= d2 <= 1.40
                    and not (x == i and shift == (0, 0, 0))):
                partners.append((x, shift))
        if not has_ring_c:
            continue
        for x, shift in partners:
            dxx = dist(i, x, shift)
            if 2.10 <= dxx <= 2.40:
                return d1, dxx
    return None


def _six_ring_through(i: int, nbrs, el) -> list[tuple[int, tuple]] | None:
    """One six-membered C/N ring through atom i (home image) as
    [(atom, shift)], or None. Depth-6 DFS over the periodic bond graph."""
    import numpy as np

    def _bonds(k: int):
        return [(j, s, d) for j, s, d in nbrs[k]
                if el[j] in ("C", "N") and 1.20 <= d <= 1.65]

    def dfs(path: list[tuple[int, tuple]]):
        cur, cur_s = path[-1]
        for j, s, _d in _bonds(cur):
            ns = tuple(int(x) for x in np.add(cur_s, s))
            if len(path) == 6:
                if j == i and ns == (0, 0, 0):
                    return list(path)
                continue
            if j == i or (j, ns) in path:
                continue
            hit = dfs(path + [(j, ns)])
            if hit:
                return hit
        return None

    return dfs([(i, (0, 0, 0))])


#: what a publication delivery consists of (checkCIF report may be
#: checkcif.json / checkcif_alerts.md / checkcif*.html|txt)
REQUIRED_DELIVERY_FILES = ("final.cif", "final.fcf", "final.res",
                           "REPORT.json", "VALIDATION.md", "SUMMARY.md")


def delivery_files(final_cif: Path) -> dict[str, Any]:
    """Which delivery files exist beside final.cif. pa1 hex-l2-r3 shipped
    without SUMMARY.md/VALIDATION.md (27 unexplained checkCIF codes, empty
    verdict) and graded like a complete delivery."""
    d = final_cif.parent
    out: dict[str, Any] = {name: (d / name).exists()
                           for name in REQUIRED_DELIVERY_FILES}
    cc = sorted(p.name for p in d.glob("checkcif*")
                if p.suffix.lower() in (".json", ".md", ".html", ".txt"))
    out["checkcif"] = bool(cc)
    out["checkcif_files"] = cc
    out["final.fab"] = (d / "final.fab").exists()
    out["missing"] = [k for k in (*REQUIRED_DELIVERY_FILES, "checkcif")
                      if not out[k]]
    return out


def _mentor_checks(project_dir: Path, final_cif: Path, sc: dict[str, Any],
                   run_reproduce: bool) -> dict[str, Any]:
    """Run every report-level check; each arm is fenced so no single
    failure (a mask FFT, an odd CIF) can take the grade down with it."""
    from .evaluate import load_reference
    out: dict[str, Any] = {"delivery_files": delivery_files(final_cif)}
    out["checkcif_a_split"] = checkcif_a_split(sc.get("checkcif"), final_cif)
    if run_reproduce:
        try:
            out["reproducibility"] = _reproduce_refinement(final_cif)
        except Exception as e:  # noqa: BLE001 - evidence arm never blocks
            out["reproducibility"] = {"error": f"{type(e).__name__}: {e}"}
    else:
        out["reproducibility"] = {"skipped": "disabled by caller"}
    rep_path = final_cif.with_name("REPORT.json")
    final_node = None
    if rep_path.exists():
        try:
            final_node = json.loads(rep_path.read_text(
                encoding="utf-8", errors="replace")).get("final_node")
        except (OSError, ValueError):
            pass
    # a name the operator loop contradicts is a delivery defect in its own
    # right: cctbx refuses the file and PLATON raises 120
    sym = _cif_symmetry_check(final_cif)
    out["cif_symmetry"] = sym
    out["cif_symmetry_inconsistent"] = sym.get("consistent") is False
    delivered_sg = sym.get("ops_setting") or sc["cif"].get("space_group")
    out["node_tree"] = node_tree_report(
        _load_project_nodes(project_dir), sc["cif"].get("r1_gt"), final_node,
        delivered_sg=delivered_sg,
        delivered_n_params=sc["cif"].get("n_params"),
        delivered_n_atoms=sc["cif"].get("n_atoms"))
    try:
        xs = load_reference(None, str(final_cif))
    except Exception:  # noqa: BLE001
        xs = None
    for key, fn in (("porosity",
                     lambda: porosity_report(final_cif, xs,
                                             sc.get("checkcif"))),
                    ("chemistry", lambda: chemistry_flags(xs))):
        try:
            out[key] = fn()
        except Exception as e:  # noqa: BLE001
            out[key] = {"error": f"{type(e).__name__}: {e}", "flags": []}
    return out


def _mentor_reasons(mc: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(blocking, notes): blocking entries hold the delivery below
    publication (never below acceptable), notes are reported only."""
    blocking: list[str] = []
    notes: list[str] = []
    split = mc.get("checkcif_a_split") or {}
    if split.get("blocking_model_quality"):
        blocking.append("blocking A alerts (model quality): "
                        + ", ".join(split["blocking_model_quality"]))
    if split.get("metadata_missing"):
        notes.append("metadata incomplete (A-level CIF-item alerts, not "
                     "scored): " + ", ".join(
                         s.split()[0] for s in split["metadata_missing"]))
    if split.get("data_quality"):
        notes.append("data-quality A alerts (describe the dataset, not the "
                     "model; must be explained, never block): " + ", ".join(
                         s.split()[0] for s in split["data_quality"]))
    missing = (mc.get("delivery_files") or {}).get("missing") or []
    if missing:
        blocking.append("delivery file set incomplete: " + ", ".join(missing))
    chem = mc.get("chemistry") or {}
    for f in (chem.get("flags") or [])[:4]:
        blocking.append("chemistry: " + f)
    por = mc.get("porosity") or {}
    porous = por.get("porous_unmasked_unmodelled")
    frac = por.get("void_fraction")
    smtbx = f"smtbx void {frac:.0%}" if isinstance(frac, float) else ""
    if porous:
        codes = ", ".join(sorted({a["code"] for a
                                  in por.get("platon_void_alerts") or []}))
        blocking.append(f"porous delivery (PLATON void alert {codes}"
                        + (f", {smtbx}" if smtbx else "")
                        + ") with neither a solvent mask nor modelled guests")
    elif por and porous is None:
        # an unknown is a gap in the evidence, never a pass: it is reported
        # and never blocks, because nothing was measured either way
        notes.append("porosity not checked: "
                     + str(por.get("note") or por.get("skipped")
                           or por.get("error") or "no porosity result")
                     + (f" ({smtbx})" if smtbx else ""))
    sym = mc.get("cif_symmetry") or {}
    if sym.get("consistent") is False:
        from ..io.cif_symmetry import conflict_summary
        blocking.append(
            "CIF symmetry inconsistent: " + conflict_summary(sym)
            + ". cctbx refuses the file (CifBuilderError) and PLATON raises "
              "120; write the Hall symbol of the refined setting, or bring "
              "the model onto the reference origin and refine there")
    nt = mc.get("node_tree") or {}
    if nt.get("better_node_existed"):
        notes.append(f"a better node existed: {nt['best_node_id']} R1 "
                     f"{nt['best_node_r1']} vs delivered "
                     f"{nt['delivered_node_r1']} "
                     f"(delta {nt['delivery_vs_best_delta']:+.4f})")
    for s in (nt.get("better_nodes_skipped") or [])[:3]:
        # named, not hidden: a lower R1 that is NOT a better answer is
        # still something the tutor should see
        notes.append(f"lower-R1 node {s['node']} (R1 {s['r1']}) is not a "
                     f"comparable model: {s['reason']}")
    rp = mc.get("reproducibility") or {}
    if rp.get("reproducible") is False:
        notes.append(f"CIF R1 {rp['r1_cif']} not reproduced by SHELXL from "
                     f"the embedded res+hkl ({rp['reproduced_r1']})"
                     + (f": {rp['note']}" if rp.get("note") else ""))
    if rp.get("packaging_note"):
        notes.append(rp["packaging_note"])
    if rp.get("delivered_res_reproducible") is False:
        blocking.append("delivered final.res does not reproduce the CIF R1")
        notes.append(
            f"delivered final.res R1 {(rp.get('delivered_res_replay') or {}).get('r1')} "
            f"vs CIF {rp.get('r1_cif')}; the embedded RES is a separate artifact, "
            "not evidence that the delivered restart file is faithful")
    return blocking, notes


# --------------------------------------------------------------------------- #
# reference layer
# --------------------------------------------------------------------------- #

#: two refinements count as the same resolution cut within this many A.
#: At d_min ~0.8 A, 0.02 A moves the limiting sphere by ~2 % in d and so
#: changes the reflection count far too little to move R1, while the cuts
#: that do make R1 incomparable (1.0 A vs 0.8 A) are an order of magnitude
#: larger.
R1_DELTA_D_MIN_TOL = 0.02


def _load_any_reference(reference: str | Path):
    from .evaluate import load_reference
    ref = Path(reference)
    if ref.suffix.lower() in (".res", ".ins"):
        return load_reference(str(ref), None)
    return load_reference(None, str(ref))


def _metric3(xs) -> list[list[float]]:
    g11, g22, g33, g12, g13, g23 = xs.unit_cell().metrical_matrix()
    return [[g11, g12, g13], [g12, g22, g23], [g13, g23, g33]]


def _reindex_onto(model_xs, ref_xs, rel_tol: float = 0.02):
    """Same lattice in a different setting? Search unimodular transforms
    with entries in {-1,0,1} comparing metric tensors, and return the
    model change-basis'd onto the reference setting (or None).

    Niggli parameter equality is NOT a sufficient identity test: near
    reduction boundaries two settings of one lattice can both look
    reduced (seen live on p770: axes agree to 0.2%, angles differ 3-4deg,
    related by [[-1,0,1],[0,-1,1],[0,0,1]]).
    """
    import itertools

    from cctbx import sgtbx

    ga, gr = _metric3(model_xs), _metric3(ref_xs)
    norm_r = sum(gr[i][j] ** 2 for i in range(3) for j in range(3)) ** 0.5

    def _mmul(a, b):
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
                for i in range(3)]

    def _t(a):
        return [[a[j][i] for j in range(3)] for i in range(3)]

    def _det(m):
        return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))

    matches = []
    for vals in itertools.product((-1, 0, 1), repeat=9):
        m = [list(vals[0:3]), list(vals[3:6]), list(vals[6:9])]
        if abs(_det(m)) != 1:
            continue
        g2 = _mmul(_t(m), _mmul(ga, m))
        err = sum((g2[i][j] - gr[i][j]) ** 2
                  for i in range(3) for j in range(3)) ** 0.5 / norm_r
        if err <= rel_tol:
            matches.append((err, m))
    if not matches:
        return []
    matches.sort(key=lambda t: t[0])
    # several distinct operators can match the metric equally well (r18
    # live failure: two candidates, only one is the true lattice
    # isomorphism for the CONTENT - metric error cannot tell them apart,
    # the caller must score each by actual atom matching). Return every
    # cell-landing candidate, best metric first.
    ref_uc = ref_xs.unit_cell()
    out = []
    seen: set[tuple] = set()
    for err, m in matches[:16]:
        for cand in (m, _int_inverse(m)):
            if cand is None:
                continue
            key = tuple(x for row in cand for x in row)
            if key in seen:
                continue
            seen.add(key)
            try:
                rot = sgtbx.rot_mx([int(x) for row in cand for x in row], 1)
                cb = sgtbx.change_of_basis_op(sgtbx.rt_mx(rot))
                xs2 = model_xs.change_basis(cb)
            except Exception:  # noqa: BLE001 - some ops invalid for the sg
                continue
            p2, pr = xs2.unit_cell().parameters(), ref_uc.parameters()
            if (all(abs(x - y) / max(y, 1e-6) <= 0.02 for x, y in
                    zip(p2[:3], pr[:3]))
                    and all(abs(x - y) <= 2.0
                            for x, y in zip(p2[3:], pr[3:]))):
                out.append((xs2, cand, err))
    return out


def _int_inverse(m):
    d = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
         - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
         + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    if d not in (1, -1):
        return None
    adj = [[(m[(i + 1) % 3][(j + 1) % 3] * m[(i + 2) % 3][(j + 2) % 3]
             - m[(i + 1) % 3][(j + 2) % 3] * m[(i + 2) % 3][(j + 1) % 3])
            for i in range(3)] for j in range(3)]
    return [[adj[i][j] * d for j in range(3)] for i in range(3)]


#: above this scatterer count, full-model emma matching is combinatorial
#: (a 400-atom P1 framework grinds for hours) - fall back to a heavy-atom
#: subset, or to cell+SG+composition phase identity when even that fails
EMMA_MAX_ATOMS = 300
#: `framework_reproduced_disorder_incomplete` needs this fraction of the
#: reference non-H atoms matched: a model missing HALF a reference cannot
#: be "the framework with an incomplete disorder model" just because every
#: miss happens to carry a PART number
DISORDER_INCOMPLETE_MIN_FRACTION = 0.85
_HEAVY_Z = 11


def _heavy_subset(xs):
    """Substructure of scatterers with Z >= _HEAVY_Z (Na and up)."""
    from cctbx.eltbx import tiny_pse
    from scitbx.array_family import flex
    keep = []
    for sc in xs.scatterers():
        elem = "".join(c for c in sc.scattering_type if c.isalpha())[:2]
        try:
            z = tiny_pse.table(elem.capitalize()).atomic_number()
        except Exception:  # noqa: BLE001 - unknown type: treat as light
            z = 0
        keep.append(z >= _HEAVY_Z)
    sel = flex.bool(keep)
    return xs.select(sel), sel.count(True)


#: How `emma.solved` - the "framework reproduced" verdict - is decided, in
#: words, so a grade never asserts a rule the reader cannot check. Kept in
#: step with benchmark.evaluate.evaluate_against_reference by
#: tests/test_grade_framework_rule.py.
EMMA_FRAMEWORK_RULE = (
    "framework reproduced (emma solved) = non-H recall >= 0.75 AND non-H "
    "precision >= 0.60; when the reference has heavy atoms (Z >= 17 or a "
    "metal) also heavy recall >= 0.99 with heavy precision >= 0.50, or "
    "heavy recall >= 0.65 with non-H recall >= 0.95 and precision >= 0.90. "
    "Reference atoms in a secondary bonded fragment and reference atoms "
    "with occupancy < 0.5 are scored apart (solvent / guest fairness); "
    "model atoms that reproduce them (a modelled counter-ion, co-former, "
    "solvent or guest) are not counted as spurious, so they lower neither "
    "recall nor precision. Matching tolerance 0.7 A, both structures "
    "brought to their reference setting first.")

#: a trailing single capital letter after a digit is the SHELX/PART
#: convention for a disorder component (C13A / C13B). Element-agnostic on
#: purpose: it must hold for any future crystal, not for one test set.
_PART_LABEL_RE = re.compile(r"^(?P<stem>[A-Za-z]{1,2}\d+)(?P<part>[A-Z])$")

#: an occupancy this far below 1 is a refined partial occupancy, i.e. a
#: disorder component / guest - not an atom of the ordered framework
_FULL_OCCUPANCY_TOL = 0.02


def _disorder_component_reasons(ref_xs, labels) -> dict[str, str]:
    """Which of `labels` are a DISORDER COMPONENT of the reference?

    Two setting- and element-independent tests, either sufficient:
      * refined occupancy below 1 (a PART with its own free variable);
      * a PART-style label suffix whose partner label exists in the same
        reference (C13A next to C13B).
    Returns {label: reason} for the ones that qualify."""
    occ: dict[str, float] = {}
    stems: dict[str, set] = {}
    for sc in ref_xs.scatterers():
        lbl = str(sc.label).strip()
        occ[lbl] = float(sc.occupancy)
        m = _PART_LABEL_RE.match(lbl)
        if m:
            stems.setdefault(m.group("stem").upper(),
                             set()).add(m.group("part"))
    out: dict[str, str] = {}
    for lbl in labels:
        lbl = str(lbl).strip()
        o = occ.get(lbl)
        if o is not None and o < 1.0 - _FULL_OCCUPANCY_TOL:
            out[lbl] = f"reference occupancy {o:.3f} < 1 (disorder component)"
            continue
        m = _PART_LABEL_RE.match(lbl)
        if m and len(stems.get(m.group("stem").upper(), set())) > 1:
            partners = sorted(stems[m.group("stem").upper()]
                              - {m.group("part")})
            out[lbl] = (f"PART-style label: the reference also carries "
                        f"{m.group('stem')}{partners[0]}")
    return out


def _framework_diagnosis(model_xs, ref_xs) -> dict[str, Any]:
    """Which REFERENCE non-H atoms did the delivery not account for?

    Deliberately unfiltered: no solvent/guest fairness rules, so the
    numbers say plainly `n_matched of n_ref`. ext2 dbu matched 26/28 and
    was reported "framework not reproduced" - the two misses were the
    0.265-occupancy minor component C12A/C13A, i.e. an incomplete
    disorder model on top of a reproduced framework, which is a different
    finding and a different remedy."""
    from cctbx import euclidean_model_matching as emma_mod

    from .evaluate import _select_elements, to_reference_setting

    out: dict[str, Any] = {}
    ref = to_reference_setting(
        _select_elements(ref_xs, lambda e: e not in ("H", "D")))
    mod = to_reference_setting(
        _select_elements(model_xs, lambda e: e not in ("H", "D")))
    n_ref, n_mod = ref.scatterers().size(), mod.scatterers().size()
    out["n_reference_non_h"], out["n_model_non_h"] = n_ref, n_mod
    if not n_ref or not n_mod:
        out["note"] = "nothing to match"
        return out
    if max(n_ref, n_mod) > EMMA_MAX_ATOMS:
        out["note"] = f"{max(n_ref, n_mod)} atoms > {EMMA_MAX_ATOMS}: skipped"
        return out
    if ref.space_group() != mod.space_group():
        out["note"] = ("model and reference are in different space groups "
                       "after reduction to the reference setting")
        return out
    if ref.unit_cell().parameters() != mod.unit_cell().parameters():
        try:
            mod = mod.customized_copy(crystal_symmetry=ref.crystal_symmetry())
        except Exception:  # noqa: BLE001 - let emma decide
            pass
    em_ref, em_mod = ref.as_emma_model(), mod.as_emma_model()
    try:
        matches = emma_mod.model_matches(
            em_ref, em_mod, tolerance=0.7,
            break_if_match_with_no_singles=False)
    except Exception as e:  # noqa: BLE001 - a diagnosis never blocks grading
        out["note"] = f"emma failed: {type(e).__name__}: {e}"
        return out
    if not matches.refined_matches:
        out["n_matched"] = 0
        out["match_fraction"] = 0.0
        out["unmatched_reference_atoms"] = [em_ref[i].label
                                            for i in range(em_ref.size())]
        out["verdict"] = "framework_not_reproduced"
        return out
    m = matches.refined_matches[0]
    matched = {i for i, _j in m.pairs}
    unmatched = [em_ref[i].label for i in range(em_ref.size())
                 if i not in matched]
    out["n_matched"] = len(m.pairs)
    out["rms"] = round(float(m.rms), 3)
    out["match_fraction"] = round(len(m.pairs) / n_ref, 3)
    out["unmatched_reference_atoms"] = unmatched
    disorder = _disorder_component_reasons(ref_xs, unmatched)
    out["unmatched_disorder_components"] = disorder
    if not unmatched:
        out["verdict"] = "framework_reproduced"
    elif (len(disorder) == len(unmatched)
          and out["match_fraction"] >= DISORDER_INCOMPLETE_MIN_FRACTION):
        out["verdict"] = "framework_reproduced_disorder_incomplete"
        out["verdict_note"] = (
            f"every reference atom the model does not account for is a "
            f"disorder component ({', '.join(sorted(disorder))}): the "
            "framework IS reproduced, the disorder model is incomplete")
    else:
        out["verdict"] = "framework_not_reproduced"
        if len(disorder) == len(unmatched):
            out["verdict_note"] = (
                f"every unmatched reference atom is a disorder component, "
                f"but only {out['match_fraction']:.2f} of the reference is "
                f"matched (floor {DISORDER_INCOMPLETE_MIN_FRACTION:.2f} for "
                f"'disorder incomplete'): too much of the reference is "
                f"missing to call the framework reproduced")
    return out


def _reference_caveat(reference: Path) -> str | None:
    """First lines of a REFERENCE-CAVEAT.md sitting beside the reference.

    Not every 'ground truth' is one. r25 graded an agent below_bar against
    a reference that turned out to be an unfinished SHELXT solution with
    the wrong element (I for Zr) and the wrong space group (P6mm for
    P 6/m m m - its own Flack 0.496 said so); the agent was right and the
    reference was wrong. When someone establishes that, the finding has to
    reach the NEXT grading run instead of living in a commit message."""
    try:
        for cand in (reference.parent / "REFERENCE-CAVEAT.md",
                     reference.with_suffix(".caveat.md")):
            if cand.exists():
                head = [ln.strip() for ln
                        in cand.read_text(encoding="utf-8",
                                          errors="replace").splitlines()
                        if ln.strip() and not ln.startswith("#")]
                return " ".join(head[:3])[:400] + f"  [{cand.name}]"
        return _self_declared_caveat(reference)
    except OSError:
        pass
    return None


def _self_declared_caveat(reference: Path) -> str | None:
    """What the reference file says about ITSELF.

    A .res carries its own provenance in REM lines, and a surprising
    share of "ground truth" turns out to be a raw SHELXT solution
    someone stopped refining: of the 21 references in benchmark/data,
    12 sit above R1 0.12 and one is at 0.35. Comparing an agent against
    those as if they were answers is how r25 produced a below_bar for a
    structure that was right. Nobody has to remember to write a caveat
    file for the obvious cases."""
    if reference.suffix.lower() not in (".res", ".ins"):
        return None
    text = reference.read_text(encoding="utf-8", errors="replace")[:20000]
    bits: list[str] = []
    m = re.search(r"REM R1 = ([\d.]+)", text)
    if m:
        try:
            if float(m.group(1)) > 0.12:
                bits.append(f"参考自身 R1 = {m.group(1)}（未精修完的模型，"
                            "其 R1 不是可比的标尺）")
        except ValueError:
            pass
    if re.search(r"REM SHELXT solution in", text):
        bits.append("参考带 'SHELXT solution' REM：是求解输出而非定稿"
                    "结构，元素指认可能是 SHELXT 的自动猜测")
    f = re.search(r"Flack x = ([\d.]+)", text)
    if f:
        try:
            if 0.35 < float(f.group(1)) < 0.65:
                bits.append(f"参考自身 Flack x = {f.group(1)}，非心群里"
                            "≈0.5 通常意味着结构其实是中心对称的，参考的"
                            "空间群选择存疑")
        except ValueError:
            pass
    return "；".join(bits) if bits else None


def _reference_layer(final_cif: Path, reference: str | Path,
                     kind: str) -> dict[str, Any]:
    from .evaluate import (evaluate_against_reference, load_cif_structure,
                           reference_r1, same_sg_type)

    out: dict[str, Any] = {"reference": str(reference),
                           "reference_kind": kind}
    caveat = _reference_caveat(Path(reference))
    if caveat:
        out["reference_caveat"] = caveat
    ref_xs = _load_any_reference(reference)
    if ref_xs is None:
        out["error"] = f"cannot load reference {reference}"
        return out
    # believe the delivered CIF's OPERATOR LOOP, not its space-group name:
    # a conflict between the two is a delivery defect, but it must not
    # poison the structure comparison (reg1-ext2 hsl: 4/13 instead of
    # 13/13 because the gemmi fallback took the name)
    agent_xs, load_info = load_cif_structure(final_cif)
    out["cif_symmetry_inconsistent"] = bool(
        load_info.get("cif_symmetry_inconsistent"))
    for key in ("cif_symmetry_note", "cif_symmetry_conflicts"):
        if load_info.get(key):
            out[key] = load_info[key]
    if agent_xs is None:
        out["error"] = f"cannot load agent structure from {final_cif}"
        return out

    out["sg_agent"] = str(agent_xs.space_group_info())
    out["sg_reference"] = str(ref_xs.space_group_info())
    out["sg_type_equal"] = same_sg_type(agent_xs, ref_xs)

    n_big = max(agent_xs.scatterers().size(), ref_xs.scatterers().size())
    subset_note = None
    if n_big > EMMA_MAX_ATOMS:
        sub_a, na_h = _heavy_subset(agent_xs)
        sub_r, nr_h = _heavy_subset(ref_xs)
        if min(na_h, nr_h) >= 3 and max(na_h, nr_h) <= EMMA_MAX_ATOMS:
            subset_note = f"heavy-only Z>={_HEAVY_Z}: {na_h}/{nr_h} atoms"
            emma_a, emma_r = sub_a, sub_r
        else:
            emma_a = emma_r = None
            out["emma_skip_reason"] = (
                f"{n_big} scatterers > {EMMA_MAX_ATOMS} and no usable "
                f"heavy subset ({na_h}/{nr_h}) - phase identity judged "
                "from cell + SG type + composition")
    else:
        emma_a, emma_r = agent_xs, ref_xs

    if emma_a is not None:
        # settings can differ even when the Niggli PARAMETERS agree (r18
        # live failure: an acute-setting delivery vs the obtuse-setting
        # reference, both validly reduced, scored 0/2 heavy matches
        # because emma ran on unaligned settings and the reindex branch
        # only fired on "incompatible"). Align FIRST whenever the raw
        # cells differ, trying every metric-matching operator and
        # keeping the one the heavy atoms actually vote for - metric
        # error alone cannot pick between candidate isomorphisms.
        def _apply_reindex() -> None:
            nonlocal agent_xs, emma_a
            scored = []
            for xs2, m, err in _reindex_onto(agent_xs, ref_xs)[:6]:
                vote = 0.0
                try:
                    sub_a2, n_a2 = _heavy_subset(xs2)
                    sub_r2, n_r2 = _heavy_subset(ref_xs)
                    if min(n_a2, n_r2) >= 1:
                        e_h = evaluate_against_reference(sub_a2, sub_r2)
                        vote = (e_h.get("heavy_match_rate")
                                or e_h.get("all_match_rate") or 0.0)
                except Exception:  # noqa: BLE001 - voting is best-effort
                    pass
                scored.append((vote, -err, xs2, m, err))
            if scored:
                scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
                _v, _ne, xs2, m, err = scored[0]
                out["reindexed_by"] = m
                out["reindex_metric_err"] = round(err, 5)
                agent_xs = xs2
                emma_a = (_heavy_subset(agent_xs)[0] if subset_note
                          else agent_xs)

        try:
            raw_similar = agent_xs.unit_cell().is_similar_to(
                ref_xs.unit_cell(), relative_length_tolerance=0.03,
                absolute_angle_tolerance=3.0)
        except Exception:  # noqa: BLE001
            raw_similar = True
        if not raw_similar:
            _apply_reindex()
        emma = evaluate_against_reference(emma_a, emma_r)
        if emma.get("cell_mismatch_with_reference") \
                and "reindexed_by" not in out:
            _apply_reindex()
            if "reindexed_by" in out:
                emma = evaluate_against_reference(emma_a, emma_r)
        if subset_note:
            emma["subset"] = subset_note
    else:
        emma = {"skipped_large_structure": True, "n_scatterers": n_big}
    out["emma"] = emma
    # disclose the rule and the raw fraction behind it: "framework not
    # reproduced" is the harshest thing this grader says, so it must show
    # its working and name the atoms it is missing
    out["emma_framework_rule"] = EMMA_FRAMEWORK_RULE
    out["emma_match_fraction_scored"] = emma.get("all_match_rate")
    if emma_a is not None:
        try:
            diag = _framework_diagnosis(agent_xs, ref_xs)
        except Exception as e:  # noqa: BLE001 - diagnosis never blocks
            diag = {"error": f"{type(e).__name__}: {e}"}
        out["framework_diagnosis"] = diag
        if diag.get("match_fraction") is not None:
            out["emma_match_fraction"] = diag["match_fraction"]
        if emma.get("solved"):
            out["framework_verdict"] = "framework_reproduced"
        elif diag.get("verdict"):
            out["framework_verdict"] = diag["verdict"]

    try:
        # after a successful reindex both structures share a setting, so a
        # direct comparison is the primary check (re-reducing would hit the
        # Niggli boundary discontinuity again); the Niggli axis deviation
        # stays as the reported diagnostic. Literature references are
        # same-phase DIFFERENT-temperature measurements - thermal expansion
        # legitimately moves cell lengths by 1-2%, so the gate widens.
        tol = 0.025 if kind == "literature" else 0.01
        direct = agent_xs.unit_cell().is_similar_to(
            ref_xs.unit_cell(), relative_length_tolerance=tol,
            absolute_angle_tolerance=2.0)
        na = _niggli(agent_xs.unit_cell().parameters())
        nr = _niggli(ref_xs.unit_cell().parameters())
        dev = max(abs(x - y) / max(y, 1e-6) for x, y in zip(na[:3], nr[:3]))
        out["niggli_axis_max_dev"] = round(dev, 4)
        out["cell_compatible"] = bool(direct or (
            dev <= tol
            and all(abs(x - y) <= 2.0 for x, y in zip(na[3:], nr[3:]))))
    except Exception as exc:  # noqa: BLE001 - cell check must not kill grading
        out["cell_check_error"] = str(exc)

    # composition/Z from the CIFs when both sides have them
    a_fields = _cif_fields(final_cif)
    out["formula_agent"] = a_fields["formula"]
    out["z_agent"] = a_fields["z"]
    r_fields: dict[str, Any] = {}
    if Path(reference).suffix.lower() == ".cif":
        try:
            r_fields = _cif_fields(Path(reference))
            out["formula_reference"] = r_fields["formula"]
            out["z_reference"] = r_fields["z"]
            ca, cr = (_formula_counts(a_fields["formula"]),
                      _formula_counts(r_fields["formula"]))
            if ca and cr:
                keys = set(ca) | set(cr)
                out["composition_max_rel_dev"] = round(max(
                    abs(ca.get(k, 0.0) - cr.get(k, 0.0))
                    / max(cr.get(k, 0.0), 1.0) for k in keys), 3)
                # H (and solvent O/H bookkeeping) conventions differ most
                # between masked deliveries - the framework identity check
                # reads better without H
                nh = [k for k in keys if k.upper() != "H"]
                if nh:
                    out["composition_max_rel_dev_non_h"] = round(max(
                        abs(ca.get(k, 0.0) - cr.get(k, 0.0))
                        / max(cr.get(k, 0.0), 1.0) for k in nh), 3)
        except Exception as exc:  # noqa: BLE001
            out["composition_check_error"] = str(exc)

    ref_p = Path(reference)
    out["r1_reference"] = reference_r1(
        str(ref_p) if ref_p.suffix.lower() in (".res", ".ins") else None,
        str(ref_p) if ref_p.suffix.lower() == ".cif" else None)
    out["r1_agent"] = a_fields["r1_gt"]
    # R1 falls when weak high-angle data are dropped, so the delta only
    # measures the models when both were refined to the same cut: a
    # delivery truncated at 1.0 A against a 0.8 A reference is a different
    # experiment, not a better refinement.
    da = out["d_min_agent"] = a_fields.get("d_min")
    dr = out["d_min_reference"] = r_fields.get("d_min")
    out["r1_delta_comparable"] = (None if da is None or dr is None
                                  else abs(da - dr) <= R1_DELTA_D_MIN_TOL)
    if (out["r1_reference"] is not None and out["r1_agent"] is not None):
        out["r1_delta"] = round(out["r1_agent"] - out["r1_reference"], 4)
        out["r1_scored"] = kind == "exact"
        if out["r1_delta_comparable"] is False:
            # kept as a number (it is a fact) but withdrawn as a criterion
            out["r1_delta_incomparable"] = True
            out["r1_scored"] = False
            out["r1_delta_note"] = (
                f"agent d_min {da} A vs reference d_min {dr} A, more than "
                f"{R1_DELTA_D_MIN_TOL} A apart: R1 delta compares two "
                "resolution cuts, not two models")
        elif out["r1_delta_comparable"] is None:
            out["r1_delta_note"] = ("resolution alignment not checked "
                                    "(d_min unknown on one side)")
    return out


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #

#: SHELX instructions - anything else with "label int x y z ..." is an atom
_SHELX_INSTRUCTIONS = frozenset(
    "TITL CELL ZERR LATT SYMM SFAC UNIT DISP LAUE REM MORE TIME END HKLF "
    "OMIT SHEL BASF TWIN EXTI SWAT HOPE MERG SPEC RESI MOVE ANIS AFIX HFIX "
    "FRAG FEND EXYZ EADP EQIV CONN PART BIND FREE DFIX DANG BUMP SAME SADI "
    "CHIV FLAT DELU SIMU DEFS ISOR NCSY SUMP L.S. CGLS BLOC DAMP STIR WGHT "
    "FVAR BOND CONF MPLA RTAB HTAB LIST ACTA SIZE TEMP WPDB FMAP GRID PLAN "
    "MOLE ABIN ANSC ANSR NEUT PRIG XNPD TWST RIGU".split())


def _is_shelx_atom_line(tokens: list[str]) -> bool:
    if len(tokens) < 5 or tokens[0].upper() in _SHELX_INSTRUCTIONS:
        return False
    try:
        int(tokens[1])
        [float(v) for v in tokens[2:5]]
    except ValueError:
        return False
    return True


def _transform_res_atoms(res_lines: list[str], r, t, cell) -> list[str]:
    """Every atom line of a SHELX res moved by x' = R x + t (fractional);
    anisotropic Uij follow the rotation (u_star' = R u_star R^T, SHELX
    order U11 U22 U33 U23 U13 U12 with the continuation line). A pure
    translation (R = I) leaves every U alone. SHELX's '10+value' fixed-
    parameter coding on coordinates is preserved."""
    from cctbx import adptbx, uctbx
    from scitbx import matrix
    R = matrix.sqr([float(v) for v in r])
    T = matrix.col([float(v) for v in t])
    ident = all(abs(v - w) < 1e-9 for v, w in zip(R.elems, (1, 0, 0, 0, 1, 0, 0, 0, 1)))
    uc = uctbx.unit_cell(cell)
    out: list[str] = []
    i = 0
    while i < len(res_lines):
        ln = res_lines[i]
        toks = ln.split()
        if not _is_shelx_atom_line(toks):
            out.append(ln)
            i += 1
            continue
        coords, fixed = [], []
        for v in toks[2:5]:
            x = float(v)
            f = abs(x) >= 5.0          # 10+p: fixed at p
            fixed.append(f)
            coords.append(x - 10.0 if f else x)
        y = R * matrix.col(coords) + T
        new = [f"{float(v) + (10.0 if f else 0.0):.6f}" for v, f in zip(y.elems, fixed)]
        rest = toks[5:]
        cont = None
        if rest and rest[-1] == "=" and i + 1 < len(res_lines):
            cont = res_lines[i + 1]
        if not ident:
            uvals = [v for v in rest if v != "="]
            if cont is not None:
                uvals = uvals + cont.split()
            # sof, U11 U22 U33 U23 U13 U12 (six U = anisotropic)
            if len(uvals) >= 7:
                try:
                    u = [float(v) for v in uvals[1:7]]
                    u_cif = (u[0], u[1], u[2], u[5], u[4], u[3])
                    us = matrix.sym(sym_mat3=adptbx.u_cif_as_u_star(uc, u_cif))
                    us2 = (R * us * R.transpose()).as_sym_mat3()
                    c2 = adptbx.u_star_as_u_cif(uc, us2)
                    shelx = [c2[0], c2[1], c2[2], c2[5], c2[4], c2[3]]
                    rest = [uvals[0]] + [f"{v:.5f}" for v in shelx[:3]] + ["="]
                    cont = "    " + " ".join(f"{v:.5f}" for v in shelx[3:]) + \
                        ("" if len(uvals) <= 7 else " " + " ".join(uvals[7:]))
                except (ValueError, RuntimeError):
                    pass
        out.append(" ".join([toks[0], toks[1]] + new + rest))
        if cont is not None:
            out.append(cont)
            i += 2
        else:
            i += 1
    return out


def _align_res_to_reference(res_lines: list[str], final_cif: Path,
                            reference: str | Path,
                            ref_cell: list[float]) -> dict[str, Any]:
    """Move the agent's model into the reference's origin/setting before
    the transplant. The reference's embedded .fab holds the mask
    coefficients for the REFERENCE origin: an agent model that sits on a
    symmetry-equivalent origin (pa4 hex: every atom at z + 1/2, a legal
    choice in P6/mmm) refines against those coefficients to R1 0.206 where
    the same framework on the reference origin (pa3) gave 0.133. The rt is
    emma's, the same alignment the reference layer uses; when the space-
    group types differ or nothing matches, the lines are left alone."""
    try:
        from .evaluate import load_reference, same_sg_type
        from cctbx import euclidean_model_matching as emma
        from scitbx.array_family import flex
    except Exception as e:  # noqa: BLE001
        return {"lines": res_lines, "applied": False,
                "note": f"alignment unavailable: {e}"}
    try:
        p = str(reference)
        ref = load_reference(p, None) if p.lower().endswith((".res", ".ins")) \
            else load_reference(None, p)
        agent = load_reference(None, str(final_cif))
        if ref is None or agent is None:
            return {"lines": res_lines, "applied": False,
                    "note": "alignment skipped: a structure did not load"}
        if not same_sg_type(ref, agent):
            return {"lines": res_lines, "applied": False,
                    "note": "alignment skipped: space-group types differ"}

        def no_h(xs):
            keep = flex.bool(["".join(c for c in sc.scattering_type
                                      if c.isalpha())[:2].capitalize()
                              not in ("H", "D") for sc in xs.scatterers()])
            return xs.select(keep)
        ref, agent = no_h(ref), no_h(agent)
        hr, _ = _heavy_subset(ref)
        ha, _ = _heavy_subset(agent)
        pair = (hr, ha) if hr.scatterers().size() and ha.scatterers().size() \
            else (ref, agent)
        m = emma.model_matches(pair[0].as_emma_model(), pair[1].as_emma_model(),
                               tolerance=1.0)
        if not m.refined_matches:
            return {"lines": res_lines, "applied": False,
                    "note": "alignment skipped: no emma match"}
        rt = m.refined_matches[0].rt
        r = [float(v) for v in rt.r.elems]
        t = [float(v) for v in rt.t.elems]
        ident = all(abs(v - w) < 1e-6 for v, w in zip(r, (1, 0, 0, 0, 1, 0, 0, 0, 1)))
        if ident and all(abs(v) < 1e-4 for v in t):
            return {"lines": res_lines, "applied": False,
                    "note": "same origin and setting as the reference"}
        moved = _transform_res_atoms(res_lines, r, t, ref_cell)
        return {"lines": moved, "applied": True, "r": r,
                "t": [round(v, 4) for v in t],
                "note": ("agent model moved onto the reference origin/setting "
                         "before the transplant (emma rt)")}
    except Exception as e:  # noqa: BLE001 - never let alignment kill the arm
        return {"lines": res_lines, "applied": False,
                "note": f"alignment failed: {type(e).__name__}: {e}"}


#: the deposited R1 counts as reproducible on the delivered data while the
#: deposited model, re-refined there, stays within this of it
R1_REFERENCE_REPRODUCIBILITY_TOL = 0.01


def _reference_model_ins(ref_txt: str, reference: Path,
                         agent_res_lines: list[str]) -> tuple[list[str], str]:
    """SHELX instruction lines for the deposited model, ready for the
    delivered data: the embedded _shelx_res_file when there is one (HKLF 5
    -> HKLF 4, batch BASF dropped), else the atom loop through iotbx.cif
    and the platform writer (H free isotropic). The agent's SHEL card is
    carried over so both models see the same reflections."""
    res = _embedded_shelx_block(ref_txt, "_shelx_res_file")
    shel = next((ln.strip() for ln in agent_res_lines
                 if ln.strip().upper().startswith("SHEL")), None)
    out: list[str] = []
    if res:
        hklf5 = any(ln.strip().upper().startswith("HKLF 5")
                    for ln in res.splitlines())
        for ln in res.splitlines():
            u = ln.strip().upper()
            if u.startswith(("ACTA", "LIST", "SHEL", "L.S.", "CGLS")):
                continue
            if u.startswith("HKLF"):
                out.append("HKLF 4")
                continue
            if hklf5 and u.startswith("BASF"):
                continue          # batch scale factors of the other file
            if u.startswith("REM") and len(ln) > 80:
                out.append(ln[:80])
                continue
            out.append(ln)
        basis = ("embedded _shelx_res_file"
                 + (" (HKLF 5 -> HKLF 4, BASF dropped)" if hklf5 else ""))
    else:
        from iotbx import cif as iotbx_cif

        from ..io.shelx_writer import ShelxModel, write_res_text
        structures = iotbx_cif.reader(file_path=str(reference)
                                      ).build_crystal_structures()
        if not structures:
            raise ValueError("reference CIF has no atom loop iotbx can read")
        xs = next(iter(structures.values()))
        wl = None
        m = re.search(r"_diffrn_radiation_wavelength\s+([\d.]+)", ref_txt)
        if m:
            wl = float(m.group(1))
        text, _ = write_res_text(ShelxModel(xray_structure=xs, wavelength=wl,
                                            scale=1.0,
                                            title="deposited model on the "
                                                  "delivered data"))
        out = [ln for ln in text.splitlines()
               if not ln.strip().upper().startswith(("HKLF", "END"))]
        out += ["HKLF 4", "END"]
        basis = "atom loop via iotbx.cif + platform writer (H free isotropic)"
    # L.S. before WGHT/FVAR, SHEL from the agent, and no zero-cycle trap
    ins: list[str] = []
    placed = False
    for ln in out:
        u = ln.strip().upper()
        if not placed and u.startswith(("WGHT", "FVAR")):
            ins.append("L.S. 10")
            if shel:
                ins.append(shel)
            placed = True
        ins.append(ln)
    if not placed:
        ins.insert(-2, "L.S. 10")
    return ins, basis


def _reference_on_delivered_data(final_cif: Path, reference: str | Path,
                                 reference_r1: float | None
                                 ) -> dict[str, Any]:
    """The deposited model refined against the DATA THE AGENT WAS GIVEN.

    A deposited R1 is only a fair bar if the deposited model can reach it
    on the delivered reflections. nm (reg1/reg8, 2026-09-04): the
    reference fcf came out of an HKLF 5 twin refinement, so the derived
    HKLF 4 file lists overlapped composites up to 8x per hkl; the deposited
    model itself refines to R1 0.094 there, not 0.0526, and two agents at
    0.0948 were scored 0.042 "above the reference". Report-level evidence
    that, when the gap exceeds R1_REFERENCE_REPRODUCIBILITY_TOL, becomes
    the basis of the R1 delta (see _effective_reference_r1)."""
    import shutil
    text = final_cif.read_text(encoding="utf-8", errors="replace")
    hkl = _embedded_shelx_block(text, "_shelx_hkl_file")
    if not hkl:
        return {"skipped": "delivery embeds no _shelx_hkl_file"}
    ref_p = Path(reference)
    ref_txt = ref_p.read_text(encoding="utf-8", errors="replace")
    if (_embedded_shelx_block(ref_txt, "_shelx_fab_file")
            or "_platon_squeeze" in ref_txt
            or re.search(r"^\s*ABIN", _embedded_shelx_block(
                ref_txt, "_shelx_res_file") or "", re.M)):
        return {"skipped": "masked reference: its mask does not transfer "
                           "to the delivered data"}
    shelxl = _shelxl_exe()
    if not shelxl.exists():
        return {"skipped": "vendor shelxl not installed"}
    final_res = final_cif.parent / "final.res"
    agent_lines = (final_res.read_text(encoding="utf-8", errors="replace")
                   .splitlines() if final_res.exists() else [])
    try:
        ins, basis = _reference_model_ins(ref_txt, ref_p, agent_lines)
    except Exception as e:  # noqa: BLE001 - evidence arm only
        return {"error": f"reference model not buildable: "
                         f"{type(e).__name__}: {e}"}
    job = REPO / "workdir" / "grades" / "_ref_on_data" / final_cif.parent.name
    shutil.rmtree(job, ignore_errors=True)
    job.mkdir(parents=True, exist_ok=True)
    (job / "job.ins").write_text("\n".join(ins) + "\n", encoding="ascii",
                                 errors="replace")
    (job / "job.hkl").write_text(hkl + "\n", encoding="utf-8")
    try:
        _run_shelxl_job(job, shelxl, 600)
    except Exception as e:  # noqa: BLE001
        return {"error": f"shelxl failed on the reference model: "
                         f"{type(e).__name__}: {e}"}
    r1, n, errs = _job_r1(job)
    if r1 is None:
        return {"error": "no R1 from the reference-model job",
                "shelxl_errors": errs, "job_dir": str(job)}
    out: dict[str, Any] = {
        "r1_reference_on_delivered_data": r1, "n_strong": n,
        "basis": basis, "deposited_r1": reference_r1, "job_dir": str(job),
    }
    if reference_r1 is not None:
        out["delta_vs_deposited"] = round(r1 - float(reference_r1), 4)
        out["reproducible"] = (out["delta_vs_deposited"]
                               <= R1_REFERENCE_REPRODUCIBILITY_TOL)
    return out


def _effective_reference_r1(rl: dict[str, Any], rod: dict[str, Any] | None
                            ) -> float | None:
    """Rewrite rl's R1 delta against the deposited model's R1 on the
    delivered data when the deposited R1 is not reproducible there.
    Returns the delta in force (None when there is none)."""
    r1d = rl.get("r1_delta")
    if not rod or rod.get("r1_reference_on_delivered_data") is None:
        return r1d
    r1a, r1r = rl.get("r1_agent"), rl.get("r1_reference")
    r1_eff = float(rod["r1_reference_on_delivered_data"])
    if r1a is None or r1r is None:
        return r1d
    if r1_eff - float(r1r) <= R1_REFERENCE_REPRODUCIBILITY_TOL:
        return r1d
    rl["r1_reference_effective"] = r1_eff
    rl["r1_delta_deposited"] = r1d
    rl["r1_delta"] = round(float(r1a) - r1_eff, 4)
    rl["r1_delta_basis"] = (
        f"the deposited model re-refined on the delivered data reaches R1 "
        f"{r1_eff} (deposited {r1r}): the deposited R1 is not reproducible "
        f"on these reflections, so the delta is measured against {r1_eff}")
    return rl["r1_delta"]


def _model_transplant(final_cif: Path, reference: str | Path,
                      reference_r1: float | None) -> dict[str, Any]:
    """Freeze the agent's final model, refine it against the REFERENCE
    data (embedded _shelx_hkl_file), report the R1 it reaches.

    Separates the two things a single grade conflates: structure
    determination quality vs data-reduction quality. Live origin (r24):
    an agent graded below_bar at R1 0.1625 on its own reduction
    reproduced the reference R1 to 0.0003 on the reference data - the
    MODEL was publication-grade, the reduction was not. Cheap and
    decisive; report-level evidence, never changes the grade."""
    import shutil
    import subprocess
    ref_txt = Path(reference).read_text(encoding="utf-8", errors="replace")
    m = re.search(r"_shelx_hkl_file\s*\n;\s*\n(.*?)\n;", ref_txt, re.S)
    if not m:
        return {"skipped": "reference has no embedded _shelx_hkl_file"}
    final_res = final_cif.parent / "final.res"
    if not final_res.exists():
        return {"skipped": "delivery has no final.res"}
    shelxl = REPO / "vendor" / "shelx" / "shelxl.exe"
    if not shelxl.exists():
        return {"skipped": "vendor shelxl not installed"}
    ref_block = _read_cif_block(Path(reference))
    ref_cell = _cell(ref_block)
    if any(v is None for v in ref_cell):
        return {"skipped": "reference cell incomplete"}
    # reference data-processing cards (TWIN/BASF/EXTI/SWAT): the fairest
    # transplant pairs the agent's atoms with the reference's treatment
    # of ITS OWN data - but only when the agent model carries none
    ref_res = re.search(r"_shelx_res_file\s*\n;\s*\n(.*?)\n;", ref_txt,
                        re.S)
    ref_cards = []
    if ref_res:
        for ln in ref_res.group(1).splitlines():
            if ln.strip().upper().split()[:1] and \
                    ln.strip().upper().split()[0] in ("TWIN", "BASF",
                                                      "EXTI", "SWAT"):
                ref_cards.append(ln.strip())
    res_lines = final_res.read_text(encoding="utf-8",
                                    errors="replace").splitlines()
    # the reference .fab (and every comparison) lives on the reference
    # origin: move the agent model there first
    alignment = _align_res_to_reference(res_lines, final_cif, reference,
                                        ref_cell)
    res_lines = alignment.pop("lines")
    agent_has_twin = any(l.strip().upper().startswith("TWIN")
                         for l in res_lines)
    wl_m = re.search(r"^\s*CELL\s+([\d.]+)", "\n".join(res_lines), re.M)
    wl = wl_m.group(1) if wl_m else "0.71073"
    out: list[str] = []
    ls_seen = False
    for ln in res_lines:
        u = ln.strip().upper()
        if u.startswith("CELL"):
            out.append("CELL %s  %.5f %.5f %.5f  %.4f %.4f %.4f"
                       % (wl, *ref_cell))
        elif u.startswith("SHEL"):
            continue                    # reference data is already cut
        elif u.startswith("HKLF"):
            # reference embedded data is HKLF 4; an HKLF5 model must drop
            # its batch BASF values (they belong to the other dataset)
            out.append("HKLF 4")
        elif u.startswith("BASF") and not agent_has_twin:
            continue
        elif u.startswith(("L.S.", "CGLS")):
            out.append("L.S. 20")
            ls_seen = True
        elif u.startswith("ACTA"):
            continue                    # no cif needed; ACTA slows the job
        elif u.startswith("REM") and len(ln) > 80:
            # SHELXL aborts the whole job on any input line over 80
            # characters ("INPUT INSTRUCTION ... IS LONGER THAN 80
            # CHARACTERS"); a 96-char provenance REM in every masked
            # delivery silently killed this arm (pa3 hex-l2g-r1)
            out.append(ln[:80])
        else:
            out.append(ln)
    if not ls_seen:                     # zero-refinement trap (lived once)
        for i, ln in enumerate(out):
            if ln.strip().upper().startswith("WGHT"):
                out.insert(i, "L.S. 20")
                break
    if ref_cards and not agent_has_twin:
        for i, ln in enumerate(out):
            if ln.strip().upper().startswith("FVAR"):
                for c in reversed(ref_cards):
                    out.insert(i + 1, c)
                break
    # a masked agent model (ABIN) needs a .fab beside the job or SHELXL
    # stops silently after the instruction block (empty .res, no R1).
    # The agent's own .fab holds mask coefficients for ITS data, so the
    # reference's embedded _shelx_fab_file (the mask that goes with the
    # reference data) is borrowed when there is one; otherwise ABIN is
    # dropped and the transplant is an unmasked framework refinement
    fab_m = re.search(r"_shelx_fab_file\s*\n;\s*\n(.*?)\n;", ref_txt, re.S)
    has_abin = any(l.strip().upper().startswith("ABIN") for l in out)
    mask_treatment = "agent model carries no ABIN (unmasked)"
    if has_abin and fab_m:
        mask_treatment = "reference _shelx_fab_file borrowed for the ABIN card"
    elif has_abin:
        out = [l for l in out if not l.strip().upper().startswith("ABIN")]
        mask_treatment = ("ABIN dropped - reference embeds no .fab; "
                          "unmasked framework refinement")
    job = REPO / "workdir" / "grades" / "_transplant" / final_cif.parent.name
    shutil.rmtree(job, ignore_errors=True)
    job.mkdir(parents=True, exist_ok=True)
    (job / "job.ins").write_text("\n".join(out) + "\n", encoding="utf-8")
    (job / "job.hkl").write_text(m.group(1) + "\n", encoding="utf-8")
    if has_abin and fab_m:
        (job / "job.fab").write_text(fab_m.group(1) + "\n", encoding="utf-8")
    try:
        subprocess.run([str(shelxl), "job"], cwd=str(job),
                       capture_output=True, timeout=300)
    except subprocess.TimeoutExpired:
        return {"error": "shelxl timed out on the transplant job"}
    lst = job / "job.lst"
    if not lst.exists():
        return {"error": "transplant shelxl produced no lst"}
    lm = re.search(r"R1 =\s+([\d.]+) for", lst.read_text(
        encoding="utf-8", errors="replace"))
    if not lm:
        return {"error": "no R1 in transplant lst"}
    r1_t = float(lm.group(1))
    res: dict[str, Any] = {
        "r1_on_reference_data": r1_t,
        "alignment": alignment,
        "reference_r1": reference_r1,
        "reference_cards_borrowed": ref_cards if not agent_has_twin else [],
        "mask_treatment": mask_treatment,
        "job_dir": str(job),
    }
    if reference_r1 is not None:
        delta = round(r1_t - float(reference_r1), 4)
        res["delta"] = delta
        res["verdict"] = (
            "publication-grade MODEL: reproduces the reference R1 on the "
            "reference data - remaining gaps are data reduction"
            if delta <= 0.015 else
            "model close to reference on reference data"
            if delta <= 0.04 else
            "model itself differs from the reference solution")
    return res


def grade_delivery(project_dir: str | Path, reference: str | Path | None = None,
                   reference_kind: str = "exact",
                   out_dir: str | Path | None = None,
                   run_checkcif: bool = True,
                   run_reproduce: bool = True) -> dict[str, Any]:
    """Grade one project's delivery. `grade_reasons` (when present) lists
    everything held against the delivery: what kept it below publication
    plus report-only notes (metadata alerts, a better node, SHELXL
    reproducibility) - so it can accompany a publication grade too."""
    project_dir = Path(project_dir)
    result: dict[str, Any] = {
        "project": str(project_dir),
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "reference" if reference else "self_consistency_only",
    }

    final_cif = find_delivery(project_dir)
    if final_cif is None:
        result["grade"] = "no_delivery"
        result["note"] = ("no publication delivery found "
                          "(CrystalPilot Results/*/final.cif + final.fcf)")
        return _write_outputs(result, project_dir, out_dir)

    sc = _self_consistency(project_dir, final_cif, run_checkcif=run_checkcif)
    result["self_consistency"] = sc
    result["delivery_layout"] = delivery_layout(project_dir, final_cif)
    mentor = _mentor_checks(project_dir, final_cif, sc, run_reproduce)
    result.update(mentor)
    m_block, m_notes = _mentor_reasons(mentor)

    if reference:
        rl = _reference_layer(final_cif, reference, reference_kind)
        result["reference_layer"] = rl
        try:
            result["model_transplant"] = _model_transplant(
                final_cif, reference, rl.get("r1_reference"))
        except Exception as e:  # noqa: BLE001 - evidence arm must never block grading
            result["model_transplant"] = {"error": f"{type(e).__name__}: {e}"}
        rod: dict[str, Any] | None = None
        if reference_kind == "exact":
            try:
                rod = _reference_on_delivered_data(
                    final_cif, reference, rl.get("r1_reference"))
            except Exception as e:  # noqa: BLE001 - evidence arm only
                rod = {"error": f"{type(e).__name__}: {e}"}
            result["reference_on_delivered_data"] = rod
        emma = rl.get("emma") or {}
        solved = bool(emma.get("solved"))
        if emma.get("skipped_large_structure"):
            # coordinate matching impossible at this size: phase identity
            # from cell + SG type + non-H composition instead
            comp = rl.get("composition_max_rel_dev_non_h")
            solved = (rl.get("sg_type_equal") is True
                      and rl.get("cell_compatible") is True
                      and (comp is None or comp <= 0.25))
            rl["solved_proxy"] = solved
        r1a = rl.get("r1_agent")
        r1d = _effective_reference_r1(rl, rod)
        if rl.get("r1_delta_basis"):
            m_notes.append(rl["r1_delta_basis"])
        # the elements on the matched sites: coordinates alone let a
        # Zn-labelled Zr framework through (pa1 hex-l1-r1)
        elements_ok = emma.get("metal_identity_ok") is not False
        reasons: list[str] = []
        # a framework whose ONLY unmatched reference atoms are a disorder
        # component IS reproduced - the disorder model is what is
        # incomplete, and that is a different finding with a different
        # remedy (ext2 dbu: 26/28, the two misses at occupancy 0.265).
        # It stays short of `publication`, which still needs strict
        # emma solved=true.
        diag = rl.get("framework_diagnosis") or {}
        disorder_only = (
            not solved
            and rl.get("framework_verdict")
            == "framework_reproduced_disorder_incomplete")
        fully_solved = solved
        if disorder_only:
            solved = True
            reasons.append(
                "framework_reproduced_disorder_incomplete: "
                f"{diag.get('n_matched')}/{diag.get('n_reference_non_h')} "
                "reference non-H atoms matched (rms "
                f"{diag.get('rms')} A); unmatched = "
                + ", ".join(f"{k} ({v})" for k, v in
                            sorted((diag.get('unmatched_disorder_components')
                                    or {}).items()))
                + " - model the missing component(s) before publication")
        elif not solved:
            frac = rl.get("emma_match_fraction")
            unmatched = (diag.get("unmatched_reference_atoms") or [])[:8]
            reasons.append(
                "framework not reproduced (emma solved=false"
                + (f", {diag.get('n_matched')}/"
                   f"{diag.get('n_reference_non_h')} reference non-H atoms "
                   f"matched, fraction {frac}" if frac is not None else "")
                + ")" + (f"; unmatched reference atoms: "
                         + ", ".join(map(str, unmatched)) if unmatched else "")
                + f". Rule: {EMMA_FRAMEWORK_RULE}")
        if rl.get("cif_symmetry_inconsistent"):
            reasons.append(
                "delivered CIF names a space group its own operator loop "
                "contradicts; the operator loop was believed so the "
                "structure comparison above is sound (see cif_symmetry)")
        if not elements_ok:
            mm = ((emma.get("heavy") or {}).get("element_mismatches")
                  or [])[:3]
            reasons.append("metal identity differs from the reference: "
                           + "; ".join(f"{r['model_el']} for {r['ref_el']} "
                                       f"(dZ {r['dz']:+d})" for r in mm))
        if rl.get("sg_type_equal") is not True:
            reasons.append("space-group type differs")
        if rl.get("cell_compatible") is False:
            reasons.append("cell incompatible")
        if not sc["self_consistent"]:
            reasons.append("delivery not self-consistent")
        # A alerts: only the model-quality ones block (checkcif_a_split);
        # metadata ones are notes. Chemistry flags, an incomplete file set
        # and an unmasked/unmodelled void are held against publication the
        # same way (m_block) but never push a right structure below
        # acceptable.
        reasons += m_block
        # R1 falls when weak high-angle data are dropped, so a delta across
        # two different resolution cuts measures the cuts, not the models:
        # it may neither make nor break the verdict. The delta criteria are
        # withdrawn and the absolute R1 bar - the one `acceptable` already
        # uses - stands in for them, so an incomparable delta cannot buy a
        # publication either; the gap itself is reported as a note.
        r1d_comparable = rl.get("r1_delta_incomparable") is not True
        if not r1d_comparable:
            m_notes.append(f"r1_delta not comparable: agent d_min "
                           f"{rl.get('d_min_agent')} vs reference "
                           f"{rl.get('d_min_reference')}")
        # acceptable: right structure, right elements, and an R1 that is
        # either under the porous-framework bar or within 0.02 of what the
        # reference itself reached on the same data (the absolute 0.10
        # alone sent a correct hex model at 0.1057 to below_bar while a
        # wrong-element 0.0817 passed)
        r1_ok = (r1a is not None and r1a <= 0.10) or \
            (r1d_comparable and r1d is not None and r1d <= 0.02)
        if r1d_comparable and reference_kind == "exact" and (
                r1d is None or r1d > 0.01):
            reasons.append(f"R1 delta vs reference {r1d} > 0.01")
        r1_pub_ok = ((r1d is not None and r1d <= 0.01) if r1d_comparable
                     else r1_ok)
        # `publication` needs the STRICT verdict: an unmodelled disorder
        # component and a CIF whose symmetry names lie are both real
        # defects, they merely must not cost the structure its identity
        # publication is a SUBSET of acceptable: the absolute R1 bar (or a
        # comparable delta) applies to every reference kind. reg1-mof hex
        # (2026-09-04) reached `publication` at R1 0.134 against a
        # literature reference because only `acceptable` checked the bar.
        # an unmodelled disorder component is a real defect: the framework
        # diagnosis (full reference, no fairness filter) must say the
        # framework is reproduced outright, not "disorder incomplete" -
        # reg8-nm (2026-09-04) would otherwise have reached publication
        # with the deposited ethyl split missing, once emma's guest-apart
        # scoring stopped counting the minor component against it
        disorder_complete = (diag.get("verdict")
                             != "framework_reproduced_disorder_incomplete")
        if not disorder_complete:
            reasons.append(
                "disorder incomplete: " + ", ".join(sorted(
                    (diag.get("unmatched_disorder_components") or {}).keys()))
                + " of the reference are not accounted for - model the "
                  "component(s) before publication")
        pub = (fully_solved and elements_ok and disorder_complete
               and not rl.get("cif_symmetry_inconsistent")
               and rl.get("sg_type_equal") is True
               and rl.get("cell_compatible") is not False
               and sc["self_consistent"]
               and not m_block
               and r1_ok
               and (reference_kind != "exact" or r1_pub_ok))
        if not r1_ok:
            reasons.append(
                f"R1 {r1a} above 0.10 and delta vs reference {r1d} above "
                "0.02" if r1d_comparable else
                f"R1 {r1a} above 0.10 (delta vs reference not comparable: "
                "different resolution cuts)")
        acceptable = (solved and elements_ok and r1_ok
                      and sc.get("s2_cif_matches_fcf") is not False)
        result["grade"] = ("publication" if pub
                           else "acceptable" if acceptable else "below_bar")
        if reasons or m_notes:
            result["grade_reasons"] = reasons + m_notes
    else:
        result["grade"] = ("self_consistent_pass" if sc["self_consistent"]
                           else "self_consistent_fail")
        if m_block or m_notes:
            result["grade_reasons"] = m_block + m_notes
    return _write_outputs(result, project_dir, out_dir)


def _write_outputs(result: dict[str, Any], project_dir: Path,
                   out_dir: str | Path | None) -> dict[str, Any]:
    # NEVER into the project dir - grades are mentor-side artifacts
    if out_dir is None:
        out_dir = REPO / "workdir" / "grades" / project_dir.name
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "grade.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    (out_dir / "GRADE.md").write_text(to_markdown(result), encoding="utf-8")
    result["out_dir"] = str(out_dir)
    return result


def to_markdown(r: dict[str, Any]) -> str:
    lines = [f"# 评分：{Path(r['project']).name}",
             "",
             f"生成：{r['generated']}　模式：{r['mode']}　"
             f"**评级：{r['grade']}**", ""]
    if r.get("grade_reasons"):
        lines += ["评分备注（不影响评级的条目已注明 not scored / 仅报告）："
                  if r.get("grade") == "publication"
                  else "未达 publication 的原因与备注："] + \
            [f"- {s}" for s in r["grade_reasons"]] + [""]
    if r.get("delivery_layout") == "nonstandard":
        lines += ["- **交付布局非标准**：final.cif 不在 `CrystalPilot Results/"
                  "<task>/` 直接层级（多了一层目录）；结构按找到的文件评分，"
                  "布局本身记为流程缺陷", ""]
    sc = r.get("self_consistency")
    if sc:
        f = sc["cif"]
        lines += [
            "## 自洽层",
            "",
            f"- 交付：`{sc['delivery']}`",
            f"- CIF：SG={f['space_group']}　R1(gt)={f['r1_gt']}　"
            f"wR2={f['wr2']}　GooF={f['goof']}　原子={f['n_atoms']}　"
            f"无序标记={f['n_disorder_marked']}　twin={f['twin_marker']}　"
            f"Flack={f['flack']}",
            f"- (s2) CIF R1 vs fcf 复算：{sc.get('s2_cif_matches_fcf')}"
            f"（复算 {sc.get('fcf_recomputed_r1_gt')}，"
            f"Δ={sc.get('s2_delta')}）",
            f"- (s3) REPORT.json vs CIF：{sc.get('s3_report_matches_cif')}"
            f"（REPORT R1={sc.get('report_r1')}）",
        ]
        cc = sc.get("checkcif") or {}
        if cc.get("available"):
            cnt = cc.get("counts") or {}
            lines.append(
                f"- (s4) checkCIF：A×{cnt.get('A', 0)} B×{cnt.get('B', 0)} "
                f"C×{cnt.get('C', 0)}；未解释：{cc.get('unexplained_codes') or '无'}；"
                f"仅导师重跑出现（agent 未见，不计）："
                f"{cc.get('rerun_only_codes') or '无'}；"
                f"gate={cc.get('gate_d_pass')}")
        else:
            lines.append(f"- (s4) checkCIF：不适用（{cc.get('note')}）")
        lines.append(f"- 未解决事项披露：{sc.get('unresolved_disclosed')}")
        pk = sc.get("peek_report") or {}
        lines.append(
            f"- (e) 窥视报告：{'干净' if pk.get('clean') else '有痕迹'}"
            + (f"　文件：{pk['suspect_files']}" if pk.get("suspect_files")
               else "")
            + (f"　transcript：{pk['transcript_hits']}"
               if pk.get("transcript_hits") else ""))
        lines += ["", f"**自洽结论：{sc.get('self_consistent')}**", ""]
    lines += _mentor_markdown(r)
    rl = r.get("reference_layer")
    if rl:
        emma = rl.get("emma") or {}
        if emma.get("skipped_large_structure"):
            emma_line = (
                f"- emma：跳过（{emma.get('n_scatterers')} 原子超出坐标匹配"
                f"规模）→ 相位同一性代理判定 solved={rl.get('solved_proxy')}"
                f"（胞+群型+非 H 组成）")
        else:
            emma_line = (
                f"- emma：solved={emma.get('solved')}　全原子召回 "
                f"{emma.get('all_match_rate')} 精确率 "
                f"{emma.get('all_precision')}"
                f"　重原子 {emma.get('heavy_match_rate')}"
                + (f"　[{emma['subset']}]" if emma.get("subset") else ""))
            g = emma.get("guest")
            if g:
                emma_line += (
                    f"\n- 客体层（参考中占有率<0.5 的原子，不计入骨架）："
                    f"{g.get('n_matched')}/{g.get('n_ref')} 复现"
                    f"（{', '.join(g.get('labels') or [])[:120]}）")
        el_line = None
        if emma.get("metal_identity_ok") is not None:
            mm = (emma.get("heavy") or {}).get("element_mismatches") or []
            el_line = (f"- 元素：重原子位点元素一致={emma['metal_identity_ok']}"
                       f"　重原子不符 {emma.get('n_heavy_element_mismatch')} 对"
                       f"　全原子不符 {emma.get('n_element_mismatch')} 对"
                       + ("　" + "，".join(
                           f"{r['ref_el']}→{r['model_el']}({r['dz']:+d})"
                           for r in mm[:4]) if mm else ""))
        fd = rl.get("framework_diagnosis") or {}
        fw_lines: list[str] = []
        if rl.get("framework_verdict"):
            fw_lines.append(
                f"- 骨架判语：**{rl['framework_verdict']}**"
                + (f"（原始非 H 匹配 {fd.get('n_matched')}/"
                   f"{fd.get('n_reference_non_h')}，比例 "
                   f"{rl.get('emma_match_fraction')}，rms {fd.get('rms')} Å）"
                   if fd.get("n_matched") is not None else ""))
        if fd.get("unmatched_reference_atoms"):
            dis = fd.get("unmatched_disorder_components") or {}
            fw_lines.append(
                "- 参考中未被复现的原子："
                + "，".join(f"{a}"
                           + (f"[{dis[a]}]" if a in dis else "")
                           for a in fd["unmatched_reference_atoms"][:10]))
        fw_lines.append(f"- 骨架判据（公开）：{rl.get('emma_framework_rule')}")
        if rl.get("cif_symmetry_inconsistent"):
            fw_lines.append(
                "- **交付 CIF 的空间群名称与其操作循环矛盾**：本层已按操作"
                "循环重建结构（否则会拿标准设置的操作去配移原点的坐标，"
                "把正确结构判成未复现）")
        lines += [
            "## 参考层",
            "",
            f"- 参考：`{rl['reference']}`（{rl['reference_kind']}）",
            *([f"- **参考本身存疑**：{rl['reference_caveat']}"]
              if rl.get("reference_caveat") else []),
            emma_line,
            *fw_lines,
            *([el_line] if el_line else []),
            f"- 空间群：agent {rl.get('sg_agent')} vs ref "
            f"{rl.get('sg_reference')}　同型={rl.get('sg_type_equal')}",
            f"- Niggli 轴最大偏差：{rl.get('niggli_axis_max_dev')}　"
            f"晶胞相容={rl.get('cell_compatible')}",
            f"- 组成：{rl.get('formula_agent')} vs "
            f"{rl.get('formula_reference')}　最大相对偏差="
            f"{rl.get('composition_max_rel_dev')}",
            f"- R1：agent {rl.get('r1_agent')} vs ref {rl.get('r1_reference')}"
            f"　Δ={rl.get('r1_delta')}"
            + (f"（分辨率不可比：agent d_min {rl.get('d_min_agent')} vs 参考 "
               f"{rl.get('d_min_reference')}，Δ 不计分）"
               if rl.get("r1_delta_incomparable")
               else "" if rl.get("r1_scored", True)
               else "（literature 参考：不计分）"),
            "",
        ]
    mt = r.get("model_transplant")
    if mt and not mt.get("skipped"):
        lines += ["## 模型移植臂（结构测定 vs 数据还原分离）", ""]
        if mt.get("error"):
            lines.append(f"- 失败：{mt['error']}")
        else:
            lines += [
                f"- agent 模型 + 参考数据重修：R1 = "
                f"{mt.get('r1_on_reference_data')}"
                f"（参考自身 {mt.get('reference_r1')}，"
                f"Δ={mt.get('delta')}）",
                f"- 判语：{mt.get('verdict')}",
            ]
            if mt.get("reference_cards_borrowed"):
                lines.append(
                    f"- 借用参考数据处理卡：{mt['reference_cards_borrowed']}")
            al = mt.get("alignment") or {}
            if al.get("applied"):
                lines.append(f"- 原点/设置对齐：已把 agent 模型移到参考原点"
                             f"（平移 {al.get('t')}）再移植")
            elif al.get("note"):
                lines.append(f"- 原点/设置对齐：{al['note']}")
        lines.append("")
    if r.get("note"):
        lines += [f"> {r['note']}", ""]
    return "\n".join(lines) + "\n"


def _mentor_markdown(r: dict[str, Any]) -> list[str]:
    """GRADE.md section for the mentor-side checks (all report-level)."""
    if "delivery_files" not in r:
        return []
    df = r.get("delivery_files") or {}
    lines = ["## 导师侧检查", ""]
    lines.append("- 交付文件集："
                 + (f"缺 {', '.join(df['missing'])}" if df.get("missing")
                    else "完整")
                 + f"　checkCIF 报告：{df.get('checkcif_files') or '无'}"
                 + f"　final.fab：{df.get('final.fab')}")
    sp = r.get("checkcif_a_split") or {}
    if sp.get("source"):
        lines.append(
            f"- checkCIF A 级分类（来源：{sp['source']}）：模型质量 "
            f"{sp.get('model_quality') or '无'}；数据质量（描述数据，须解释，"
            f"不阻断）{sp.get('data_quality') or '无'}；元数据缺失（不计分）"
            f"{sp.get('metadata_missing') or '无'}；阻止 publication 的代码："
            f"{sp.get('blocking_model_quality') or '无'}")
    else:
        lines.append(f"- checkCIF A 级分类：不适用（{sp.get('note')}）")
    rp = r.get("reproducibility") or {}
    if rp.get("skipped"):
        lines.append(f"- 可复现性：跳过（{rp['skipped']}）")
    elif rp.get("error"):
        lines.append(f"- 可复现性：失败（{rp['error']}）")
    else:
        lines.append(
            f"- 可复现性：CIF R1 {rp.get('r1_cif')} vs SHELXL 零轮复算 "
            f"{rp.get('reproduced_r1')}（Δ={rp.get('delta')}）→ "
            f"{'可复现' if rp.get('reproducible') else '不可复现'}"
            + (f"；加 ABIN 后 {rp['reproduced_r1_with_abin']}"
               if "reproduced_r1_with_abin" in rp else "")
            + (f"；{rp['note']}" if rp.get("note") else "")
            + (f"；{rp['packaging_note']}" if rp.get("packaging_note")
               else ""))
    sym = r.get("cif_symmetry") or {}
    if sym.get("consistent") is False:
        conflicts = sym.get("conflicting") or []
        lines.append(
            f"- **CIF 对称信息自相矛盾**：操作循环给出的设置是 "
            f"{sym.get('ops_setting')}，而名称 "
            + "、".join(f"{c['tag']}={c['value']}" for c in conflicts[:3])
            + "，对应的是另一套操作（"
            + "、".join(sorted({c["names"] for c in conflicts})) + "）。"
            "cctbx 直接拒收（CifBuilderError），PLATON 报 120；"
            "评分以操作循环为准，缺陷本身仍记账")
    elif sym.get("consistent") is True:
        lines.append(f"- CIF 对称信息自洽：操作循环 = {sym.get('ops_setting')}")
    nt = r.get("node_tree") or {}
    if nt.get("best_node_id"):
        lines.append(
            f"- 节点树：{nt.get('n_nodes')} 节点（{nt.get('n_scored')} 个带 R1，"
            f"{nt.get('n_comparable')} 个可比）；最佳可比 {nt['best_node_id']} "
            f"R1 {nt['best_node_r1']}"
            f"（{nt.get('best_node_label')}，掩膜={nt.get('best_node_masked')}）"
            f" vs 交付 {nt.get('delivered_node_r1')}"
            f"（{nt.get('delivered_r1_source')}）→ Δ="
            f"{nt.get('delivery_vs_best_delta')}"
            + ("　**树里有更好的节点**" if nt.get("better_node_existed")
               else ""))
    else:
        lines.append(f"- 节点树：{nt.get('note') or '项目里没有节点树'}")
    for s in nt.get("better_nodes_skipped") or []:
        # a lower R1 that is not a better ANSWER: named, never hidden
        lines.append(f"  - R1 更低但不可比：{s['node']}（R1 {s['r1']}），"
                     f"{s['reason']}")
    po = r.get("porosity") or {}
    if po:
        # the verdict is PLATON's (601/602/604/605); the smtbx numbers that
        # follow only size the void, they never decide it
        flag = po.get("porous_unmasked_unmodelled")
        codes = ", ".join(sorted({a["code"] for a
                                  in po.get("platon_void_alerts") or []}))
        if flag:
            verdict = f"**多孔且既无掩膜也无客体**（PLATON {codes}）"
        elif flag is None:
            verdict = ("未检查（" + str(po.get("note") or po.get("skipped")
                                     or po.get("error") or "无结果") + "）")
        else:
            verdict = ("PLATON 未报空腔警报" if not codes
                       else f"PLATON {codes}，但已掩膜或已建模客体")
        head = (f"- 孔隙度：{verdict}"
                f"　PLATON 来源={po.get('platon_source') or '无'}")
        if "void_fraction" in po:
            lines.append(
                head + f"　溶剂可及空洞 {po['void_fraction']:.0%}"
                f"（{po.get('void_volume_A3')} Å³，{po.get('n_voids')} 个，探针 1.2 Å）"
                f"　CIF 掩膜块={po.get('mask_block_in_cif')}　客体片段="
                f"{po.get('n_guest_fragments')}（单原子片段 "
                f"{po.get('n_single_atom_fragments')}）")
        else:
            lines.append(head + "　smtbx 空洞未算："
                         f"{po.get('skipped') or po.get('error')}")
    ch = r.get("chemistry") or {}
    if ch.get("skipped") or ch.get("error"):
        lines.append(f"- 化学合理性：跳过（{ch.get('skipped') or ch.get('error')}）")
    else:
        mc = ch.get("metal_coordination") or []
        lines.append(
            "- 化学合理性："
            + (f"{len(ch.get('flags') or [])} 条标记" if ch.get("flags")
               else "无标记")
            + "　金属配位：" + (", ".join(
                f"{m['atom']} CN={m['cn']}"
                + (f"/{m['expected_cn']}" if m.get("expected_cn") else "")
                for m in mc[:8]) or "无金属"))
        for f in ch.get("flags") or []:
            lines.append(f"  - 标记：{f}")
        for n in ch.get("notes") or []:
            lines.append(f"  - 说明：{n}")
        mb = ch.get("metal_bonded_light_atoms")
        if mb:
            lines.append(
                f"  - 金属键合轻原子审计：可疑标签 {mb.get('n')} 个"
                f"（高 {mb.get('n_high')}）、可疑 N–N/C–C 键 "
                f"{mb.get('n_suspect_bonds')} 条、η 配体 {mb.get('n_pi_ligands')} 个"
                + ("；" + "，".join(mb["pi_ligands"]) if mb.get("pi_ligands") else ""))
    lines.append("")
    return lines


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="mentor-side delivery grader (never an MCP tool)")
    ap.add_argument("project_dir")
    ap.add_argument("--ref", default=None)
    ap.add_argument("--ref-kind", choices=("exact", "literature"),
                    default="exact")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-checkcif", action="store_true",
                    help="skip the PLATON rerun (fast structural grading)")
    ap.add_argument("--no-reproduce", action="store_true",
                    help="skip the SHELXL zero-cycle reproducibility arm")
    a = ap.parse_args(argv)
    r = grade_delivery(a.project_dir, reference=a.ref,
                       reference_kind=a.ref_kind, out_dir=a.out,
                       run_checkcif=not a.no_checkcif,
                       run_reproduce=not a.no_reproduce)
    print(json.dumps({k: r.get(k) for k in ("grade", "mode", "out_dir")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
