"""SHELXL .lst readback: the blocks run_shelxl's summary used to drop.

Until r33 `summarize_shelxl_job` read only R1/wR2/GooF, Flack, shift/esd,
WGHT and the restraint table - and it read SHELXL's own `**` lines ONLY on
the hard-abort path, so a job that finished successfully threw its warning
banners away. Everything the vendor prints between the last cycle and the
Q-peak list (analysis of variance, most disagreeable reflections) was never
looked at by any tool; agents SHELL-grepped job.lst for it or, more often,
never saw it at all.

Knowledge basis (docs/scxrd-expert-practice.md):

* §2.7  K = Mean[Fo^2]/Mean[Fc^2] high for the weakest reflections, plus
        "for all of the most disagreeable reflections Fo >> Fc", plus a
        shared integer index relation among those reflections ("For all
        these reflections: h + l = 5n") is the classic twinning signature;
        Clegg's pseudo-merohedral example is diagnosed off max K alone
        (P-1 untwinned max K 4.01 -> twinned max K 1.09).
* §13.4 restraints: "the final s.u.s on restrained parameters ... should be
        similar to those on equivalent unrestrained parameters".
* §13.7 "s.u.s from crystal-structure refinements tend to be
        underestimated" (factor ~1.5-2).
* §15.2 "Residuals larger than about three times the requested standard
        uncertainty should always be investigated."
* §17.4 the acceptance criterion for a weighting scheme is that "the
        variance shows no marked systematic trends with the magnitude of
        Fc2 or of resolution" - NOT that GooF is near 1.
* §17.5 IUCr editorial criterion "Poor convergence - maximum shift/s.u. >
        1.5", with the four directions the editors ask about.

Encoding principles (docs/scxrd-expert-knowledge-review.md §4):

* P3  every number is computed from the table in front of us; no case
      constants, and the "how far is far" reference is the table's OWN
      median / spread, reported alongside the verdict as `rule`.
* P12 criteria are one-directional. An anomaly indicates a problem;
      the absence of one is reported as "no ... detected", never as a
      pass, and never with the words pass / fine / OK.
* P13 report the DIRECTION of a deviation and what each direction
      suggests - K above and K below the table median mean different
      things and must not be collapsed into "deviates by x".
* P14 capability boundaries are stated in the output itself (what the
      block can and cannot decide).

Reading strings are English to match the rest of tools_shelxl; the one
mandated Chinese clause is SU_UNDERESTIMATED, appended to every verdict
that divides by an s.u.
"""
from __future__ import annotations

import math
import re
import statistics
from typing import Any

#: Appended verbatim to any verdict whose ratio has an s.u. in the
#: denominator (KNOWLEDGE §13.7; platform-wide convention, PLAN §3).
SU_UNDERESTIMATED = ("s.u. 系统性低估 1.5–2×（Linden §13.7），本比值是下限")

#: The restraint residual bar is the only literature-fixed number in this
#: module and it is a REQUESTED s.u. multiple, not a property of any one
#: crystal: "Residuals larger than about three times the requested
#: standard uncertainty should always be investigated" (§15.2).
RESTRAINT_SIGMA_BAR = 3.0
#: IUCr editorial convergence criterion, §17.5 (again a ratio, not a
#: crystal-specific quantity).
SHIFT_ESD_BAR = 1.5


# --------------------------------------------------------------------- #
# 1. warnings                                                            #
# --------------------------------------------------------------------- #

def parse_shelxl_warnings(text: str) -> list[str]:
    """Every `**` line SHELXL printed, stripped and de-duplicated in order.

    SHELXL brackets its banners in double asterisks:

        ** Warning:     1  atoms may be split and     0  atoms NPD **
        ** WARNING: These times are only approximate for multiple threads.
                    To get better estimates run with -t1 **

    (the second banner wraps, so both halves are separate entries), and it
    also prints `*******` when a refined value overflows its field - which
    is itself a finding, so no line carrying `**` is filtered out here.
    The same text with a nonzero count and with zero counts differ only in
    the asterisks:

            0  atoms may be split and     0  atoms NPD

    i.e. SHELXL brackets the line only when it has something to say.

    Returns [] (never None) when the job printed no banners: an empty list
    is "SHELXL raised nothing", which is evidence, not a pass (P12).
    """
    seen: list[str] = []
    for ln in text.splitlines():
        if "**" not in ln:
            continue
        s = ln.strip()
        if s and s not in seen:
            seen.append(s)
    return seen


