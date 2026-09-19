"""SHELX cross-engine tools: real SHELXL check/adopt runs (Flack readback),
vendor SHELXT solving.

Split out of tools_extra (r12 module split); registration stays in
tools_extra.register_refine_tools.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import statistics
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..io.twin import twin_basf_error
from ..procutil import NO_WINDOW, hidden_popen_kwargs
from ..tools.base import ToolContext, ToolResult
from .shelx_cards import extra_cards_help, validate_extra_cards
from .shelxl_lst import (parse_disagreeable_reflections,
                         parse_free_variables, parse_shelxl_warnings,
                         parse_variance_table, restraint_residual_reading,
                         shift_esd_reading)
from .toolbase import _ProjectTool

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SHELXL = REPO_ROOT / "vendor" / "shelx" / "shelxl.exe"

#: the extra_cards whitelist, rendered once for run_shelxl's schema
_EXTRA_CARDS_HELP = extra_cards_help()

#: SHELXT -x default: a try is accepted when CFOM > x + 0.01*max(20-m, 0)
#: (m = try number), i.e. the bar drops 0.01 per try down to x at try 20
SHELXT_ACCEPT_X = 0.65
# -m is iterations PER TRY; above this the tries stop fitting any budget
# (pa2: 7/17 calls timed out, all with -m >= 300; -m100 finished in 70-150 s)
SHELXT_M_CAP = 500

# one row of SHELXT's phasing table:
#   Try N(iter)  CC   R(weak)   CHEM    CFOM    best  Sig(min) N(P1) Vol/N
#     5  2928   86.38  0.2341  0.7514  0.6490  0.6490  1.975   591   32.51
_SHELXT_TRY_ROW = re.compile(
    r"^\s*(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+"
    r"([\d.]+)\s+([\d.]+)\s+(\d+)\s+([\d.]+)\s*$", re.M)


def shelxt_accept_bar(try_number: int, x: float = SHELXT_ACCEPT_X) -> float:
    """CFOM a given try must beat (SHELXT's -x rule)."""
    return x + 0.01 * max(20 - int(try_number), 0)


def shelxt_space_group_name(symbol: str) -> str:
    """Hermann-Mauguin symbol -> the name SHELXT's -s switch wants.

    SHELXT prints and reads groups as 'P2(1)/c', 'Pna2(1)', 'Cccm',
    'P-62m' (no spaces, screw axes in parentheses) and -s wants '/'
    replaced by '_'. sgtbx's lookup symbol for a monoclinic group is the
    full 'P 1 21/c 1'; the two unique-axis '1' tokens are dropped.
    Already SHELXT-shaped input passes through untouched."""
    # setting suffixes (':H', ':R', ':1', ':2') are sgtbx notation; SHELXT
    # rejects them ('** Unknown space group "R-3:H" **', pa2 hex-l2-r1)
    # and uses the hexagonal axes / origin choice of the .ins anyway
    s = re.sub(r"\s*:\s*[HhRr12]\s*$", "", symbol.strip())
    if " " not in s and ("(" in s or "_" in s):
        return s
    hm = s
    try:
        from cctbx import sgtbx
        hm = sgtbx.space_group_info(s).type().lookup_symbol()
    except Exception:  # noqa: BLE001 - unknown symbol: format as given
        pass
    # sgtbx's lookup symbol puts the setting suffix back ('R -3 :H')
    hm = re.sub(r"\s*:\s*[HhRr12]\s*$", "", hm)
    toks = hm.split()
    if len(toks) == 4 and sum(1 for t in toks[1:] if t == "1") == 2:
        toks = [toks[0]] + [t for t in toks[1:] if t != "1"]

    def screw(tok: str) -> str:
        return re.sub(r"^(-?)([2346])([1-5])(?=$|/)",
                      lambda m: f"{m.group(1)}{m.group(2)}({m.group(3)})", tok)
    return "".join(screw(t) for t in toks).replace("/", "_")


# one Q-peak row of a SHELXL .res (PLAN output):
#   Q1    1   0.0958  0.2419  0.4306  11.00000  0.05    3.93
_Q_PEAK_ROW = re.compile(
    r"^Q(\d+)\s+\d+\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+"
    r"-?\d+\.\d+\s+-?\d+\.\d+\s+(-?\d+\.\d+)\s*$", re.M)
_Q_EXTREMES = re.compile(
    r"REM Highest difference peak\s+(-?\d+\.\d+),\s+deepest hole\s+"
    r"(-?\d+\.\d+)")


def parse_q_peaks(res_text: str) -> dict[str, Any]:
    """SHELXL's residual-peak table from a .res (PLAN output): fractional
    sites, heights (e/A^3, the last column) and the REM extremes line.
    SHELXL's order (descending height) is kept, so Q1 is index 0.

    pa1: run_shelxl never stored its Q peaks, so the session's peak table
    (and add_atoms_from_difference_map's indices) went stale after every
    adopt, and agents SHELL-grepped job.res for the peak list."""
    sites: list[tuple[float, float, float]] = []
    heights: list[float] = []
    for m in _Q_PEAK_ROW.finditer(res_text):
        sites.append((float(m.group(2)), float(m.group(3)),
                      float(m.group(4))))
        heights.append(float(m.group(5)))
    ext = _Q_EXTREMES.search(res_text)
    return {"sites": sites, "heights": heights,
            "max": float(ext.group(1)) if ext else None,
            "min": float(ext.group(2)) if ext else None}


def parse_flack_lst(text: str) -> dict[str, Any] | None:
    """Flack x from a SHELXL .lst: classical-fit line + Parsons' quotient
    continuation line (vendor-verbatim formats; su in parentheses is in
    units of the value's last decimal place unless it carries its own dot).

        Flack x =    1.546(999) by classical fit to all intensities
                    -0.431(999) from 857 selected quotients (Parsons' method)
        ** Absolute structure cannot be determined reliably **
    """
    def _val(vs: str, sus: str) -> tuple[float, float]:
        v = float(vs)
        if "." in sus:
            return v, float(sus)
        dec = len(vs.split(".")[1]) if "." in vs else 0
        return v, int(sus) * 10.0 ** -dec

    out: dict[str, Any] = {}
    mc = re.search(r"Flack x =\s*(-?[\d.]+)\s*\(\s*([\d.]+)\s*\)\s*by "
                   r"classical fit", text)
    if mc:
        v, su = _val(mc.group(1), mc.group(2))
        out["classical"] = {"value": v, "su": su}
    mp = re.search(r"^\s*(-?[\d.]+)\s*\(\s*([\d.]+)\s*\)\s*from\s+(\d+)\s+"
                   r"selected quotients \(Parsons' method\)", text, re.M)
    if mp:
        v, su = _val(mp.group(1), mp.group(2))
        out["parsons"] = {"value": v, "su": su,
                          "n_quotients": int(mp.group(3))}
    if not out:
        return None
    out["determined"] = ("Absolute structure cannot be determined"
                         not in text)
    # Parsons' quotients are the more robust estimator for weak anomalous
    # signal - prefer them when SHELXL printed both
    pick = out.get("parsons") or out["classical"]
    out["value"], out["su"] = pick["value"], pick["su"]
    out["method"] = "parsons" if "parsons" in out else "classical"
    return out


def flack_verdict(value: float, su: float, determined: bool = True) -> str:
    """Honest reading of a Flack parameter for the summary note.

    NB SHELXL's banner '** Absolute structure cannot be determined
    reliably **' fires BOTH when the su is too large AND when x lands
    near 0.5 with a SMALL su (racemic twin - neither hand dominates,
    which is a determination, just not of a single hand). r21 live case:
    Flack 0.51(1) carried the banner, and the old su-blind branch here
    labelled it 'no determination power (su > 0.3)' - contradicting the
    printed number in the same summary. Judge by value+su first; the
    banner is reported as context, never as the verdict."""
    banner = ("" if determined
              else " (SHELXL banner: 'cannot be determined reliably')")
    if su > 0.30:
        return ("no determination power (su > 0.3)" + banner +
                " - normal for light-atom structures with Mo radiation; "
                "disclose the absolute structure as not reliably determined")
    if abs(value) <= max(2.0 * su, 0.10):
        return "consistent with the correct absolute structure" + banner
    if abs(value - 1.0) <= max(2.0 * su, 0.10):
        return ("indicates the inverted structure - run invert_structure, "
                "then re-refine and re-check" + banner)
    if 0.30 <= value <= 0.70:
        note = ("suggests racemic/inversion twinning - consider "
                "set_twin(law=inversion) and let SHELXL refine BASF")
        if not determined:
            note += (" (the SHELXL banner here means neither hand "
                     "dominates, not that the estimate is weak)")
        return note
    return ("intermediate value - check data quality, absorption and "
            "possible twinning before drawing conclusions" + banner)


def parse_shift_esd(lst_text: str) -> dict[str, Any] | None:
    """Convergence readout from the .lst 'Mean shift/esd' cycle lines.

    Verbatim format: ' Mean shift/esd =   0.002  Maximum =     0.029 for
    U22 C9X'. Agents grepped these by SHELL in five campaigns because the
    summary carried only R factors (process-audit T1/#6)."""
    hits = re.findall(r"Mean shift/esd =\s*([\d.]+)\s+Maximum =\s*(-?[\d.]+)"
                      r"(?:\s+for\s+(\S+(?:\s+\S+)?))?", lst_text)
    if not hits:
        return None
    mean, mx, param = hits[-1]
    out: dict[str, Any] = {
        "n_cycles_reported": len(hits),
        "final_mean": float(mean),
        "final_max": float(mx),
        "converged": abs(float(mx)) <= 0.05,
    }
    if param:
        out["final_max_param"] = param.strip()
    return out


def parse_wght_lines(res_text: str) -> tuple[list[float], list[float]] | None:
    """(used, suggested) WGHT schemes from an OUTPUT .res.

    SHELXL echoes the scheme it used among the instruction cards and
    appends its updated suggestion as a second WGHT line near the end of
    the file (the classic 'copy WGHT from .res back to .ins' loop). With
    a single line (or L.S. 0) the two coincide."""
    rows = re.findall(r"^\s*WGHT((?:\s+-?[\d.]+)+)", res_text, re.M)
    if not rows:
        return None
    def _vals(row: str) -> list[float]:
        return [float(t) for t in row.split()][:2]
    used = _vals(rows[0])
    suggested = _vals(rows[-1])
    for v in (used, suggested):
        while len(v) < 2:
            v.append(0.0)
    return used, suggested


def wght_agrees(used: list[float], suggested: list[float]) -> bool:
    """SHELXL's suggested scheme counts as converged when a moved by at
    most 0.005 and b by at most max(0.5, 5 %) - the tolerance run_shelxl
    has reported as wght_converged since r13, now shared with the
    mode='adopt_wght' loop so both stop at the same point."""
    return (abs(suggested[0] - used[0]) <= 0.005
            and abs(suggested[1] - used[1])
            <= max(0.5, 0.05 * abs(used[1])))


def next_round_ins_text(res_text: str, wght: list[float]) -> str:
    """The classic 'copy .res to .ins with the new WGHT' step, as text.

    Everything up to and including END is kept verbatim (SHELXL's echoed
    header, cards, ABIN, the refined atoms and FVARs), the header WGHT
    card - the one before HKLF - becomes `wght`, and the trailer after END
    (the suggestion line itself, Q peaks) is dropped so the next job reads
    exactly one scheme. This is what every pa1 agent did by hand via
    set_weights + run_shelxl, 2-3 rounds per delivery (hex-l2-r2, hex-l0-r1,
    cu-l3-r1, cage-l0-r1) after mode='adopt' turned out to keep the USED
    scheme (load_res_model stops at END and never sees the suggestion)."""
    out: list[str] = []
    replaced = seen_hklf = False
    for ln in res_text.splitlines():
        toks = ln.split()
        head = toks[0].upper() if toks else ""
        if head == "HKLF":
            seen_hklf = True
        if head == "WGHT" and not seen_hklf and not replaced:
            out.append("WGHT %.6f %.6f" % (float(wght[0]), float(wght[1])))
            replaced = True
            continue
        out.append(ln)
        if head == "END":
            break
    if not replaced:
        raise ValueError("no WGHT card before HKLF in the .res text")
    return "\n".join(out) + "\n"


_RESTRAINT_KW = (r"DFIX|DANG|SADI|SAME|FLAT|SIMU|DELU|RIGU|ISOR|BUMP|CHIV"
                 r"|NCSY|EADP|EXYZ")


def parse_disagreeable_restraints(lst_text: str) -> dict[str, Any] | None:
    """Final 'Disagreeable restraints before cycle N' section as a compact
    health summary: count + worst offenders by |error|/sigma. Entry lines
    may omit Observed/Target (SIMU prints only Error/Sigma/Restraint)."""
    sections = re.split(r"Disagreeable restraints before cycle\s+\d+",
                        lst_text)
    if len(sections) < 2:
        return None
    tail = sections[-1]
    entries: list[tuple[float, str]] = []
    for ln in tail.splitlines():
        if re.match(r"\s*(Observed|Target)", ln):
            continue
        m = re.search(rf"(-?\d+\.\d+)\s+(\d+\.\d+)\s+"
                      rf"((?:{_RESTRAINT_KW})\b.*?)\s*$", ln)
        if m:
            err, sig = float(m.group(1)), float(m.group(2))
            entries.append((abs(err) / max(sig, 1e-9), ln.strip()))
        elif entries and not ln.strip():
            break                      # section ends at the first blank
    if not entries:
        return None
    entries.sort(key=lambda t: -t[0])
    out: dict[str, Any] = {
        "n": len(entries),
        "worst": [ln for _, ln in entries[:3]],
        "note": "final-cycle table; err/sigma ratios "
                + ", ".join(f"{r:.1f}" for r, _ in entries[:3])}
    # r33: the ratios were printed but never judged. KNOWLEDGE §15.2 gives
    # the one-directional bar ("Residuals larger than about three times the
    # requested standard uncertainty should always be investigated").
    out.update(restraint_residual_reading(
        [{"line": ln, "ratio": round(r, 2)} for r, ln in entries]))
    return out


def _stage_job_hkl(project, job: Path, source: Path | None = None) -> str:
    """<job>/job.hkl = the project's reflections, as a hard link to the
    byte-identical immutable reflection revision when one exists (the 6 MB
    hkl used to be copied into every job directory: 391 MB of one file in
    a real 8-hour session), else a copy. Returns "link" | "copy"."""
    from .storage import link_or_copy, reflection_revision_files
    src = Path(source) if source is not None else Path(project.hkl_path)
    return link_or_copy(src, job / "job.hkl",
                        immutable=reflection_revision_files(project.dir))


def _link_or_copy(src: Path, dst: Path, immutable=()) -> str:
    from .storage import link_or_copy
    return link_or_copy(src, dst, immutable=immutable)


def _execute_shelxl(exe: Path, job: Path,
                    timeout_s: int) -> tuple[str, str, str | None]:
    """Run shelxl on <job>/job.ins. Returns (res_text, stdout, error);
    error is None when SHELXL exited 0 and left a job.res behind.

    After a successful run the reflection block SHELXL embeds in job.cif
    (a verbatim second copy of job.hkl, 6 MB per job) is replaced by a
    marker when it is byte-identical to that file; storage.restore_
    embedded_hkl puts it back wherever the complete CIF is needed
    (publication assembly, checkCIF staging)."""
    try:
        proc = subprocess.run(
            [str(exe), "job"], cwd=str(job), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, errors="replace",
            timeout=int(timeout_s), creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return "", "", f"shelxl timed out after {timeout_s} s ({job.name})"
    out_res = job / "job.res"
    if proc.returncode != 0 or not out_res.exists():
        tail = (proc.stdout or "")[-800:]
        return "", proc.stdout or "", (
            f"shelxl failed (exit {proc.returncode}): {tail}")
    try:
        from .storage import strip_embedded_hkl
        strip_embedded_hkl(job)
    except OSError:
        pass          # a full-size job.cif is only a storage cost
    return (out_res.read_text(encoding="utf-8", errors="replace"),
            proc.stdout or "", None)


def refinement_counts(cif_text: str, res_text: str = "") -> dict[str, int]:
    """Counts reported by this engine job, not the strong-reflection subset."""
    out: dict[str, int] = {}
    total = re.search(r"\band\s+[0-9.]+\s+for\s+(?:all\s+)?(\d+)\s+(?:data|reflections)\b",
                      res_text, re.IGNORECASE)
    if total:
        out["n_reflections"] = int(total.group(1))
    if cif_text:
        try:
            import gemmi
            block = gemmi.cif.read_string(cif_text).sole_block()
            for key, tag in (("n_params", "_refine_ls_number_parameters"),
                             ("n_reflections", "_refine_ls_number_reflns"),
                             ("n_restraints", "_refine_ls_number_restraints")):
                raw = block.find_value(tag)
                value = str(raw).strip("'\"") if raw is not None else ""
                if re.fullmatch(r"[0-9]+", value):
                    out[key] = int(value)
        except (RuntimeError, ValueError):
            pass
    return out


def summarize_shelxl_job(job: Path, text: str, l_s: int,
                         proc_stdout: str = "") -> tuple[
                             dict[str, Any] | None, dict[str, Any],
                             str | None]:
    """R1/wR2/GooF, Flack, shift/esd, WGHT used vs suggested, disagreeable
    restraints and Q peaks of one finished SHELXL job -> (shelxl, q_peaks,
    error). Writes the job's .ok completion marker on success. Shared by
    run_shelxl's first job and every round of the mode='adopt_wght' loop
    (the loop needs the same readback per round, so the parsing left the
    run() method).

    r33 (PLAN T1.1) added the .lst blocks nothing used to read - SHELXL's
    `**` banners on the SUCCESS path (`warnings`/`n_warnings`), the
    analysis of variance (`variance_analysis`, the criterion §17.4
    actually gives for a weighting scheme), the most disagreeable
    reflections with their direction and index pattern
    (`disagreeable_reflections`, §2.7), a >3-sigma flag on the restraint
    residuals (§15.2) and the four IUCr candidate directions when max
    shift/esd > 1.5 (§17.5). See crystalpilot/refine/shelxl_lst.py; every
    block is absent from the summary rather than defaulted when SHELXL
    did not print it."""
    mr = re.search(r"R1\s*=\s*([0-9.]+)\s*for\s*(\d+).*?and\s*([0-9.]+)\s*for", text)
    mw = re.search(r"wR2\s*=\s*([0-9.]+)", text)
    mg = re.search(r"GooF\s*=\s*S\s*=\s*([0-9.]+)", text)
    if not (mr and mw and mg):
        # surface SHELXL's own error lines (empty .res = hard abort)
        lst = job / "job.lst"
        errs = []
        if lst.exists():
            errs = [ln.strip() for ln in
                    lst.read_text(encoding="utf-8",
                                  errors="replace").splitlines()
                    if "**" in ln][:8]
        detail = ("; ".join(errs) if errs
                  else (proc_stdout or "")[-400:])
        return None, {}, (
            f"shelxl produced no refinement summary "
            f"(job.res {'empty' if not text.strip() else 'unparsable'})."
            f" SHELXL says: {detail}")
    shelxl = {"r1_strong": float(mr.group(1)), "n_strong": int(mr.group(2)),
              "r1_all": float(mr.group(3)), "wr2": float(mw.group(1)),
              "goof": float(mg.group(1))}
    # absolute structure: SHELXL prints Flack x for every
    # non-centrosymmetric refinement - not reading it was a platform
    # blind spot (AGENTS said "check Flack first", no tool carried it)
    lst_path = job / "job.lst"
    lst_text = (lst_path.read_text(encoding="utf-8", errors="replace")
                if lst_path.exists() else "")
    cifp = job / "job.cif"
    cif_text = cifp.read_text(encoding="utf-8", errors="replace") if cifp.exists() else ""
    shelxl.update(refinement_counts(cif_text, text))
    flack = parse_flack_lst(lst_text) if lst_text else None
    if flack is None:
        if cif_text:
            mfl = re.search(
                r"_refine_ls_abs_structure_Flack\s+(-?[\d.]+)\((\d+)\)",
                cif_text)
            if mfl:
                v = float(mfl.group(1))
                dec = (len(mfl.group(1).split(".")[1])
                       if "." in mfl.group(1) else 0)
                flack = {"value": v,
                         "su": int(mfl.group(2)) * 10.0 ** -dec,
                         "method": "cif", "determined": True}
    if flack:
        shelxl["flack"] = round(flack["value"], 4)
        shelxl["flack_su"] = round(flack["su"], 4)
        shelxl["flack_method"] = flack["method"]
        shelxl["flack_note"] = flack_verdict(
            flack["value"], flack["su"], flack.get("determined", True))
        if "n_quotients" in (flack.get("parsons") or {}):
            shelxl["flack_n_quotients"] = \
                flack["parsons"]["n_quotients"]
    # convergence / weighting / restraint health: the exact numbers
    # agents kept SHELL-grepping job.lst and job.res for across five
    # campaigns (process-audit T1/#6: ~22 greps + three generations of
    # WGHT-adoption workarounds)
    shift = parse_shift_esd(lst_text)
    if shift:
        reading = shift_esd_reading(shift["final_max"])
        if reading:
            shift["reading"] = reading
        shelxl["shift_esd"] = shift
    # r33 .lst readback (PLAN T1.1). Everything below is read on the
    # SUCCESS path too - the `**` banners used to be looked at only when
    # the R1/wR2/GooF regexes failed, so a job that finished normally
    # dropped its own warnings on the floor.
    warnings = parse_shelxl_warnings(lst_text)
    if warnings:
        shelxl["n_warnings"] = len(warnings)
        shelxl["warnings"] = warnings[:12]
    variance = parse_variance_table(lst_text)
    if variance:
        shelxl["variance_analysis"] = variance
    disagree = parse_disagreeable_reflections(lst_text)
    if disagree:
        shelxl["disagreeable_reflections"] = disagree
    # r34 (PLAN T1.6): the refined free variables AND THEIR ESDS. The .res
    # carries the values only, so until now a disorder occupancy came back
    # as a bare number with no uncertainty and no tool could say whether
    # the split it encodes is supported by the data (reg1-ext2: two
    # deposited PART splits delivered unmodelled, one abandoned trial).
    fvars_lst = parse_free_variables(lst_text)
    if fvars_lst:
        shelxl["free_variables"] = {
            ("osf" if k == 1 else f"fvar{k}"): {
                "value": d["value"], "su": d["su"],
                "shift_esd": d["shift_esd"]}
            for k, d in sorted(fvars_lst.items())}
    wghts = parse_wght_lines(text)
    if wghts:
        used, suggested = wghts
        shelxl["wght_used"] = used
        if l_s >= 1:
            shelxl["suggested_wght"] = suggested
            converged = wght_agrees(used, suggested)
            shelxl["wght_converged"] = converged
            if not converged:
                # pa1: every agent read the old 'mode=adopt takes the
                # suggestion automatically' promise, found it false
                # (adopt keeps the USED scheme) and fell back to hand
                # loops of set_weights + run_shelxl (hex-l2-r2 x3,
                # hex-l0-r1, cu-l3-r1, cage-l0-r1)
                shelxl["wght_note"] = (
                    f"SHELXL suggests WGHT {suggested[0]:g} "
                    f"{suggested[1]:g} (ran with {used[0]:g} "
                    f"{used[1]:g}): run_shelxl(mode='adopt_wght') copies "
                    f"the suggestion into the next job and repeats until "
                    f"it stabilizes, then adopts (mode='adopt' keeps the "
                    f"scheme it ran with; set_weights is the manual path)")
    dis = parse_disagreeable_restraints(lst_text)
    if dis:
        shelxl["disagreeable_restraints"] = dis
    q_peaks = parse_q_peaks(text)
    if q_peaks["max"] is not None:
        shelxl["diff_map_max"] = q_peaks["max"]
        shelxl["diff_map_min"] = q_peaks["min"]
    shelxl["n_q_peaks"] = len(q_peaks["sites"])
    # completion marker: write_outputs only assembles publication CIFs
    # from jobs that actually finished (a failed follow-up run must not
    # let an older job masquerade as current)
    (job / ".ok").write_text("", encoding="ascii")
    return shelxl, q_peaks, None


def _stale_afix_message(stale: list[dict[str, Any]]) -> str:
    """Every riding group SHELXL would refuse, in one message.

    The point is completeness: SHELXL reports what it happens to reach
    before terminating, so fixing them one at a time cost the ka1 cage
    lane six add_hydrogens/run_shelxl rounds. All of them are here.
    """
    lines = [
        f"not run: {len(stale)} riding-H group(s) in this model carry an "
        f"AFIX code SHELXL's connectivity check would refuse, and SHELXL "
        f"aborts the whole job on those (\"** BAD AFIX ... CONNECTIVITY OR "
        f"PART NUMBERS ... ** TERMINATING BECAUSE OF BAD HFIX OR AFIX "
        f"INSTRUCTIONS **\") rather than refining. The H metadata is "
        f"replayed as it was recorded, so this means the model changed "
        f"after add_hydrogens ran (atoms added from the difference map, "
        f"an element reassigned, a new space group, atoms that moved). "
        f"ALL of them are listed here - fix them in one round:"]
    for s in stale[:40]:
        lines.append(
            f"  - {s['atom']} ({s['kind']}, AFIX {s['afix']}, H "
            f"{', '.join(s['h']) or '?'}): needs {s['expected']} bonded "
            f"neighbour(s), the model gives {s['n_bonded']} "
            f"({', '.join(s['bonded']) or 'none'})"
            + (f", or {s['n_after_dropping_heavy']} once SHELXL drops "
               f"{', '.join(s['droppable'])} (outside its Z 6-10 window)"
               if s["droppable"] else ""))
    if len(stale) > 40:
        lines.append(f"  ... and {len(stale) - 40} more")
    lines.append(
        "Re-run add_hydrogens (same parameters) to re-derive every riding "
        "group from the model as it stands now - carriers that no longer "
        "fit any AFIX code are then skipped with reason "
        "afix_connectivity_mismatch instead of being written out - or "
        "delete the offending H with edit_atoms if the site is wrong. Do "
        "not reach for exclude= one label at a time.")
    return "\n".join(lines)


def disorder_acceptance(xs, groups: list[dict[str, Any]],
                        shelxl: dict[str, Any], ses,
                        r1_now: float | None) -> list[dict[str, Any]]:
    """Per-disorder-group acceptance blocks for a finished SHELXL job.

    This is the read-back that makes a PART split falsifiable: SHELXL's
    refined free variable AND its esd, the two components' U_eq against
    the model's own median, their closest approach against the DATA's own
    d_min, and delta R1 against the pre-split R1 the split recorded - each
    with the rule that produced its reading and a verdict of supported /
    inconclusive / revoke plus what to do next. See refine/disorder_accept.

    Best-effort by construction: a refinement result must never be lost
    because a derived reading raised.
    """
    from .disorder_accept import data_d_min, group_acceptance
    out: list[dict[str, Any]] = []
    fvs = shelxl.get("free_variables") or {}
    origins = {int(o["fvar_index"]): o
               for o in (ses.flags.get("disorder_origins") or [])
               if o.get("fvar_index")}
    d_min = data_d_min(ses)
    split_labels = {str(m.get("label", "")).upper()
                    for g in (groups or []) for m in (g.get("members") or [])}
    for g in groups or []:
        try:
            k = int(g.get("fvar_index") or 0)
            out.append(group_acceptance(
                xs, g, free_var=fvs.get(f"fvar{k}"), d_min_data=d_min,
                r1_now=r1_now, origin=origins.get(k),
                split_labels=split_labels,
                peaks=ses.flags.get("diff_map_peaks")))
        except Exception as e:  # noqa: BLE001 - advisory block only
            out.append({"fvar_index": g.get("fvar_index"),
                        "error": f"acceptance reading unavailable: {e}"})
    return out


def _acceptance_summary(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """The one-line headline: which groups need action, in the agent's
    words. P12 - a group that came back `supported` is reported as "the
    null split was excluded", never as a pass."""
    counts: dict[str, int] = {}
    for b in blocks:
        counts[b.get("verdict", "error")] = \
            counts.get(b.get("verdict", "error"), 0) + 1
    parts = []
    if counts.get("revoke"):
        parts.append(f"{counts['revoke']} group(s) REVOKE (the refined "
                     f"occupancy is not distinguishable from a single site "
                     f"- model_disorder(undo=...) removes them cleanly)")
    if counts.get("inconclusive"):
        parts.append(f"{counts['inconclusive']} group(s) inconclusive (the "
                     f"ratio is not determined; restrain and re-refine, or "
                     f"disclose the disorder as unmodelled)")
    if counts.get("supported"):
        parts.append(f"{counts['supported']} group(s) supported (the null "
                     f"split is excluded at 2 s.u. - add the suggested "
                     f"SADI/SIMU restraints and keep)")
    if counts.get("unknown") or counts.get("pending"):
        parts.append("some group(s) have no refined s.u. yet - run with "
                     "l_s >= 4")
    return {"verdicts": counts,
            "reading": "; ".join(parts) or "no disorder group in this model"}


def _wght_row(n: int, shelxl: dict[str, Any]) -> dict[str, Any]:
    return {"round": n, "used": shelxl.get("wght_used"),
            "suggested": shelxl.get("suggested_wght"),
            "goof": shelxl.get("goof"), "r1_strong": shelxl.get("r1_strong"),
            "wr2": shelxl.get("wr2")}


class RunShelxl(_ProjectTool):
    name = "run_shelxl"
    description = (
        "Run the real SHELXL-2019/3 on the current model as an independent "
        "engine: writes a complete .ins (atoms, AFIX riding H, restraint "
        "cards, WGHT, solvent mask exported as ABIN .fab), executes shelxl, "
        "parses R1/wR2/GooF. mode='check' only reports agreement with the "
        "in-process engine; mode='adopt' additionally takes the SHELXL-refined "
        "model back into the session as a new node (keeping the WGHT it ran "
        "with); mode='adopt_wght' is the weighting-scheme convergence loop: "
        "it copies the WGHT SHELXL suggests at the end of each job into the "
        "next job (.res -> .ins, the model is not re-serialized in between) "
        "until suggested and used agree or wght_rounds extra jobs ran, then "
        "adopts the last job - use it once the model is essentially complete "
        "(mask/disorder settled), and read wght_loop.history for the GooF "
        "trail. Riding H are re-derived per carrier on adopt (replaced, never "
        "duplicated; labels of the adopted model are kept). Use as "
        "cross-validation before finalizing. Both modes read back the "
        "whole .lst: SHELXL's own ** banners, the analysis of variance "
        "(K vs Fc and vs resolution - the trend test §17.4 gives for a "
        "weighting scheme, not GooF), the most disagreeable reflections "
        "with the direction of their Fo^2-Fc^2 imbalance and any shared "
        "index relation, restraint residuals over 3 sigma, and the "
        "convergence reading. BUDGET: each SHELXL job is killed at timeout_s "
        "(default 300 s) and the tool returns ok=false naming how far it "
        "got, with the session unchanged; mode='adopt_wght' runs up to "
        "1+wght_rounds jobs in sequence, so its ceiling is that multiple "
        "(~1500 s by default) - it is still the CHEAP way to settle weights "
        "on a large model, far cheaper than optimize_weights.")
    params_schema = {
        "type": "object",
        "properties": {
            "mode": {"type": "string",
                     "enum": ["check", "adopt", "adopt_wght"],
                     "default": "check"},
            "l_s": {"type": "integer", "default": 8,
                    "description": "L.S. cycles per job (0 = just compute "
                                   "R factors; adopt_wght needs >= 1)"},
            "timeout_s": {"type": "integer", "default": 300,
                          "description": "seconds per SHELXL job"},
            "wght_rounds": {"type": "integer", "default": 4,
                            "description": "mode='adopt_wght': max extra "
                                           "SHELXL jobs after the first "
                                           "(1-10); the loop stops early "
                                           "once the suggestion stabilizes"},
            "extra_cards": {
                "type": "array", "items": {"type": "string"},
                "description": (
                    "Extra SHELX instruction cards for this job, one per "
                    "entry, checked against a whitelist before the job "
                    "runs. THE reason to use it: `EQIV $n <symop>` + "
                    "`HTAB D A` / `HTAB D A_$n` are the only way to get a "
                    "_geom_hbond_* loop WITH esds into the delivered CIF "
                    "(SHELXL measures it; nothing else can). Accepted "
                    "families - " + _EXTRA_CARDS_HELP + ". Atom names are "
                    "checked against the model, every `_$n` must have its "
                    "EQIV in the same list, an EQIV operator must belong to "
                    "the space group, and long cards are split with SHELX "
                    "`=` continuation; anything else is refused by name "
                    "without running SHELXL. MPLA/RTAB land in the .lst "
                    "only - SHELXL writes no plane block into the CIF."),
            },
            "reason": {"type": "string",
                       "description": "why these extra_cards (recorded in "
                                      "the result, never interpreted)"},
            "replace_cards": {
                "type": "boolean", "default": False,
                "description": (
                    "Cards an adopted job refined with stay with the model "
                    "(effective cards: node.json effective_state, model.res) "
                    "and ride into every later job automatically. true = "
                    "drop that set and use only this call's extra_cards "
                    "(persisted on adopt).")},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        import math
        import os
        from ..io.shelx_model import load_res_model
        from ..io.shelx_writer import (ShelxModel, afix_connectivity_problems,
                                       shelxl_command_block, write_fab,
                                       write_res)
        from .restraints import (emit_shelx_cards, preflight,
                                 preflight_applicability)

        ses = ctx.session
        exe = Path(os.environ.get("CRYSTALPILOT_SHELXL", str(DEFAULT_SHELXL)))
        if not exe.exists():
            return ToolResult.failure(
                f"shelxl.exe not found at {exe} (run scripts/setup_vendor_shelx.py "
                "or set CRYSTALPILOT_SHELXL)")
        mode = str(params.get("mode", "check"))
        if mode not in ("check", "adopt", "adopt_wght"):
            return ToolResult.failure(
                f"mode={mode!r} is not one of check / adopt / adopt_wght")
        if mode == "adopt_wght" and int(params.get("l_s", 8)) < 1:
            return ToolResult.failure(
                "mode='adopt_wght' needs l_s >= 1: SHELXL only suggests a "
                "weighting scheme after refining")
        twin_error = twin_basf_error(ses.flags.get("twin"))
        if twin_error:
            return ToolResult.failure(
                twin_error + ". Reapply set_twin with the intended n and "
                "basf list before run_shelxl; SHELXL was not run and the "
                "session is unchanged.")
        job = self._new_job_dir()

        flags = ses.flags
        weights = flags.get("weights") or {}
        scale_k = flags.get("scale_k")
        fvar = math.sqrt(scale_k) if scale_k and scale_k > 0 else 1.0
        h_meta = flags.get("h_riding_meta") or {}
        extra = []
        f_mask = flags.get("f_mask")
        if f_mask is not None:
            # SHELXL matches .fab lines by index against ITS merged set; a
            # P1-complete expansion guarantees every reflection finds its A,B
            fm_p1 = f_mask.expand_to_p1().generate_bijvoet_mates()
            n = write_fab(fm_p1, job / "job.fab")
            extra.append("ABIN")
        cards = shelxl_command_block(l_s=int(params.get("l_s", 8)), extra=extra)
        # experimental metadata cards: SHELXL's ACTA output then carries the
        # temperature / crystal size (and estimates T_min/max from SIZE)
        exp = (self.project.experiment()
               if hasattr(self.project, "experiment") else {})
        # WP4: when temperature_K is unknown we deliberately emit no TEMP
        # card. SHELXL then falls back to its own default (20 C / 293 K)
        # purely for riding-H bond-length/ADP geometry - a harmless
        # approximation - but also prints that same 293(2) into the ACTA
        # CIF's _diffrn_ambient_temperature / _cell_measurement_temperature
        # as if it were measured. That is not this module's problem to
        # solve by fabricating a TEMP card; assemble_publication_cif() in
        # report/publication.py is responsible for forcing both CIF tags
        # back to '?' whenever exp has no temperature_K, so the unmeasured
        # value never survives into the delivered CIF as a number.
        if exp.get("temperature_K") is not None:
            cards.append("TEMP %.1f" % (float(exp["temperature_K"]) - 273.15))
        size = ((exp.get("crystal") or {}).get("size_mm")
                if isinstance(exp.get("crystal"), dict) else None) \
            or exp.get("crystal_size")
        if size and len(size) == 3:
            cards.append("SIZE %.3f %.3f %.3f" % tuple(sorted(map(float, size))))
        # agent-supplied instruction cards (D11: HTAB is the only route to
        # _geom_hbond_* WITH esds). Checked BEFORE the model is serialized,
        # because SHELXL's own answer to a bad card is to abort the job and
        # leave the reason in the .lst - here every rejection names the card.
        extra_cards, extra_note = [], None
        raw_extra = params.get("extra_cards")
        reason = str(params.get("reason") or "").strip()
        if raw_extra and not isinstance(raw_extra, (list, tuple)):
            return ToolResult.failure(
                "extra_cards must be a list of SHELX instruction strings")
        replace_cards = bool(params.get("replace_cards"))
        # round-3 WP2: the instruction cards an adopted job refined with
        # are model state (flags.effective_cards, node.json effective_state,
        # model.res) and ride into every later job the way restraints do -
        # a later run_shelxl without them used to refine a different model
        # silently (forensic T-d: EADP/SUMP lost between n0209 and
        # final.res). replace_cards=true drops the inherited set.
        effective_prev = ([] if replace_cards
                          else list(flags.get("effective_cards") or []))
        applied_eff: list[str] = []
        from ..io.shelx_writer import element_of, sanitize_labels
        scatterers = list(ses.model.scatterers())
        labels = [sc.label for sc in scatterers]
        gate_kw: dict[str, Any] = dict(
            labels=labels,
            elements={element_of(sc.scattering_type) for sc in scatterers},
            rename=sanitize_labels(labels),
            space_group=ses.model.space_group())
        if effective_prev:
            lines_e, applied_eff, err = validate_extra_cards(
                effective_prev, base_cards=cards, **gate_kw)
            if err:
                return ToolResult.failure(
                    "an effective instruction card from an earlier adopted "
                    "job no longer fits this model (SHELXL was not run, the "
                    "session is unchanged): " + err + " - restate the set "
                    "with run_shelxl(replace_cards=true, extra_cards=[...]) "
                    "or restore the atoms it names")
            cards.extend(lines_e)
        if raw_extra:
            known = {" ".join(str(c).upper().split()) for c in applied_eff}
            fresh = [c for c in raw_extra
                     if " ".join(str(c).upper().split()) not in known]
            if fresh:
                lines, extra_cards, err = validate_extra_cards(
                    fresh, base_cards=cards, **gate_kw)
                if err:
                    return ToolResult.failure(
                        "extra_cards rejected (SHELXL was not run, the session "
                        "is unchanged): " + err)
                cards.extend(lines)
            extra_note = ("SHELXL - not CrystalPilot - measures whatever "
                          "these cards ask for; HTAB rows reach the "
                          "delivered CIF as _geom_hbond_* with esds, MPLA "
                          "and RTAB reach the .lst only")
        effective_now = applied_eff + [
            c for c in extra_cards
            if c.upper() not in {x.upper() for x in applied_eff}]
        from .nodes import serialization_extras
        extras = serialization_extras(flags)
        extras.pop("instruction_cards", None)     # already in `cards`
        # pre-flight: h_riding_meta is replayed VERBATIM into the .ins, so
        # a model that changed after add_hydrogens (atoms added from the
        # difference map, an element reassigned, a new space group) can
        # carry AFIX groups whose connectivity SHELXL refuses - and it
        # then aborts the whole job instead of refining (ka1
        # cage-tools-r1: 8 of 16 tool failures, six add_hydrogens(exclude=
        # [...one more...]) rounds). Same rule SHELXL uses, checked here,
        # every offender named at once, and the fix is one call.
        stale = afix_connectivity_problems(
            ses.model, h_meta.get("per_carrier"), extras.get("parts"))
        if stale:
            return ToolResult.failure(_stale_afix_message(stale))
        # round-3 WP3: the restraint cards go into the .ins as written;
        # terms SHELXL will not apply (different non-zero PARTs) are named
        # in the result instead of vanishing in the .lst
        rs_specs = list(flags.get("restraints") or [])
        rs_preflight = (preflight(ses.model, rs_specs, flags)
                        if rs_specs else None)
        rs_note = preflight_applicability(rs_preflight)
        write_res(ShelxModel(
            xray_structure=ses.model,
            # None (not 0.71073): the writer then says in a REM that no
            # DISP could be generated instead of pretending Mo K-alpha
            wavelength=ses.dataset.wavelength or None,
            z=getattr(self.project, "_z", None),
            title="CrystalPilot cross-check",
            instruction_cards=cards,
            restraint_cards=emit_shelx_cards(list(flags.get("restraints") or [])),
            weights=(float(weights.get("a", 0.1)), float(weights.get("b", 0.0))),
            scale=fvar, cell_esd=getattr(self.project, "_cell_esd", None),
            h_riding=h_meta.get("per_carrier"), **extras), job / "job.ins")
        _stage_job_hkl(self.project, job)
        l_s = int(params.get("l_s", 8))
        timeout_s = int(params.get("timeout_s", 300))
        text, stdout, err = _execute_shelxl(exe, job, timeout_s)
        if err:
            return ToolResult.failure(err)
        shelxl, q_peaks, err = summarize_shelxl_job(job, text, l_s, stdout)
        if err:
            return ToolResult.failure(err)
        wght_loop: dict[str, Any] | None = None
        if mode == "adopt_wght":
            # the SHELXL-side WGHT loop; `job`/`text`/`shelxl` now describe
            # the LAST round, which is the one adopted below
            job, text, shelxl, q_peaks, wght_loop = self._converge_wght(
                exe, job, text, shelxl, q_peaks, l_s, timeout_s,
                int(params.get("wght_rounds", 4)))
        out_res = job / "job.res"
        snap = ses.last_refinement()
        engine_r1 = snap.r1_strong if snap else None
        agrees = (engine_r1 is not None
                  and abs(shelxl["r1_strong"] - engine_r1) < 0.005)
        summary: dict[str, Any] = {
            "engine": "SHELXL-2019/3 (independent)",
            "shelxl": shelxl,
            "smtbx_last_r1": engine_r1,
            "delta_r1": (round(shelxl["r1_strong"] - engine_r1, 4)
                         if engine_r1 is not None else None),
            "agrees_with_engine": agrees,
            # WP1: the check's verdict as a verdict, not a flag to dig for
            "scientific_outcome": {
                "verdict": ("supports" if agrees else
                            "inconclusive" if engine_r1 is None else "against"),
                "reasons": [("SHELXL R1 within 0.005 of the in-process engine"
                             if agrees else
                             "no in-process refinement to compare against"
                             if engine_r1 is None else
                             f"SHELXL R1 differs from the in-process engine "
                             f"by {shelxl['r1_strong'] - engine_r1:+.4f}")],
                "measured_by": "independent SHELXL R1 vs smtbx R1 "
                               "(|delta| < 0.005)"},
            "mask_exported": f_mask is not None,
            "job_dir": str(job),
            **({"restraints_preflight": rs_preflight} if rs_preflight else {}),
            **({"applicability": rs_note} if rs_note else {}),
            **({"wght_loop": wght_loop} if wght_loop else {}),
        }
        if extra_cards:
            summary["extra_cards"] = {
                "applied": extra_cards, "note": extra_note,
                **({"reason": reason} if reason else {}),
                "hbond_loop_in_cif": bool(
                    (job / "job.cif").exists()
                    and "_geom_hbond_atom_site_label_D" in (
                        job / "job.cif").read_text(encoding="utf-8",
                                                   errors="replace")),
            }
        elif reason:
            summary["reason"] = reason
        if effective_now or replace_cards:
            summary["effective_cards"] = {
                "cards": effective_now,
                "from_earlier_jobs": applied_eff,
                "added_now": extra_cards,
                "replaced": replace_cards,
                "persisted": mode != "check",
                "note": ("in this job's .ins; on adopt they stay with the "
                         "node (node.json effective_state, model.res) and "
                         "ride into every later job until "
                         "replace_cards=true" if mode != "check" else
                         "mode=check: used for this job only, nothing "
                         "persisted")}
        if wght_loop and wght_loop.get("error"):
            summary["warning"] = wght_loop["error"]
        from .tools_parameters import occupancy_adp_correlations
        occupancy_lst = job / "job.lst"
        occupancy_correlations = occupancy_adp_correlations(
            occupancy_lst.read_text(encoding="utf-8", errors="replace") if occupancy_lst.exists() else "")
        if mode == "check":
            summary["no_state_change"] = True
            # the acceptance verdict is available WITHOUT adopting: this is
            # the cheap way to test a trial split, which is exactly what
            # the reg1-ext2 agents needed and did not have
            if ses.flags.get("disorder_groups"):
                try:
                    from ..io.shelx_model import load_res_model
                    from .nodes import disorder_from_parsed
                    p_chk = load_res_model(out_res)
                    dg_chk, _tw = disorder_from_parsed(p_chk)
                    from .tools_parameters import site_occupancy_readback
                    summary["site_occupancies"] = site_occupancy_readback(
                        p_chk.structure, dg_chk, shelxl.get("free_variables") or {}, occupancy_correlations)
                    blocks = disorder_acceptance(
                        p_chk.structure, [g for g in dg_chk if len(g["members"]) > 1], shelxl, ses,
                        shelxl["r1_strong"])
                    if blocks:
                        summary["disorder_acceptance"] = blocks
                        summary["disorder_verdict"] = \
                            _acceptance_summary(blocks)
                except Exception as e:  # noqa: BLE001 - advisory block
                    summary["disorder_acceptance_error"] = str(e)
            if q_peaks["sites"]:
                summary["q_peaks"] = {
                    "top": [{"q": i + 1, "site": [round(x, 4) for x in s],
                             "height": h}
                            for i, (s, h) in enumerate(zip(
                                q_peaks["sites"][:8], q_peaks["heights"][:8]))],
                    "note": ("SHELXL's residual peaks for ITS refined copy "
                             "of the model - not made the session's peak "
                             "table because the session model did not "
                             "move. mode='adopt' stores them as the peak "
                             "table (peak_indices for "
                             "add_atoms_from_difference_map); inspect_map "
                             "computes the in-process map of the current "
                             "model."),
                }
            return ToolResult(ok=True, summary=summary)

        # adopt: SHELXL-refined model becomes the session model
        parsed = load_res_model(out_res)
        xs = parsed.structure
        xs.scattering_type_registry(table="it1992")
        ses.model = xs
        ses.flags["afix_groups"] = parsed.afix_groups
        if parsed.afix_groups:
            summary["afix_groups_preserved"] = len(parsed.afix_groups)
        ses.flags["weights"] = {"a": parsed.weights[0], "b": parsed.weights[1]}
        if parsed.scale:
            ses.flags["scale_k"] = float(parsed.scale) ** 2
        # WP2: the cards this job refined with are now the model's
        if effective_now:
            ses.flags["effective_cards"] = list(effective_now)
            ses.flags["effective_cards_job"] = job.name
        else:
            ses.flags.pop("effective_cards", None)
            ses.flags.pop("effective_cards_job", None)
        # SHELXL refined the free variables (disorder occupancies) and BASF:
        # refresh the linkage metadata from what it wrote back
        from .nodes import disorder_from_parsed, loose_parts_from_parsed
        dg, twin = disorder_from_parsed(parsed)
        if dg or ses.flags.get("disorder_groups"):
            ses.flags["disorder_groups"] = dg
        loose = loose_parts_from_parsed(parsed, dg)
        if loose or ses.flags.get("parts_extra"):
            ses.flags["parts_extra"] = loose
        if twin or ses.flags.get("twin"):
            if twin:
                ses.flags["twin"] = twin
            summary["twin_basf_refined"] = (twin or {}).get("basf")
        if dg:
            from .tools_parameters import site_occupancy_readback
            summary["site_occupancies"] = site_occupancy_readback(
                ses.model, dg, shelxl.get("free_variables") or {}, occupancy_correlations)
            summary["disorder_occupancies"] = {
                f"fvar{g['fvar_index']}": round(g["value"], 4) for g in dg}
            # T1.6: the value alone decides nothing. Attach the refined
            # s.u. + verdict to each group record (so checkout, node.json
            # and inspect_model all carry it) and report the block.
            fvs = shelxl.get("free_variables") or {}
            for g in dg:
                value = fvs.get(f"fvar{g['fvar_index']}")
                if len(g["members"]) == 1 and value:
                    g["free_variable"] = {**value, "measured_by": job.name}
            split_groups = [g for g in dg if len(g["members"]) > 1]
            blocks = disorder_acceptance(ses.model, split_groups, shelxl, ses,
                                         shelxl["r1_strong"])
            for g, blk in zip(split_groups, blocks):
                if "free_variable" in blk:
                    # provenance: the in-process refine holds occupancies
                    # fixed, so this value/s.u. stays valid until the NEXT
                    # SHELXL job - naming the job that measured it keeps a
                    # later reader from mistaking it for a live number
                    g["free_variable"] = {**blk["free_variable"],
                                          "measured_by": job.name}
                    g["verdict"] = blk.get("verdict")
            ses.flags["disorder_groups"] = dg
            if blocks:
                summary["disorder_acceptance"] = blocks
                summary["disorder_verdict"] = _acceptance_summary(blocks)
            if not fvs:
                summary["disorder_note"] = (
                    "SHELXL printed no free-variable esd for this job "
                    "(l_s = 0 refines nothing): the occupancies above are "
                    "the values it ran with, not a measurement. Re-run with "
                    "l_s >= 4 before judging any split.")
        ses.flags.pop("h_constraints", None)
        if parsed.h_riding and not self.project._h_replay_is_lossless(
                ses.model, parsed):
            # split-occupancy / special-AFIX H: re-placement would silently
            # drop them - keep the SHELXL model's H verbatim, same policy
            # as checkout/import (process-audit T3: replay loss hit 10+
            # campaigns, up to 183 H in one adopt)
            ses.flags["h_riding_meta"] = {
                "per_carrier": parsed.h_riding,
                "elements": sorted({g["carrier"][:1].upper()
                                    for g in parsed.h_riding})}
            summary["h_note"] = (
                f"kept {sum(len(g.get('h', [])) for g in parsed.h_riding)} "
                f"H verbatim (split/special H present - replay would lose "
                f"them); AFIX groups preserved for SHELX round-trip, "
                f"in-process refine treats H as free atoms")
        elif parsed.h_riding:
            # re-derive in-process riding constraints for exactly the H the
            # SHELXL model carries: per-carrier replace, count-mismatch
            # detection, labels kept and never aliased (see replay_riding_h
            # for the hex-l2-r2 duplicate / resurrected-H failures and the
            # pa2 cage-l0-r2 doubled-label failure this replaces)
            summary.update(replay_riding_h(
                self.project.registry, self.project.ctx, ses,
                parsed.h_riding))
        if q_peaks["sites"]:
            # SHELXL's Q peaks become the session's difference-map table:
            # same row shape as refine's (site, height, nearest atom), so
            # add_atoms_from_difference_map(peak_indices) indexes them and
            # the node commit saves them (peaks.json)
            from ..tools.refinement_tools import annotate_peaks
            ses.flags["diff_map_peaks"] = annotate_peaks(
                ses.model, q_peaks["sites"], q_peaks["heights"])
            summary["diff_map_peaks"] = ses.flags["diff_map_peaks"][:8]
            summary["diff_map_max"] = q_peaks["max"]
            summary["diff_map_min"] = q_peaks["min"]
            summary["peak_table_note"] = (
                f"{len(q_peaks['sites'])} SHELXL Q peaks are now the "
                f"session's peak table (index = Q number - 1); saved with "
                f"the node, restored by checkout/branch")
        from ..pipeline.session import RefinementSnapshot
        ses.refinement_history.append(RefinementSnapshot(
            label="shelxl_adopt", r1_strong=shelxl["r1_strong"],
            r1_all=shelxl["r1_all"], wr2=shelxl["wr2"], goof=shelxl["goof"],
            n_params=shelxl.get("n_params", -1),
            n_reflections=shelxl.get("n_reflections", -1),
            diff_map_max=q_peaks["max"], diff_map_min=q_peaks["min"],
            flack=shelxl.get("flack"), flack_su=shelxl.get("flack_su")))
        try:
            used_model = load_res_model(job / "job.ins")
            used_weights = shelxl.get("wght_used") or used_model.weights
            measured_conditions = {
                "definition": "shelxl-r-factors-v1",
                "weights": {"a": float(used_weights[0]), "b": float(used_weights[1])},
                "applied_cards": list(used_model.data_cards or []), "cutoff_application": "applied",
                "mask_used": bool(used_model.uses_abin),
                "experiment": {"temperature_K": used_model.temperature_K,
                               "crystal_size": used_model.crystal_size}}
        except (OSError, ValueError, RuntimeError):
            measured_conditions = {"definition": None, "weights": None,
                                   "applied_cards": None, "cutoff_application": "unknown", "mask_used": None}
        ses._crystalpilot_shelxl_measurement = {
            "engine": "SHELXL", "job": job.name, "limited": False, **measured_conditions}

        summary["adopted"] = True
        # ses.model, not xs: the riding replay / verbatim rescue above may
        # have replaced the structure object
        summary["n_atoms"] = ses.model.scatterers().size()
        return ToolResult(ok=True, summary=summary)

    def _new_job_dir(self, tag: str = "", base_name: str = "") -> Path:
        """Fresh job directory. The old second-resolution name let two
        jobs within one second share a directory (the WGHT loop on a small
        structure runs SHELXL in well under a second). Loop rounds pass
        round 0's name as base_name so the family reads as one job:
        job_<stamp>, job_<stamp>_w1, job_<stamp>_w2 ..."""
        base = self.project.dir / ".crystalpilot" / "refine" / "shelxl"
        name = ((base_name or time.strftime("job_%Y%m%d_%H%M%S"))
                + (f"_{tag}" if tag else ""))
        job = base / name
        n = 0
        while job.exists():
            n += 1
            job = base / f"{name}_{n}"
        job.mkdir(parents=True, exist_ok=True)
        return job

    def _converge_wght(self, exe: Path, job: Path, text: str,
                       shelxl: dict[str, Any], q_peaks: dict[str, Any],
                       l_s: int, timeout_s: int, rounds: int) -> tuple[
                           Path, str, dict[str, Any], dict[str, Any],
                           dict[str, Any]]:
        """mode='adopt_wght': the .res -> .ins WGHT loop, SHELXL-side.

        Round 0 is the job just run from the session. Every further round
        copies the previous job's .res (refined atoms, FVARs, cards, ABIN)
        into a new job with SHELXL's suggested WGHT as the used one, until
        wght_agrees() or `rounds` extra jobs. The model is never
        re-serialized from the session in between (no riding replay, no
        label drift), and the LAST job is the one adopted, so write_outputs
        finds a SHELXL job matching the node exactly. A failed round stops
        the loop: the last completed round is still adopted and the error
        goes into the summary (partial convergence beats none, and the
        agent sees the message). pa1 agents did this loop by hand (2-3
        set_weights + run_shelxl pairs per delivery) or never did it -
        GooF 1.5-1.7 in several deliveries."""
        rounds = max(0, min(int(rounds), 10))
        history = [_wght_row(0, shelxl)]
        error: str | None = None
        round0 = job.name
        for n in range(1, rounds + 1):
            if shelxl.get("wght_converged") or not shelxl.get("suggested_wght"):
                break
            nxt = self._new_job_dir(f"w{n}", base_name=round0)
            try:
                ins = next_round_ins_text(text, shelxl["suggested_wght"])
            except ValueError as e:
                error = f"WGHT round {n} not started: {e}"
                break
            (nxt / "job.ins").write_text(ins, encoding="ascii",
                                         errors="replace")
            _stage_job_hkl(self.project, nxt, source=job / "job.hkl")
            if (job / "job.fab").exists():
                # the mask coefficients of the previous round, unchanged:
                # a hard link, not a second 3 MB copy
                _link_or_copy(job / "job.fab", nxt / "job.fab", immutable=[job / "job.fab"])
            text2, stdout2, err = _execute_shelxl(exe, nxt, timeout_s)
            if err:
                error = f"WGHT round {n} failed: {err}"
                break
            shelxl2, q2, err = summarize_shelxl_job(nxt, text2, l_s, stdout2)
            if err:
                error = f"WGHT round {n} failed: {err}"
                break
            job, text, shelxl, q_peaks = nxt, text2, shelxl2, q2
            history.append(_wght_row(n, shelxl))
        used = shelxl.get("wght_used") or [0.0, 0.0]
        sug = shelxl.get("suggested_wght") or used
        converged = bool(shelxl.get("wght_converged"))
        n_extra = len(history) - 1
        if converged:
            note = (f"WGHT converged after {n_extra} extra SHELXL round(s): "
                    f"{used[0]:g} {used[1]:g} (GooF {shelxl['goof']:.3f}, "
                    f"R1 {shelxl['r1_strong']:.4f}); adopted into the "
                    f"session with the refined model")
        else:
            note = (f"WGHT still moving after {n_extra} extra round(s) "
                    f"(used {used[0]:g} {used[1]:g} -> suggested {sug[0]:g} "
                    f"{sug[1]:g}); the last completed round is adopted - "
                    f"run mode='adopt_wght' again (more wght_rounds or "
                    f"l_s) or accept it and disclose")
        loop: dict[str, Any] = {"history": history, "rounds_run": n_extra,
                                "converged": converged, "note": note}
        if error:
            loop["error"] = error
        # drop the wght_note of the final round: the loop note above says
        # what happened; a leftover 'run adopt_wght' pointer would send
        # the agent in a circle
        if converged:
            shelxl.pop("wght_note", None)
        return job, text, shelxl, q_peaks, loop


# ==========================================================================

#: SHELX instruction cards - a line starting with one of these is never an
#: atom, whatever its field count (TWIN's nine matrix numbers, SIMU's
#: three esds...)
SHELX_INSTRUCTIONS = frozenset({
    "TITL", "CELL", "ZERR", "LATT", "SYMM", "SFAC", "UNIT", "TEMP",
    "SIZE", "L.S.", "CGLS", "BOND", "CONF", "ACTA", "FMAP", "PLAN",
    "WGHT", "FVAR", "HKLF", "END", "REM", "MORE", "AFIX", "PART",
    "DFIX", "DANG", "SADI", "SAME", "FLAT", "SIMU", "DELU", "RIGU",
    "ISOR", "EADP", "EXYZ", "SUMP", "TWIN", "BASF", "MERG", "OMIT",
    "SHEL", "EQIV", "HTAB", "MPLA", "RTAB", "ABIN", "LIST", "EXTI",
    "SWAT", "ANIS", "GRID", "SPEC", "STIR", "DISP", "RESI", "BIND",
    "FREE", "MOLE", "EGCF",
})


def _scan_shelx_atoms(text: str) -> tuple[list[tuple[str, str]], list[float]]:
    """([(label, element)], fvar_floats) from SHELX ins/res text: every
    atom line after FVAR up to HKLF/END, the element read from the SFAC
    table ('?' when the SFAC index points outside it)."""
    sfac: list[str] = []
    fvar: list[float] = []
    rows: list[tuple[str, str]] = []
    in_atoms = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        head = line.split()[0].upper()
        if head == "SFAC":
            sfac.extend(t.capitalize() for t in line.split()[1:]
                        if not any(c.isdigit() for c in t) or t.isalpha())
            continue
        if head == "FVAR":
            for t in line.split()[1:]:
                try:
                    fvar.append(float(t))
                except ValueError:
                    pass
            in_atoms = True
            continue
        if head in SHELX_INSTRUCTIONS or head.startswith("REM"):
            if head == "HKLF" or head == "END":
                break
            continue
        f = line.split()
        if len(f) >= 6 and in_atoms:
            try:
                sfac_i = int(f[1])
                float(f[2]); float(f[3]); float(f[4])
            except ValueError:
                continue
            rows.append((f[0], sfac[sfac_i - 1]
                         if 1 <= sfac_i <= len(sfac) else "?"))
    return rows, fvar


def _shelx_atom_stats(text: str) -> tuple[int, int, list[float]]:
    """(n_atoms, n_hydrogens, fvar_floats) from SHELX ins/res text.

    The delivery three-way audit (practice-770 rounds 4-7 did it by hand):
    a 'matching' SHELXL job must agree with the node model on atom count,
    H count and free variables - R1 proximity alone let a 20-cycle check
    job with SHELXL-moved FVARs masquerade as the node's state.
    """
    rows, fvar = _scan_shelx_atoms(text)
    return len(rows), sum(1 for _lbl, el in rows if el == "H"), fvar


def _shelx_atom_rows(text: str) -> list[tuple[str, str]]:
    """[(label, element)] of every atom line in SHELX ins/res text, in
    file order - the label/element leg of the delivery pairing (a job
    whose atoms were retyped or relabelled afterwards is not the node's
    job even when every count still agrees)."""
    return _scan_shelx_atoms(text)[0]


def _res_zerr_z(text: str) -> int | None:
    """Z from a SHELX res/ins ZERR card (None when absent/unparsable)."""
    m = re.search(r"^\s*ZERR\s+(\d+)", text, re.M)
    return int(m.group(1)) if m else None


def rescue_lost_h(ses, parsed_h_riding: list[dict],
                  h_snapshot: dict[str, dict[str, Any]],
                  lost: list[str]) -> dict[str, Any]:
    """Carrier-level verbatim rescue for H the riding replay dropped.

    The old behaviour on adopt was drop-and-warn, forcing a manual
    rebuild loop every time the H classifier drifted (process-audit T3:
    r18 H11 five-round oscillation, r20 C11 recurring, r22 both arms,
    up to 183 H in one r12 adopt). Instead: for every carrier that lost
    any H, remove whatever the replay DID place for it and restore the
    SHELXL model's H verbatim (positions from h_snapshot), so each
    carrier's group stays internally consistent; the parsed AFIX groups
    re-enter h_riding_meta so SHELX jobs keep riding semantics. Free
    (non-riding) H that vanished are restored individually. In-process
    constraints are cleared (indices were invalidated by the edit).
    Returns the summary fields to merge."""
    from cctbx import xray
    from cctbx.array_family import flex

    lost_set = {l.upper() for l in lost}
    rescue_groups = [g for g in parsed_h_riding
                     if any(h.upper() in lost_set for h in g.get("h", []))]
    rescued_carriers = {g["carrier"].upper() for g in rescue_groups}
    affected_h = {h.upper() for g in rescue_groups for h in g.get("h", [])}
    grouped = {h.upper() for g in parsed_h_riding for h in g.get("h", [])}
    affected_h |= {h for h in lost_set if h not in grouped}
    # whatever the replay DID place on a rescued carrier goes too, by the
    # replay's OWN labels: in hex-l2-r2 rename_atoms had turned H4 into
    # H4A, the replay re-placed 'H4', the label-keyed removal below missed
    # it and the verbatim H4A landed next to it - six duplicated riding H,
    # 26 -> 32 atoms, in a delivery
    meta_now = ses.flags.get("h_riding_meta") or {}
    for g in (meta_now.get("per_carrier") or []):
        if str(g.get("carrier", "")).upper() in rescued_carriers:
            affected_h |= {str(h).upper() for h in g.get("h", [])}

    keep = flex.bool(
        [not (sc.scattering_type.strip().capitalize() == "H"
              and sc.label.upper() in affected_h)
         for sc in ses.model.scatterers()])
    ses.model = ses.model.select(keep)
    restored: list[str] = []
    for lbl in sorted(affected_h):
        snap = h_snapshot.get(lbl)
        if snap is None:
            continue
        ses.model.add_scatterer(xray.scatterer(
            label=snap["label"], site=snap["site"], u=snap["u_iso"],
            occupancy=snap["occupancy"], scattering_type="H"))
        restored.append(snap["label"])
    meta = ses.flags.get("h_riding_meta") or {}
    pc = [g for g in (meta.get("per_carrier") or [])
          if g.get("carrier", "").upper() not in rescued_carriers]
    pc += rescue_groups
    meta["per_carrier"] = pc
    ses.flags["h_riding_meta"] = meta
    ses.flags.pop("h_constraints", None)

    out: dict[str, Any] = {
        "h_replay_rescued": {"h": restored,
                             "carriers": sorted(rescued_carriers)},
        "h_replay_note": (
            f"riding replay could not re-derive {len(lost)} H (classifier "
            f"drift); their carriers' H were restored VERBATIM from the "
            f"SHELXL model - SHELX jobs keep the AFIX riding, in-process "
            f"refine treats them as free atoms (run add_hydrogens with "
            f"explicit params to re-derive in-process riding if needed)"),
    }
    still_lost = sorted(lost_set - {r.upper() for r in restored})
    if still_lost:
        out["h_replay_lost"] = still_lost
        out["h_replay_warning"] = (
            f"{len(still_lost)} H could not be restored from the SHELXL "
            "model either - do NOT deliver without resolving")
    return out


def _h_labels(model) -> set[str]:
    return {sc.label.upper() for sc in model.scatterers()
            if sc.scattering_type.strip().capitalize() == "H"}


def _frac_dist(uc, a, b) -> float:
    d = [x - y - round(x - y) for x, y in zip(a, b)]
    return float(uc.length(d))


def _restrict_replay_params(model, parsed_groups: list[dict],
                            h_params: dict[str, Any]) -> dict[str, Any]:
    """add_hydrogens parameters that re-derive H ONLY on carriers the
    loaded model already protonates.

    A replay must rebuild riding constraints for the H that exist, not
    re-run the protonation decision: hex-l2-r2 deleted the O5-H (edit_atoms,
    U 0.21 ghost) and the next adopt brought it back because the stored
    force_kind still named O5; a model with freshly added carbons would
    get H the agent never asked for. Stale force_kind/exclude labels
    (renamed or deleted atoms) are dropped too - add_hydrogens refuses
    unknown labels, and until it validated before stripping, that refusal
    left the model with no H at all (hex-l2-r2 first adopt: all 7 H
    'rescued' and blamed on classifier drift)."""
    p = dict(h_params)
    elems = [str(e).capitalize() for e in (p.get("elements") or ["C"])]
    carriers = {str(g.get("carrier", "")).upper() for g in parsed_groups}
    labels = {sc.label.upper(): sc.scattering_type.strip().capitalize()
              for sc in model.scatterers()}
    p["elements"] = elems
    p["force_kind"] = {str(k).upper(): v
                       for k, v in (p.get("force_kind") or {}).items()
                       if str(k).upper() in carriers}
    exclude = {str(x).upper() for x in (p.get("exclude") or [])
               if str(x).upper() in labels}
    exclude |= {lbl for lbl, el in labels.items()
                if el in elems and el != "H" and lbl not in carriers}
    p["exclude"] = sorted(exclude)
    return p


def _apply_label_changes(ses, changed: dict[str, str]) -> None:
    """Relabel scatterers in place and keep every label-keyed flag in
    step (riding meta, live constraint checks, PART membership) - the
    same bookkeeping rename_atoms does."""
    from .nodes import _apply_rename_to_disorder, _apply_rename_to_h_meta
    up = {k.upper(): v for k, v in changed.items()}
    for sc in list(ses.model.scatterers()):
        new = up.get(sc.label.upper())
        if new is not None:
            sc.label = new
    ren = dict(changed)
    ren.update(up)
    if ses.flags.get("afix_groups"):
        from .nodes import _apply_rename_to_afix_groups
        ses.flags["afix_groups"] = _apply_rename_to_afix_groups(ses.flags["afix_groups"], ren)
    meta = ses.flags.get("h_riding_meta")
    if meta:
        ses.flags["h_riding_meta"] = _apply_rename_to_h_meta(meta, ren)
    for con in (ses.flags.get("h_constraints") or []):
        checks = getattr(con, "checks", None)
        if checks:
            con.checks = [(i, ren.get(lbl, ren.get(lbl.upper(), lbl)))
                          for i, lbl in checks]
    if ses.flags.get("disorder_groups"):
        ses.flags["disorder_groups"] = _apply_rename_to_disorder(
            ses.flags["disorder_groups"], ren)
    if ses.flags.get("parts_extra"):
        ses.flags["parts_extra"] = {
            str(ren.get(l, ren.get(str(l).upper(), l))).upper(): p
            for l, p in ses.flags["parts_extra"].items()}


def _relabel_replayed_h(ses, parsed_groups: list[dict],
                        h_snapshot: dict[str, dict[str, Any]],
                        skip: set[str]) -> int:
    """Give re-derived H the labels the loaded model used (same carrier,
    same H count, nearest position wins). add_hydrogens names H after the
    carrier ('H4'); without this every adopt/checkout undid rename_atoms'
    canonical labels ('H4A') and that label churn is what made the
    hex-l2-r2 replay call re-derived H 'lost'."""
    meta = ses.flags.get("h_riding_meta") or {}
    parsed_of = {str(g.get("carrier", "")).upper(): list(g.get("h", []))
                 for g in parsed_groups}
    uc = ses.model.unit_cell()
    site_of = {sc.label.upper(): tuple(sc.site)
               for sc in ses.model.scatterers()}
    changed: dict[str, str] = {}
    for g in (meta.get("per_carrier") or []):
        c = str(g.get("carrier", "")).upper()
        old = parsed_of.get(c)
        new = [str(h) for h in g.get("h", [])]
        if c in skip or not old or len(old) != len(new):
            continue
        if [h.upper() for h in old] == [h.upper() for h in new]:
            continue
        own = {h.upper() for h in new}
        remaining = list(old)
        pairs: list[tuple[str, str]] = []
        for nl in new:
            s_new = site_of.get(nl.upper())
            if s_new is None or not remaining:
                pairs = []
                break
            best = min(remaining, key=lambda ol: _frac_dist(
                uc, s_new, (h_snapshot.get(ol.upper()) or {}).get(
                    "site", s_new)))
            remaining.remove(best)
            pairs.append((nl, best))
        for nl, ol in pairs:
            if nl.upper() == ol.upper():
                continue
            if ol.upper() in site_of and ol.upper() not in own:
                continue            # that label belongs to another atom now
            changed[nl] = ol
    if changed:
        _apply_label_changes(ses, changed)
    return len(changed)


def replay_riding_h(registry, ctx, ses, parsed_groups: list[dict],
                    h_params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rebuild in-process riding constraints for the H of a freshly loaded
    model (run_shelxl adopt, node checkout) WITHOUT changing which atoms
    exist. Idempotent per carrier: the H a carrier already has are
    replaced by the re-derived set, never duplicated, never resurrected
    on carriers whose H were deleted, and they keep the loaded model's
    labels. Returns the summary fields to merge (h_replay counts + note,
    plus rescue_lost_h's fields when a carrier had to be kept verbatim).

    What it replaces (hex-l2-r2, pa1): a label-keyed replay that (a)
    counted relabelled H as lost and rescued them verbatim NEXT TO the
    re-derived ones (26 -> 32 atoms in the delivery, 'ZERR 3 vs cif 1'
    coherence loop), (b) re-protonated a deliberately deleted O-H from a
    stale force_kind, and (c) when add_hydrogens refused a stale label it
    had already stripped every H, so all of them came back 'rescued' under
    a 'classifier drift' explanation.

    Label discipline (pa2 cage-l0-r2, n0101 -> n0102 and n0106 -> n0107):
    everything below - the count check, rescue_lost_h's removal, the
    relabelling - identifies an H by its label, so a label must mean the
    same atom before and after the add_hydrogens call. add_hydrogens names
    multi-H groups on 4-character carriers by sequence (H1, H2 ...) and
    would happily give C03P the 'H1'/'H2' that were C03C's H in the loaded
    model; after SHELXL's 25 cycles moved that cage, six CH2 carriers read
    as aromatic CH and the sequence shifted onto other carriers' labels.
    rescue_lost_h then deleted the 'lost' H1..H8 - by then C03P/C03Q/C03R/
    C04S's fresh H - and restored the verbatim ones under labels the
    surviving replay entries still named: 28 -> 20 H, eleven labels
    written twice, every later checkout dead in iotbx's duplicate-label
    error. The loaded model's H labels are therefore RESERVED for the
    add_hydrogens call (_reserve_labels): fresh H never alias them, and a
    carrier whose re-derived H count differs from the loaded model's in
    EITHER direction keeps the loaded H verbatim (an adopt/checkout must
    reproduce exactly the H the file carries - n0131 -> n0132 gained an H
    on adopt and write_outputs then refused the job: 'H 31 vs node 32')."""
    from ..tools.base import invoke

    meta_before = dict(ses.flags.get("h_riding_meta") or {})
    agent_params = (dict(meta_before.get("params") or {}) if h_params is None
                    else dict(h_params))
    params = dict(agent_params)
    elem_of = {sc.label.upper(): sc.scattering_type.strip().capitalize()
               for sc in ses.model.scatterers()}
    if not params.get("elements"):
        params["elements"] = sorted(
            {elem_of.get(str(g.get("carrier", "")).upper(), "C")
             for g in parsed_groups} & {"C", "N", "O"}) or ["C"]
        agent_params.setdefault("elements", params["elements"])
    h_snapshot: dict[str, dict[str, Any]] = {}
    for sc in ses.model.scatterers():
        if sc.scattering_type.strip().capitalize() == "H":
            h_snapshot[sc.label.upper()] = {
                "label": sc.label, "site": tuple(sc.site),
                "u_iso": float(sc.u_iso), "occupancy": float(sc.occupancy)}
    n_before = len(h_snapshot)
    carriers = {str(g.get("carrier", "")).upper() for g in parsed_groups}
    params = _restrict_replay_params(ses.model, parsed_groups, params)
    # the loaded model's H labels stay off limits for the fresh H: every
    # step below matches old and new H by label (see the docstring)
    params["_reserve_labels"] = sorted(h_snapshot)

    def _restore_params() -> None:
        # the stored params stay the AGENT's last add_hydrogens call, not
        # this replay's derived exclude list
        meta = ses.flags.get("h_riding_meta")
        if isinstance(meta, dict):
            meta["params"] = dict(agent_params)

    res = invoke(registry, ctx, "add_hydrogens", params)
    out: dict[str, Any] = {}
    if not res.ok:
        # a failed add_hydrogens has stripped every H before refusing -
        # the loaded model's H all come back verbatim
        out.update(rescue_lost_h(ses, parsed_groups, h_snapshot,
                                 sorted(h_snapshot)))
        _restore_params()
        out["h_replay"] = {"replaced": 0, "added": 0,
                           "kept_verbatim": n_before, "relabelled": 0,
                           "n_h_before": n_before,
                           "n_h_after": len(_h_labels(ses.model)),
                           "failed": res.error}
        out["h_replay_note"] = (
            f"riding replay FAILED ({res.error}); all {n_before} H of the "
            f"loaded model were restored verbatim - SHELX jobs keep their "
            f"AFIX riding, in-process refine treats them as free atoms; run "
            f"add_hydrogens explicitly to rebuild riding constraints")
        return out
    meta_after = ses.flags.get("h_riding_meta") or {}
    replayed = {str(g.get("carrier", "")).upper(): list(g.get("h", []))
                for g in (meta_after.get("per_carrier") or [])}
    # a carrier whose re-derived H count differs from the loaded model's
    # (fewer OR more: the classifier read the moved geometry differently)
    # keeps the loaded H verbatim - the replay must reproduce the file's
    # H set, not re-decide it
    mismatch: list[str] = []
    lost_labels: list[str] = []
    for g in parsed_groups:
        c = str(g.get("carrier", "")).upper()
        if len(replayed.get(c, [])) != len(g.get("h", [])):
            mismatch.append(c)
            lost_labels.extend(g.get("h", []))
    grouped = {h.upper() for g in parsed_groups for h in g.get("h", [])}
    h_now = _h_labels(ses.model)
    free_lost = sorted(l for l in h_snapshot
                       if l not in grouped and l not in h_now)
    n_replaced = sum(len(hs) for c, hs in replayed.items()
                     if c in carriers and c not in mismatch)
    n_added = sum(len(hs) for c, hs in replayed.items() if c not in carriers)
    if mismatch or free_lost:
        out.update(rescue_lost_h(ses, parsed_groups, h_snapshot,
                                 lost_labels + free_lost))
    relabelled = _relabel_replayed_h(ses, parsed_groups, h_snapshot,
                                     set(mismatch))
    # Rebuilding constraints is not a refinement: adopt/checkout must keep
    # the loaded coordinates, including SHELXL's refined methyl torsion.
    # Matching H counts alone previously let a valid R1 accompany a different
    # model (Astra org: final.res LS0 0.0381 vs source/CIF 0.0264).
    preserved = 0
    for sc in ses.model.scatterers():
        snap = h_snapshot.get(sc.label.upper())
        if snap is not None and sc.scattering_type.strip().capitalize() == "H":
            sc.site = snap["site"]
            sc.u_iso = snap["u_iso"]
            sc.occupancy = snap["occupancy"]
            preserved += 1
    original_groups = {str(g.get("carrier", "")).upper(): g for g in parsed_groups}
    for group in (ses.flags.get("h_riding_meta") or {}).get("per_carrier", []):
        original = original_groups.get(str(group.get("carrier", "")).upper())
        if original and "afix" in original:
            group["afix"] = original["afix"]
    out["h_coordinates_preserved"] = preserved
    _restore_params()
    n_rescued = len((out.get("h_replay_rescued") or {}).get("h") or [])
    n_after = len(_h_labels(ses.model))
    out["h_replay"] = {"replaced": n_replaced, "added": n_added,
                       "kept_verbatim": n_rescued, "relabelled": relabelled,
                       "n_h_before": n_before, "n_h_after": n_after}
    n_car = len([c for c in replayed if c in carriers and c not in mismatch])
    parts = [f"riding constraints re-derived for {n_replaced} H on {n_car} carrier(s) "
             f"(replaced in place, not duplicated); {preserved} loaded H "
             f"coordinates/ADPs/occupancies preserved; an explicit in-process "
             f"refine may re-idealize riding geometry"]
    if n_added:
        parts.append(f"{n_added} H added on carriers that had none")
    if n_rescued:
        parts.append(
            f"{n_rescued} H on {sorted(mismatch)} kept verbatim from the "
            f"loaded model (replay derived a different H count for them: "
            f"SHELX jobs keep their AFIX riding, in-process refine treats "
            f"them as free atoms)")
    if relabelled:
        parts.append(f"{relabelled} H kept the loaded model's labels")
    if n_after != n_before:
        parts.append(f"H count changed {n_before} -> {n_after}")
    out["h_replay_note"] = "; ".join(parts)
    return out


def shelx_latt_symm(sg) -> tuple[int, list[str]]:
    """SHELX LATT code + SYMM cards for a cctbx space group.

    LATT carries centring AND centricity; SYMM must list ONLY the
    representative rotation ops sg(0, 0, i) - never the centring
    translations. The old all_ops() enumeration also emitted the pure
    centring translations (e.g. X+1/2,Y+1/2,Z) as SYMM cards, which
    duplicates what LATT already declares and makes SHELXT abort with
    'produced no solution' before phasing starts - run_shelxt was dead
    on EVERY centred lattice (r22 live: 3/3 failures on Cccm; both
    campaign agents independently diagnosed the redundant SYMM by
    reading job.ins).
    """
    centring = {"P": 1, "I": 2, "R": 3, "F": 4, "A": 5, "B": 6,
                "C": 7}.get(sg.conventional_centring_type_symbol(), 1)
    latt = centring if sg.is_centric() else -centring
    seen: set[str] = set()
    symm: list[str] = []
    for i_smx in range(sg.n_smx()):
        xyz = sg(0, 0, i_smx).as_xyz()
        if xyz == "x,y,z":
            continue
        ln = "SYMM " + xyz.upper()
        if ln not in seen:
            seen.add(ln)
            symm.append(ln)
    return latt, symm


# ==========================================================================
# run_shelxt support: progress files, background jobs, process liveness
# ==========================================================================

#: SHELXT raises the dual-space iteration count of every new BATCH of tries
#: by this factor (its own schedule - the N(iter) column reads 100, 146,
#: 214, 313, 458, 671, 982, 1438 for -m100 in every job.lxt seen, whatever
#: the crystal). The estimator MEASURES the ratio from the job's own table
#: and falls back to this only while a single batch has landed.
SHELXT_ITER_GROWTH = 1.464
#: SHELXT's -x rule reaches its floor (x) at this try number
SHELXT_FLOOR_TRY = 20
#: safety factor on the estimated remaining phasing time when the phasing
#: grace extends a budget (the estimate comes from the job's own pace)
PHASING_GRACE_FACTOR = 1.5
#: background-job registry, per project: .crystalpilot/refine/shelxt/_jobs.json
SHELXT_JOBS_FILE = "_jobs.json"
#: space-group search grace: while the SHELXT process still burns CPU the
#: search grace is extended in slices, up to this multiple of search_grace_s
#: in total (2026-09-18: 18 groups of 6/mmm on a 39 A hexagonal cell took
#: 775 s with SHELXT printing nothing - a healthy search must not be killed
#: at a guessed budget, because a killed run cannot be resumed)
SEARCH_ACTIVE_EXT_FACTOR = 2.0
#: below this CPU utilisation (cores) over a poll the process counts as idle
SEARCH_ACTIVE_MIN_UTIL = 0.2
_JOBS_LOCK = threading.Lock()
#: watchdog threads of detached jobs that THIS process started or re-attached
#: (job dir -> {"thread", "job"})
_DETACHED: dict[str, dict[str, Any]] = {}


def _write_json_atomic(path: Path, obj: dict[str, Any]) -> None:
    """Write-then-rename so a reader never sees a half-written file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            # Windows: a reader may hold the target open for a moment
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _pid_alive(pid: int | None, started_at: float | None = None) -> bool:
    """Is `pid` a live process - and, when its start time is known, still
    the SAME one (pids get reused)?"""
    if not pid:
        return False
    try:
        import psutil
    except ImportError:
        psutil = None
    if psutil is not None:
        try:
            p = psutil.Process(int(pid))
            if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                return False
            if (started_at is not None
                    and abs(p.create_time() - float(started_at)) > 120):
                return False
            return True
        except psutil.Error:      # NoSuchProcess / AccessDenied (not ours)
            return False
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


class _CpuActivity:
    """Is a process still working? CPU seconds it consumed between two
    samples, per wall second (0 = idle, 1 = one core busy). None until
    two samples exist or when the process cannot be inspected."""

    def __init__(self, pid: int | None) -> None:
        self.pid = pid
        self._cpu: float | None = None
        self._t: float | None = None
        self.last_util: float | None = None

    def sample(self) -> float | None:
        if not self.pid:
            return None
        try:
            import psutil
            ct = psutil.Process(int(self.pid)).cpu_times()
            cpu = float(ct.user) + float(ct.system)
        except Exception:  # noqa: BLE001 - psutil missing / process gone
            return None
        now = time.time()
        util: float | None = None
        if self._cpu is not None and self._t is not None and now > self._t:
            util = max(0.0, cpu - self._cpu) / (now - self._t)
        self._cpu, self._t = cpu, now
        if util is not None:
            self.last_util = util
        return util


class _PidHandle:
    """Popen-like view (poll / kill / wait / pid) of a process this
    server did NOT spawn: the watchdog re-attached to a SHELXT that
    outlived the server process which started it."""

    def __init__(self, pid: int) -> None:
        import psutil
        self._psutil = psutil
        self._p = psutil.Process(int(pid))
        self.pid = int(pid)
        self.returncode: int | None = None

    def poll(self) -> int | None:
        try:
            if (self._p.is_running()
                    and self._p.status() != self._psutil.STATUS_ZOMBIE):
                return None
        except self._psutil.Error:
            pass
        if self.returncode is None:
            self.returncode = -1          # exit status unknowable here
        return self.returncode

    def kill(self) -> None:
        try:
            self._p.kill()
        except self._psutil.Error:
            pass

    def wait(self, timeout: float | None = None) -> None:
        try:
            self._p.wait(timeout)
        except self._psutil.Error:
            pass


def _jobs_update(base_dir: Path, job_name: str, **fields: Any) -> None:
    """Upsert one record in the project's background-job registry."""
    path = base_dir / SHELXT_JOBS_FILE
    with _JOBS_LOCK:
        data = _read_json(path) or {}
        jobs = [j for j in (data.get("jobs") or []) if isinstance(j, dict)]
        for j in jobs:
            if j.get("job") == job_name:
                j.update(fields)
                break
        else:
            jobs.append({"job": job_name, **fields})
        data["jobs"] = jobs[-50:]
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            _write_json_atomic(path, data)
        except OSError:
            pass


class RunShelxt(_ProjectTool):
    name = "run_shelxt"
    description = (
        "Solve the structure ab initio with the real SHELXT (dual-space "
        "phasing, then automatic space-group determination inside the Laue "
        "class) - the official tool of choice when the built-in charge "
        "flipping struggles (large cells, heavy-atom + light-atom mixtures). "
        "Needs only the cell + element list, no starting atoms. Writes a "
        "TREF job from the session cell/SFAC, runs vendor shelxt.exe, parses "
        "every candidate solution (R1/Rweak/space group) from the .lxt, and "
        "with adopt=true (default) imports the best solution as a new node "
        "- including SHELXT's space-group verdict when the cell setting is "
        "unchanged. SHELXT may propose a different space group than the "
        "current declaration: that is evidence, and it is reported either "
        "way. NOTE: SHELXT determines the group WITHIN the Laue class "
        "implied by the job's LATT/SYMM (taken from the session) - with a "
        "P-1 placeholder start it will only consider triclinic groups; "
        "settle the Laue class first (audit_reflection_data / space-group "
        "screen) when it is unknown. BUDGET: SHELXT phases in batches of "
        "-t tries (one per thread) and accepts a try once its CFOM beats "
        "x + 0.01*max(20-m, 0) (x = 0.65, m = tries done) at the end of a "
        "batch, so it usually runs 16-20 tries, and it raises the "
        "iterations per try ~1.46x every batch (the N(iter) column) - the "
        "last batch is the most expensive. A try costs seconds on a small "
        "cell and tens of seconds on a large one (e.g. -m300 on a ~20 000 "
        "A^3 cell with 4 threads: ~15-50 s per try, so 300-1000 s of "
        "phasing); n_phase_sets (-m, iterations per try) scales that "
        "linearly. NOTHING is written until phasing AND the space-group "
        "search finish: a killed run leaves no .res and cannot be resumed. "
        "Progress: every ~20 s a progress notification and the job's "
        "progress.json (stage, tries_done, best_cfom, passed_acceptance, "
        "per_try_s, estimated_remaining_s) are refreshed, and the phasing "
        "grace keeps a run alive once a try clears the CFOM floor. When "
        "blocking for minutes is inconvenient use detach=true and poll "
        "job_status. Typical sequence: run_shelxt(detach=true) -> "
        "run_shelxt(job_status=<job>) every 60-120 s -> "
        "run_shelxt(from_job=<job>) once the status says finished. Every "
        "result - solution, timeout or refusal alike - carries a "
        "solution_capability block (d_min, heaviest declared Z, "
        "completeness, tier routine/harder/no_record) stating what the "
        "physics expects of THIS data before the attempt, so a failure in "
        "the tier this platform has no record for is not read as evidence "
        "that the structure is unsolvable.")
    params_schema = {
        "type": "object",
        "properties": {
            "composition": {
                "type": "string",
                "description": "elements (optionally with per-formula "
                               "counts) e.g. 'C H N P Ni La' or "
                               "'C48 H69 La N4 Ni P2'; default: element "
                               "types already in the session model/SFAC"},
            "z": {"type": "integer",
                  "description": "formula units per cell for UNIT when "
                                 "counts are given (default 2)"},
            "adopt": {"type": "boolean", "default": True,
                      "description": "import the best solution as a new "
                                     "node (false: report only)"},
            "timeout_s": {
                "type": "integer", "default": 600,
                "description": "Wall-clock budget for SHELXT's dual-space "
                               "PHASING stage only. Once job.lxt shows "
                               "phasing finished, the space-group search "
                               "that follows is NOT cut by this budget - "
                               "it gets search_grace_s on top, because "
                               "killing a finished phasing discards the "
                               "solution. When this budget runs out while "
                               "the try table already holds a CFOM above "
                               "the acceptance floor, phasing_grace_s "
                               "extends it automatically (the run is then "
                               "certain to be accepted within a known "
                               "number of tries). A timeout reports "
                               "tries_done / best_cfom / passed_acceptance "
                               "/ per_try_s / estimated_total_s / "
                               "suggested_timeout_s from the job's own "
                               "table. Rule of thumb: ~20 tries x the "
                               "per-try time (seconds on a small cell; "
                               "e.g. -m300 on a ~20 000 A^3 cell with 4 "
                               "threads runs ~15-50 s per try = 300-1000 "
                               "s of phasing) - budget accordingly, or "
                               "use detach=true and poll job_status "
                               "instead of blocking."},
            "search_grace_s": {
                "type": "integer", "default": 900,
                "description": "Extra seconds granted to the space-group "
                               "search + element assignment AFTER phasing "
                               "has finished (default 900). The whole run "
                               "is bounded by timeout_s + phasing grace "
                               "actually used + search_grace_s; while the "
                               "SHELXT process is still consuming CPU the "
                               "search grace is extended in slices (at most "
                               "2 x search_grace_s more) instead of killing "
                               "a healthy search that cannot be resumed. "
                               "SHELXT prints nothing during the search; "
                               "with a heavy atom declared it evaluates "
                               "every group of the Laue class (-a), "
                               "10-15 min on a large hexagonal cell."},
            "phasing_grace_s": {
                "type": "integer", "default": 600,
                "description": "Automatic extension of the phasing budget "
                               "(default 600, 0 = off): when timeout_s "
                               "runs out but the try table already holds "
                               "a CFOM above SHELXT's acceptance floor "
                               "(-x, 0.65 unless the job set -x), the run "
                               "is certain to be accepted at the batch "
                               "where the bar x + 0.01*(20-m) drops below "
                               "that CFOM, so killing it would discard a "
                               "solution. The tool then keeps it running "
                               "for min(phasing_grace_s, 1.5 x remaining "
                               "time), the remaining time being estimated "
                               "from THIS job's N(iter) column and pace "
                               "and re-estimated as tries land; a "
                               "progress notification says so. Reported "
                               "as phasing_grace_used_s / phasing_note. "
                               "Only a run whose best CFOM is still below "
                               "the floor is killed at timeout_s."},
            "detach": {
                "type": "boolean", "default": False,
                "description": "Start SHELXT and return IMMEDIATELY with "
                               "{job, job_dir, pid, started_at}; SHELXT "
                               "keeps running in the background under the "
                               "same staged budget (timeout_s / "
                               "phasing_grace_s / search_grace_s, "
                               "enforced by a watchdog that also writes "
                               "the final state into progress.json). "
                               "Then poll run_shelxt(job_status=<job>) "
                               "every 60-120 s and adopt with "
                               "run_shelxt(from_job=<job>) once the "
                               "status is 'finished'. Use it instead of "
                               "blocking for minutes on a large cell. The "
                               "workbench shows the job's stage live and "
                               "after the turn ends, so you may end the turn "
                               "while it runs rather than sleep-poll. "
                               "Mutually exclusive with job_status and "
                               "from_job."},
            "job_status": {
                "type": "string",
                "description": "Do not run SHELXT: report the state of a "
                               "job (name under .crystalpilot/refine/"
                               "shelxt/ or absolute path) and return at "
                               "once - stage (starting / phasing / "
                               "phasing (grace) / space-group search / "
                               "element assignment / finished / killed / "
                               "failed), running, elapsed_s, tries_done, "
                               "best_cfom, passed_acceptance, per_try_s, "
                               "estimated_remaining_s, last_lxt_line, "
                               "has_solution and the next step. Reads "
                               "progress.json + the live job.lxt + the "
                               "process state; never waits. Works for "
                               "detached and blocking jobs alike."},
            "space_group": {
                "type": "string",
                "description": "SHELXT -s: solve in THIS space group only "
                               "(e.g. 'P 21', 'P 21/c', 'Cccm', 'Pna21' - "
                               "any Hermann-Mauguin form; must belong to "
                               "the job's Laue class and cell setting). "
                               "Skips the whole-class search: use it when "
                               "the group is already settled, or to force "
                               "a non-centrosymmetric subgroup SHELXT "
                               "keeps rejecting in favour of its "
                               "centrosymmetric parent."},
            "from_job": {
                "type": "string",
                "description": "Do not run SHELXT: adopt the solution of a "
                               "job that already finished (job directory "
                               "name under .crystalpilot/refine/shelxt/, "
                               "e.g. 'job_20260902_013028', or an absolute "
                               "path). Use it after detach=true once "
                               "job_status says finished, to import a "
                               "solution whose adoption was skipped, or "
                               "one from a previous session; the job's "
                               "cell must match the session cell. A job "
                               "that was killed before writing its .res "
                               "has nothing to adopt - the error then "
                               "says how long it ran, how far it got and "
                               "which timeout_s to re-run with."},
            "chem_quality": {
                "type": "boolean", "default": False,
                "description": "SHELXT -y: rank solutions by Chem x CC "
                               "(bond-angle 95-135 deg plausibility) "
                               "instead of CC alone. Helps metal-organic "
                               "frameworks; unsuitable for purely "
                               "inorganic structures (the angle prior is "
                               "organic-shaped)."},
            "all_space_groups": {
                "type": "boolean", "default": False,
                "description": "SHELXT -a: test EVERY space group in the "
                               "Laue class instead of the alpha-based "
                               "shortlist - use when the alpha gap is "
                               "ambiguous or the shortlist's groups all "
                               "produce poor solutions (covers -g/-h/-w). "
                               "NOTE: SHELXT turns -a on BY ITSELF when "
                               "any element heavier than Sc is expected, "
                               "so setting this false does not shorten "
                               "the search for a metal-bearing structure "
                               "- it is not a way to make a slow run "
                               "faster (verified in r25: the log said "
                               "'-a set to extend space group search "
                               "because atom heavier than Sc expected')."},
            "n_phase_sets": {
                "type": "integer", "minimum": 20, "maximum": 500,
                "description": "SHELXT -m<N>: dual-space iterations PER "
                               "TRY (the N(iter) column of the try table) "
                               "- NOT the number of phase sets or tries; "
                               "SHELXT decides how many tries it runs "
                               "(usually 16-20, until the CFOM bar is "
                               "cleared) and raises N(iter) ~1.46x every "
                               "batch by itself. Cost is linear in N: on "
                               "a ~20 000 A^3 cell with 4 threads one try "
                               "costs ~5 s at -m100 (SHELXT's default) "
                               "and ~15-50 s at -m300, i.e. 300-1000 s "
                               "of phasing (pa2: every SHELXT timeout had "
                               "N >= 300, every N = 100 call finished in "
                               "70-150 s). Leave unset unless the try "
                               "table shows 'CC fine but map is garbage'; "
                               "a timeout's suggested_n_phase_sets says "
                               "how far to LOWER it to fit a budget - "
                               "raising it never fixes a timeout. Values "
                               "above 500 are clamped to 500 and "
                               "reported."},
            "solve_resolution": {
                "type": "number", "minimum": 0.5, "maximum": 3.0,
                "description": "SHELXT -d<dmin>: truncate the noisiest "
                               "shells FOR SOLVING ONLY (official advice "
                               "for problem structures; SHELXT default "
                               "0.8). Phasing may use harsher cuts than "
                               "refinement ever should - after adopting "
                               "a solution, refine against the FULL "
                               "data again. (Do NOT copy this habit to "
                               "solve_superflip: charge flipping "
                               "degrades badly under truncation.)"},
        },
    }

    @staticmethod
    def _cli_flags(params: dict, cores: int = 0) -> list[str]:
        """Translate typed ladder params into SHELXT CLI flags."""
        flags: list[str] = []
        if cores > 0:
            # SHELXT sizes its thread pool from the MACHINE ("use 5 or max
            # available"), which is not the same as the cores it is
            # allowed to run on: r25 logged "32 threads running in
            # parallel" inside a 4-core affinity mask at BelowNormal.
            # Oversubscribing a pinned budget 8:1 buys nothing and costs
            # wall clock in exactly the phase that was timing out.
            flags.append(f"-t{cores}")
        if params.get("chem_quality"):
            flags.append("-y")
        if params.get("all_space_groups"):
            flags.append("-a")
        if params.get("n_phase_sets"):
            flags.append(f"-m{min(int(params['n_phase_sets']), SHELXT_M_CAP)}")
        if params.get("solve_resolution"):
            flags.append(f"-d{float(params['solve_resolution']):g}")
        if params.get("space_group"):
            flags.append("-s" + shelxt_space_group_name(
                str(params["space_group"])))
        return flags

    @staticmethod
    def _shelxt_command(exe: Path, flags: list[str]) -> list[str]:
        """The command line of a job (tests substitute a stand-in)."""
        return [str(exe), *flags, "job"]

    @staticmethod
    def _lxt_status(txt: str) -> dict[str, Any]:
        """Stage snapshot of a (possibly still running) SHELXT job.lxt.

        SHELXT writes, in order: the Laue group, the phasing try table
        (one row per finished try), '<n> attempts, solution <m> selected
        with best CFOM = <c>' + 'Structure solution: <t> secs' when
        phasing is done, the space-group search summary + candidate
        table, 'Assign elements and isotropic refinement <t> secs', and a
        'SHELXT finished at ... Total time' banner. Pure function; every
        field is None/empty until its line exists."""
        st: dict[str, Any] = {
            "stage": "starting", "laue": None, "tries": [],
            "best_cfom": None, "accept_x": SHELXT_ACCEPT_X,
            "phased": False, "phasing_s": None, "n_attempts": None,
            "selected_try": None, "n_groups": None, "sg_search_s": None,
            "assign_s": None, "finished": False, "total_s": None,
            "auto_a": "set to extend space group search" in txt,
            "threads": None, "started_at": None, "last_line": None,
        }
        # 'identified as' when SHELXT chose the class itself, 'set to'
        # under -s<group> - the second form was unparsed until pa2, so
        # every -s timeout was reported as 'no progress / start-up
        # problem' while SHELXT was in fact phasing
        m = re.search(r"Laue group (?:identified as|set to) number\s+(\d+):"
                      r"\s*(\S+)", txt)
        if m:
            st["laue"], st["laue_number"] = m.group(2), int(m.group(1))
            st["stage"] = "phasing"
        mm = re.search(r"Command line parameters:.*?-m(\d+)", txt)
        st["m_iter"] = int(mm.group(1)) if mm else None
        cl = re.search(r"Command line parameters:\s*(.*)", txt)
        if cl:
            st["cli"] = cl.group(1).strip()
            mx = re.search(r"-x([\d.]+)", cl.group(1))
            if mx:
                st["accept_x"] = float(mx.group(1))
            mt = re.search(r"-t(\d+)", cl.group(1))
            if mt:
                st["threads"] = int(mt.group(1))
        # the pool SHELXT actually runs = the batch size of the try table
        mt = re.search(r"(\d+) threads running in parallel", txt)
        if mt:
            st["threads"] = int(mt.group(1))
        ms = re.search(r"Started at (\d\d:\d\d:\d\d) on (\d\d \w{3} \d{4})",
                       txt)
        if ms:
            st["started_at"] = f"{ms.group(2)} {ms.group(1)}"
        head = txt.find("Try N(iter)")
        if head >= 0:
            for r in _SHELXT_TRY_ROW.finditer(txt[head:]):
                st["tries"].append({
                    "try": int(r.group(1)), "n_iter": int(r.group(2)),
                    "cc": float(r.group(3)), "r_weak": float(r.group(4)),
                    "chem": float(r.group(5)), "cfom": float(r.group(6)),
                    "best": float(r.group(7))})
        if st["tries"]:
            st["best_cfom"] = max(t["cfom"] for t in st["tries"])
        m = re.search(r"(\d+) attempts, solution\s+(\d+) selected with best "
                      r"CFOM =\s*([\d.]+)", txt)
        if m:
            st.update(phased=True, n_attempts=int(m.group(1)),
                      selected_try=int(m.group(2)),
                      best_cfom=float(m.group(3)),
                      stage="space-group search")
        m = re.search(r"Structure solution:\s*([\d.]+)\s*secs", txt)
        if m:
            st.update(phased=True, phasing_s=float(m.group(1)),
                      stage="space-group search")
        m = re.search(r"(\d+) Centrosymmetric and\s+(\d+) non-centrosymmetric "
                      r"space groups evaluated", txt)
        if m:
            st["n_groups"] = int(m.group(1)) + int(m.group(2))
        m = re.search(r"Space group determination:\s*([\d.]+)\s*secs", txt)
        if m:
            st.update(sg_search_s=float(m.group(1)),
                      stage="element assignment")
        m = re.search(r"Assign elements and isotropic refinement\s*([\d.]+)"
                      r"\s*secs", txt)
        if m:
            st["assign_s"] = float(m.group(1))
        m = re.search(r"SHELXT finished at .*Total time:\s*([\d.]+)\s*secs",
                      txt)
        if m:
            st.update(finished=True, total_s=float(m.group(1)),
                      stage="finished")
        for ln in reversed(txt.splitlines()):
            if ln.strip():
                st["last_line"] = ln.strip()[:160]
                break
        return st

    @staticmethod
    def _accept_at_try(best: float | None, x: float, n: int,
                       threads: int) -> int | None:
        """The try count at which SHELXT's -x rule accepts `best`.

        SHELXT runs tries in batches of one per thread and checks after
        each batch whether the best CFOM so far beats
        x + 0.01*max(20 - m, 0) for m = tries done; the accepting batch
        is the first one ending at m with that bar below `best`. None
        when `best` never clears the floor x."""
        if best is None or best <= x:
            return None
        t = max(1, int(threads or 1))
        m = max(t, ((int(n) + t - 1) // t) * t)
        while best <= shelxt_accept_bar(m, x):
            m += t
        return m

    @staticmethod
    def _phasing_estimate(st: dict[str, Any], elapsed: float,
                          timeout_s: int | None = None) -> dict[str, Any]:
        """Where phasing stands and what it still needs, from the job's own
        try table: nothing here is a constant of any crystal.

        - passed_acceptance: best CFOM > the -x floor (SHELXT's own rule)
        - accept_at_try: the batch end where the bar drops below best
        - per-iteration pace = elapsed x threads / sum(N(iter)) - the
          wall cost of one batch is its N(iter) times that pace, and
          SHELXT raises N(iter) every batch by a ratio measured from the
          table (SHELXT_ITER_GROWTH until two batches exist); the
          remaining time is the sum over the batches still to run
          (an in-flight batch counts in full: estimates err long)
        - suggested_timeout_s = 1.3 x estimated phasing total, rounded
          up to 60 s; suggested_n_phase_sets = the -m that fits the same
          run into timeout_s (only when a try costs > 20 s and only
          LOWER than the job's -m)"""
        tries = st.get("tries") or []
        n = len(tries)
        x = float(st.get("accept_x") or SHELXT_ACCEPT_X)
        best = st.get("best_cfom")
        t = max(1, int(st.get("threads") or 1))
        m_iter = st.get("m_iter")
        passed = best is not None and best > x
        est: dict[str, Any] = {
            "tries_done": n, "best_cfom": best, "accept_x": x,
            "bar_now": round(shelxt_accept_bar(n + 1, x), 2),
            "passed_acceptance": bool(passed), "threads": t,
            "m_iter": m_iter, "per_try_s": None, "iter_growth": None,
            "accept_at_try": None, "tries_remaining": None,
            "estimated_remaining_s": None, "estimated_total_s": None,
            "floor_reach_s": None,
            "suggested_timeout_s": None, "suggested_n_phase_sets": None,
        }
        if not n or elapsed <= 0:
            return est
        # once phasing has finished the wall clock keeps running through
        # the space-group search, so the pace must come from the phasing
        # time SHELXT logged (2026-09-18: 12 tries in 35 s were reported
        # as 72-80 s per try after 15 min of search)
        phase_wall = elapsed
        if st.get("phased") and st.get("phasing_s"):
            phase_wall = max(0.001, min(elapsed, float(st["phasing_s"])))
        per_try = phase_wall / n
        est["per_try_s"] = round(per_try, 1)
        iters = [max(1, int(tr["n_iter"])) for tr in tries]
        distinct: list[int] = []
        for v in iters:
            if not distinct or v != distinct[-1]:
                distinct.append(v)
        ratios = [b / a for a, b in zip(distinct, distinct[1:]) if a > 0]
        g = statistics.median(ratios) if ratios else SHELXT_ITER_GROWTH
        g = min(max(float(g), 1.0), 3.0)
        est["iter_growth"] = round(g, 3)
        pace = phase_wall * t / sum(iters)       # wall s per batch iteration
        last_iter = iters[-1]
        b_now = (n + t - 1) // t                 # batch the last row belongs to
        b_start = b_now if n % t else b_now + 1  # in-flight batch counts in full

        def _batches_s(b_end: int) -> float:
            return sum(pace * last_iter * g ** (b - b_now)
                       for b in range(b_start, b_end + 1))

        target = RunShelxt._accept_at_try(best, x, n, t) if passed else None
        if target is not None:
            rem = _batches_s((target + t - 1) // t)
            est.update(accept_at_try=target,
                       tries_remaining=max(0, target - n),
                       estimated_remaining_s=round(rem, 1),
                       estimated_total_s=round(elapsed + rem, 1))
            est["suggested_timeout_s"] = int(math.ceil(
                (elapsed + rem) * 1.3 / 60.0)) * 60
        elif n < SHELXT_FLOOR_TRY:
            # nothing above the floor yet: the earliest any try can be
            # accepted is the batch in which the bar reaches the floor
            rem = _batches_s((SHELXT_FLOOR_TRY + t - 1) // t)
            est["floor_reach_s"] = round(rem, 1)
        ref_total = (est["estimated_total_s"] if target is not None else
                     (elapsed + est["floor_reach_s"]
                      if est["floor_reach_s"] is not None else None))
        if timeout_s and ref_total and per_try > 20:
            m_cur = int(m_iter or 100)
            m_new = int(m_cur * float(timeout_s) / (ref_total * 1.3)) // 10 * 10
            m_new = max(20, min(m_new, m_cur))
            if m_new < m_cur:
                est["suggested_n_phase_sets"] = m_new
        return est

    @staticmethod
    def _grace_extension(est: dict[str, Any], grace_left: float,
                         poll_s: float = 2.0) -> float:
        """Seconds of phasing grace to grant now: the job's own remaining
        estimate x PHASING_GRACE_FACTOR, capped by what is left; 0 when
        no try has cleared the floor (a bigger budget is not the lever)."""
        if grace_left <= 0 or not est.get("passed_acceptance"):
            return 0.0
        rem = est.get("estimated_remaining_s")
        if rem is None:
            return 0.0
        want = max(float(rem) * PHASING_GRACE_FACTOR, 5 * poll_s, 10.0)
        return float(min(grace_left, want))

    @staticmethod
    def _phasing_verdict(st: dict[str, Any], elapsed: float,
                         limit: int | None = None,
                         phasing_grace_used: float | None = None,
                         phasing_grace_s: int | None = None) -> str:
        """What the try table says about 'is more time worth it?'."""
        tries = st["tries"]
        n = len(tries)
        if not n:
            return ("no try has completed yet - on a large cell a single "
                    "try can take minutes; rows appear as tries finish")
        est = RunShelxt._phasing_estimate(st, elapsed, timeout_s=limit)
        best = est["best_cfom"] or 0.0
        x = est["accept_x"]
        cc = max(t["cc"] for t in tries)
        rw = min(t["r_weak"] for t in tries)
        per_try = elapsed / n
        m_iter = st.get("m_iter")
        cost = ""
        if m_iter and m_iter > 100:
            cost = (f" at -m{m_iter} (iterations per try; the cost is "
                    f"linear in it - -m100 would be ~{per_try * 100 / m_iter:.0f} "
                    f"s per try)")
        stats = (f"{n} tries done, best CFOM {best:.3f} (CC {cc:.1f}, "
                 f"R(weak) {rw:.3f}), ~{per_try:.0f} s per try{cost}")
        if est["passed_acceptance"] and est["accept_at_try"]:
            msg = (f"{stats}: this CFOM already clears the floor {x:.2f} "
                   f"that applies from try {SHELXT_FLOOR_TRY} on (the bar "
                   f"is {est['bar_now']:.2f} now and drops 0.01 per try), "
                   f"so SHELXT accepts it at the end of the batch ending "
                   f"with try {est['accept_at_try']} ({est['threads']} "
                   f"tries per batch, {est['tries_remaining']} more "
                   f"tries) - ~{est['estimated_remaining_s']:.0f} s more "
                   f"at this job's own pace (N(iter) grows x"
                   f"{est['iter_growth']:.2f} per batch), so a larger "
                   f"timeout_s finishes it: timeout_s >= "
                   f"{est['suggested_timeout_s']} (estimated phasing "
                   f"total {est['estimated_total_s']:.0f} s x 1.3)")
            if est["suggested_n_phase_sets"]:
                msg += (f", or n_phase_sets={est['suggested_n_phase_sets']} "
                        f"to fit the same tries into {limit} s (fewer "
                        f"iterations per try - never raise it)")
            if phasing_grace_used:
                msg += (f". The automatic phasing grace already added "
                        f"{phasing_grace_used:.0f} s"
                        + (f" of {phasing_grace_s} s" if phasing_grace_s
                           else "") + " and ran out too")
            elif phasing_grace_s == 0:
                msg += (". phasing_grace_s=0 disabled the automatic "
                        "extension that would have kept it running")
            return msg
        msg = (f"{stats}: below the acceptance floor {x:.2f} that "
               f"applies from try {SHELXT_FLOOR_TRY} on, so more time only "
               f"buys more tries of the same kind")
        if est["floor_reach_s"] is not None:
            msg += (f" (reaching try {SHELXT_FLOOR_TRY} would take ~"
                    f"{est['floor_reach_s']:.0f} s more at this pace)")
        msg += (". Change the search instead of the budget: "
                "solve_resolution to drop the noisy shells, composition "
                "with the heavy atoms actually present, chem_quality "
                "on/off, or space_group=... once the group is known "
                "(raising n_phase_sets only makes each try slower")
        if est["suggested_n_phase_sets"]:
            msg += (f"; n_phase_sets={est['suggested_n_phase_sets']} would "
                    f"fit {SHELXT_FLOOR_TRY} tries into {limit} s")
        return msg + ")"

    @staticmethod
    def _progress_line(st: dict[str, Any], elapsed: float, budget: int,
                       grace: int, est: dict[str, Any] | None = None,
                       ext_s: float = 0.0, phasing_grace_s: int = 0,
                       search_ref: dict[str, Any] | None = None,
                       search_ext_s: float = 0.0) -> str:
        """One heartbeat: which stage, how far, how much budget is left."""
        tail = " (inside the tool, not waiting on approval)"
        if st["finished"]:
            return f"run_shelxt: SHELXT finished, importing{tail}"
        if st["sg_search_s"] is not None:
            return (f"run_shelxt: {st['n_groups'] or '?'} space groups "
                    f"evaluated in {st['sg_search_s']:.0f} s; assigning "
                    f"elements / isotropic refinement, {elapsed:.0f} s "
                    f"elapsed{tail}")
        if st["phased"]:
            ps = st["phasing_s"] or 0.0
            left = budget + ext_s + grace + search_ext_s - elapsed
            why = (" (SHELXT is silent here; -a: every group of the class "
                   "is evaluated because a heavy atom is declared)"
                   if st.get("auto_a") else
                   " (SHELXT is silent here)")
            ref = (f"; this project's earlier {search_ref['laue']} searches "
                   f"took ~{search_ref['median_s']:.0f} s"
                   if search_ref else "")
            return (f"run_shelxt: phasing FINISHED in {ps:.0f} s (CFOM "
                    f"{st['best_cfom']:.3f}, {st['n_attempts']} tries); "
                    f"space-group search over Laue class {st['laue']} "
                    f"running {max(0.0, elapsed - ps):.0f} s{why}{ref} - "
                    f"this stage is not cut by timeout_s, {left:.0f} s of "
                    f"grace left{tail}")
        if st["laue"]:
            n = len(st["tries"])
            if n:
                best = (f"best CFOM {st['best_cfom']:.3f}, bar "
                        f"{shelxt_accept_bar(n + 1, st['accept_x']):.2f} now "
                        f"(floor {st['accept_x']:.2f} from try "
                        f"{SHELXT_FLOOR_TRY})")
                if est and est.get("passed_acceptance") and est.get(
                        "accept_at_try"):
                    best += (f" - clears the floor, acceptance expected at "
                             f"try {est['accept_at_try']}")
                    if est.get("estimated_remaining_s") is not None:
                        best += f" (~{est['estimated_remaining_s']:.0f} s more)"
            else:
                best = "no try finished yet"
            budget_txt = (f"{elapsed:.0f}/{budget + ext_s:.0f} s of the "
                          f"phasing budget")
            if ext_s > 0:
                budget_txt += (f" (extended by {ext_s:.0f} s of the "
                               f"{phasing_grace_s} s phasing grace)")
            return (f"run_shelxt: phasing in Laue class {st['laue']} - "
                    f"{n} tries done, {best}, {budget_txt}{tail}")
        return (f"run_shelxt: reading data / Patterson setup, "
                f"{elapsed:.0f} s{tail}")

    @staticmethod
    def _run_staged(cmd: list[str], cwd: Path, budget_s: int, grace_s: int,
                    progress: Any = None, poll_s: float = 2.0,
                    heartbeat_s: float = 20.0, phasing_grace_s: int = 0,
                    state: dict[str, Any] | None = None,
                    on_start: Any = None) -> dict[str, Any]:
        """Run SHELXT with a STAGE-aware budget (see _watch_loop).

        timeout_s bounds the phasing stage (extended by up to
        phasing_grace_s once a try clears the CFOM floor); the moment
        job.lxt shows phasing finished, the space-group search gets
        grace_s more. on_start(pid) fires as soon as the process exists
        (detach mode reports the pid before the loop ends)."""
        out_path = cwd / "shelxt.stdout.log"
        t0 = time.time()
        with open(out_path, "wb") as out:
            # stdin=DEVNULL: never share the MCP server's stdin pipe (a
            # pending transport read on it blocks the child's start-up
            # stdin probe - the superflip 17/17 hang); hidden_popen_kwargs
            # keeps the console off the user's desktop
            proc = subprocess.Popen(
                cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=out,
                stderr=subprocess.STDOUT, **hidden_popen_kwargs())
            return RunShelxt._watch_loop(
                proc, cwd, t0, budget_s, grace_s, progress=progress,
                poll_s=poll_s, heartbeat_s=heartbeat_s,
                phasing_grace_s=phasing_grace_s, state=state,
                on_start=on_start)

    @staticmethod
    def _watch_loop(proc: Any, cwd: Path, t0: float, budget_s: int,
                    grace_s: int, progress: Any = None, poll_s: float = 2.0,
                    heartbeat_s: float = 20.0, phasing_grace_s: int = 0,
                    state: dict[str, Any] | None = None,
                    on_start: Any = None) -> dict[str, Any]:
        """Watch a running SHELXT: staged budget, phasing grace, heartbeat
        notifications and the job's progress.json.

        Every poll parses job.lxt. While phasing: past budget_s the run
        is killed UNLESS a try already clears the acceptance floor, in
        which case the budget is extended by _grace_extension (the job's
        own remaining-time estimate x 1.5, re-estimated whenever the
        extension runs out, phasing_grace_s in total). Once phased, the
        search gets grace_s beyond the (extended) phasing budget.
        progress.json is rewritten atomically on every stage / try-count
        change and every heartbeat, and a final time with stage
        finished / killed / failed, so job_status can report a job this
        loop no longer watches. Returns {returncode, elapsed, timed_out
        (None | 'phasing' | 'search'), stdout_tail, status, estimate,
        stage, error, phasing_grace_used_s, phasing_grace_granted_s,
        phasing_note, progress_json}."""
        lxt = cwd / "job.lxt"
        prog_path = cwd / "progress.json"
        out_path = cwd / "shelxt.stdout.log"
        budget_s = int(budget_s)
        grace_s = int(grace_s)
        phasing_grace_s = max(0, int(phasing_grace_s or 0))
        base: dict[str, Any] = dict(state or {})
        base.update({
            "job": cwd.name, "job_dir": str(cwd),
            "pid": getattr(proc, "pid", None),
            "started_at": datetime.fromtimestamp(t0).isoformat(
                timespec="seconds"),
            "started_at_epoch": round(float(t0), 3),
            "budget": {"timeout_s": budget_s, "search_grace_s": grace_s,
                       "phasing_grace_s": phasing_grace_s},
        })
        tail_note = " (inside the tool, not waiting on approval)"
        timed_out: str | None = None
        ext_s = 0.0                  # phasing grace granted so far
        grace_note: str | None = None
        search_ext_s = 0.0           # search grace granted beyond grace_s
        search_note: str | None = None
        search_ref: Any = "unset"    # sibling-job reference, read once
        cpu = _CpuActivity(getattr(proc, "pid", None))
        phased_at: float | None = None
        last_beat = t0
        last_key: tuple | None = None
        st: dict[str, Any] = RunShelxt._lxt_status("")
        est: dict[str, Any] = RunShelxt._phasing_estimate(st, 0.0,
                                                          timeout_s=budget_s)

        def _read_lxt() -> str:
            if not lxt.exists():
                return ""
            try:
                return lxt.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return ""

        def _used(elapsed: float) -> float:
            if phased_at is not None:
                return max(0.0, phased_at - budget_s)
            return max(0.0, elapsed - budget_s) if ext_s > 0 else 0.0

        def _write(stage: str, running: bool, elapsed: float,
                   **extra: Any) -> None:
            rec = dict(base)
            rec.update({
                "stage": stage, "running": running,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "elapsed_s": round(elapsed, 1), "laue": st.get("laue"),
                "tries_done": est["tries_done"],
                "best_cfom": est["best_cfom"],
                "accept_x": est["accept_x"], "bar_now": est["bar_now"],
                "passed_acceptance": est["passed_acceptance"],
                "per_try_s": est["per_try_s"],
                "accept_at_try": est["accept_at_try"],
                "estimated_remaining_s": (est["estimated_remaining_s"]
                                          if not st["phased"] else None),
                "phasing_finished": bool(st["phased"]),
                "phasing_grace_granted_s": round(ext_s, 1),
                "phasing_grace_used_s": round(_used(elapsed), 1),
                "phasing_note": grace_note,
                "last_lxt_line": st.get("last_line"),
                "has_solution": (cwd / "job_a.res").exists(),
                "timed_out": timed_out,
                **RunShelxt._search_outlook(
                    cwd.parent, cwd, st, elapsed,
                    reference=(None if search_ref == "unset"
                               else search_ref)),
                "search_grace_extended_s": round(search_ext_s, 1),
                "search_grace_note": search_note,
            })
            rec.update(extra)
            if running:
                rec.setdefault("next", f"poll run_shelxt(job_status="
                                       f"'{cwd.name}') again in 60-120 s")
            try:
                _write_json_atomic(prog_path, rec)
            except OSError:
                pass

        _write("starting", True, 0.0)
        if on_start is not None:
            # signalled only once progress.json exists: a detached caller
            # may query job_status the instant this returns
            try:
                on_start(getattr(proc, "pid", None))
            except Exception:  # noqa: BLE001 - best-effort signal
                pass
        try:
            while proc.poll() is None:
                now = time.time()
                elapsed = now - t0
                st = RunShelxt._lxt_status(_read_lxt())
                est = RunShelxt._phasing_estimate(st, elapsed,
                                                  timeout_s=budget_s)
                if st["phased"] and phased_at is None:
                    phased_at = elapsed
                if st["phased"] and search_ref == "unset":
                    search_ref = RunShelxt._search_reference(
                        cwd.parent, st.get("laue"),
                        RunShelxt._exhaustive_search(st), exclude=cwd.name)
                util = cpu.sample() if st["phased"] else None
                stage = st["stage"]
                if not st["phased"]:
                    if elapsed > budget_s + ext_s:
                        add = (RunShelxt._grace_extension(
                                   est, phasing_grace_s - ext_s, poll_s)
                               if phasing_grace_s > 0 else 0.0)
                        if add <= 0:
                            timed_out = "phasing"
                            break
                        ext_s += add
                        grace_note = (
                            f"best CFOM {est['best_cfom']:.4f} already "
                            f"clears SHELXT's acceptance floor "
                            f"{est['accept_x']:.2f}, acceptance expected at "
                            f"try {est['accept_at_try']} (~"
                            f"{est['estimated_remaining_s']:.0f} s more at "
                            f"this job's pace): phasing budget extended by "
                            f"{add:.0f} s instead of killing it ({ext_s:.0f} "
                            f"of {phasing_grace_s} s phasing grace granted)")
                        if progress is not None:
                            try:
                                progress("run_shelxt: " + grace_note
                                         + tail_note)
                            except Exception:  # noqa: BLE001
                                pass
                        last_beat = now
                    if ext_s > 0:
                        stage = "phasing (grace)"
                elif elapsed > budget_s + ext_s + grace_s + search_ext_s:
                    # search grace used up: a process still burning CPU
                    # is a healthy exhaustive search (SHELXT is silent
                    # here), so it gets another bounded slice; an idle
                    # one is a hang and is killed
                    add = RunShelxt._search_extension(
                        util if util is not None else cpu.last_util,
                        grace_s, search_ext_s)
                    if add <= 0:
                        timed_out = "search"
                        break
                    search_ext_s += add
                    search_note = (
                        f"search grace of {grace_s} s used up after "
                        f"{elapsed:.0f} s, but the SHELXT process is still "
                        f"working ({(util if util is not None else cpu.last_util or 0.0):.2f} cores over the last poll): "
                        f"search grace extended by {add:.0f} s instead of "
                        f"killing a search that cannot be resumed "
                        f"({search_ext_s:.0f} of at most "
                        f"{SEARCH_ACTIVE_EXT_FACTOR * max(grace_s, 60):.0f} s "
                        f"extension granted)")
                    if progress is not None:
                        try:
                            progress("run_shelxt: " + search_note
                                     + tail_note)
                        except Exception:  # noqa: BLE001
                            pass
                    last_beat = now
                key = (stage, est["tries_done"], st.get("n_groups"))
                beat = now - last_beat >= heartbeat_s
                if beat:
                    last_beat = now
                    if progress is not None:
                        try:
                            progress(RunShelxt._progress_line(
                                st, elapsed, budget_s, grace_s, est=est,
                                ext_s=ext_s, phasing_grace_s=phasing_grace_s,
                                search_ref=(None if search_ref == "unset"
                                            else search_ref),
                                search_ext_s=search_ext_s))
                        except Exception:  # noqa: BLE001 - best-effort
                            pass
                if beat or key != last_key:
                    _write(stage, True, elapsed)
                    last_key = key
                time.sleep(poll_s)
        finally:
            if proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
                try:
                    proc.wait(timeout=30)
                except Exception:  # noqa: BLE001 - kill is best-effort
                    pass
        elapsed = time.time() - t0
        st = RunShelxt._lxt_status(_read_lxt())
        est = RunShelxt._phasing_estimate(st, elapsed, timeout_s=budget_s)
        tail = ""
        try:
            tail = out_path.read_text(encoding="utf-8",
                                      errors="replace")[-600:]
        except OSError:
            pass
        rc = getattr(proc, "returncode", None)
        has_res = (cwd / "job_a.res").exists()
        used = _used(elapsed)
        error: str | None = None
        if timed_out:
            stage = "killed"
            error = RunShelxt._timeout_message(
                cwd, elapsed, budget_s,
                int(grace_s + search_ext_s) if timed_out == "search" else None,
                phasing_grace_used=(used if ext_s > 0 else None),
                phasing_grace_s=phasing_grace_s)
            nxt = ("re-run run_shelxt with the budget the error suggests "
                   "(a killed run cannot be resumed)")
        elif has_res:
            stage = "finished"
            nxt = f"run_shelxt(from_job='{cwd.name}') adopts the solution"
        else:
            stage = "failed"
            error = (f"SHELXT exited {rc} without writing a solution; "
                     f"output tail: {tail[-300:]}")
            nxt = "read job.lxt / shelxt.stdout.log in the job dir"
        _write(stage, False, elapsed, returncode=rc, error=error, next=nxt)
        return {"returncode": rc, "elapsed": elapsed, "timed_out": timed_out,
                "stdout_tail": tail, "status": st, "estimate": est,
                "stage": stage, "error": error,
                "phasing_grace_used_s": round(used, 1),
                "phasing_grace_granted_s": round(ext_s, 1),
                "phasing_note": grace_note,
                "search_grace_extended_s": round(search_ext_s, 1),
                "search_grace_note": search_note,
                "progress_json": str(prog_path)}

    @staticmethod
    def _timeout_message(job: Path, elapsed: float, limit: int,
                         grace: int | None = None,
                         phasing_grace_used: float | None = None,
                         phasing_grace_s: int | None = None) -> str:
        """What the killed job had actually achieved, from job.lxt.

        SHELXT logs the Laue group, the phasing try table, 'Structure
        solution: N secs' when phasing is done, then works through the
        space groups of that class. Knowing WHICH half was running is the
        difference between 'give it more time' and 'this approach is
        wrong' - and the try table says whether more time can even help
        (pa1: 7/16 timeouts were reported as 'no progress' by a regex that
        allowed one space where SHELXT writes two for single-digit Laue
        numbers; the agents blind-retried or abandoned SHELXT)."""
        txt = ""
        lxt = job / "job.lxt"
        if lxt.exists():
            txt = lxt.read_text(encoding="utf-8", errors="replace")
        st = RunShelxt._lxt_status(txt)
        head = f"shelxt hit the {limit} s limit after {elapsed:.0f} s"
        parts: list[str] = []
        if st["phased"]:
            ps = st["phasing_s"]
            parts.append(
                f"{head}, but PHASING HAD ALREADY FINISHED in "
                + (f"{ps:.3f} s" if ps is not None else "time")
                + (f" (best CFOM {st['best_cfom']:.4f}, "
                   f"{st['n_attempts']} tries)"
                   if st["best_cfom"] is not None else "")
                + (f" (phasing itself ran {phasing_grace_used:.0f} s past "
                   f"timeout_s under the phasing grace)"
                   if phasing_grace_used else "")
                + " - the remaining time went into the space-group search"
                + (f" over Laue class {st['laue']}" if st["laue"] else "")
                + (f", which outlived the {grace} s search grace as well"
                   if grace else "")
                + ". This is a compute budget problem, not evidence against "
                "the method: re-run with a larger timeout_s / "
                "search_grace_s, or restrict the search with "
                "space_group=... (SHELXT -s) when the group is settled")
        elif st["laue"]:
            parts.append(f"{head}, during phasing in Laue class "
                         f"{st['laue']} (no solution yet): "
                         + RunShelxt._phasing_verdict(
                             st, elapsed, limit=limit,
                             phasing_grace_used=phasing_grace_used,
                             phasing_grace_s=phasing_grace_s))
        else:
            parts.append(f"{head}, before writing any progress to job.lxt "
                         "(not even the Laue group - check job.ins/job.hkl "
                         "and the log tail; this is a start-up problem, "
                         "not a hard structure)")
        if st["auto_a"]:
            parts.append(
                "NOTE: SHELXT re-enabled the full space-group search itself "
                "('-a set to extend space group search because atom heavier "
                "than Sc expected'), so all_space_groups=false does not "
                "shorten anything for a metal-bearing structure")
        parts.append(f"job dir: {job}")
        return ". ".join(parts)

    # -- space-group search stage -----------------------------------------

    @staticmethod
    def _exhaustive_search(st: dict[str, Any]) -> bool:
        """Does this job evaluate every group of its Laue class? True
        under -a on the command line or when SHELXT switched -a on itself
        (an atom heavier than Sc declared)."""
        if st.get("auto_a"):
            return True
        return bool(re.search(r"(^|\s)-a(\d|\.|\s|$)", st.get("cli") or ""))

    @staticmethod
    def _search_reference(base_dir: Path, laue: str | None,
                          exhaustive: bool, exclude: str | None = None,
                          limit: int = 60) -> dict[str, Any] | None:
        """How long SHELXT's space-group search took on THIS project's
        earlier jobs of the same Laue class and the same search scope
        (exhaustive -a vs. the default early-stop / -s single group):
        the only honest reference for a stage SHELXT does not narrate.
        None when no sibling job finished such a search. No constant of
        any crystal is involved - the reference is the project's own."""
        if not laue or not base_dir.exists():
            return None
        times: list[float] = []
        jobs: list[str] = []
        for d in sorted(base_dir.glob("job_*"))[-limit:]:
            if exclude and d.name == exclude:
                continue
            try:
                txt = (d / "job.lxt").read_text(encoding="utf-8",
                                                errors="replace")
            except OSError:
                continue
            sib = RunShelxt._lxt_status(txt)
            if sib.get("laue") != laue or sib.get("sg_search_s") is None:
                continue
            n_groups = int(sib.get("n_groups") or 0)
            if (n_groups >= 2) != bool(exhaustive):
                continue
            times.append(float(sib["sg_search_s"]))
            jobs.append(d.name)
        if not times:
            return None
        return {"n_jobs": len(times), "laue": laue,
                "exhaustive": bool(exhaustive),
                "median_s": round(statistics.median(times), 1),
                "max_s": round(max(times), 1),
                "last_s": round(times[-1], 1), "last_job": jobs[-1]}

    @staticmethod
    def _search_outlook(base_dir: Path, job: Path, st: dict[str, Any],
                        elapsed: float,
                        reference: Any = "auto") -> dict[str, Any]:
        """The space-group search stage as facts: how long it has run,
        why it can be long, what the same project's earlier jobs needed
        and how a re-run skips it. Empty (Nones) before phasing ends."""
        out: dict[str, Any] = {
            "auto_a": bool(st.get("auto_a")),
            "exhaustive_search": RunShelxt._exhaustive_search(st),
            "search_elapsed_s": None, "search_reference": None,
            "search_note": None,
        }
        if not st.get("phased"):
            return out
        if st.get("sg_search_s") is not None:
            out["search_elapsed_s"] = round(float(st["sg_search_s"]), 1)
        else:
            out["search_elapsed_s"] = round(max(
                0.0, elapsed - float(st.get("phasing_s") or 0.0)), 1)
        ref = (RunShelxt._search_reference(
                   base_dir, st.get("laue"), out["exhaustive_search"],
                   exclude=job.name)
               if reference == "auto" else reference)
        out["search_reference"] = ref
        if st.get("sg_search_s") is None:
            parts = [f"SHELXT prints nothing during the space-group "
                     f"search; {out['search_elapsed_s']:.0f} s into it"]
            if out["exhaustive_search"]:
                parts.append(
                    f"every space group of Laue class {st.get('laue')} "
                    "is evaluated one by one"
                    + (" (-a: SHELXT switched this on itself because an "
                       "atom heavier than Sc is declared)"
                       if st.get("auto_a") else " (-a)"))
            if ref:
                parts.append(
                    f"{ref['n_jobs']} earlier job(s) of this project in "
                    f"{ref['laue']} needed {ref['median_s']:.0f} s "
                    f"(max {ref['max_s']:.0f} s) for this stage")
            parts.append("the workbench shows this stage live even after "
                         "the turn ends; space_group=<settled group> "
                         "(SHELXT -s) skips it on a re-run")
            out["search_note"] = "; ".join(parts)
        return out

    @staticmethod
    def _search_extension(util: float | None, grace_s: int,
                          ext_so_far: float) -> float:
        """Seconds of search grace to grant now that the search grace
        has run out: a slice while the process is still busy (a healthy
        exhaustive search), 0 when it is idle (hang) or uninspectable,
        or when SEARCH_ACTIVE_EXT_FACTOR x search_grace_s is used up."""
        if util is None or util < SEARCH_ACTIVE_MIN_UTIL:
            return 0.0
        cap = SEARCH_ACTIVE_EXT_FACTOR * max(int(grace_s), 60)
        left = cap - float(ext_so_far)
        if left <= 0:
            return 0.0
        return float(min(left, max(60.0, 0.25 * int(grace_s))))

    # -- background jobs --------------------------------------------------

    @staticmethod
    def _resolve_job(name: str, base_dir: Path) -> Path:
        job = Path(name)
        return job if job.is_absolute() else base_dir / name

    @staticmethod
    def _lxt_elapsed_estimate(job: Path, st: dict[str, Any]) -> float | None:
        """Run length of a job nobody recorded: SHELXT's own 'Started at'
        banner against the .lxt's last write."""
        s = st.get("started_at")
        if not s:
            return None
        try:
            t_start = datetime.strptime(s, "%d %b %Y %H:%M:%S").timestamp()
            mtime = (job / "job.lxt").stat().st_mtime
        except (ValueError, OSError):
            return None
        d = mtime - t_start
        return d if 0 <= d < 7 * 86400 else None

    @staticmethod
    def _detached_worker(cmd: list[str] | None, job: Path, budget_s: int,
                         grace_s: int, phasing_grace_s: int, on_start: Any,
                         handle: Any = None, t0: float | None = None) -> None:
        """Body of a detached job's watchdog thread: run (or re-attach to)
        SHELXT under the staged budget, then record the outcome in the
        registry. The last progress.json write is done by _watch_loop."""
        base_dir = job.parent
        info: dict[str, Any] = {}
        try:
            if handle is None:
                info = RunShelxt._run_staged(
                    cmd or [], job, budget_s, grace_s, progress=None,
                    phasing_grace_s=phasing_grace_s,
                    state={"detached": True}, on_start=on_start)
            else:
                info = RunShelxt._watch_loop(
                    handle, job, float(t0 or time.time()), budget_s, grace_s,
                    progress=None, phasing_grace_s=phasing_grace_s,
                    state={"detached": True, "reattached": True})
        except Exception as e:  # noqa: BLE001 - must not die silently
            info = {"stage": "failed", "error": f"{type(e).__name__}: {e}"}
            try:
                rec = _read_json(job / "progress.json") or {}
                rec.update({"stage": "failed", "running": False,
                            "error": info["error"],
                            "updated_at": datetime.now().isoformat(
                                timespec="seconds")})
                _write_json_atomic(job / "progress.json", rec)
            except OSError:
                pass
        finally:
            _DETACHED.pop(str(job), None)
            if on_start is not None:
                try:
                    on_start(None)
                except Exception:  # noqa: BLE001
                    pass
        _jobs_update(base_dir, job.name, stage=info.get("stage"),
                     finished_at=datetime.now().isoformat(timespec="seconds"),
                     error=info.get("error"),
                     elapsed_s=round(float(info.get("elapsed") or 0), 1))

    def _start_detached(self, cmd: list[str], job: Path, base_dir: Path,
                        budget: int, grace: int, pgrace: int,
                        flags: list[str]) -> ToolResult:
        started = threading.Event()
        box: dict[str, Any] = {}

        def _on_start(pid: int | None) -> None:
            if pid is not None:
                box["pid"] = pid
            started.set()

        th = threading.Thread(
            target=self._detached_worker,
            args=(cmd, job, budget, grace, pgrace, _on_start),
            daemon=True, name=f"shelxt-watch-{job.name}")
        _DETACHED[str(job)] = {"thread": th, "job": job.name}
        th.start()
        started.wait(15.0)
        pid = box.get("pid")
        if pid is None:
            prog = _read_json(job / "progress.json") or {}
            return ToolResult.failure(
                f"detach: SHELXT did not start ("
                f"{prog.get('error') or 'no process within 15 s'}); "
                f"job dir {job}")
        now = datetime.now().isoformat(timespec="seconds")
        _jobs_update(base_dir, job.name, job_dir=str(job), pid=pid,
                     started_at=now, cmd=cmd, stage="running",
                     budget={"timeout_s": budget, "search_grace_s": grace,
                             "phasing_grace_s": pgrace})
        return ToolResult(ok=True, summary={
            "job": job.name, "job_dir": str(job), "pid": pid,
            "started_at": now, "detached": True, "no_state_change": True,
            "cli_flags": flags,
            "budget": {"timeout_s": budget, "search_grace_s": grace,
                       "phasing_grace_s": pgrace},
            "progress_json": str(job / "progress.json"),
            "registry": str(base_dir / SHELXT_JOBS_FILE),
            "note": (
                f"SHELXT is running in the background (pid {pid}) under "
                f"the same staged budget as a blocking call (timeout_s "
                f"{budget} on phasing, phasing_grace_s {pgrace} automatic "
                f"extension once a try clears the CFOM floor, "
                f"search_grace_s {grace} for the space-group search); this "
                f"call did not wait. Poll with run_shelxt(job_status="
                f"'{job.name}') every 60-120 s - it returns at once with "
                f"stage / tries / best CFOM / estimate - and once the "
                f"stage is 'finished' adopt with run_shelxt(from_job="
                f"'{job.name}'); a 'killed' stage carries the timeout "
                f"diagnosis and the suggested budget. Do not start a "
                f"second SHELXT on this project while it runs. The "
                f"workbench shows this job's stage live (status rail + a "
                f"system row in the conversation) and keeps showing it "
                f"after this turn ends, so you may tell the user what is "
                f"running and end the turn instead of sleeping. Expect "
                f"the space-group search to be long and SILENT when a "
                f"heavy atom is declared (SHELXT then evaluates every "
                f"group of the Laue class; 10-15 min on a large "
                f"hexagonal cell); space_group=<group> skips it once the "
                f"group is settled."),
        })

    def _reattach_watchdog(self, job: Path, prog: dict[str, Any]) -> bool:
        try:
            handle = _PidHandle(int(prog["pid"]))
        except Exception:  # noqa: BLE001 - psutil missing / process gone
            return False
        budget = prog.get("budget") or {}
        th = threading.Thread(
            target=self._detached_worker,
            args=(None, job, int(budget.get("timeout_s", 600)),
                  int(budget.get("search_grace_s", 900)),
                  int(budget.get("phasing_grace_s", 600)), None),
            kwargs={"handle": handle,
                    "t0": float(prog.get("started_at_epoch") or time.time())},
            daemon=True, name=f"shelxt-watch-{job.name}")
        _DETACHED[str(job)] = {"thread": th, "job": job.name}
        th.start()
        return True

    def _job_status(self, job: Path) -> ToolResult:
        """Read-only, instant state of a job: progress.json + the live
        job.lxt + the process. Never waits, never adopts."""
        base_dir = job.parent
        prog = _read_json(job / "progress.json")
        lxt = job / "job.lxt"
        if prog is None and not lxt.exists():
            watch = _DETACHED.get(str(job))
            if watch and watch["thread"].is_alive():
                # registered a moment ago, nothing on disk yet
                return ToolResult(ok=True, summary={
                    "job": job.name, "job_dir": str(job),
                    "stage": "starting", "running": True,
                    "tries_done": 0, "best_cfom": None,
                    "passed_acceptance": False, "has_solution": False,
                    "watchdog": "this process", "no_state_change": True,
                    "next": f"just started - poll run_shelxt(job_status="
                            f"'{job.name}') again in 60-120 s"})
            known = (sorted(p.name for p in base_dir.glob("job_*"))
                     if base_dir.exists() else [])
            return ToolResult.failure(
                f"job_status: {job} has neither progress.json nor job.lxt "
                f"- not a run_shelxt job (jobs under {base_dir}: "
                f"{known[-8:] or 'none'})")
        prog = prog or {}
        txt = ""
        if lxt.exists():
            try:
                txt = lxt.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
        st = self._lxt_status(txt)
        now = time.time()
        t0 = prog.get("started_at_epoch")
        watch = _DETACHED.get(str(job))
        watch_alive = bool(watch and watch["thread"].is_alive())
        pid = prog.get("pid")
        pid_alive = _pid_alive(pid, t0)
        has_res = (job / "job_a.res").exists()
        recorded_running = bool(prog.get("running"))
        stage = str(prog.get("stage") or st["stage"])
        notes: list[str] = []
        running = False
        if watch_alive:
            running = True
        elif recorded_running and pid_alive:
            # the SHELXT process outlived the server process that started
            # it (restart): re-attach a watchdog so its budget still holds
            running = True
            if self._reattach_watchdog(job, prog):
                notes.append("the SHELXT process outlived its watchdog "
                             "(server restart?) - a new watchdog was "
                             "attached with the job's original budget")
            else:
                notes.append("the SHELXT process is running without a "
                             "watchdog (server restart?) and none could be "
                             "re-attached - it finishes on its own; the "
                             "budget no longer applies")
        elif recorded_running:
            stage = "finished" if (has_res or st["finished"]) else "died"
            notes.append("progress.json still said running but the process "
                         "is gone and no completion was recorded (server "
                         "restart or external kill)")
        if running:
            elapsed = ((now - float(t0)) if t0
                       else float(prog.get("elapsed_s") or 0.0))
            stage = st["stage"]
            if prog.get("phasing_grace_granted_s") and not st["phased"]:
                stage = "phasing (grace)"
        else:
            elapsed = float(prog.get("elapsed_s") or 0.0) or float(
                self._lxt_elapsed_estimate(job, st) or 0.0)
            if not prog:
                stage = "finished" if (has_res or st["finished"]) else \
                    "stopped (no progress record)"
        budget = prog.get("budget") or {}
        est = self._phasing_estimate(st, elapsed,
                                     timeout_s=budget.get("timeout_s"))
        updated_ago = None
        if prog.get("updated_at"):
            try:
                updated_ago = round(now - datetime.fromisoformat(
                    str(prog["updated_at"])).timestamp())
            except ValueError:
                updated_ago = None
        summary: dict[str, Any] = {
            "job": job.name, "job_dir": str(job), "stage": stage,
            "running": running, "pid": pid,
            "started_at": prog.get("started_at"),
            "elapsed_s": round(elapsed, 1), "laue": st["laue"],
            "tries_done": est["tries_done"], "best_cfom": est["best_cfom"],
            "accept_x": est["accept_x"], "bar_now": est["bar_now"],
            "passed_acceptance": est["passed_acceptance"],
            "per_try_s": est["per_try_s"],
            "accept_at_try": est["accept_at_try"],
            "estimated_remaining_s": (est["estimated_remaining_s"]
                                      if running and not st["phased"]
                                      else None),
            "phasing_finished": st["phased"], "phasing_s": st["phasing_s"],
            "n_space_groups_evaluated": st["n_groups"],
            "phasing_grace_used_s": prog.get("phasing_grace_used_s"),
            "phasing_note": prog.get("phasing_note"),
            "last_lxt_line": st.get("last_line"),
            "has_solution": has_res, "budget": budget,
            **self._search_outlook(base_dir, job, st, elapsed),
            "search_grace_extended_s": prog.get("search_grace_extended_s"),
            "progress_updated_s_ago": updated_ago,
            "watchdog": ("this process" if str(job) in _DETACHED
                         else "none"),
            "no_state_change": True,
        }
        if prog.get("error"):
            summary["error"] = prog["error"]
        if running and st["phased"] and st["sg_search_s"] is None:
            summary["next"] = (
                f"still running - phasing is done, SHELXT is in its silent "
                f"space-group search; poll run_shelxt(job_status="
                f"'{job.name}') again in 120-180 s (the user sees this "
                f"stage live in the workbench), do not start another "
                f"SHELXT on this project meanwhile")
        elif running:
            summary["next"] = (
                f"still running - poll run_shelxt(job_status='{job.name}') "
                f"again in 60-120 s; do not start another SHELXT on this "
                f"project meanwhile")
        elif has_res:
            summary["next"] = (f"finished - run_shelxt(from_job="
                               f"'{job.name}') adopts the solution")
        elif stage == "killed":
            summary["next"] = ("killed at its budget - see error for the "
                               "diagnosis and the suggested timeout_s / "
                               "n_phase_sets; a killed run cannot be resumed")
        else:
            summary["next"] = ("no solution file - read error / job.lxt "
                               "in the job dir")
        if notes:
            summary["notes"] = notes
        return ToolResult(ok=True, summary=summary)

    def _no_res_message(self, job: Path, st: dict[str, Any]) -> str:
        """from_job on a job without job_a.res: say what happened to it
        (killed at x s / still running / crashed), how far it got, and
        what budget a re-run needs - SHELXT cannot resume a killed run."""
        prog = _read_json(job / "progress.json") or {}
        watch = _DETACHED.get(str(job))
        alive = bool(watch and watch["thread"].is_alive())
        n = len(st["tries"])
        if alive or (prog.get("running")
                     and _pid_alive(prog.get("pid"),
                                    prog.get("started_at_epoch"))):
            return (f"from_job: {job.name} is STILL RUNNING (stage "
                    f"{st['stage']}, {n} tries done"
                    + (f", best CFOM {st['best_cfom']:.4f}"
                       if st["best_cfom"] is not None else "")
                    + f") - nothing to adopt yet; poll run_shelxt("
                      f"job_status='{job.name}') and call from_job once it "
                      f"says finished")
        elapsed = prog.get("elapsed_s")
        if elapsed is None:
            elapsed = self._lxt_elapsed_estimate(job, st)
        budget = prog.get("budget") or {}
        est = self._phasing_estimate(st, float(elapsed or 0.0),
                                     timeout_s=budget.get("timeout_s"))
        killed = prog.get("stage") == "killed" or bool(prog.get("timed_out"))
        if killed:
            how = f"was killed by its budget after {float(elapsed):.0f} s"
        elif elapsed:
            how = (f"stopped after ~{float(elapsed):.0f} s without a "
                   f"completion record (crashed, or killed from outside)")
        else:
            how = "stopped"
        where = ("during the space-group search (phasing HAD finished)"
                 if st["phased"] else "during phasing")
        if n:
            tries = (f"{n} tries done, best CFOM {est['best_cfom']:.4f} "
                     f"{'above' if est['passed_acceptance'] else 'below'} "
                     f"the acceptance floor {est['accept_x']:.2f}")
        else:
            tries = "no try had finished"
        head = (f"from_job: {job.name} {how} {where} and left no .res "
                f"({tries}). SHELXT cannot resume a killed run and job.lxt "
                f"holds no adoptable coordinates. ")
        if st["phased"]:
            fix = ("Re-run run_shelxt with a larger search_grace_s, or "
                   "space_group=... to skip the whole-class search")
        elif est["passed_acceptance"] and est["suggested_timeout_s"]:
            fix = (f"Re-run run_shelxt with timeout_s >= "
                   f"{est['suggested_timeout_s']} (estimated phasing total "
                   f"{est['estimated_total_s']:.0f} s x 1.3)"
                   + (f", or n_phase_sets={est['suggested_n_phase_sets']} "
                      f"to fit the same tries into the old budget"
                      if est["suggested_n_phase_sets"] else "")
                   + " - the automatic phasing grace (phasing_grace_s) then "
                     "keeps such a run alive once a try clears the floor; "
                     "detach=true + job_status avoids blocking on it")
        else:
            fix = ("No try cleared the acceptance floor, so a bigger budget "
                   "is not the lever: change the search (solve_resolution, "
                   "composition with the heavy atoms actually present, "
                   "chem_quality, space_group=)"
                   + (f"; n_phase_sets={est['suggested_n_phase_sets']} "
                      f"would make {SHELXT_FLOOR_TRY} tries fit the old "
                      f"budget" if est["suggested_n_phase_sets"] else ""))
        return head + fix + f". Job dir: {job}"

    # -- the tool -------------------------------------------------------

    @staticmethod
    def _capability(ses, params: dict[str, Any]) -> dict[str, Any] | None:
        """solution_capability for this call: SHELXT phases at -d when one
        is given, otherwise at the data's own d_min, and its element list
        is the composition string when the caller passed one."""
        from ..chem import solvability
        try:
            d = params.get("solve_resolution")
            comp_raw = str(params.get("composition") or "").strip()
            els, el_src = None, ""
            if comp_raw:
                from .tools_frames import parse_composition
                els = list(parse_composition(comp_raw) or {})
                el_src = f"composition given to this call ({comp_raw!r})"
            return solvability.session_capability(
                ses, d_min=float(d) if d else None,
                d_min_source=(f"SHELXT -d{float(d):g} solve truncation"
                              if d else "merged data (SHELXT sees all of it)"),
                elements=els, elements_source=el_src)
        except Exception:  # noqa: BLE001 - a disclosure must not fail a call
            return None

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from ..chem import solvability
        block = self._capability(getattr(ctx, "session", None), params)
        return solvability.attach(self._run(ctx, **params), block)

    def _run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from ..io.shelx_model import load_res_model

        ses = ctx.session
        if ses is None or ses.dataset is None:
            return ToolResult.failure("no dataset in session")
        base_dir = self.project.dir / ".crystalpilot" / "refine" / "shelxt"
        from_job = str(params.get("from_job") or "").strip()
        job_status = str(params.get("job_status") or "").strip()
        detach = bool(params.get("detach", False))
        modes = [k for k, v in (("detach", detach),
                                ("job_status", job_status),
                                ("from_job", from_job)) if v]
        if len(modes) > 1:
            return ToolResult.failure(
                f"{' and '.join(modes)} are mutually exclusive - the "
                "sequence is run_shelxt(detach=true) -> run_shelxt("
                "job_status=<job>) every 60-120 s -> run_shelxt(from_job="
                "<job>) once the status says finished")
        if job_status:
            return self._job_status(self._resolve_job(job_status, base_dir))

        # SHELXT only reads HKLF 4: it hard-rejects an HKLF 5 job, and
        # feeding it batched data labelled HKLF 4 misreads the overlap rows
        # (probe on p770 twin data: R1 0.42, wrong group, nonsense formula)
        from .tools_frames import hklf5_batch_count
        n_dom = hklf5_batch_count(self.project.hkl_path)
        if n_dom >= 2:
            return ToolResult.failure(
                f"crystal.hkl is HKLF5-batched ({n_dom} domains) and SHELXT "
                "cannot consume twin-batch data. Solve from the vendor "
                "HKLF4 export (TWINABS writes one next to the HKLF5 file; "
                "re-ingest with hkl=<that file> or run "
                "solve_charge_flipping, which uses the batch>0 rows), then "
                "switch back to the HKLF5 data for final SHELXL refinement.")

        # -- job files ------------------------------------------------------
        cs = ses.symmetry or (ses.model.crystal_symmetry()
                              if ses.model is not None else None)
        if cs is None:
            return ToolResult.failure("no crystal symmetry in session")
        uc = cs.unit_cell().parameters()
        wl = ses.dataset.wavelength or 0.71073
        sg = cs.space_group()
        latt, symm_lines = shelx_latt_symm(sg)

        flags: list[str] = []
        run_info: dict[str, Any] = {}
        budget = int(params.get("timeout_s", 600))
        grace = int(params.get("search_grace_s", 900))
        pgrace = max(0, int(params.get("phasing_grace_s", 600)))
        if from_job:
            # adopt a finished job instead of running: agents asked for
            # this in pa1 ("maybe I can import a job file instead?") after
            # a solution's adoption was skipped or a re-run only repeated
            # what a previous job had already produced. The job's own
            # SFAC is what gets adopted, so no composition is needed here
            job = self._resolve_job(from_job, base_dir)
            if not (job / "job.lxt").exists():
                watch = _DETACHED.get(str(job))
                prog = _read_json(job / "progress.json") or {}
                if (watch and watch["thread"].is_alive()) or (
                        prog.get("running")
                        and _pid_alive(prog.get("pid"),
                                       prog.get("started_at_epoch"))):
                    # a detached job that has not written its .lxt yet
                    return ToolResult.failure(self._no_res_message(
                        job, self._lxt_status("")))
                return ToolResult.failure(
                    f"from_job: no job.lxt in {job} - list {base_dir} "
                    "for finished jobs")
            job_cell = None
            try:
                for ln in (job / "job.ins").read_text(
                        encoding="ascii", errors="replace").splitlines():
                    if ln.upper().startswith("CELL"):
                        job_cell = [float(x) for x in ln.split()[2:8]]
                        break
            except OSError:
                pass
            if job_cell:
                drift = max(abs(a - b) / max(abs(b), 1e-6)
                            for a, b in zip(job_cell, uc))
                if drift > 0.005:
                    return ToolResult.failure(
                        f"from_job: that job was run on cell "
                        f"{[round(x, 3) for x in job_cell]}, the session "
                        f"cell is {[round(x, 3) for x in uc]} - not the "
                        "same data; run SHELXT afresh")
            run_info = {"reused_job": str(job), "stdout_tail": "",
                        "status": self._lxt_status(
                            (job / "job.lxt").read_text(
                                encoding="utf-8", errors="replace"))}
        else:
            exe = Path(os.environ.get(
                "CRYSTALPILOT_SHELXT",
                str(DEFAULT_SHELXL.with_name("shelxt.exe"))))
            if not exe.exists():
                return ToolResult.failure(
                    f"shelxt.exe not found at {exe} (run "
                    "scripts/setup_vendor_shelx.py or set CRYSTALPILOT_SHELXT)")

            # -- elements / UNIT --------------------------------------------
            comp_raw = str(params.get("composition") or "").strip()
            counts: dict[str, float] = {}
            if comp_raw:
                from .tools_frames import parse_composition
                counts = parse_composition(comp_raw)
            elif ses.model is not None and ses.model.scatterers().size():
                for sc in ses.model.scatterers():
                    el = sc.scattering_type.strip()
                    counts[el] = counts.get(el, 0.0) + 1.0
            if not counts:
                ins_el = ses.flags.get("ins_elements") if ses else None
                if ins_el and ins_el.get("elements"):
                    el_str = " ".join(ins_el["elements"])
                    unit_vals = ins_el.get("unit") or []
                    if unit_vals:
                        unit_str = " ".join(f"{u:g}" for u in unit_vals)
                        qualifier = (
                            f"UNIT {unit_str} is a placeholder, not a "
                            "formula" if ins_el.get("unit_is_placeholder")
                            else f"UNIT {unit_str} is a vendor/cold-start "
                                 "declaration, not confirmed evidence")
                    else:
                        qualifier = "it has no UNIT card - counts unknown"
                    return ToolResult.failure(
                        f"no composition given; the ins declares SFAC "
                        f"{el_str} ({qualifier}). Pass "
                        f"composition='{el_str}' to use it as SHELXT's "
                        "element list - the composition string is a "
                        "phasing aid, not an element claim.")
                return ToolResult.failure(
                    "no element list available - pass composition='C H N "
                    "...' (elements normally come from set_experiment, "
                    "an ins file's SFAC via ingest_vendor_data(ins=...), "
                    "or atoms already in the session model)")
            z = int(params.get("z") or 2)
            elements = sorted(counts, key=lambda e: (e != "C", e != "H", e))
            every_one = all(abs(v - 1.0) < 1e-6 for v in counts.values())
            unit = [20.0 if every_one else counts[e] * z for e in elements]

            job = base_dir / time.strftime("job_%Y%m%d_%H%M%S")
            n = 0
            while job.exists():                 # two starts within a second
                n += 1
                job = base_dir / (time.strftime("job_%Y%m%d_%H%M%S") + f"_{n}")
            job.mkdir(parents=True, exist_ok=True)
            esd = getattr(self.project, "_cell_esd", None) or [0.0] * 6
            ins = ["TITL CrystalPilot run_shelxt",
                   "CELL %.5f %.4f %.4f %.4f %.3f %.3f %.3f" % (wl, *uc),
                   "ZERR %.2f %.4f %.4f %.4f %.3f %.3f %.3f" % (float(z), *esd),
                   f"LATT {latt}"]
            ins += symm_lines
            ins += ["SFAC " + " ".join(elements),
                    "UNIT " + " ".join(f"{u:g}" for u in unit),
                    "TREF", "HKLF 4", "END", ""]
            (job / "job.ins").write_text("\n".join(ins), encoding="ascii")
            _stage_job_hkl(self.project, job)

            from ..procutil import cpu_limit_cores
            flags = self._cli_flags(
                params, min(cpu_limit_cores(), os.cpu_count() or 1))
            cmd = self._shelxt_command(exe, flags)
            if detach:
                return self._start_detached(cmd, job, base_dir, budget,
                                            grace, pgrace, flags)
            # SHELXT phases FIRST and searches space groups SECOND, and the
            # search is the long half on a big cell in a large Laue class.
            # A bare "timed out" threw away a finished solution twice in
            # r25 and five times in pa1 (phasing done in 37-574 s, killed
            # in the search). The staged runner cuts only the phasing
            # stage at timeout_s - and not even that once a try clears
            # the CFOM floor (phasing grace; pa2 killed two runs one batch
            # short of the solution they were later re-run for) - and lets
            # a finished phasing complete its search (search_grace_s),
            # reporting the stage as it goes (notifications + progress.json).
            run_info = self._run_staged(
                cmd, job, budget, grace,
                progress=getattr(ctx, "progress", None),
                phasing_grace_s=pgrace, state={"detached": False})
            if run_info["timed_out"]:
                est = run_info.get("estimate") or {}
                return ToolResult(
                    ok=False,
                    error=run_info.get("error") or self._timeout_message(
                        job, run_info["elapsed"], budget,
                        grace if run_info["timed_out"] == "search" else None),
                    summary={"timeout": {
                        "stage": run_info["timed_out"],
                        "elapsed_s": round(float(run_info["elapsed"]), 1),
                        "tries_done": est.get("tries_done"),
                        "best_cfom": est.get("best_cfom"),
                        "passed_acceptance": est.get("passed_acceptance"),
                        "per_try_s": est.get("per_try_s"),
                        "estimated_total_s": est.get("estimated_total_s"),
                        "suggested_timeout_s": est.get("suggested_timeout_s"),
                        "suggested_n_phase_sets":
                            est.get("suggested_n_phase_sets"),
                        "phasing_grace_used_s":
                            run_info.get("phasing_grace_used_s"),
                        "job_dir": str(job),
                        "progress_json": run_info.get("progress_json")}})

        # -- parse candidate table from job.lxt -----------------------------
        # format:  R1  Rweak Alpha SysAbs  Orientation  Space group
        #          [Flack_x]  File  Formula
        lst = job / "job.lxt"
        sols: list[dict[str, Any]] = []
        if lst.exists():
            in_table = False
            for line in lst.read_text(encoding="utf-8",
                                      errors="replace").splitlines():
                if "R1  Rweak" in line and "Space group" in line:
                    in_table = True
                    continue
                if not in_table:
                    continue
                t = line.split()
                if len(t) < 6:
                    if sols:
                        break
                    continue
                try:
                    nums = [float(x) for x in t[:4]]
                except ValueError:
                    break
                fidx = next((i for i, x in enumerate(t)
                             if x.startswith("job_")), None)
                if fidx is None:
                    continue
                sols.append({"r1": nums[0], "rweak": nums[1],
                             "alpha": nums[2], "sys_abs": nums[3],
                             "space_group": t[fidx - 2]
                             if t[fidx - 1].replace(".", "", 1)
                                 .lstrip("-").isdigit() else t[fidx - 1],
                             "file": t[fidx],
                             "formula": " ".join(t[fidx + 1:])})
        best_res = job / "job_a.res"
        if not best_res.exists():
            if from_job:
                # pa2 cage-l0-r1: two from_job calls on a job that had been
                # killed during phasing were answered with 'exit None'
                return ToolResult.failure(self._no_res_message(
                    job, run_info.get("status") or self._lxt_status("")))
            tail = run_info.get("stdout_tail") or ""
            lxt_tail = ""
            if lst.exists():
                lxt_tail = lst.read_text(encoding="utf-8",
                                         errors="replace")[-500:]
            return ToolResult.failure(
                f"SHELXT produced no solution (exit "
                f"{run_info.get('returncode')}). Output tail: {tail}"
                + (f" | job.lxt tail: {lxt_tail}" if lxt_tail else ""))
        head = best_res.read_text(encoding="utf-8",
                                  errors="replace").splitlines()
        titl = head[0] if head else ""
        st = run_info.get("status") or {}
        if not st.get("finished") and lst.exists():
            st = self._lxt_status(lst.read_text(encoding="utf-8",
                                                errors="replace"))
        summary: dict[str, Any] = {
            "engine": "SHELXT (vendor, official)",
            "best": titl.strip(),
            "solutions": sols[:8],
            "job_dir": str(job),
            # budget facts for the NEXT run on this cell: how long each
            # stage took and how many tries phasing needed
            "phasing": {
                "laue_group": st.get("laue"),
                "n_tries": st.get("n_attempts") or len(st.get("tries") or []),
                "selected_try": st.get("selected_try"),
                "best_cfom": st.get("best_cfom"),
                "phasing_s": st.get("phasing_s"),
                "n_space_groups_evaluated": st.get("n_groups"),
                "sg_search_s": st.get("sg_search_s"),
                "assign_s": st.get("assign_s"),
                "total_s": st.get("total_s"),
                "m_iterations_per_try": st.get("m_iter"),
                "per_try_s": (round(float(st["phasing_s"])
                                    / max(1, len(st.get("tries") or [])), 1)
                              if st.get("phasing_s") and st.get("tries")
                              else None),
            },
            "search_scope_note": (
                "SHELXT tested only space groups of the LATTICE TYPE "
                "declared in job.ins (LATT) - its Laue determination and "
                "the -a search never question the centring, so a wrong "
                "centred declaration is simply echoed (pa2 hex: R-3 "
                "'confirmed' by SHELXT on data with no R absences); "
                "centring evidence comes from screen_space_groups / "
                "change_space_group's absence audit"),
            **({"budget_note": (
                f"n_phase_sets={params.get('n_phase_sets')} was clamped to "
                f"-m{SHELXT_M_CAP}: -m is iterations PER TRY, the cost is "
                f"linear in it and SHELXT runs >= 20 tries")}
               if (params.get("n_phase_sets") or 0) > SHELXT_M_CAP else {}),
            **({"reused_job": run_info["reused_job"]}
               if run_info.get("reused_job") else
               {"elapsed_s": round(float(run_info.get("elapsed") or 0), 1),
                "budget": {"timeout_s": budget, "search_grace_s": grace,
                           "phasing_grace_s": pgrace},
                "phasing_grace_used_s": run_info.get("phasing_grace_used_s"),
                "progress_json": run_info.get("progress_json"),
                **({"phasing_note": run_info["phasing_note"]}
                   if run_info.get("phasing_note") else {})}),
            **({"cli_flags": flags} if flags else {}),
            **({"solve_resolution_note":
                "solution was phased on -d truncated data; refine the "
                "adopted model against the FULL-resolution hkl"}
               if params.get("solve_resolution") else {}),
        }
        if not params.get("adopt", True):
            summary["no_state_change"] = True
            return ToolResult(ok=True, summary=summary)

        parsed = load_res_model(best_res)
        xs = parsed.structure
        xs.scattering_type_registry(table="it1992")
        new_cell = xs.unit_cell().parameters()
        drift = max(abs(a - b) / max(abs(b), 1e-6)
                    for a, b in zip(new_cell[:3], uc[:3]))
        if drift > 0.02:
            summary["no_state_change"] = True
            summary["note"] = (
                f"SHELXT re-set the cell ({[round(x, 3) for x in new_cell]} "
                f"vs {[round(x, 3) for x in uc]}) - adopting across a "
                f"setting change would desync crystal.hkl. Inspect "
                f"job_a.res / re-index the data first.")
            return ToolResult(ok=True, summary=summary)
        try:
            merge = ses.set_symmetry(xs.crystal_symmetry())
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                f"solution parsed but data re-merge failed under "
                f"{xs.space_group_info()}: {exc}")
        ses.model = xs
        if run_info.get("reused_job"):
            # the registry is what the workbench's background-job watcher
            # reads: a finished solution stops being 'waiting for adoption'
            _jobs_update(base_dir, Path(run_info["reused_job"]).name,
                         adopted_at=datetime.now().isoformat(
                             timespec="seconds"))
        summary.update({
            "adopted": True,
            "space_group": str(xs.space_group_info()),
            "n_atoms": xs.scatterers().size(),
            "merge": merge,
            "note": ("SHELXT assigns elements heuristically - verify with "
                     "density/coordination (inspect_model) before "
                     "anisotropic refinement"),
        })
        return ToolResult(ok=True, summary=summary)

# ==========================================================================
# typed metadata entry points (process-audit T1: WGHT / Z had no tool-face
# writes, spawning three generations of workarounds - export/hand-edit/
# re-ingest loops in r13, final.cif hand-edits in r14, cif+import round
# trips in r20/r21 plus the r21 twin on/off dance)
# ==========================================================================

class SetWeights(_ProjectTool):
    name = "set_weights"
    description = (
        "Set the session weighting scheme (SHELX 'WGHT a b') directly - no "
        "smtbx refinement run needed. The next refine and run_shelxl "
        "serialize exactly this scheme, so use it to adopt run_shelxl's "
        "suggested_wght in check-mode workflows and on HKLF5/TWIN data "
        "where optimize_weights refuses to run. Iterate until the "
        "suggestion stabilizes (run_shelxl summary carries suggested_wght "
        "+ wght_converged); a one-cycle run_shelxl(l_s=1) is enough to "
        "verify. NB run_shelxl(mode='adopt_wght') runs that loop for you "
        "and adopts the converged scheme with the model; mode='adopt' keeps "
        "the scheme it ran with. This tool is for explicit weight "
        "experiments and check-mode loops.")
    params_schema = {
        "type": "object",
        "properties": {
            "a": {"type": "number", "minimum": 0.0, "maximum": 2.0,
                  "description": "WGHT first parameter (typical 0.01-0.2)"},
            "b": {"type": "number", "default": 0.0,
                  "minimum": 0.0, "maximum": 1000.0,
                  "description": "WGHT second parameter (>= 0)"},
        },
        "required": ["a"],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        if ses is None:
            return ToolResult.failure("no active session")
        if ses.model is None:
            return ToolResult.failure(
                "set_weights needs a session with a model - the scheme is "
                "committed with a model node (and weights only matter once "
                "there is something to refine)")
        a = float(params["a"])
        b = float(params.get("b", 0.0))
        if not (0.0 <= a <= 2.0):
            return ToolResult.failure(
                f"a={a} outside sane range [0, 2] - SHELX WGHT a is "
                "typically 0.01-0.2; refuse rather than write a typo")
        if not (0.0 <= b <= 1000.0):
            return ToolResult.failure(
                f"b={b} outside sane range [0, 1000]")
        old = dict(ses.flags.get("weights") or {})
        ses.flags["weights"] = {"a": a, "b": b}
        summary: dict[str, Any] = {
            "old": old or {"a": 0.1, "b": 0.0},
            "new": {"a": a, "b": b},
            "note": ("session WGHT updated - refine and run_shelxl now "
                     "serialize this scheme; verify convergence with "
                     "run_shelxl(l_s=1) and check suggested_wght"),
        }
        if a > 0.5:
            summary["warning"] = (f"a={a} is unusually large - double-check "
                                  "this came from a SHELXL suggestion, not "
                                  "a typo")
        return ToolResult(ok=True, summary=summary)


class SetResolutionLimit(_ProjectTool):
    name = "set_resolution_limit"
    description = (
        "Set the refinement resolution cutoff (SHELX 'SHEL 999 d_min') as "
        "session state - carried by every node, serialized into every "
        "run_shelxl / run_olex2 job and the publication CIF. Published "
        "R factors are cut-data R factors: the r24 live case delivered "
        "uncut 0.58 A data and paid ~+0.02 R1 in weak high-angle noise "
        "while the reference structure was cut at 0.81 A. Take the d_min "
        "from estimate_resolution's shell table (CC1/2 >= 0.3, I/sigma "
        ">= 2 are the usual criteria), state it as reason, and DISCLOSE "
        "the cutoff in the validation report. d_min=null removes the "
        "cutoff. The in-process refine engine ignores SHEL (it warns via "
        "data_cards_note) - judge final numbers by run_shelxl.")
    params_schema = {
        "type": "object",
        "properties": {
            "d_min": {"type": ["number", "null"],
                      "minimum": 0.4, "maximum": 3.0,
                      "description": "resolution cutoff in Angstroms "
                                     "(0.4-3.0, e.g. 0.81); null removes it"},
            "reason": {"type": "string",
                       "description": "evidence for this cutoff (shell "
                                      "statistics, PLAT023...)"},
        },
        "required": ["d_min", "reason"],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        if ses is None:
            return ToolResult.failure("no session")
        if not str(params.get("reason") or "").strip():
            return ToolResult.failure(
                "reason is required - cite the shell statistics that "
                "justify the cutoff")
        cards = [c for c in (ses.flags.get("data_cards") or [])
                 if not c.strip().upper().startswith("SHEL")]
        d_min = params.get("d_min")
        if d_min is None:
            ses.flags["data_cards"] = cards
            return ToolResult(ok=True, summary={
                "removed": True,
                "note": "SHEL cutoff removed - full data range refines"})
        d_min = float(d_min)
        if not (0.4 <= d_min <= 3.0):
            return ToolResult.failure(
                f"d_min={d_min} outside sane range [0.4, 3.0] A")
        if ses.fo_sq is not None:
            try:
                data_d_min = ses.fo_sq.d_min()
                if d_min < data_d_min - 1e-3:
                    return ToolResult.failure(
                        f"d_min={d_min} is BEYOND the data (which ends at "
                        f"{data_d_min:.3f} A) - a no-op cutoff hides the "
                        "fact that no cut was made")
            except Exception:  # noqa: BLE001 - advisory check only
                pass
        cards.append(f"SHEL 999 {d_min:.3f}")
        ses.flags["data_cards"] = cards
        return ToolResult(ok=True, summary={
            "shel": f"SHEL 999 {d_min:.3f}",
            "reason": str(params["reason"]),
            "note": ("cutoff is session state now: run_shelxl / run_olex2 "
                     "and the delivery CIF all apply it. Re-run run_shelxl "
                     "and quote the cut R factors; disclose the cutoff in "
                     "VALIDATION.md"),
        })


class SetZ(_ProjectTool):
    name = "set_z"
    description = (
        "Set Z (formula units per cell) for the project - the number "
        "written into ZERR and used for formula/Z bookkeeping in "
        "deliverables. Solving tools estimate Z from volume heuristics "
        "and get it wrong routinely (z_estimated leaked into delivered "
        "CIFs in four campaigns); until now the only fixes were hand-"
        "editing CIFs or full re-ingest chains. Commits a node (the node "
        "model.res carries the new ZERR), so the delivery pairing audit "
        "will reject older SHELXL jobs - re-run run_shelxl after this so "
        "a matching job exists for write_outputs.")
    params_schema = {
        "type": "object",
        "properties": {
            "z": {"type": "integer", "minimum": 1, "maximum": 192,
                  "description": "formula units per unit cell (1-192)"},
            "reason": {"type": "string",
                       "description": "one line on where this Z comes from "
                                      "(e.g. 'complete molecule count in "
                                      "cell / sg order')"},
        },
        "required": ["z", "reason"],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        p = self.project
        if ses is None or ses.model is None:
            return ToolResult.failure(
                "set_z needs a session with a model - Z is written into "
                "the node's ZERR line, and an atomless session has no node "
                "to carry it")
        z = int(params["z"])
        if not (1 <= z <= 192):
            return ToolResult.failure(f"z={z} outside sane range [1, 192]")
        old = getattr(p, "_z", None)
        p._z = z
        # sanity mirror: per-formula non-H composition at this Z, plus how
        # it sits against the space-group order (Z < order means special
        # positions / fractional Z')
        xs = ses.model
        content = xs.unit_cell_content()
        per_formula = {e: round(n / z, 2)
                       for e, n in sorted(content.items()) if e != "H"}
        order = xs.space_group().order_z()
        summary: dict[str, Any] = {
            "old_z": old, "new_z": z,
            "reason": str(params["reason"]),
            "sg_order": order,
            "z_prime": round(z / order, 3),
            "per_formula_non_h": per_formula,
            "note": ("ZERR now carries this Z in every new node/job; "
                     "re-run run_shelxl so write_outputs finds a matching "
                     "job (older jobs are rejected on the Z audit)"),
        }
        frac = [e for e, n in per_formula.items()
                if abs(n - round(n)) > 0.01]
        if frac:
            summary["warning"] = (
                f"non-integer per-formula counts for {frac} at Z={z} - "
                "either the model is incomplete/has partial occupancies "
                "(fine if disclosed) or this Z is wrong")
        return ToolResult(ok=True, summary=summary)