# --------------------------------------------------------------------- #
# 2. analysis of variance                                                #
# --------------------------------------------------------------------- #

_VARIANCE_HEADER = "Analysis of variance for reflections employed in refinement"
_ROW_LABELS = {"Number in group": "n", "GooF": "goof", "K": "k", "R1": "r1"}


def _floats(row: str) -> list[float | None]:
    """SHELXL prints '477.', '-3.185', 'inf' and (on overflow) '******'."""
    out: list[float | None] = []
    for tok in row.split():
        if tok.lower() in ("inf", "infinity"):
            out.append(math.inf)
            continue
        try:
            out.append(float(tok))
        except ValueError:
            out.append(None)
    return out


def _variance_block(chunk: str) -> dict[str, Any] | None:
    """One of the two sub-tables: a bounds line then labelled rows."""
    lines = chunk.splitlines()
    if not lines:
        return None
    bounds = _floats(lines[0])
    block: dict[str, Any] = {"bounds": bounds}
    for ln in lines[1:]:
        for label, key in _ROW_LABELS.items():
            m = re.match(rf"\s*{re.escape(label)}\s+(\S.*)$", ln)
            if m:
                block[key] = _floats(m.group(1))
                break
    if "k" not in block:
        return None
    return block


def _finite(vals: list[float | None] | None) -> list[float]:
    return [v for v in (vals or []) if v is not None and math.isfinite(v)]


def _monotonic(vals: list[float]) -> str | None:
    """'increasing' / 'decreasing' / None, strict over >= 4 points."""
    if len(vals) < 4:
        return None
    diffs = [b - a for a, b in zip(vals, vals[1:])]
    if all(d > 0 for d in diffs):
        return "increasing"
    if all(d < 0 for d in diffs):
        return "decreasing"
    return None


#: How far from the table's own median K counts as "far". P3: the
#: reference and the spread both come from the table in front of us - the
#: median K and the median absolute deviation of the same row - so a table
#: that swings +-30 % everywhere does not flag one group at 1.3x. The
#: relative floor stops a table that is flat to four decimals from
#: reporting its own rounding noise as a trend. Both numbers are printed
#: in `rule`.
_K_SIGMA_MULT = 3.0            # robust 3 sigma
_MAD_TO_SIGMA = 1.4826         # MAD -> sigma for a normal distribution
_K_MIN_REL_DEV = 0.25          # ... and at least 25 % of the median K


def _bin_label(bounds: list[float | None], i: int, unit: str) -> str:
    """'0.000-0.026' for group i, from the bounds line SHELXL printed."""
    def fmt(v: float | None) -> str:
        if v is None:
            return "?"
        if math.isinf(v):
            return "inf"
        return f"{v:g}"
    if bounds and i + 1 < len(bounds):
        return f"{fmt(bounds[i])}-{fmt(bounds[i + 1])} {unit}"
    return f"group {i + 1}"


def _k_readings(block: dict[str, Any], axis: str) -> list[str]:
    """Directional readings for one K row. axis is 'fc' or 'resolution'."""
    ks = block.get("k") or []
    finite = _finite(ks)
    out: list[str] = []
    if len(finite) < 3:
        return out
    med = statistics.median(finite)
    unit = "Fc/Fc(max)" if axis == "fc" else "A"
    n_groups = len(ks)
    # negative K first: mean Fo^2 below zero in a group is not a "trend",
    # it is a statement about the data in that group
    for i, k in enumerate(ks):
        if k is not None and math.isfinite(k) and k <= 0:
            out.append(
                f"K by {axis}: group {i + 1}/{n_groups} "
                f"({_bin_label(block.get('bounds') or [], i, unit)}) has "
                f"K = {k:g}, i.e. the group's mean Fo^2 is not positive - "
                f"candidate causes: that group is dominated by "
                f"background-level or negative intensities, or the scale/"
                f"extinction model has gone wrong there. Ratios to the "
                f"table median are not meaningful for such a group.")
    if med <= 0:
        out.append(
            f"K by {axis}: the table's own median K is {med:g} (not "
            f"positive), so the relative test below cannot be applied; "
            f"read the raw K row.")
        return out
    mad = statistics.median([abs(v - med) for v in finite])
    bar = max(_K_SIGMA_MULT * _MAD_TO_SIGMA * mad, _K_MIN_REL_DEV * med)
    lo_half = n_groups / 2.0
    for i, k in enumerate(ks):
        if k is None or not math.isfinite(k) or k <= 0:
            continue
        ratio = k / med
        if abs(k - med) <= bar:
            continue
        where = _bin_label(block.get("bounds") or [], i, unit)
        high = k > med
        head = (f"K by {axis}: group {i + 1}/{n_groups} ({where}) has "
                f"K = {k:g}, {ratio:.2f}x the table's own median K "
                f"({med:g})")
        if axis == "fc":
            weak_end = i < lo_half
            if high and weak_end:
                out.append(
                    head + " - among the WEAKEST reflections Fo^2 sits "
                    "systematically ABOVE Fc^2. Candidate causes: an "
                    "unmodelled weak scatterer (guest/solvent/minor "
                    "disorder component), twinning (the classic "
                    "signature, KNOWLEDGE §2.7), or the treatment of "
                    "negative intensities. Distinguish them by writing "
                    "out the indices of the most disagreeable "
                    "reflections and by looking at the difference map.")
            elif not high and weak_end:
                out.append(
                    head + " - among the WEAKEST reflections Fo^2 sits "
                    "systematically BELOW Fc^2. Candidate causes: a "
                    "scatterer that is over-modelled there (occupancy "
                    "too high, wrong/too heavy element on a light site), "
                    "or a weighting scheme that over-weights weak data. "
                    "Note this is the OPPOSITE direction to the "
                    "twinning signature of §2.7.")
            elif not high:
                out.append(
                    head + " - among the STRONGEST reflections Fo^2 sits "
                    "systematically BELOW Fc^2. Candidate causes: "
                    "extinction (try an EXTI refinement) or a weighting "
                    "scheme that under-weights the strong data.")
            else:
                out.append(
                    head + " - among the STRONGEST reflections Fo^2 sits "
                    "systematically ABOVE Fc^2. Candidate causes: an "
                    "over-applied extinction correction, a scale-factor "
                    "problem, or heavy-atom scattering power that is "
                    "under-modelled.")
        else:
            out.append(
                head + (" - Fo^2 above Fc^2" if high else
                        " - Fo^2 below Fc^2") +
                " in that resolution shell. Candidate causes: scale/decay "
                "with resolution, an ADP model that is wrong at this end "
                "of the range, absorption, or (at the low-angle end) "
                "beam-stop shading and overlaps.")
    return out


def parse_variance_table(text: str) -> dict[str, Any] | None:
    """SHELXL's 'Analysis of variance' block -> the two K tables + reading.

    Verbatim shape (SHELXL-2019/3), both sub-tables 10 groups wide with an
    11-value bounds line; the Fc table has no R1 row, the resolution table
    does, and the resolution bounds run from the HIGHEST resolution
    (smallest d) to `inf`::

     Analysis of variance for reflections employed in refinement      K = ...

     Fc/Fc(max)       0.000    0.008 ...    1.000
     Number in group       477.     394. ...
                GooF      0.695    0.913 ...
                 K        0.459    1.267 ...

     Resolution(A)    0.78     0.82 ...     inf
     Number in group       419.     417. ...
                GooF      0.961    0.849 ...
                 K        0.843    0.942 ...
                 R1       0.134    0.104 ...

    K may be negative (a group whose mean Fo^2 came out below zero) - seen
    live on a ka1-cage job (K = -3.185 in one shell), so nothing here
    assumes K > 0.

    Returns None when the block is absent (L.S. 0 jobs still print it; a
    hard abort does not). Never returns a fabricated default.

    Why this exists: §17.4 says a weighting scheme is accepted when "the
    variance shows no marked systematic trends with the magnitude of Fc2
    or of resolution" - i.e. THIS table, not GooF, is the criterion. And
    §2.7 makes the low-Fc end of it the twinning detector.
    """
    idx = text.find(_VARIANCE_HEADER)
    if idx < 0:
        return None
    tail = text[idx + len(_VARIANCE_HEADER):]
    for stop in ("Recommended weighting scheme", "Most Disagreeable",
                 "Principal mean square"):
        cut = tail.find(stop)
        if cut >= 0:
            tail = tail[:cut]
    m_fc = re.search(r"^\s*Fc/Fc\(max\)\s+(\S.*)$", tail, re.M)
    m_res = re.search(r"^\s*Resolution\(A\)\s+(\S.*)$", tail, re.M)
    out: dict[str, Any] = {}
    marks = [(m.start(), name, m) for name, m in
             (("by_fc", m_fc), ("by_resolution", m_res)) if m]
    marks.sort()
    for j, (start, name, m) in enumerate(marks):
        end = marks[j + 1][0] if j + 1 < len(marks) else len(tail)
        chunk = m.group(1) + "\n" + tail[m.end():end]
        block = _variance_block(chunk)
        if block:
            out[name] = block
    if not out:
        return None

    reading: list[str] = []
    res = out.get("by_resolution")
    if "by_fc" in out:
        reading += _k_readings(out["by_fc"], "fc")
    if res:
        reading += _k_readings(res, "resolution")
    # the no-trend sentence answers the K question only; the R1 note below
    # is a separate statement and must not suppress it
    n_k_readings = len(reading)
    if res:
        ks = _finite(res.get("k"))
        trend = _monotonic(ks)
        if trend:
            n_k_readings += 1
            reading.append(
                f"K varies monotonically across the resolution table "
                f"({'rising' if trend == 'increasing' else 'falling'} from "
                f"the high-resolution end to the low-resolution end) - "
                f"candidate causes: an overall scale/decay term, or an ADP "
                f"model that absorbs resolution dependence it should not. "
                f"A monotonic K is the trend §17.4 asks the weighting "
                f"scheme to remove.")
        r1s = res.get("r1")
        if r1s:
            fin = _finite(r1s)
            if len(fin) >= 4:
                hi_end, lo_end = fin[0], fin[-1]
                reading.append(
                    f"R1 per resolution shell runs {hi_end:g} at the "
                    f"highest-resolution shell to {lo_end:g} at the "
                    f"lowest-resolution shell. R1 rising towards high "
                    f"resolution (the outer shells) is EXPECTED - weaker "
                    f"data, larger relative errors - and is NOT flagged "
                    f"here.")
                if lo_end > hi_end:
                    reading.append(
                        "R1 is instead HIGHEST at the low-resolution end, "
                        "which is the opposite of the expected direction. "
                        "Candidate causes: beam-stop shading or overlapped "
                        "low-angle reflections, extinction, absorption, or "
                        "a scale problem on the strongest data - the "
                        "low-angle reflections are the ones a missing "
                        "solvent/guest region shows up in.")
    if not n_k_readings:
        reading.insert(0, (
            "no K trend detected: no group deviates from the table's own "
            "median K by more than the spread of the table itself (see "
            "`rule`), and K is not monotonic with resolution. This is the "
            "absence of one signal, not a verdict on the weighting scheme "
            "or on the model."))
    out["reading"] = reading
    out["rule"] = (
        f"a group is called far-from-median when its K differs from the "
        f"MEDIAN K of its own table by more than max("
        f"{_K_SIGMA_MULT:g} x {_MAD_TO_SIGMA} x MAD(K of that table), "
        f"{_K_MIN_REL_DEV:g} x median K) - both the reference and the "
        f"spread come from this table, no fixed K value is used; K <= 0 "
        f"is always reported; 'monotonic' means every step across the "
        f"shells has the same sign. Direction is reported because it "
        f"discriminates: K above the median at the weak end is the "
        f"twinning/missing-scatterer direction (§2.7), K below it at the "
        f"strong end is the extinction/weighting direction (§17.4).")
    out["capability_note"] = (
        "this block reads SHELXL's printed table only. It cannot tell "
        "twinning from an unmodelled guest by itself - that needs the "
        "index pattern of the most disagreeable reflections, the "
        "difference map, and the cell metric (P14).")
    return out


# --------------------------------------------------------------------- #
# 3. most disagreeable reflections                                       #
# --------------------------------------------------------------------- #

_DISAGREE_HEADER = "Most Disagreeable Reflections"
#: h k l [*] Fo^2 Fc^2 Error/esd Fc/Fc(max) Resolution(A)
_DISAGREE_ROW = re.compile(
    r"^\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s*(\*?)\s+"
    r"(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+"
    r"(-?\d+\.\d+)\s+(-?\d+\.\d+)\s*$")

#: simple integer index relations, tried at several moduli. Deliberately
#: element- and case-agnostic: these are lattice arithmetic, the same set
#: for a MOF, a salt and a metallocene.
_INDEX_COMBOS: tuple[tuple[str, tuple[int, int, int]], ...] = (
    ("h", (1, 0, 0)), ("k", (0, 1, 0)), ("l", (0, 0, 1)),
    ("h+k", (1, 1, 0)), ("h+l", (1, 0, 1)), ("k+l", (0, 1, 1)),
    ("h+k+l", (1, 1, 1)),
    ("h-k", (1, -1, 0)), ("h-l", (1, 0, -1)), ("k-l", (0, 1, -1)),
    ("h+k-l", (1, 1, -1)), ("h-k+l", (1, -1, 1)), ("-h+k+l", (-1, 1, 1)),
)
_INDEX_MODULI = (2, 3, 4, 5, 6)
#: a pattern is reported only when its probability of arising by chance,
#: multiplied by the number of hypotheses tried, stays under this
_INDEX_CHANCE_BAR = 0.01
#: how many of the worst rows the index test looks at
_INDEX_MAX_ROWS = 20

#: |LATT n| -> the index relations EVERY measured reflection of that
#: lattice already satisfies, so finding them among the worst rows says
#: nothing. Live false positive that made this necessary: an I-centred
#: workbench job (LATT 2) reported "all 20 worst reflections satisfy
#: h+k+l = 2n" - true of all 4166 of them. SHELXL's LATT numbering:
#: 1 P, 2 I, 3 R(obverse on hexagonal axes), 4 F, 5 A, 6 B, 7 C.
_LATT_CONDITIONS: dict[int, tuple[tuple[tuple[int, int, int], int], ...]] = {
    1: (),
    2: (((1, 1, 1), 2),),
    3: (((-1, 1, 1), 3),),
    4: (((1, 1, 0), 2), ((1, 0, 1), 2), ((0, 1, 1), 2)),
    5: (((0, 1, 1), 2),),
    6: (((1, 0, 1), 2),),
    7: (((1, 1, 0), 2),),
}


def parse_latt(text: str) -> int | None:
    """|LATT n| from the .ins instructions SHELXL echoes into the .lst.

    None means "no LATT card seen" - reported as not-checked rather than
    silently treated as primitive (the platform's standing rule against
    encoding 'not checked' as 'passed').
    """
    m = re.search(r"^\s*LATT\s+(-?\d+)", text, re.M)
    return abs(int(m.group(1))) if m else None


def _lattice_implies(coeffs: tuple[int, int, int], m: int, residue: int,
                     latt: int | None) -> bool:
    """Is (coeffs mod m == residue) already true of the whole lattice?"""
    if latt is None or residue != 0:
        return False
    for cond, cm in _LATT_CONDITIONS.get(latt, ()):
        if cm != m:
            continue
        a = tuple(x % m for x in coeffs)
        b = tuple(x % m for x in cond)
        nb = tuple((-x) % m for x in cond)
        if a == b or a == nb:
            return True
    return False


def _index_pattern(rows: list[dict[str, Any]],
                   latt: int | None = None) -> dict[str, Any] | None:
    """A shared integer index relation among the worst-fitting rows.

    §2.7's worked case ends "For all these reflections: h + l = 5n" and the
    source's own comment is that writing the indices out "often gives the
    twin law directly". This is therefore a HINT generator, not a test:
    the output says so, and a pattern is only reported when it is unlikely
    to be a coincidence of the handful of rows SHELXL printed.

    `latt` is |LATT n| from the job: relations the lattice centring
    already imposes on EVERY reflection carry no information here and are
    skipped.
    """
    use = rows[:_INDEX_MAX_ROWS]
    k = len(use)
    if k < 4:
        return None
    hkl = [r["hkl"] for r in use]
    n_zone_hyp = 3
    n_mod_hyp = len(_INDEX_COMBOS) * len(_INDEX_MODULI)

    # (a) a constant column: every worst row lies in the same zone
    span = max((abs(v) for t in hkl for v in t), default=0)
    n_values = 2 * span + 1
    for axis, name in enumerate("hkl"):
        vals = {t[axis] for t in hkl}
        if len(vals) != 1 or n_values < 2:
            continue
        chance = n_zone_hyp * (1.0 / n_values) ** (k - 1)
        if chance <= _INDEX_CHANCE_BAR:
            v = next(iter(vals))
            return {"kind": "zone", "expression": name, "value": v,
                    "n_rows_checked": k, "chance_probability": chance,
                    "n_hypotheses": n_zone_hyp + n_mod_hyp,
                    "lattice_centring": (
                        f"LATT {latt}" if latt else "not checked "
                        "(no LATT card in the .lst)"),
                    "hint": (
                        f"every one of the {k} worst-fitting reflections "
                        f"lies in the {name} = {v} zone. A whole zone "
                        f"fitting worse than the rest is a HINT, not a "
                        f"finding: candidate causes are a twin law that "
                        f"leaves that zone overlapped, a centring or "
                        f"superstructure the model does not have, or a "
                        f"detector/beam-stop artefact on that zone. "
                        f"Confirm against the cell metric and the "
                        f"systematic-absence table before acting.")}

    # (b) a shared residue modulo m for one of the simple combinations;
    #     the most restrictive (largest modulus) wins
    best: dict[str, Any] | None = None
    for name, (a, b, c) in _INDEX_COMBOS:
        for m in _INDEX_MODULI:
            residues = {(a * h + b * kk + c * ll) % m for h, kk, ll in hkl}
            if len(residues) != 1:
                continue
            r = next(iter(residues))
            if _lattice_implies((a, b, c), m, r, latt):
                continue        # true of every reflection of this lattice
            chance = n_mod_hyp * (1.0 / m) ** (k - 1)
            if chance > _INDEX_CHANCE_BAR:
                continue
            if best is None or m > best["modulus"]:
                best = {"kind": "modulus", "expression": name, "modulus": m,
                        "residue": r, "n_rows_checked": k,
                        "chance_probability": chance,
                        "n_hypotheses": n_zone_hyp + n_mod_hyp,
                        "lattice_centring": (
                            f"LATT {latt}" if latt else "not checked "
                            "(no LATT card in the .lst)")}
    if best is None:
        return None
    name, m, r = best["expression"], best["modulus"], best["residue"]
    rel = (f"{name} = {m}n" if r == 0 else f"{name} = {m}n+{r}")
    if r == 0:
        best["gcd"] = m
    best["hint"] = (
        f"all {best['n_rows_checked']} worst-fitting reflections satisfy "
        f"{rel} (relations the lattice centring already imposes on every "
        f"reflection are excluded; centring: {best['lattice_centring']}). "
        f"A shared integer index relation among the most disagreeable "
        f"reflections is a HINT towards a twin law or a centring / "
        f"superstructure the model does not have - KNOWLEDGE §2.7 records "
        f"a case diagnosed exactly this way (\"For all these reflections: "
        f"h + l = 5n\"), and its own advice is that writing the indices "
        f"out often gives the twin law directly. It is a hint: the same "
        f"relation also appears when a pseudo-translation or a detector "
        f"artefact hits one lattice sub-set. Check the cell metric and "
        f"the absence table next.")
    return best


def parse_disagreeable_reflections(text: str) -> dict[str, Any] | None:
    """SHELXL's 'Most Disagreeable Reflections' table + a directional read.

    Verbatim shape (SHELXL-2019/3); rows are printed in descending
    Error/esd order and a '*' after l marks suppressed / Rfree rows::

     Most Disagreeable Reflections (* if suppressed or used for Rfree).
     Error/esd is calculated as sqrt(wD^2/<wD^2>) ...

         h   k   l          Fo^2          Fc^2    Error/esd  Fc/Fc(max) ...

         0   3   1       5658.53        448.63       9.77       0.026 ...

    Returns None when the block is absent. `n_fo_gt_fc` / `n_fo_lt_fc` are
    counted over EVERY parsed row; `worst` carries only the top rows so the
    tool summary stays readable.

    Direction matters (P13): §2.7's twinning case is "for all of the most
    disagreeable reflections Fo >> Fc", i.e. the model is missing
    scattering power; the mirror case (Fo^2 < Fc^2 dominant) points at
    scattering power the model has invented or over-corrected.
    """
    idx = text.find(_DISAGREE_HEADER)
    if idx < 0:
        return None
    rows: list[dict[str, Any]] = []
    for ln in text[idx:].splitlines():
        m = _DISAGREE_ROW.match(ln)
        if not m:
            if rows and ln.strip():
                break     # table ended ('Bond lengths and angles', ...)
            continue
        rows.append({
            "hkl": (int(m.group(1)), int(m.group(2)), int(m.group(3))),
            "suppressed": m.group(4) == "*",
            "fo_sq": float(m.group(5)), "fc_sq": float(m.group(6)),
            "error_esd": float(m.group(7)),
            "fc_over_fc_max": float(m.group(8)),
            "d_A": float(m.group(9)),
        })
    if not rows:
        return None
    n_gt = sum(1 for r in rows if r["fo_sq"] > r["fc_sq"])
    n_lt = sum(1 for r in rows if r["fo_sq"] < r["fc_sq"])
    n = len(rows)
    # a fair split has mean n/2 and sigma sqrt(n)/2; call the imbalance
    # directional only past one sigma (P3: derived from n, not a constant)
    sigma = math.sqrt(n) / 2.0
    bar = n / 2.0 + sigma
    out: dict[str, Any] = {
        "n_rows": n, "n_fo_gt_fc": n_gt, "n_fo_lt_fc": n_lt,
        "n_suppressed": sum(1 for r in rows if r["suppressed"]),
        "worst": [{"hkl": list(r["hkl"]), "fo_sq": r["fo_sq"],
                   "fc_sq": r["fc_sq"], "error_esd": r["error_esd"],
                   "d_A": r["d_A"]} for r in rows[:8]],
        "rule": (f"the Fo^2>Fc^2 / Fo^2<Fc^2 split is called directional "
                 f"only when the majority exceeds n/2 + sqrt(n)/2 "
                 f"(one binomial sigma of a fair split; here "
                 f"{bar:.1f} of {n}); the index-relation test reports a "
                 f"pattern only when its chance probability times the "
                 f"number of relations tried stays under "
                 f"{_INDEX_CHANCE_BAR:g}."),
    }
    reading: list[str] = []
    if n_gt > bar:
        reading.append(
            f"{n_gt} of the {n} worst-fitting reflections have Fo^2 > "
            f"Fc^2: the OBSERVED intensities are stronger than the model "
            f"predicts. Candidate causes: a missing scatterer (guest, "
            f"solvent, a disorder component, a heavier element than "
            f"assigned), twinning, or reflections wrongly treated as "
            f"systematically absent. KNOWLEDGE §2.7 pairs exactly this "
            f"direction with a high K in the weakest groups as the "
            f"twinning signature.")
    elif n_lt > bar:
        reading.append(
            f"{n_lt} of the {n} worst-fitting reflections have Fo^2 < "
            f"Fc^2: the model OVER-predicts these intensities. Candidate "
            f"causes: extinction, an over-weighted or too-heavy atom, a "
            f"wrong element assignment, or an atom that should not be "
            f"there at all.")
    else:
        reading.append(
            f"no directional imbalance detected in the worst rows "
            f"({n_gt} with Fo^2 > Fc^2, {n_lt} with Fo^2 < Fc^2 of {n}). "
            f"That is the absence of one signal, not a statement that the "
            f"model accounts for these reflections.")
    pattern = _index_pattern(rows, parse_latt(text))
    if pattern:
        out["index_pattern"] = pattern
        reading.append(pattern["hint"])
    out["reading"] = reading
    return out


# --------------------------------------------------------------------- #
# 4. restraint residuals                                                 #
# --------------------------------------------------------------------- #

def restraint_residual_reading(entries: list[dict[str, Any]]
                               ) -> dict[str, Any]:
    """`over_3_sigma` flags + the §15.2 / §13.4 evidence sentence.

    `entries` are {"line", "ratio"} pairs from the final 'Disagreeable
    restraints' table, ratio = |Error| / Sigma. §15.2: "Residuals larger
    than about three times the requested standard uncertainty should
    always be investigated."

    The negative branch is deliberately NOT a pass claim (P12): §13.4's
    acceptance sentence ("the final s.u.s on restrained parameters should
    be similar to those on equivalent unrestrained parameters") is about
    the refined s.u.s, which this table does not carry, so all that can
    honestly be said here is that no residual exceeded 3 sigma.
    """
    flagged = [e for e in entries if e["ratio"] > RESTRAINT_SIGMA_BAR]
    out: dict[str, Any] = {
        "n_over_3_sigma": len(flagged),
        "entries": [{**e, "over_3_sigma": e["ratio"] > RESTRAINT_SIGMA_BAR}
                    for e in entries[:8]],
    }
    if flagged:
        worst = flagged[0]
        out["reading"] = (
            f"{len(flagged)} restraint residual(s) exceed "
            f"{RESTRAINT_SIGMA_BAR:g}x the sigma requested for them "
            f"(worst {worst['ratio']:.1f}x: {worst['line']}). §15.2: "
            f"\"Residuals larger than about three times the requested "
            f"standard uncertainty should always be investigated\" - the "
            f"restraint and the data are pulling against each other, so "
            f"either the target is wrong for this chemistry or the "
            f"structure really does deviate; §13.4's companion check is "
            f"whether a difference peak has appeared on the restrained "
            f"atom's own position. Do not simply loosen sigma to make "
            f"the flag go away. " + SU_UNDERESTIMATED)
    else:
        out["reading"] = (
            f"no restraint residual exceeds {RESTRAINT_SIGMA_BAR:g}x its "
            f"requested sigma (§15.2). This is evidence that the "
            f"restraints and the data are not in open conflict; it is not "
            f"a statement that the restraints are appropriate - a "
            f"restraint to a wrong target with a loose sigma also lands "
            f"here. " + SU_UNDERESTIMATED)
    return out


# --------------------------------------------------------------------- #
# 5. shift / esd                                                         #
# --------------------------------------------------------------------- #

def shift_esd_reading(final_max: float) -> str | None:
    """Four candidate directions when max shift/esd exceeds 1.5 (§17.5).

    Returns None below the bar - saying nothing is the correct output for
    "this check did not fire" (P12). The four directions are the ones the
    IUCr editors ask authors about verbatim: "Author immediately asked to
    identify the problem (Flack parameter? extinction parameter? H atoms?
    disorder?)".
    """
    if abs(final_max) <= SHIFT_ESD_BAR:
        return None
    return (
        f"max shift/esd = {final_max:g} exceeds {SHIFT_ESD_BAR:g}, the "
        f"IUCr editorial criterion for poor convergence (§17.5: \"Poor "
        f"convergence - maximum shift/s.u. > 1.5\"). Four candidate "
        f"directions, none of them a conclusion: (1) simply not converged "
        f"yet - run more cycles and see whether the maximum falls; "
        f"(2) correlated parameters trading against each other - "
        f"occupancy vs U, the Flack parameter, the extinction parameter; "
        f"(3) a wrong element on the moving site, where Z and U absorb "
        f"one another; (4) an oscillating disorder split or a restrained "
        f"group being pulled two ways. The IUCr wording asks exactly "
        f"this: \"Flack parameter? extinction parameter? H atoms? "
        f"disorder?\". " + SU_UNDERESTIMATED)


# --------------------------------------------------------------------- #
# 6. free variables (FVAR) with their esds                               #
# --------------------------------------------------------------------- #

#: SHELXL prints one parameter listing per least-squares cycle, verbatim:
#:
#:      N      value        esd    shift/esd  parameter
#:
#:      1     0.31623     0.00074     0.000    OSF
#:      2     0.70179     0.00130     0.001   FVAR  2
#:
#: The overall scale is free variable 1 (OSF); the disorder occupancies are
#: 2..n and are exactly the k of a SHELX sof code +/-(10k+p). The .res
#: carries the refined VALUES only - the esd, which is the entire basis of
#: an occupancy verdict, exists nowhere else but here.
_PARAM_HEADER = re.compile(r"^\s*N\s+value\s+esd\s+shift/esd\s+parameter\s*$",
                           re.M)
_FVAR_ROW = re.compile(
    r"^\s*\d+\s+(-?[\d.]+|\*+)\s+([\d.]+|\*+)\s+(-?[\d.]+|\*+)\s+"
    r"(OSF|FVAR\s+(\d+))\s*$")


def _num(tok: str) -> float | None:
    """SHELXL prints '******' when a value overflows its field."""
    if "*" in tok:
        return None
    try:
        return float(tok)
    except ValueError:
        return None


def parse_free_variables(text: str) -> dict[int, dict[str, Any]] | None:
    """Refined free variables and their esds from the LAST cycle listing.

    -> {1: {"name": "OSF", ...}, 2: {"name": "FVAR 2", "value", "su",
    "shift_esd"}, ...} keyed by the SHELX free-variable number, so a
    disorder group's fvar_index indexes it directly. None when the job
    printed no parameter listing at all (l_s = 0 refines nothing, and a
    ratio with no s.u. must read as "not determined", never as 0).
    """
    # end(), not start(): the leading `\s*` swallows the blank line before
    # the header, so start() would point one line too early
    ends = [m.end() for m in _PARAM_HEADER.finditer(text)]
    if not ends:
        return None
    out: dict[int, dict[str, Any]] = {}
    for ln in text[ends[-1]:].splitlines():
        if ln.strip().startswith("Mean shift/esd"):
            break
        m = _FVAR_ROW.match(ln)
        if not m:
            if ln.strip() and not ln.strip()[0].isdigit():
                break
            continue
        k = 1 if m.group(4).startswith("OSF") else int(m.group(5))
        out[k] = {"name": "OSF" if k == 1 else f"FVAR {k}",
                  "value": _num(m.group(1)), "su": _num(m.group(2)),
                  "shift_esd": _num(m.group(3))}
    return out or None
