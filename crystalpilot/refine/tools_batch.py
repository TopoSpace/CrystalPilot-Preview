"""Batch hypothesis tests on throw-away branches: ghost_test, element_scan.

pa1 (32 cells, 2026-09) showed the agents running the same four-step loop
by hand for every atom or element they wanted to test - branch ->
edit_atoms -> refine/run_shelxl -> checkout - and losing the thread:

- hex-l2-r2: 84 branch / 74 checkout / 82 edit_atoms / 94 refine calls;
  two full ghost passes over the framework (branch names ghost_test_<atom>
  then ghost_test2_<atom>; 25 atoms x 4 calls ~ 100 calls, 33:56-36:18).
- cage-l2-r2: 116 branch / 78 checkout / 100 edit_atoms / 106 run_shelxl.
- cage-l0-r1: three element ladders over the six metal sites (7, 9 and 3
  candidates; ~30 + ~36 + ~12 calls, ~25 min) whose conclusion was "R
  cannot tell" - R fell monotonically with Z on an incomplete, unmasked
  model (Cr 0.258 -> Br 0.247), which is exactly what such a model does.
- hex-l1-r1: identical coordinates, Zn 0.0817 vs Zr 0.0904; the R ladder
  picked Zn on a 79%-void cell with no mask while every chemical signal
  (CN 8, M-O 2.12-2.24 A, mu3-O capped M6, wavelength on the Zr K edge,
  +2.2 e/A^3 residual ON the Zn sites) said Zr.
- Across the batch 166 anonymous ghost/delete branches and 66 element
  branches; more than once a candidate was compared against another
  branch's head instead of the node it was cut from.

One call now runs the whole ladder under the project lock: one baseline
(re-checked-out from disk before every candidate), one reference
refinement with the same protocol so deltas are like-for-like, one table.
Throw-away nodes live on branches named diag/<tool>/<baseline>/<candidate>
and carry a diagnostic note, and the baseline is checked out again when
the call returns - on failure too. Verdicts come with their criterion;
element_scan ranks scattering-power evidence but never picks an element.
Both tools are bounded: candidates per call, a wall-clock budget that is
checked BEFORE each candidate (an in-process refinement cannot be
interrupted, so the budget is honoured by not starting what will not
fit), and a message that names what was not tested.

ka1 (2026-09) added the free-occupancy protocol. element_scan used to set
grad_occupancy and run its ordinary all-free refinement, which does not
refine an occupancy: the atom's own ADP is 1:1 correlated with it and
absorbs the whole scattering-power mismatch, and Levenberg-Marquardt
damping on a few-hundred-parameter model starves the lone occupancy
shift. All three cage-lane calls came back with occupancy exactly 1.000
on every row, so occupancy x Z degenerated into Z, "full-occupancy Cl vs
full-occupancy O" dug a -14 e/A^3 hole, Cl was "excluded", and both arms
shipped an O where the published structure has Cl. The occupancy is now
refined ALONE first (every site and ADP held - a one-parameter least
squares), exactly as probe_site has always done it, and the electron
count is read one-directionally: how many electrons sit there, plus the
elements whose Z brackets that count - never a winner.
"""
from __future__ import annotations

import json
import math
import re
import time
from typing import Any

from ..tools.base import ToolContext, ToolResult
from .toolbase import _ProjectTool

#: per-call bounds: each candidate costs one checkout + one refinement
MAX_GHOST_CANDIDATES = 12
MAX_SCAN_ELEMENTS = 8
DEFAULT_BUDGET_S = 900
#: hard ceiling - codex's own tool timeout is 3900 s and other calls on
#: the same project give up queueing after QUEUE_MAX_S (1800 s)
MAX_BUDGET_S = 3000
MIN_BUDGET_S = 60
MAX_CYCLES = 20
#: stage A of a free-occupancy test (the occupancy alone, every site and
#: ADP in the model held): a one-parameter least squares converges in this
#: many cycles, where a fully free refinement lets Levenberg-Marquardt
#: damping - and the atom's own ADP - starve a lone occupancy
OCC_ONLY_CYCLES = 3
#: an ADP below this is not a displacement: an atom carrying the wrong
#: element drives its own U down through zero to compensate, and an
#: occupancy measured at that held U measures the compensation, not the
#: site. Generic - the fence is on the ADP, never on an element
U_MIN_PHYSICAL = 0.005
U_MAX_PHYSICAL = 0.50
U_FALLBACK = 0.05

#: ghost criterion - the R1 fence. It only discriminates when a real atom
#: of the candidate's weight would clear it on THIS model (_detectability):
#: pa2 cage-l0-r1 (R1 0.25, 60% void unmasked) a C moves R1 by ~0.001, so
#: "< 0.002" was read as "ghost" for 66 atoms, 22 of them real. Below the
#: floor the verdict rests on the returning peak. chem/asu_sanity.py's
#: ghost_atom_suspect advice defers to the verdicts given here.
GHOST_R1_RISE = 0.002
GHOST_PEAK_REAL = 1.0        # e/A^3 returning at the vacated site
GHOST_PEAK_NONE = 0.5
SITE_RADIUS_A = 0.7          # sphere read around the vacated site
NEIGHBOUR_CUTOFF_A = 2.8
RIPPLE_ZONE_A = 1.3          # 1-2 e/A^3 termination ripples next to a metal

#: ripple pre-verdict (ka1 cage-tools-r1, 2026-09-03): 113 sites tested,
#: 0 ghost. Among them Fourier ripples 0.72-1.05 A from a Zr with
#: Uiso = -0.001 came back 'real' - of course a ripple returns after the
#: deletion, that is what a ripple IS - so the only deletion licence sat
#: behind acknowledge_real and the agent had to force 96 deletes through
#: it. A site that close to a much heavier atom is not an independent
#: atom and the delete/refine test cannot say anything about it. The fence
#: is radii- and Z-based, no element list and no fixed distance:
#: "much heavier" = Z_neighbour >= RIPPLE_Z_FACTOR x Z_site; "impossibly
#: close" = inside the covalent-radii sum of the pair minus
#: RIPPLE_BOND_SLACK_A (the shortest bond those two elements could form);
#: "carries no density of its own" = Uiso <= 0 or occ*Z below
#: RIPPLE_ELECTRON_FRACTION of the neighbour's occ*Z.
RIPPLE_Z_FACTOR = 2.0
RIPPLE_BOND_SLACK_A = 0.25
RIPPLE_ELECTRON_FRACTION = 0.10

#: real_kind indicators (T1.7b): a 'real' verdict says the density is
#: GENUINE, not that an atom belongs there. Density that is real in the
#: Fourier sense can still be an average no atom label represents - an
#: average over stacking faults / layer offsets, a modulated or
#: superstructure whose satellites were integrated into the Bragg data, or
#: diffuse scattering folded into it. Naming such density is what produced
#: the ka1 cage lane's anonymous atoms and its forced-deletion loops. Each
#: fence below is read against THIS model's own scale (its framework
#: median) or against the pair's own covalent radii, so none is tuned to a
#: crystal, an element or a structure class, and none of them touches a
#: verdict.
#: (1) smeared, PRIMARY: a site at FULL occupancy whose Ueq is this many
#: times the framework median and above SMEAR_UEQ_MIN_A2 is not an atom
#: vibrating harder - it is density spread over positions (U 0.15 A^2 is
#: already a 0.39 A rms displacement). At partial occupancy a large U is
#: just the ordinary occupancy-ADP correlation, hence the occupancy leg.
SMEAR_UEQ_FACTOR = 3.0
SMEAR_UEQ_MIN_A2 = 0.15
SMEAR_FULL_OCC = 0.98
#: (2) near-regular chain/plane of sub-atomic peaks, PRIMARY: >= 3
#: candidates whose nearest-neighbour spacings agree to CHAIN_SPACING_TOL,
#: at a spacing that is NOT a bond for those elements (below
#: CHAIN_BOND_SHORT_FACTOR x their covalent-radii sum = peaks sampling one
#: continuous ridge; above the sum + CHAIN_BOND_LONG_A = a lattice-like
#: repeat with no chemistry), each holding less than SUB_ATOMIC_E_FRACTION
#: of the framework's median electron count. A real aliphatic chain is
#: regular too - it sits INSIDE the bond window and is not sub-atomic.
CHAIN_MIN_MEMBERS = 3
CHAIN_SPACING_TOL = 0.15
CHAIN_BOND_SHORT_FACTOR = 0.8
CHAIN_BOND_LONG_A = 0.5
SUB_ATOMIC_E_FRACTION = 0.5
#: (3) symmetry-image overlap, PRIMARY: two images of the SAME atom closer
#: than the shortest bond that element could form with itself (2 x its
#: covalent radius) are not two atoms - the site sits just off a symmetry
#: element and the space group folds its own image onto it. Distances
#: below IMAGE_SELF_MIN_A are the site itself (a special position), which
#: is ordinary crystallography and never fires.
IMAGE_SELF_MIN_A = 0.05
#: (4) isolated, SUPPORTING: no model atom within the pair's covalent-radii
#: sum + ISOLATION_SLACK_A, i.e. the density bonds to nothing. An ordinary
#: lattice solvent is isolated too, so this never raises the flag alone.
ISOLATION_SLACK_A = 0.45
#: (5) off-site, SUPPORTING: the returning density is not centred on the
#: vacated coordinates (the value AT the old site is below this fraction of
#: the largest value in the SITE_RADIUS_A sphere) - what a ridge passing
#: nearby looks like, and also what a simply mispositioned atom looks like.
OFF_SITE_FRACTION = 0.5

#: element_scan readiness fences
UNASSIGNED_PEAK_E = 1.5
UNASSIGNED_MIN_D_A = 1.0
PACKING_VOID_FRACTION = 0.5
HIGH_R1 = 0.20

#: -- electron counts on an incomplete model ------------------------------
#: A DISCLOSED HEURISTIC, not a verdict. Above this R1 every electron count
#: read off the model (omit-map integral, refined occupancy x Z) is biased
#: LOW: Fc is missing scattering everywhere, the overall scale absorbs part
#: of Fo, and the count at one site under-reads. ka1 cage (2026-09): the
#: model at R1 0.16-0.23 measured ~10 e at a site the published structure
#: has as Cl (17 e), and both arms delivered O there.
LOW_COUNT_R1 = 0.15
#: how far ABOVE a low-biased count candidates stay in play (the cage case
#: under-read by a factor 1.7; 2.0 keeps that inside the proposal)
LOW_COUNT_FACTOR = 2.0
#: counting accuracy of an electron count on a converged model
COUNT_TOL_REL = 0.15
#: occupancy x Z "clusters" when the largest count is within this factor of
#: the smallest: the candidates all scaled to the same electron count and
#: the scan cannot separate them (form-factor shape alone spreads a real
#: cluster by a few tens of percent across a row of the periodic table)
COUNT_CLUSTER_FACTOR = 1.6
#: never propose more than this many candidates from one measured count
#: (the band is reported whole below this - thinning must not be able to
#: drop the heavy end, which is the end an incomplete model hides)
MAX_BRACKET_ELEMENTS = 12
#: noble gases and elements that do not occur in ordinary crystals - the
#: bracket is over the periodic table, these are the only exclusions
_NO_BRACKET = {"He", "Ne", "Ar", "Kr", "Xe", "Rn", "Tc", "Pm", "Po", "At",
               "Fr", "Ra", "Ac", "Pa", "Np"}

ELEMENT_RULE = (
    "elements by chemistry, not by R (元素身份由化学定，不由 R 定): coordination "
    "number and geometry, M-O / M...M distances, cluster motif, synthesis, "
    "wavelength vs absorption edge decide. The scan measures scattering "
    "power at the site, which separates rows of the periodic table, not "
    "neighbours (Zn/Cu, Zr/Nb/Y); a lower R1 is not an identification.")

GHOST_CRITERION = (
    "ripple (checked BEFORE the delete/refine test, from the baseline "
    "model alone) = the site sits closer to a much heavier neighbour "
    f"(Z >= {RIPPLE_Z_FACTOR:g}x its own) than the two covalent radii sum "
    f"minus {RIPPLE_BOND_SLACK_A} A - inside the shortest bond those "
    "elements could form - AND carries no density of its own (Uiso <= 0, "
    f"or occ*Z below {RIPPLE_ELECTRON_FRACTION:g} of the neighbour's): a "
    "Fourier / series-termination ripple of the heavy atom, not an "
    "independent atom. The delete-and-refine test cannot judge it (the "
    "ripple comes back after the deletion because it is the heavy atom's "
    "own truncation artefact), so no returning peak or dR1 is read as "
    "evidence for it; deleting it needs no acknowledge_real. "
    f"real = a peak >= {GHOST_PEAK_REAL} e/A^3 returns within "
    f"{SITE_RADIUS_A} A of the vacated site AND R1 rises >= {GHOST_R1_RISE}; "
    f"ghost = nothing returns (< {GHOST_PEAK_NONE} e/A^3) AND R1 changes "
    f"< {GHOST_R1_RISE} (unchanged or better); anything else = inconclusive "
    "with the reason. Deltas are against a reference refinement of the "
    "baseline with the SAME engine and cycles, not against the node's "
    "recorded metrics. SENSITIVITY FLOOR: the R1 fence is only informative "
    "when a real atom of the candidate's weight would clear it on this "
    "model (expected_delta_r1_if_real >= "
    f"{GHOST_R1_RISE}, r1_fence_informative=true per row); when it is below "
    "the detectability floor (high R1, unmasked void, light or partial "
    "atom) dR1 cannot "
    "separate real from ghost and the verdict rests on the returning peak "
    f"alone: >= {GHOST_PEAK_REAL} e/A^3 = real, < {GHOST_PEAK_NONE} = ghost "
    "(unless R1 still rose >= the fence, which says the atom absorbed "
    "density that is not localised there = inconclusive), between = "
    "inconclusive. Every verdict comes with a disposition: 'ghost' is the "
    "only deletion licence; 'real' atoms are named, refined at free "
    "occupancy, or absorbed in the mask with an acknowledged reason "
    "(edit_atoms refuses to delete them silently - the verdict is on the "
    "project's ghost ledger); 'inconclusive' is kept and re-tested after "
    "the model is more complete. A group judged real is real as a unit.")

#: what to do with each verdict - travels with every row and, for 'real',
#: onto the ghost ledger that edit_atoms consults before a delete
DISPOSITION = {
    "real": ("keep: give it a chemical identity (guest / solvent / "
             "counter-ion / disorder component / missing framework atom), "
             "or refine it at free occupancy (element_scan free_occupancy "
             "/ probe_site), or absorb it into the solvent mask by deleting "
             "WITH acknowledge_real - never delete it silently. real means "
             "the density is genuine, not that it is an atom; if "
             "`real_kind_hint` is possibly_non_atomic, do not label it "
             " - check the data-side indicators first"),
    "ghost": "delete",
    "ripple": ("delete: it is the heavy neighbour's Fourier / termination "
               "ripple, not an independent atom - edit_atoms takes it "
               "WITHOUT acknowledge_real (the verdict is on the ghost "
               "ledger either way). Report it as a ripple, and if such "
               "peaks are everywhere treat the cause (absorption / "
               "extinction correction, resolution cut, scattering "
               "factors), not the peaks"),
    "inconclusive": ("keep for now: not a deletion licence - re-test after "
                     "the model is more complete (mask, elements, ADPs) and "
                     "read the map and the chemistry"),
}
GROUP_REAL_NOTE = ("the group is real as a unit; single-member re-tests are "
                   "not deletion licences for its members")

#: how the indicators combine into real_kind_hint. Disclosed with every
#: row that carries the hint - the agent must be able to check the reading.
REAL_KIND_CRITERION = (
    "real_kind_hint reads the SAME 'real' verdict for what the density "
    "physically IS, and never changes it: 'atom_like' = no indicator "
    f"fired; 'possibly_non_atomic' = at least one PRIMARY indicator fired "
    f"(smeared_adp: Ueq >= {SMEAR_UEQ_FACTOR:g}x the model's own framework "
    f"median and >= {SMEAR_UEQ_MIN_A2} A^2 at occupancy >= "
    f"{SMEAR_FULL_OCC:g}; regular_sub_atomic_chain: >= {CHAIN_MIN_MEMBERS} "
    f"candidates spaced regularly to {CHAIN_SPACING_TOL:.0%} at a distance "
    "that is no bond for those elements, each below "
    f"{SUB_ATOMIC_E_FRACTION:g} of the framework's median electron count; "
    "symmetry_image_overlap: the site's own symmetry image closer than "
    "2 x its covalent radius), OR at least two SUPPORTING ones "
    "(isolated_density, returning_density_off_site - an ordinary guest atom "
    "shows either one, so neither raises the flag alone). No indicator "
    "establishes a non-atomic origin and none is a verdict: each is "
    "reported with its measured numbers and its threshold, and the hint "
    "only says which DATA-side check settles the question "
    "(non_atomic_note). Checks that could not be measured on this model are "
    "listed in non_atomic_checks_unavailable rather than assumed absent.")

#: what possibly_non_atomic means and how to settle it - DATA side, before
#: any label is put on the site (tool names are the registry's own)
NON_ATOMIC_NOTE = (
    "real means the density is genuine, NOT that it is an atom. Density "
    "that is real in the Fourier sense can be an AVERAGE that no atom "
    "label represents: (a) stacking faults / layer offsets - the cell "
    "averages over the fault and leaves smeared, ridge-like density "
    "between the layers or along the stacking direction; (b) a modulated "
    "structure or a superstructure - density that repeats with a "
    "periodicity this cell does not have, usually with systematically weak "
    "'extra' reflections (satellites) integrated into the main data; (c) "
    "diffuse scattering folded into the Bragg intensities. Modelling any "
    "of these as atoms is what produces unnamed atoms and forced-deletion "
    "loops. Settle it on the DATA side BEFORE naming the site: "
    "reflection_statistics (index-parity classes = pseudo-translation / "
    "supercell evidence, <|E^2-1|>, per-shell R_int / completeness / "
    "<I/sigma> - a superstructure shows up as one parity class far weaker "
    "than the others), audit_reflection_data (duplicate-observation "
    "consistency, R_int in the current Laue class vs triclinic, "
    "systematic-absence violations, and the R1-vs-R_int mismatch that "
    "points at twinning or modulation rather than noise), check_symmetry "
    "(is this cell and space group the right description of the lattice at "
    "all), and inspect_map at the site (compact peak, or a ridge running "
    "between layers?). If the frames are still available, satellites and "
    "diffuse streaks are visible BETWEEN the Bragg rows - that is the "
    "direct evidence. If the data say average, report an average - a "
    "solvent mask or a disorder model with an honest description - instead "
    "of naming an atom that is not there.")


class _Refusal(Exception):
    """A clean refusal before/while running - turned into ToolResult.failure."""


def _now() -> float:
    return time.monotonic()


def _split_group(item: Any) -> list[str]:
    """'O7' -> ['O7']; 'O7+O8' / 'O7,O8' / ['O7','O8'] -> ['O7','O8']."""
    if isinstance(item, (list, tuple)):
        parts = [str(x) for x in item]
    else:
        parts = re.split(r"[+,\s]+", str(item).strip())
    return [p.strip() for p in parts if p and p.strip()]


def _resolve_labels(xs, wanted: list[str]) -> tuple[list[str], list[str], dict]:
    """Case-insensitive label match (same rule as edit_atoms): returns the
    model's own spelling of each label, the misses, and close matches."""
    import difflib
    by_upper: dict[str, list[str]] = {}
    for sc in xs.scatterers():
        by_upper.setdefault(sc.label.upper(), []).append(sc.label)
    found, missing, close = [], [], {}
    for lbl in wanted:
        hit = by_upper.get(lbl.upper())
        if hit and len(hit) == 1:
            found.append(hit[0])
        else:
            missing.append(lbl)
            close[lbl] = [l for c in difflib.get_close_matches(
                lbl.upper(), list(by_upper), n=2, cutoff=0.6)
                for l in by_upper[c]]
    return found, missing, close


def _element_symbol(scattering_type: str) -> str:
    m = re.match(r"[A-Za-z]{1,2}", scattering_type.strip())
    return m.group(0).capitalize() if m else scattering_type.strip()


def _atomic_number(el: str) -> int | None:
    try:
        from cctbx.eltbx import tiny_pse
        return int(tiny_pse.table(el).atomic_number())
    except Exception:  # noqa: BLE001 - unknown symbol
        return None


def _valid_scattering_type(el: str) -> bool:
    try:
        from cctbx.eltbx import xray_scattering
        xray_scattering.it1992(el, True)
        return True
    except Exception:  # noqa: BLE001 - not in the IT1992 table
        return False


# ==========================================================================
# electron counts: how far to trust one, and which elements it brackets.
# Shared by element_scan (occupancy x Z), probe_site and
# integrate_difference_density so all three read a count the same way.
# ==========================================================================

def latest_r1(ses) -> float | None:
    """R1 of the session's most recent refinement, or None."""
    try:
        snap = ses.last_refinement()
    except Exception:  # noqa: BLE001 - a session without history
        return None
    r1 = getattr(snap, "r1_strong", None) if snap is not None else None
    return float(r1) if isinstance(r1, (int, float)) else None


def count_is_low_biased(r1: float | None) -> bool:
    """Is the model far enough from converged that electron counts under-read?"""
    return isinstance(r1, (int, float)) and float(r1) > LOW_COUNT_R1


def low_count_note(r1: float | None) -> str | None:
    """The calibration sentence for an electron count read on an incomplete
    model - None when the model is good enough for the count to stand."""
    if not count_is_low_biased(r1):
        return None
    return (
        f"CALIBRATION (disclosed heuristic, not a verdict): the model's "
        f"latest R1 is {float(r1):.3f} > {LOW_COUNT_R1}. Electron counts "
        f"read off a model this far from converged are systematically LOW - "
        f"Fc is missing scattering everywhere, the overall scale absorbs "
        f"part of Fo, and an omit map or a refined occupancy under-reads at "
        f"every site (ka1 cage 2026-09: ~10 e measured at a site the "
        f"published structure has as Cl = 17 e, and the site was delivered "
        f"as O). Read the number as a LOWER BOUND: on this model "
        f"'~8 e supports O' is NOT a safe reading. Elements up to about "
        f"{LOW_COUNT_FACTOR:g}x the measured count stay in play until the "
        f"model is complete (all atoms placed, solvent masked, ADPs and "
        f"weights settled) and the count is measured again.")


def _bracket_pool() -> list[tuple[int, str]]:
    """(Z, symbol) of every element that occurs in ordinary crystals, from
    the periodic table itself - not a curated candidate list."""
    from cctbx.eltbx import tiny_pse
    out: list[tuple[int, str]] = []
    for z in range(3, 93):
        try:
            sym = tiny_pse.table(z).symbol()
        except Exception:  # noqa: BLE001 - gaps in the table
            continue
        if sym in _NO_BRACKET:
            continue
        out.append((z, sym))
    return out


def bracketing_elements(n_electrons: float | None, *,
                        low_biased: bool = False,
                        max_n: int = MAX_BRACKET_ELEMENTS) -> list[str]:
    """Elements whose atomic number BRACKETS a measured electron count.

    Element-generic by construction: the pool is the periodic table (minus
    noble gases and elements absent from ordinary crystals) and the band is
    computed from the count, so nothing here is tuned to one crystal or one
    element. The band is [n/(1+COUNT_TOL_REL), n*(1+COUNT_TOL_REL)], widened
    upwards to n*LOW_COUNT_FACTOR when the count is known to be biased low
    (low_count_note). The nearest pool element below and above the band are
    always included, so the count is bracketed even when nothing falls
    inside it - a site measured at 10 e on an incomplete model therefore
    proposes the halogens as well as O/F, which is exactly the reading the
    cage lane missed.
    """
    if not isinstance(n_electrons, (int, float)) or n_electrons <= 0:
        return []
    n = float(n_electrons)
    lo = n / (1.0 + COUNT_TOL_REL)
    hi = n * (LOW_COUNT_FACTOR if low_biased else (1.0 + COUNT_TOL_REL))
    pool = _bracket_pool()
    inside = [(z, s) for z, s in pool if lo <= z <= hi]
    below = [(z, s) for z, s in pool if z < lo]
    above = [(z, s) for z, s in pool if z > hi]
    picked = list(inside)
    if below:
        picked.append(below[-1])
    if above:
        picked.append(above[0])
    picked = sorted(set(picked))
    if len(picked) > max_n >= 4:
        # keep both ends of the band (the heavy end is the one an
        # incomplete model hides, and dropping it is the whole failure this
        # proposal exists to prevent) and the elements the count sits on as
        # measured; fill the rest EVENLY across the band, never towards n
        must = {picked[0], picked[-1]}
        must.update(sorted(picked, key=lambda p: abs(p[0] - n))[:2])
        rest = [p for p in picked if p not in must]
        keep = max(max_n - len(must), 0)
        step = len(rest) / float(keep) if keep else 0.0
        must.update(rest[min(len(rest) - 1, int(i * step))]
                    for i in range(keep))
        picked = sorted(must)
    return [s for _z, s in picked]


def electron_bracket_note(n_electrons: float | None, elements: list[str],
                          low_biased: bool) -> str | None:
    """One-directional reading of an electron count: what the site holds,
    plus the elements that count brackets - never a winner."""
    if not elements or not isinstance(n_electrons, (int, float)):
        return None
    band = (f"up to ~{n_electrons * LOW_COUNT_FACTOR:.0f} e (the count is "
            f"biased low on this model)" if low_biased else
            f"~{n_electrons * (1 + COUNT_TOL_REL):.0f} e")
    return (
        f"the site holds ~{n_electrons:.1f} electrons (measured), plausibly "
        f"{band}. Elements whose Z brackets that count AT FULL OCCUPANCY: "
        f"{elements}. The count alone cannot tell them apart - and a heavier "
        f"element at partial occupancy gives the SAME count (probe_site's "
        f"occupancy x Z ladder), so a heavy candidate is never excluded by "
        f"this number alone. Decide by chemistry (coordination, distances, "
        f"the synthesis, the solvent the crystal was grown from), not by "
        f"this list, and measure again once the model is complete.")


def _ueq_table(xs) -> dict[str, float]:
    uc = xs.unit_cell()
    return {sc.label.upper(): float(sc.u_iso_or_equiv(uc))
            for sc in xs.scatterers()}


def _neighbours(xs, site, exclude: set[str],
                cutoff: float = NEIGHBOUR_CUTOFF_A) -> list[dict[str, Any]]:
    """Nearest model atoms (symmetry-aware) around a fractional site."""
    uc = xs.unit_cell()
    ops = xs.space_group().all_ops()
    out = []
    for sc in xs.scatterers():
        if sc.label.upper() in exclude:
            continue
        best = None
        for op in ops:
            s = op * sc.site
            d = uc.distance(
                tuple(site[k] - math.floor(site[k] - s[k] + 0.5)
                      for k in range(3)), s)
            if best is None or d < best:
                best = d
        if best is not None and best <= cutoff:
            out.append({"label": sc.label,
                        "element": _element_symbol(sc.scattering_type),
                        "occupancy": round(float(sc.occupancy), 3),
                        "d_A": round(float(best), 2)})
    out.sort(key=lambda n: n["d_A"])
    return out[:6]


def _atoms_info(xs, labels: list[str]) -> list[dict[str, Any]]:
    """Site / element / occupancy / Ueq / neighbours of each label, read
    from the model BEFORE it is edited."""
    uc = xs.unit_cell()
    by_upper = {sc.label.upper(): sc for sc in xs.scatterers()}
    excl = {l.upper() for l in labels}
    out = []
    for lbl in labels:
        sc = by_upper[lbl.upper()]
        out.append({
            "label": sc.label,
            "element": _element_symbol(sc.scattering_type),
            "site_frac": [round(float(x), 4) for x in sc.site],
            "_site": tuple(float(x) for x in sc.site),
            "occupancy": round(float(sc.occupancy), 3),
            "ueq_baseline": round(float(sc.u_iso_or_equiv(uc)), 4),
            "neighbours": _neighbours(xs, sc.site, excl),
        })
    return out


def _ripple_check(atom: dict[str, Any]) -> dict[str, Any] | None:
    """Is this site a Fourier ripple of a much heavier neighbour rather
    than an independent atom? Read from the BASELINE model alone, before
    anything is deleted.

    `atom` is one _atoms_info row (element, occupancy, ueq_baseline,
    neighbours with label/element/occupancy/d_A). Element-generic: the
    fence is the pair's own covalent-radii sum and the two atomic numbers,
    so it reads the same for a C next to Zr, an O next to Pb or an N next
    to U, and it never fires between two atoms of comparable weight.

      1. nearest neighbour with Z >= RIPPLE_Z_FACTOR x the site's Z;
      2. it sits closer than covalent_radius(site) +
         covalent_radius(neighbour) - RIPPLE_BOND_SLACK_A: inside the
         shortest bond those two elements could form, so no chemistry
         puts an atom there;
      3. the site carries no density of its own - Uiso <= 0 (a refinement
         that pushed the ADP through zero) or occ*Z below
         RIPPLE_ELECTRON_FRACTION of the neighbour's occ*Z.

    Returns the evidence (also the row's reading), or None.
    """
    from ..chem.connectivity import covalent_radius
    el = str(atom.get("element") or "")
    z_site = _atomic_number(el)
    if not z_site:
        return None
    ueq = atom.get("ueq_baseline")
    occ = float(atom.get("occupancy") or 0.0)
    best = None
    for nb in atom.get("neighbours") or []:
        z_nb = _atomic_number(str(nb.get("element") or ""))
        if not z_nb or z_nb < RIPPLE_Z_FACTOR * z_site:
            continue
        d = nb.get("d_A")
        if not isinstance(d, (int, float)):
            continue
        if best is None or d < best[0]:
            best = (float(d), nb, z_nb)
    if best is None:
        return None
    d, nb, z_nb = best
    r_sum = covalent_radius(el) + covalent_radius(str(nb["element"]))
    if d >= r_sum - RIPPLE_BOND_SLACK_A:
        return None
    occ_nb = float(nb.get("occupancy") or 1.0)
    e_site = occ * z_site
    e_nb = occ_nb * z_nb
    frac = (e_site / e_nb) if e_nb > 0 else None
    triggers = []
    if isinstance(ueq, (int, float)) and ueq <= 0:
        triggers.append(f"Uiso {ueq:+.4f} is not positive")
    if frac is not None and frac <= RIPPLE_ELECTRON_FRACTION:
        triggers.append(f"it holds {e_site:.1f} electrons against the "
                        f"neighbour's {e_nb:.1f} ({frac:.0%})")
    if not triggers:
        return None
    return {
        "neighbour": nb["label"], "neighbour_element": nb["element"],
        "d_A": round(d, 2),
        "covalent_sum_A": round(r_sum, 2),
        "fence_A": round(r_sum - RIPPLE_BOND_SLACK_A, 2),
        "z_site": z_site, "z_neighbour": z_nb,
        "electron_fraction": (round(frac, 3) if frac is not None else None),
        "ueq_baseline": ueq,
        "trigger": " and ".join(triggers),
        "reading": (
            f"{d:.2f} A from {nb['label']} ({nb['element']}, Z {z_nb}) - "
            f"inside the shortest {nb['element']}-{el} bond those elements "
            f"could form (covalent radii sum {r_sum:.2f} A less "
            f"{RIPPLE_BOND_SLACK_A} A = {r_sum - RIPPLE_BOND_SLACK_A:.2f} A) "
            f"and {' and '.join(triggers)}: this is a Fourier / "
            "series-termination ripple of the heavy neighbour, not an "
            "independent atom. A ripple comes back after the deletion "
            "because it is the heavy atom's own truncation artefact, so "
            "neither the returning peak nor dR1 is evidence for it. "
            "Delete it - edit_atoms needs no acknowledge_real for a "
            "ripple verdict; disclose it as a heavy-atom ripple, and if "
            "such peaks ring the heavy atoms everywhere, treat the cause "
            "(absorption / extinction correction, resolution cut, "
            "scattering factors) rather than the peaks."),
    }


def _group_ripple(infos: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Ripple evidence for a candidate: every member must be a ripple (a
    group is judged as a unit, and one real member makes the group real)."""
    hits = [_ripple_check(a) for a in infos]
    if not hits or any(h is None for h in hits):
        return None
    if len(hits) == 1:
        return hits[0]
    out = dict(hits[0])
    out["members"] = [{"atom": a["label"], **{k: h[k] for k in
                                              ("neighbour", "d_A", "trigger")}}
                      for a, h in zip(infos, hits)]
    out["reading"] = ("every member of this group is a ripple of a much "
                      "heavier neighbour: " + hits[0]["reading"])
    return out


def _fence_note(rows: list[dict[str, Any]],
                reference_residual_max: Any) -> str | None:
    """One sentence when the R1 fence discriminated nothing in this call.

    Fires when every tested candidate sat below the detectability floor
    (r1_fence_informative=false) and not one came back 'ghost' - the pa2 /
    ka1 pattern where 113 sites produced 0 ghosts and the middle band was
    read as 'real'. It says what the fence could NOT do and which evidence
    can still separate the cases; it never upgrades a verdict.
    """
    tested = [r for r in rows if r.get("verdict") and not r.get("error")]
    if not tested:
        return None
    if any(r.get("verdict") == "ghost" for r in tested):
        return None
    if not all(r.get("r1_fence_informative") is False for r in tested):
        return None
    noise = (f"{reference_residual_max} e/A^3"
             if isinstance(reference_residual_max, (int, float))
             else "the baseline's largest residual")
    return (
        f"NO DISCRIMINATING POWER in this call: all {len(tested)} tested "
        f"candidates sat below the detectability floor "
        f"(r1_fence_informative=false) and not one came back 'ghost', so "
        f"dR1 separated nothing here and the verdicts above rest on the "
        f"returning peak alone - read that peak against this model's own "
        f"noise (the baseline's largest residual anywhere is {noise}: a "
        f"peak that does not clearly beat it is noise, not an atom), and "
        f"measure the electrons directly instead of guessing - "
        f"probe_site / element_scan(free_occupancy=true) refine the site's "
        f"occupancy x Z - before calling anything real or deleting it.")


def _site_residuals(ses, sites: list[tuple],
                    radius: float = SITE_RADIUS_A) -> list[dict[str, Any]]:
    """Fo-Fc residual read at given sites of the CURRENT model: max and
    min inside a sphere (a returning peak is rarely centred exactly on
    the old coordinates) plus the interpolated value at the point."""
    from cctbx import maptbx
    from cctbx.array_family import flex

    from ..tools.refinement_tools import difference_map_real
    xs = ses.model
    try:
        _fft, real, _k = difference_map_real(
            ses, xs, f_mask=ses.flags.get("f_mask"))
    except ValueError as e:
        return [{"error": str(e)} for _ in sites]
    uc = xs.unit_cell()
    out = []
    for s in sites:
        cart = uc.orthogonalize(s)
        sel = maptbx.grid_indices_around_sites(
            unit_cell=uc, fft_n_real=real.focus(), fft_m_real=real.all(),
            sites_cart=flex.vec3_double([cart]),
            site_radii=flex.double([radius]))
        vals = real.select(sel)
        if vals.size() == 0:
            out.append({"error": "empty sphere"})
            continue
        out.append({"max": round(float(flex.max(vals)), 2),
                    "min": round(float(flex.min(vals)), 2),
                    "at_site": round(float(real.eight_point_interpolation(s)),
                                     2)})
    return out


def _signed(res: dict[str, Any]) -> float | None:
    if "max" not in res:
        return None
    return res["max"] if abs(res["max"]) >= abs(res["min"]) else res["min"]


def _packing_estimate(xs) -> float | None:
    """Raw vdW-sphere volume of the model over the cell volume (spheres of
    bonded atoms overlap, so dense crystals score >~0.8; a MOF with an
    empty channel scores well below 0.5). Cheap stand-in for the mask's
    void fraction when no mask has been computed."""
    try:
        from cctbx.eltbx import van_der_waals_radii
        vdw = van_der_waals_radii.vdw.table
        vol = 0.0
        for sc in xs.scatterers():
            r = float(vdw.get(_element_symbol(sc.scattering_type), 1.7))
            vol += (4.0 / 3.0 * math.pi * r ** 3 * float(sc.occupancy)
                    * float(sc.multiplicity()))
        return vol / float(xs.unit_cell().volume())
    except Exception:  # noqa: BLE001 - advisory only
        return None


def _detectability(xs, labels: list[str], r1_ref: float | None
                   ) -> dict[str, Any]:
    """Can the R1 fence see an atom of this weight on THIS model?

    Pure function of the baseline model. The candidate's share of the
    scattering (scattering_fraction = occ*Z*m of the candidate over the
    same sum for all non-H atoms) and a heuristic for the R1 rise a REAL
    atom of that weight would produce when removed: delta = occ*Z*sqrt(m)
    / sqrt(sum_j occ_j^2 Z_j^2 m_j) over all non-H atoms (a group sums its
    members in quadrature), expected dR1 ~ sqrt(R1_ref^2 + delta^2) -
    R1_ref - the missing atom's contribution adds in quadrature to the
    residual the model already has. Nothing here is tuned to a crystal
    class: only the model's own scattering-power distribution (any space
    group, via multiplicity) and its reference R1 enter. On a converged
    small-molecule model a C moves R1 by ~0.01; on a high-R1 heavy-atom
    framework by a few thousandths, and a partially occupied light atom
    by far less than the 0.002 fence, which then has no discriminating
    power. r1_fence_informative is None when there is no reference R1.
    """
    want = {lb.upper() for lb in labels}
    num_lin = 0.0        # sum occ*Z*m over the candidate
    num_sq = 0.0         # sum occ^2*Z^2*m over the candidate
    den_lin = 0.0
    den_sq = 0.0
    for sc in xs.scatterers():
        el = _element_symbol(sc.scattering_type)
        if el == "H":
            continue
        z = _atomic_number(el) or 6
        occ = float(sc.occupancy)
        m = float(sc.multiplicity() or 1)
        lin = occ * z * m
        sq = occ * occ * z * z * m
        den_lin += lin
        den_sq += sq
        if sc.label.upper() in want:
            num_lin += lin
            num_sq += sq
    frac = num_lin / den_lin if den_lin > 0 else None
    delta = math.sqrt(num_sq / den_sq) if den_sq > 0 else None
    expected = None
    informative = None
    if delta is not None and isinstance(r1_ref, (int, float)):
        r = max(float(r1_ref), 0.0)
        expected = math.sqrt(r * r + delta * delta) - r
        informative = expected >= GHOST_R1_RISE
    return {
        "scattering_fraction": (round(frac, 5) if frac is not None else None),
        "expected_delta_r1_if_real": (round(expected, 4)
                                      if expected is not None else None),
        "r1_fence_informative": informative,
    }


def _floor_verdict(delta_r1: float, peak: float,
                   expected: float | None) -> tuple[str, str]:
    """Verdict when the R1 fence is below the detectability floor: a real
    atom of this weight would not have moved R1 by the fence, so dR1 <
    fence proves nothing and the returning peak decides. A rise >= the
    fence is still information - more than the atom itself could explain
    - and keeps the 'not localised' reading."""
    floor = (f"dR1 fence below the detectability floor (expected "
             f"<= {expected:.4f} for a real atom of this weight, fence "
             f"{GHOST_R1_RISE}); verdict rests on the returning peak"
             if expected is not None else
             "dR1 fence below the detectability floor for an atom of this "
             "weight; verdict rests on the returning peak")
    if peak >= GHOST_PEAK_REAL:
        return "real", (
            f"a {peak:.2f} e/A^3 peak returns at the vacated site while R1 "
            f"moves {delta_r1:+.4f} - {floor}: the density is real - give "
            "it a chemical identity (guest solvent, counter-ion, disorder "
            "component, missing framework atom), refine it at free "
            "occupancy, or absorb it in the solvent mask with an "
            "acknowledged reason; never keep it anonymous and never delete "
            "it silently")
    if peak < GHOST_PEAK_NONE:
        if delta_r1 >= GHOST_R1_RISE:
            return "inconclusive", (
                f"R1 rises by {delta_r1:+.4f} - more than a real atom of "
                f"this weight could explain (expected <= "
                f"{expected if expected is not None else 0.0:.4f}) - but "
                f"only {peak:.2f} e/A^3 returns at the site: the atom was "
                "absorbing density that is not localised there (disorder, "
                "wrong position, a neighbour's ADP) - inspect_map around "
                "the neighbours before deciding")
        return "ghost", (
            f"nothing returns at the site (max {peak:.2f} e/A^3) - {floor}, "
            f"so R1 {delta_r1:+.4f} carries no information here: no density "
            "supports this atom - delete it")
    return "inconclusive", (
        f"peak {peak:.2f} e/A^3 between the fences and {floor}: borderline "
        "- read the map and the chemistry, do not decide on this number "
        "alone")


def _ghost_verdict(delta_r1: float | None, peak: float | None,
                   nearest_metal: dict | None,
                   fence_informative: bool | None = True,
                   expected_delta_r1: float | None = None,
                   ripple: dict | None = None) -> tuple[str, str]:
    """Four verdicts with their reason. A `ripple` classification (read
    from the baseline model before the test, see _ripple_check) settles
    the site on its own: the delete/refine numbers cannot judge a
    truncation artefact. Otherwise fence_informative=False switches to
    the floor regime (see _detectability): the R1 fence carries no
    information and the verdict rests on the returning peak."""
    if ripple:
        why = ripple["reading"]
        if isinstance(delta_r1, (int, float)) and isinstance(peak, (int, float)):
            why += (f" [the test ran anyway: {peak:.2f} e/A^3 came back and "
                    f"R1 moved {delta_r1:+.4f} - exactly what a ripple does]")
        return "ripple", why
    if delta_r1 is None or peak is None:
        return "inconclusive", "refinement or map read failed - see error"
    if fence_informative is False:
        verdict, reason = _floor_verdict(delta_r1, peak, expected_delta_r1)
    elif peak >= GHOST_PEAK_REAL and delta_r1 >= GHOST_R1_RISE:
        verdict = "real"
        reason = (f"a {peak:.2f} e/A^3 peak returns at the vacated site and "
                  f"R1 rises by {delta_r1:+.4f} (>= {GHOST_R1_RISE}): the "
                  "density is real - give it a chemical identity (guest "
                  "solvent, disorder component, missing framework atom) or "
                  "absorb it in the solvent mask; never keep it anonymous")
    elif peak < GHOST_PEAK_NONE and delta_r1 < GHOST_R1_RISE:
        verdict = "ghost"
        reason = (f"nothing returns at the site (max {peak:.2f} e/A^3) and "
                  f"R1 changes by {delta_r1:+.4f} (< {GHOST_R1_RISE}): no "
                  "density supports this atom - delete it")
    else:
        verdict = "inconclusive"
        if peak >= GHOST_PEAK_REAL:
            reason = (f"a {peak:.2f} e/A^3 peak returns but R1 moves only "
                      f"{delta_r1:+.4f}: real but low-weight density "
                      "(partial occupancy, H-like, or a termination ripple)")
        elif delta_r1 >= GHOST_R1_RISE:
            reason = (f"R1 rises by {delta_r1:+.4f} but only {peak:.2f} "
                      "e/A^3 returns at the site: the atom was absorbing "
                      "density that is not localised there (disorder, wrong "
                      "position, a neighbour's ADP) - inspect_map around "
                      "the neighbours before deciding")
        else:
            reason = (f"peak {peak:.2f} e/A^3 between the fences with R1 "
                      f"{delta_r1:+.4f}: borderline - read the map and the "
                      "chemistry, do not decide on this number alone")
    if nearest_metal and nearest_metal["d_A"] <= RIPPLE_ZONE_A:
        reason += (f" [{nearest_metal['d_A']} A from {nearest_metal['label']}"
                   f" ({nearest_metal['element']}): inside the Fourier-"
                   "ripple zone of a heavy atom, where 1-2 e/A^3 features "
                   "are normal - weigh the peak accordingly]")
    return verdict, reason


# ==========================================================================
# real_kind: is genuine density an ATOM at all? (T1.7b)
#
# ka1 cage (2026-09): 'real' rows were read as "an atom belongs here", the
# agent named what it could and the rest came back as anonymous atoms that
# were force-deleted later. A delete-and-refine test answers "is this
# density genuine?", never "is this density an atom?": an average over
# stacking faults or layer offsets, the satellites of a modulated or
# superstructure, and diffuse scattering folded into the Bragg data all
# return a peak and all raise R1 when removed. The indicators below are
# read from the baseline model and from the numbers the test already has;
# they are advisory, they never enter _ghost_verdict, and each one is
# reported with its measured numbers and its threshold.
# ==========================================================================

def _median(values) -> float | None:
    vals = sorted(float(v) for v in values if isinstance(v, (int, float)))
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def _framework_scale(xs, exclude: set[str]) -> dict[str, Any]:
    """The scale THIS model works at: median Ueq and median electron count
    (occ x Z) over its own non-H atoms, the candidate excluded. Every
    real_kind fence that would otherwise become a fixed number is read
    against these medians, so the rules travel to any structure class."""
    uc = xs.unit_cell()
    ueq: list[float] = []
    electrons: list[float] = []
    for sc in xs.scatterers():
        el = _element_symbol(sc.scattering_type)
        if el == "H" or sc.label.upper() in exclude:
            continue
        try:
            ueq.append(float(sc.u_iso_or_equiv(uc)))
        except Exception:  # noqa: BLE001 - a broken ADP must not stop the read
            pass
        z = _atomic_number(el)
        if z:
            electrons.append(float(sc.occupancy) * z)
    return {"n_framework_atoms": len(ueq),
            "median_ueq": _median(ueq),
            "median_electrons": _median(electrons)}


def _min_image_distance(uc, a, b) -> float:
    """Distance between two fractional sites, `a` taken in the cell image
    nearest to `b` (the same nearest-image rule as _neighbours)."""
    return float(uc.distance(tuple(a[k] - math.floor(a[k] - b[k] + 0.5)
                                   for k in range(3)), b))


def _self_image_distance(xs, site) -> float | None:
    """Shortest distance between a fractional site and a DISTINCT symmetry
    image of itself. Images at ~0 A are the site itself (an atom on a
    special position - ordinary crystallography), so they are skipped;
    lattice translations are not images in this sense. None when the space
    group has no other operation (P1) - the check does not apply there."""
    uc = xs.unit_cell()
    best = None
    for op in xs.space_group().all_ops():
        d = _min_image_distance(uc, site, op * tuple(site))
        if d < IMAGE_SELF_MIN_A:
            continue
        if best is None or d < best:
            best = d
    return best


def _site_symmetry_context(xs, site, radius: float) -> dict[str, Any]:
    """cctbx's own site-symmetry reading of a site: the symmetry element it
    would snap onto within `radius`, how far away it is, and the order of
    the site symmetry there. Empty when the site is on a general position
    by that tolerance."""
    try:
        from cctbx import crystal as _crystal
        sps = _crystal.special_position_settings(
            xs.crystal_symmetry(),
            min_distance_sym_equiv=max(float(radius), IMAGE_SELF_MIN_A))
        ss = sps.site_symmetry(tuple(site))
        if ss.is_point_group_1():
            return {}
        return {"site_symmetry_ops": int(ss.n_matrices()),
                "special_position_op": str(ss.special_op()),
                "distance_to_special_position_A": round(
                    float(ss.distance_moved()), 2)}
    except Exception:  # noqa: BLE001 - advisory context only
        return {}


def _model_non_atomic_signals(xs, infos: list[dict[str, Any]]
                              ) -> dict[str, Any]:
    """Non-atomic indicators readable from the BASELINE model, before the
    candidate is deleted. `infos` are _atoms_info rows.

    Returns {"fired": [...], "unavailable": [...], "framework": {...}}.
    Nothing here changes a verdict.
    """
    from ..chem.connectivity import covalent_radius
    fired: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    labels = [str(a.get("label")) for a in infos]
    scale = _framework_scale(xs, {lb.upper() for lb in labels})
    med_u = scale.get("median_ueq")
    med_e = scale.get("median_electrons")

    # (1) an ADP far above the framework's, at full occupancy: smeared
    if isinstance(med_u, (int, float)) and med_u > 0:
        hits = []
        for a in infos:
            u = a.get("ueq_baseline")
            occ = float(a.get("occupancy") or 0.0)
            if not isinstance(u, (int, float)) or occ < SMEAR_FULL_OCC:
                continue
            if u >= SMEAR_UEQ_MIN_A2 and u >= SMEAR_UEQ_FACTOR * med_u:
                hits.append((u / med_u, str(a["label"]), float(u), occ))
        if hits:
            hits.sort(reverse=True)
            ratio, lbl, u, occ = hits[0]
            fired.append({
                "indicator": "smeared_adp", "weight": "primary",
                "atoms": [h[1] for h in hits], "worst_atom": lbl,
                "ueq": round(u, 4), "occupancy": round(occ, 3),
                "framework_median_ueq": round(med_u, 4),
                "ratio_to_framework": round(ratio, 1),
                "rms_displacement_A": round(math.sqrt(u), 2),
                "criterion": (f"Ueq >= {SMEAR_UEQ_FACTOR:g}x this model's "
                              f"own framework median AND >= "
                              f"{SMEAR_UEQ_MIN_A2} A^2, at occupancy >= "
                              f"{SMEAR_FULL_OCC:g}"),
                "reading": (
                    f"{lbl} carries Ueq {u:.3f} A^2 at occupancy {occ:.2f} - "
                    f"{ratio:.1f}x the framework median ({med_u:.3f} A^2), "
                    f"an rms displacement of {math.sqrt(u):.2f} A. At FULL "
                    f"occupancy that is not one atom vibrating harder: the "
                    f"density is spread over positions - a layer offset / "
                    f"stacking average, a modulation this cell does not "
                    f"carry, or unresolved disorder. (At partial occupancy "
                    f"a large U would be the ordinary occupancy-ADP "
                    f"correlation, which is why the fence asks for full "
                    f"occupancy.)"),
            })
    else:
        unavailable.append({
            "indicator": "smeared_adp",
            "why": "this model has no non-H framework atom to take a "
                   "median Ueq from"})

    # (2) a near-regular chain / plane of sub-atomic peaks
    if len(infos) >= CHAIN_MIN_MEMBERS:
        if not isinstance(med_e, (int, float)) or med_e <= 0:
            unavailable.append({
                "indicator": "regular_sub_atomic_chain",
                "why": "this model has no non-H framework atom to take a "
                       "median electron count from"})
        else:
            uc = xs.unit_cell()
            sites = [a["_site"] for a in infos]
            nn = [min(_min_image_distance(uc, s, t)
                      for j, t in enumerate(sites) if j != i)
                  for i, s in enumerate(sites)]
            mean = sum(nn) / len(nn)
            spread = (max(nn) - min(nn)) / mean if mean > 0 else None
            r_pair = 2.0 * max(covalent_radius(str(a.get("element") or "C"))
                               for a in infos)
            lo, hi = CHAIN_BOND_SHORT_FACTOR * r_pair, r_pair + CHAIN_BOND_LONG_A
            electrons = [float(a.get("occupancy") or 0.0)
                         * (_atomic_number(str(a.get("element") or "")) or 0)
                         for a in infos]
            regular = spread is not None and spread <= CHAIN_SPACING_TOL
            unbonded = mean < lo or mean > hi
            sub_atomic = max(electrons) <= SUB_ATOMIC_E_FRACTION * med_e
            if regular and unbonded and sub_atomic:
                where = ("shorter than any bond those elements form"
                         if mean < lo else
                         "a lattice-like repeat, no bond at that distance")
                fired.append({
                    "indicator": "regular_sub_atomic_chain",
                    "weight": "primary",
                    "atoms": labels, "n_members": len(infos),
                    "spacing_A": round(mean, 2),
                    "spacing_spread": round(spread, 3),
                    "bond_window_A": [round(lo, 2), round(hi, 2)],
                    "electrons_per_site": [round(e, 1) for e in electrons],
                    "framework_median_electrons": round(med_e, 1),
                    "criterion": (
                        f">= {CHAIN_MIN_MEMBERS} candidates whose "
                        f"nearest-neighbour spacings agree to "
                        f"{CHAIN_SPACING_TOL:.0%}, at a spacing outside the "
                        f"bond window {round(lo, 2)}-{round(hi, 2)} A of "
                        f"their own covalent radii, each holding <= "
                        f"{SUB_ATOMIC_E_FRACTION:g}x the framework's median "
                        f"electron count"),
                    "reading": (
                        f"{len(infos)} candidates sit {mean:.2f} A apart to "
                        f"within {spread:.0%} - {where} - and each holds at "
                        f"most {max(electrons):.1f} e against a framework "
                        f"median of {med_e:.1f} e. A regular row or sheet of "
                        f"sub-atomic maxima is what a continuous ridge looks "
                        f"like once a peak search samples it: an average "
                        f"over layer offsets / stacking faults, or the "
                        f"periodicity of a superstructure the cell does not "
                        f"carry. A real chain of bonded atoms is regular "
                        f"too, but it sits INSIDE the bond window and its "
                        f"members are not sub-atomic."),
                })

    # (3) the site's own symmetry images overlap
    overlaps = []
    for a in infos:
        el = str(a.get("element") or "")
        try:
            d_img = _self_image_distance(xs, a["_site"])
        except Exception as e:  # noqa: BLE001 - a bad site must not stop the read
            unavailable.append({"indicator": "symmetry_image_overlap",
                                "atoms": [str(a.get("label"))],
                                "why": f"{type(e).__name__}: {e}"})
            continue
        if d_img is None:            # P1: the site has no symmetry image
            continue
        fence = 2.0 * covalent_radius(el)
        if d_img < fence:
            overlaps.append((d_img, str(a["label"]), el, fence, a["_site"]))
    if overlaps:
        overlaps.sort()
        d_img, lbl, el, fence, site = overlaps[0]
        entry = {
            "indicator": "symmetry_image_overlap", "weight": "primary",
            "atoms": [o[1] for o in overlaps], "worst_atom": lbl,
            "image_distance_A": round(d_img, 2),
            "fence_A": round(fence, 2),
            "criterion": (f"the shortest distance to the site's OWN symmetry "
                          f"image is below 2 x its covalent radius "
                          f"({round(fence, 2)} A for {el}) - the shortest "
                          f"bond that element could form with itself"),
        }
        entry.update(_site_symmetry_context(xs, site, d_img))
        near = entry.get("distance_to_special_position_A")
        entry["reading"] = (
            f"{lbl}'s own symmetry image is {d_img:.2f} A away, closer than "
            f"two such atoms could ever bond ({fence:.2f} A)"
            + (f"; cctbx puts a {entry.get('site_symmetry_ops')}-fold site "
               f"symmetry ({entry.get('special_position_op')}) {near} A from "
               f"it" if near is not None else "")
            + ". Two images of the SAME atom cannot both hold an atom: the "
            "site lies on or just off a symmetry element and the space group "
            "is folding its own image onto it. That is what a layer offset "
            "or a stacking fault looks like after averaging, and it is also "
            "how an unresolved symmetry-related disorder pair appears - "
            "check the symmetry and the map before naming anything here.")
        fired.append(entry)

    # (4) supporting: the density bonds to nothing outside the candidate set
    contacts = []
    for a in infos:
        el = str(a.get("element") or "")
        for nb in a.get("neighbours") or []:
            d = nb.get("d_A")
            if not isinstance(d, (int, float)):
                continue
            fence = (covalent_radius(el)
                     + covalent_radius(str(nb.get("element") or ""))
                     + ISOLATION_SLACK_A)
            contacts.append((float(d), fence, str(nb.get("label")),
                             str(nb.get("element"))))
    if not any(d <= fence for d, fence, _lb, _el in contacts):
        nearest = min(contacts) if contacts else None
        fired.append({
            "indicator": "isolated_density", "weight": "supporting",
            "atoms": labels,
            "nearest_atom": (nearest[2] if nearest else None),
            "nearest_distance_A": (round(nearest[0], 2) if nearest else None),
            "bond_fence_A": (round(nearest[1], 2) if nearest else None),
            "neighbour_search_radius_A": NEIGHBOUR_CUTOFF_A,
            "criterion": (f"no model atom outside the candidate set within "
                          f"the pair's covalent-radii sum + "
                          f"{ISOLATION_SLACK_A} A (neighbours are listed to "
                          f"{NEIGHBOUR_CUTOFF_A} A)"),
            "reading": (
                (f"the nearest atom outside the candidate set is "
                 f"{nearest[2]} at {nearest[0]:.2f} A, beyond the "
                 f"{nearest[1]:.2f} A a bond between those elements would "
                 f"need" if nearest else
                 f"no model atom lies within {NEIGHBOUR_CUTOFF_A} A")
                + ": this density is bonded to nothing. Ordinary lattice "
                "solvent is isolated too, so on its own this says only that "
                "chemistry cannot anchor the site - it raises the flag only "
                "together with a second indicator."),
        })

    return {"fired": fired, "unavailable": unavailable, "framework": scale}


def _real_kind(signals: dict[str, Any] | None,
               residuals: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """real_kind_hint + the indicators behind it, for a row whose density
    the test found GENUINE. Verdict-free by construction: the caller adds
    these keys to a finished row and no verdict is recomputed."""
    fired = list((signals or {}).get("fired") or [])
    unavailable = list((signals or {}).get("unavailable") or [])

    # the returning density's own placement: is it centred where the atom
    # was, or is the atom sitting on the flank of something larger?
    best = None
    for r in residuals or []:
        if not isinstance(r, dict):
            continue
        if isinstance(r.get("max"), (int, float)) and isinstance(
                r.get("at_site"), (int, float)):
            if best is None or r["max"] > best["max"]:
                best = r
    if best is None:
        unavailable.append({
            "indicator": "returning_density_off_site",
            "why": "no residual density was read at the vacated site"})
    elif best["max"] < GHOST_PEAK_NONE:
        unavailable.append({
            "indicator": "returning_density_off_site",
            "why": (f"only {best['max']:.2f} e/A^3 came back at the site - "
                    f"too little to say where its centre is")})
    elif best["at_site"] < OFF_SITE_FRACTION * best["max"]:
        fired.append({
            "indicator": "returning_density_off_site", "weight": "supporting",
            "peak_in_sphere": best["max"], "value_at_site": best["at_site"],
            "ratio": round(best["at_site"] / best["max"], 2),
            "sphere_radius_A": SITE_RADIUS_A,
            "criterion": (f"the density AT the vacated coordinates is below "
                          f"{OFF_SITE_FRACTION:g}x the largest value in the "
                          f"{SITE_RADIUS_A} A sphere around them"),
            "reading": (
                f"the returning density peaks at {best['max']:.2f} e/A^3 "
                f"inside the {SITE_RADIUS_A} A sphere but is only "
                f"{best['at_site']:.2f} e/A^3 at the coordinates the atom "
                f"had: what came back is not centred on the atom. A ridge or "
                f"a smear passing near the site reads like this - and so "
                f"does an atom that was simply in the wrong place, which is "
                f"why this counts only with a second indicator."),
        })
    # peak shape is NOT measured here, and is not reported as absent
    unavailable.append({
        "indicator": "peak_shape",
        "why": ("the difference-map peak search returns positions and "
                "heights only - no second moments, principal axes or "
                "split-peak flag - so 'the returning peak is elongated or "
                "split' cannot be measured from what ghost_test has. It is "
                "unmeasured, not absent: look at the site with inspect_map "
                "(or a map viewer) to judge the shape.")})

    primary = [i for i in fired if i.get("weight") == "primary"]
    supporting = [i for i in fired if i.get("weight") != "primary"]
    flagged = bool(primary) or len(supporting) >= 2
    out: dict[str, Any] = {
        "real_kind_hint": ("possibly_non_atomic" if flagged else "atom_like"),
        "non_atomic_indicators": fired,
        "non_atomic_checks_unavailable": unavailable,
    }
    if flagged:
        out["non_atomic_note"] = NON_ATOMIC_NOTE
    return out


def _attach_real_kind(row: dict[str, Any], signals: dict[str, Any] | None,
                      residuals: list[dict[str, Any]] | None) -> None:
    """Add the real_kind keys to a finished row: to every 'real' row, and
    to an 'inconclusive' row when the same indicators are present. The
    verdict, the reason and the disposition are never touched."""
    verdict = row.get("verdict")
    if verdict not in ("real", "inconclusive"):
        return
    kind = _real_kind(signals, residuals)
    if verdict == "real" or kind["non_atomic_indicators"]:
        row.update(kind)


def _delta(a: float | None, b: float | None) -> float | None:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return round(float(a) - float(b), 4)
    return None


def _sayer(progress):
    def say(msg: str) -> None:
        if progress is None:
            return
        try:
            progress(msg)
        except Exception:  # noqa: BLE001 - liveness is best-effort
            pass
    return say


# ==========================================================================
class _BatchTool(_ProjectTool):
    """Shared machinery: baseline bookkeeping, the per-candidate refinement,
    diagnostic-branch labelling, and the restore that runs on every exit."""

    tag = "batch"

    # -- parameters --------------------------------------------------------
    @staticmethod
    def _common_params(params: dict[str, Any]) -> tuple[int, str, int]:
        # explicit 0 must be refused, not silently turned into the default
        cycles = params.get("cycles")
        cycles = 4 if cycles is None else int(cycles)
        if not 1 <= cycles <= MAX_CYCLES:
            raise _Refusal(f"cycles must be 1-{MAX_CYCLES} (got {cycles})")
        engine = str(params.get("engine") or "refine")
        if engine not in ("refine", "shelxl"):
            raise _Refusal("engine must be 'refine' (in-process smtbx, "
                           "default) or 'shelxl' (run_shelxl adopt)")
        budget = params.get("time_budget_s")
        budget = DEFAULT_BUDGET_S if budget is None else int(budget)
        if not MIN_BUDGET_S <= budget <= MAX_BUDGET_S:
            raise _Refusal(f"time_budget_s must be {MIN_BUDGET_S}-"
                           f"{MAX_BUDGET_S} s (got {budget}); split the "
                           "candidate list over several calls instead")
        return cycles, engine, budget

    # -- baseline ----------------------------------------------------------
    def _begin(self, params: dict[str, Any]) -> tuple[str, dict, float]:
        """Resolve the baseline node, remember the pre-call pointers, and
        rebuild the live session from it (disk is the truth - the loop
        must start from the node, not from whatever the session holds)."""
        project = self.project
        if project.session is None:
            project.open()
        nodes = project.nodes
        pre = nodes.state()
        ref = params.get("node_id") or pre.get("active_node")
        if not ref:
            raise _Refusal("no node to test on yet - import or solve a "
                           "model first")
        try:
            baseline = nodes.resolve(str(ref))
        except KeyError as e:
            raise _Refusal(str(e))
        t0 = _now()
        try:
            project.checkout(baseline)
        except Exception as e:  # noqa: BLE001 - a node that fails to load
            raise _Refusal(f"could not rebuild the session from {baseline}: "
                           f"{type(e).__name__}: {e}")
        return baseline, pre, _now() - t0

    def _restore(self, baseline: str, pre: dict,
                 checkout: bool = True) -> dict[str, Any]:
        """Leave the baseline checked out with the pointers the caller had.
        checkout=False when the live session is already the baseline."""
        project = self.project
        nodes = project.nodes
        if checkout:
            try:
                project.checkout(baseline)
            except Exception as e:  # noqa: BLE001 - must be reported, not hidden
                return {"restored": False, "node": baseline,
                        "error": f"checkout of {baseline} FAILED after the "
                                 f"tests: {type(e).__name__}: {e} - run "
                                 f"checkout('{baseline}') yourself"}
        st = nodes.state()
        branch = st.get("active_branch")
        if pre.get("active_node") == baseline and pre.get("active_branch"):
            branch = pre["active_branch"]
        elif str(branch or "").startswith("diag/"):
            plain = [b for b, h in st["branches"].items()
                     if h == baseline and not b.startswith("diag/")]
            branch = plain[0] if plain else (pre.get("active_branch")
                                             or "main")
        nodes.set_active(baseline, branch=branch)
        return {"restored": True, "node": baseline, "branch": branch}

    def _cut(self, name: str, baseline: str, checkout: bool) -> None:
        """Point a diagnostic branch at the baseline and make the live
        session equal to it (a fresh checkout: the previous candidate's
        refinement moved the session away from the baseline)."""
        self.project.nodes.branch(name, from_ref=baseline)
        if checkout:
            self.project.checkout(baseline)

    def _mark(self, node_id: str | None, baseline: str, candidate: str,
              step: str) -> None:
        """Label a throw-away node so list_nodes reads 'diagnostic', not an
        anonymous refine (pa1 trees carried 166 unlabelled ghost nodes)."""
        if not node_id:
            return
        try:
            p = self.project.nodes.node_dir(node_id) / "node.json"
            meta = json.loads(p.read_text(encoding="utf-8"))
            meta["note"] = (f"diagnostic {self.tag}: {candidate} [{step}] - "
                            f"throw-away branch from {baseline}, not a "
                            f"delivery candidate")
            meta["diagnostic"] = {"tool": self.tag, "baseline": baseline,
                                  "candidate": candidate, "step": step}
            p.write_text(json.dumps(meta, indent=2, ensure_ascii=False,
                                    default=str), encoding="utf-8")
        except Exception:  # noqa: BLE001 - a label must never fail a test
            pass

    # -- one refinement ----------------------------------------------------
    def _refine_once(self, engine: str, cycles: int, progress,
                     seconds_left: float) -> dict[str, Any]:
        """One short refinement of the live session with the chosen engine;
        normalised metrics + the committed node. The ADP model is left as
        the baseline has it (no promotion to anisotropic)."""
        t0 = _now()
        if engine == "shelxl":
            r = self.project.invoke_tool(
                "run_shelxl", {"mode": "adopt", "l_s": cycles,
                               "timeout_s": int(max(30.0, seconds_left))},
                progress=progress)
            if not r.ok:
                return {"ok": False, "error": r.error,
                        "elapsed_s": _now() - t0}
            sh = r.summary.get("shelxl") or {}
            m = {k: sh.get(k) for k in ("r1_strong", "r1_all", "wr2", "goof")}
        else:
            r = self.project.invoke_tool(
                "refine", {"mode": "isotropic", "n_cycles": cycles},
                progress=progress)
            if not r.ok:
                return {"ok": False, "error": r.error,
                        "elapsed_s": _now() - t0}
            m = {k: r.summary.get(k)
                 for k in ("r1_strong", "r1_all", "wr2", "goof", "n_params",
                           "diff_map_max", "diff_map_min")}
        m.update({"ok": True, "node": r.summary.get("node"),
                  "branch": r.summary.get("branch"),
                  "n_atoms": r.summary.get("n_atoms"),
                  "elapsed_s": _now() - t0})
        return m

    # -- free occupancy ----------------------------------------------------
    @staticmethod
    def _free_occupancy(xs, labels: list[str]) -> None:
        """Set the occupancy gradient flag on the named scatterers."""
        want = {lb.upper() for lb in labels}
        for sc in xs.scatterers():
            if sc.label.upper() in want:
                sc.flags.set_grad_occupancy(True)

    def _refine_occupancy_only(self, labels: list[str],
                               progress) -> dict[str, Any]:
        """Stage A: the named occupancies alone, every site and ADP held.

        Setting grad_occupancy and then running the ordinary all-free
        refinement does NOT refine an occupancy in practice: the atom's own
        ADP is 1:1 correlated with it and absorbs the whole scattering-power
        mismatch, and Levenberg-Marquardt damping on a few-hundred-parameter
        model starves the lone occupancy shift (ka1 cage 2026-09: three
        element_scan(free_occupancy=true) calls, every row occupancy exactly
        1.000). probe_site never had the bug because it runs this stage
        first; both tools now share it. Holding every site and ADP makes it a
        one-parameter least squares that converges at once.
        """
        t0 = _now()
        ses = self.project.session
        self._free_occupancy(ses.model, labels)
        u_held, u_reset = self._hold_physical_u(ses.model, labels)
        everyone = [sc.label for sc in ses.model.scatterers()]
        r = self.project.invoke_tool(
            "refine", {"mode": "isotropic", "n_cycles": OCC_ONLY_CYCLES,
                       "fix_atoms": everyone}, progress=progress)
        out: dict[str, Any] = {"u_held": u_held, "u_reset": u_reset,
                               "elapsed_s": _now() - t0}
        if not r.ok:
            out.update({"ok": False, "error": r.error})
            return out
        out.update({"ok": True, "node": r.summary.get("node"),
                    "occupancies": self._read_occupancies(
                        self.project.session.model, labels),
                    "elapsed_s": _now() - t0})
        return out

    @classmethod
    def _hold_physical_u(cls, xs, labels: list[str]
                         ) -> tuple[float | None, bool]:
        """Give the site a physical ADP before its occupancy is measured.

        An atom carrying the WRONG element drives its own U down, often
        through zero, to compensate: an occupancy measured while that U is
        held measures the compensation, not the site. When the site's Ueq is
        below the physical floor it is replaced by the model's own median
        ADP (any element, any crystal - nothing here is a per-element
        constant), and the substitution is reported. Returns (Ueq held,
        was it substituted)."""
        from cctbx import adptbx
        uc = xs.unit_cell()
        want = {lb.upper() for lb in labels}
        stand_in = cls._median_u(xs)
        held: list[float] = []
        reset = False
        for sc in xs.scatterers():
            if sc.label.upper() not in want:
                continue
            if float(sc.u_iso_or_equiv(uc)) < U_MIN_PHYSICAL:
                if sc.flags.use_u_aniso():
                    sc.u_star = adptbx.u_iso_as_u_star(uc, stand_in)
                else:
                    sc.u_iso = stand_in
                reset = True
            held.append(float(sc.u_iso_or_equiv(uc)))
        if not held:
            return None, False
        return round(sum(held) / len(held), 4), reset

    @staticmethod
    def _median_u(xs) -> float:
        """Median physical Ueq of the model's own non-H atoms."""
        uc = xs.unit_cell()
        vals = sorted(
            u for u in (float(sc.u_iso_or_equiv(uc)) for sc in xs.scatterers()
                        if _element_symbol(sc.scattering_type) != "H")
            if U_MIN_PHYSICAL <= u <= U_MAX_PHYSICAL)
        return round(vals[len(vals) // 2], 4) if vals else U_FALLBACK

    @staticmethod
    def _read_occupancies(xs, labels: list[str]) -> list[float]:
        want = {lb.upper() for lb in labels}
        return [round(float(sc.occupancy), 4) for sc in xs.scatterers()
                if sc.label.upper() in want]

    # -- budget ------------------------------------------------------------
    @staticmethod
    def _budget_exhausted(elapsed: float, estimate: float,
                          budget: float) -> bool:
        return elapsed + estimate > budget

    @staticmethod
    def _timeout_message(tool: str, tested: int, total: int, elapsed: float,
                         per_candidate: float, budget: int,
                         not_tested: list[str], param: str) -> str:
        return (f"time budget {budget} s: {tool} tested {tested} of {total} "
                f"candidates in {elapsed:.0f} s (~{per_candidate:.0f} s per "
                f"candidate incl. checkout) and did NOT start "
                f"{not_tested} - starting one would have overrun the budget "
                f"(an in-process refinement cannot be interrupted). Results "
                f"above are complete for the tested ones. Call again with "
                f"{param}={not_tested} (every call is bounded), use fewer "
                f"cycles or engine='shelxl' for a large model, or raise "
                f"time_budget_s (max {MAX_BUDGET_S}) only if the "
                f"per-candidate time makes the remaining set fit.")


# ==========================================================================
class GhostTest(_BatchTool):
    name = "ghost_test"
    tag = "ghost_test"
    description = (
        "Delete-and-refine test for a LIST of atoms in one call: for each "
        "atom (or '+'-joined group) a throw-away branch is cut from the "
        "baseline node, the atom is deleted, a short refinement runs, and "
        "the residual density at the vacated site, dR1/dwR2/dGooF against a "
        "reference refinement of the baseline (same engine, same cycles) "
        "and the neighbours' Ueq are tabulated with a verdict per atom: "
        "real (a peak comes back where it was and R worsens), ghost "
        "(nothing comes back, R unchanged or better), ripple (read from "
        "the baseline model BEFORE the test: the site is buried inside a "
        "much heavier neighbour's covalent sphere with no density of its "
        "own - a Fourier/termination artefact the delete-and-refine test "
        "cannot judge, because a ripple always comes back) or "
        "inconclusive with the reason. Each row states whether the R1 "
        "fence can even see an "
        "atom of that weight on this model (expected_delta_r1_if_real, "
        "r1_fence_informative - below the floor the peak alone decides; "
        "when the fence discriminated nothing at all the summary says so) "
        "and a disposition: 'ghost' and 'ripple' license a delete "
        "('ripple' without acknowledge_real); 'real' atoms "
        "go on the project's ghost ledger and edit_atoms refuses to delete "
        "them without acknowledge_real; 'inconclusive' is re-tested later. "
        "A 'real' row also carries real_kind_hint (atom_like / "
        "possibly_non_atomic) with the indicators behind it: real means the "
        "density is GENUINE, not that it is an atom - an average over "
        "stacking faults, a modulation/superstructure or diffuse scattering "
        "also comes back after a delete, and naming it as an atom is what "
        "creates unnamed atoms that are force-deleted later. "
        "Replaces the branch->edit_atoms->refine->checkout loop. Diagnostic "
        "nodes stay on branches diag/ghost_test/<baseline>/<atom>; the "
        "baseline is checked out again when the call returns. BUDGET: max "
        f"{MAX_GHOST_CANDIDATES} candidates and time_budget_s (default "
        f"{DEFAULT_BUDGET_S} s), checked BEFORE each candidate because an "
        "in-process refinement cannot be interrupted - at the budget you get "
        "the rows that finished plus the named list of atoms that were not "
        "started, so re-issue with just those (the candidate already running "
        "may overrun by one refinement).")
    params_schema = {
        "type": "object",
        "properties": {
            "atoms": {
                "type": "array", "items": {"type": "string"},
                "description": "atom labels to test one at a time; write "
                               "'O7+O8' to delete several atoms as ONE "
                               f"group; max {MAX_GHOST_CANDIDATES} per call"},
            "cycles": {"type": "integer", "default": 4,
                       "description": "refinement cycles per test (1-20)"},
            "node_id": {"type": "string",
                        "description": "baseline node or branch (default: "
                                       "the active node)"},
            "engine": {"type": "string", "enum": ["refine", "shelxl"],
                       "default": "refine",
                       "description": "in-process smtbx refine (default) or "
                                      "run_shelxl(mode='adopt') - needed for "
                                      "twinned / HKLF5 data, often faster on "
                                      "very large models"},
            "time_budget_s": {"type": "integer", "default": DEFAULT_BUDGET_S,
                              "description": f"wall-clock budget ({MIN_BUDGET_S}"
                                             f"-{MAX_BUDGET_S} s); candidates "
                                             "that would overrun it are not "
                                             "started and are listed back"},
        },
        "required": ["atoms"],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        progress = getattr(ctx, "progress", None)
        say = _sayer(progress)
        groups = [g for g in (_split_group(x) for x in (params.get("atoms")
                                                         or [])) if g]
        if not groups:
            return ToolResult.failure("give at least one atom label in "
                                      "'atoms' (e.g. ['O7', 'C12+C13'])")
        if len(groups) > MAX_GHOST_CANDIDATES:
            return ToolResult.failure(
                f"{len(groups)} candidates exceed the per-call maximum of "
                f"{MAX_GHOST_CANDIDATES}: nothing was run. Split the list - "
                f"start with the atoms asu_sanity/validate flagged as ghost "
                f"suspects, the rest in a second call.")
        try:
            cycles, engine, budget = self._common_params(params)
            baseline, pre, t_checkout = self._begin(params)
        except _Refusal as e:
            return ToolResult.failure(str(e))
        t_start = _now()
        project = self.project

        # labels are resolved against the BASELINE model, all of them,
        # before anything runs - a typo must not cost a refinement
        resolved: list[list[str]] = []
        missing: list[str] = []
        close: dict = {}
        seen: set[str] = set()
        for g in groups:
            found, miss, cl = _resolve_labels(project.session.model, g)
            missing += miss
            close.update(cl)
            key = "+".join(found)
            if found and key.upper() not in seen:
                seen.add(key.upper())
                resolved.append(found)
        if missing:
            restore = self._restore(baseline, pre, checkout=False)
            return ToolResult.failure(
                f"unknown atom label(s) {missing} in baseline {baseline}: "
                f"nothing was run (close labels: {close}); the baseline "
                f"stays checked out ({restore.get('branch')}). "
                f"inspect_model detail='atoms' lists the current labels.")

        summary: dict[str, Any] = {
            "baseline": {"node": baseline,
                         "branch_before": pre.get("active_branch"),
                         "engine": engine, "cycles": cycles},
            "criterion": GHOST_CRITERION,
        }
        rows: list[dict[str, Any]] = []
        verdicts: dict[str, str] = {}
        not_tested: list[str] = []
        try:
            # -- reference: the baseline itself under the same protocol
            ref_branch = f"diag/ghost_test/{baseline}/reference"
            self._cut(ref_branch, baseline, checkout=False)
            say(f"ghost_test: reference refinement of {baseline} "
                f"({engine}, {cycles} cycles) before {len(resolved)} "
                f"candidate(s)")
            ref = self._refine_once(engine, cycles, progress, budget)
            if not ref["ok"]:
                summary["error_stage"] = "reference"
                return ToolResult(ok=False, summary=summary, error=(
                    f"reference refinement of {baseline} failed "
                    f"({ref['error']}) - there is nothing to compare "
                    f"against, so no candidate was run. Fix the baseline "
                    f"first (twinned / HKLF5 data need engine='shelxl')."))
            self._mark(ref["node"], baseline, "reference", "refine")
            ses_ref = project.session
            ref_ueq = _ueq_table(ses_ref.model)
            from ..tools.refinement_tools import _difference_map_analysis
            ref_map = _difference_map_analysis(
                ses_ref, ses_ref.model, n_peaks=20,
                f_mask=ses_ref.flags.get("f_mask"))
            summary["baseline"]["reference"] = {
                "node": ref["node"], "branch": ref_branch,
                "r1_strong": ref.get("r1_strong"), "wr2": ref.get("wr2"),
                "goof": ref.get("goof"), "n_atoms": ref.get("n_atoms"),
                "residual_max": ref_map.get("max"),
                "residual_min": ref_map.get("min"),
                "elapsed_s": round(ref["elapsed_s"], 1),
                "note": ("deltas below are against THIS refinement; the "
                         "largest residual anywhere in the baseline is the "
                         "noise level a returning peak must beat"),
            }
            r1_ref_txt = (f"{ref['r1_strong']:.4f}"
                          if isinstance(ref.get("r1_strong"), (int, float))
                          else "n/a")
            summary["sensitivity_note"] = (
                f"expected_delta_r1_if_real is the R1 rise a REAL atom of "
                f"that scattering weight would produce on this model "
                f"(reference R1 {r1_ref_txt}; the atom's share of the "
                f"scattering added in quadrature to the residual the model "
                f"already has); where it is below the {GHOST_R1_RISE} fence "
                f"(r1_fence_informative=false) a small dR1 is what a real "
                f"atom gives too, so dR1 cannot separate real from ghost "
                f"and the verdict rests on the returning peak alone - the "
                f"higher the reference R1 and the lighter or more partial "
                f"the atom, the lower the floor.")

            # -- candidates
            t_last = 0.0
            for gi, labels in enumerate(resolved):
                key = "+".join(labels)
                elapsed = _now() - t_start
                est = max(ref["elapsed_s"] + t_checkout, t_last) * 1.1
                if self._budget_exhausted(elapsed, est, budget):
                    not_tested = ["+".join(l) for l in resolved[gi:]]
                    summary["timeout"] = self._timeout_message(
                        "ghost_test", len(rows), len(resolved), elapsed,
                        max(est / 1.1, 1e-9), budget, not_tested, "atoms")
                    break
                tc0 = _now()
                branch = f"diag/ghost_test/{baseline}/{key}"
                row: dict[str, Any] = {"atoms": key, "branch": branch}
                try:
                    self._cut(branch, baseline, checkout=True)
                    info = _atoms_info(project.session.model, labels)
                    row["elements"] = [a["element"] for a in info]
                    row["occupancy"] = [a["occupancy"] for a in info]
                    row["site_frac"] = [a["site_frac"] for a in info]
                    row["ueq_baseline"] = [a["ueq_baseline"] for a in info]
                    # can the R1 fence see an atom of this weight here?
                    det = _detectability(project.session.model, labels,
                                         ref.get("r1_strong"))
                    row.update(det)
                    # pre-verdict, from the baseline model alone: a site
                    # buried inside a much heavier atom's covalent sphere
                    # is that atom's Fourier ripple and no delete/refine
                    # number can judge it
                    ripple = _group_ripple(info)
                    if ripple:
                        row["ripple"] = ripple
                    # is genuine density here even an ATOM? read from the
                    # baseline model, BEFORE the delete changes it
                    try:
                        signals = _model_non_atomic_signals(
                            project.session.model, info)
                    except Exception as e:  # noqa: BLE001 - advisory only
                        signals = {"fired": [], "unavailable": [
                            {"indicator": "model_side_indicators",
                             "why": f"{type(e).__name__}: {e}"}]}
                    nbrs: list[dict[str, Any]] = []
                    for a in info:
                        for nb in a["neighbours"]:
                            if all(nb["label"] != x["label"] for x in nbrs):
                                nbrs.append(dict(nb))
                    # _diagnostic: this delete is the test itself, not a
                    # disposal - it bypasses edit_atoms' ghost-ledger guard
                    r_edit = project.invoke_tool(
                        "edit_atoms", {"operations": [
                            {"action": "delete", "atoms": labels}],
                            "_diagnostic": True},
                        progress=progress)
                    if not r_edit.ok:
                        raise _Refusal(f"delete failed: {r_edit.error}")
                    self._mark(r_edit.summary.get("node"), baseline, key,
                               "delete")
                    res = self._refine_once(
                        engine, cycles, progress,
                        budget - (_now() - t_start))
                    if not res["ok"]:
                        raise _Refusal(f"refinement without {key} failed: "
                                       f"{res['error']}")
                    self._mark(res["node"], baseline, key, "refine")
                    ses_c = project.session
                    residuals = _site_residuals(ses_c, [a["_site"]
                                                        for a in info])
                    after_ueq = _ueq_table(ses_c.model)
                    from ..chem.knowledge import is_metal
                    nearest_metal = None
                    for nb in nbrs:
                        nb["ueq_reference"] = (
                            round(ref_ueq[nb["label"].upper()], 4)
                            if nb["label"].upper() in ref_ueq else None)
                        nb["ueq_after"] = (
                            round(after_ueq[nb["label"].upper()], 4)
                            if nb["label"].upper() in after_ueq else None)
                        if is_metal(nb["element"]) and (
                                nearest_metal is None
                                or nb["d_A"] < nearest_metal["d_A"]):
                            nearest_metal = nb
                    peaks = [r["max"] for r in residuals if "max" in r]
                    peak = max(peaks) if peaks else None
                    holes = [r["min"] for r in residuals if "min" in r]
                    row.update({
                        "node": res["node"], "n_atoms": res.get("n_atoms"),
                        "r1_strong": res.get("r1_strong"),
                        "wr2": res.get("wr2"), "goof": res.get("goof"),
                        "delta_r1": _delta(res.get("r1_strong"),
                                           ref.get("r1_strong")),
                        "delta_wr2": _delta(res.get("wr2"), ref.get("wr2")),
                        "delta_goof": _delta(res.get("goof"),
                                             ref.get("goof")),
                        "residual_at_site": residuals,
                        "peak_at_site": peak,
                        "hole_at_site": min(holes) if holes else None,
                        "neighbours": nbrs,
                    })
                    verdict, reason = _ghost_verdict(
                        row["delta_r1"], peak, nearest_metal,
                        fence_informative=det["r1_fence_informative"],
                        expected_delta_r1=det["expected_delta_r1_if_real"],
                        ripple=ripple)
                    row["verdict"], row["reason"] = verdict, reason
                    row["disposition"] = DISPOSITION[verdict]
                    _attach_real_kind(row, signals, residuals)
                    if len(labels) > 1 and verdict == "real":
                        row["group_note"] = GROUP_REAL_NOTE
                    # the verdict outlives this result: edit_atoms reads
                    # the ledger before any delete
                    try:
                        from . import ghost_ledger
                        entry = ghost_ledger.record(project.dir, {
                            "labels": labels,
                            "site_frac": row["site_frac"],
                            "verdict": verdict, "reason": reason,
                            "delta_r1": row["delta_r1"],
                            "peak_at_site": peak,
                            "baseline": baseline, "node": res["node"],
                            "reference_r1": ref.get("r1_strong"),
                            "engine": engine, "cycles": cycles,
                            "group": len(labels) > 1,
                            "expected_delta_r1_if_real":
                                det["expected_delta_r1_if_real"],
                            "r1_fence_informative":
                                det["r1_fence_informative"],
                            **({"ripple": ripple} if ripple else {}),
                            **({"real_kind_hint": row["real_kind_hint"]}
                               if row.get("real_kind_hint") else {}),
                        })
                        row["ledger_id"] = entry["id"]
                    except Exception as e:  # noqa: BLE001 - the ledger must never fail a test
                        row["ledger_error"] = f"{type(e).__name__}: {e}"
                except _Refusal as e:
                    row["error"] = str(e)
                    row["verdict"] = "inconclusive"
                    row["reason"] = "the test could not be completed"
                    row["disposition"] = DISPOSITION["inconclusive"]
                except Exception as e:  # noqa: BLE001 - one candidate must not kill the table
                    row["error"] = f"{type(e).__name__}: {e}"
                    row["verdict"] = "inconclusive"
                    row["reason"] = "the test could not be completed"
                    row["disposition"] = DISPOSITION["inconclusive"]
                t_last = _now() - tc0
                row["elapsed_s"] = round(t_last, 1)
                rows.append(row)
                verdicts[key] = row["verdict"]
                say(f"ghost_test: {len(rows)}/{len(resolved)} {key} -> "
                    f"{row['verdict']} (R1 {row.get('r1_strong')} vs ref "
                    f"{ref.get('r1_strong')}, peak {row.get('peak_at_site')}"
                    f" e/A^3); {(_now() - t_start):.0f} s of {budget} s")
        finally:
            summary["restore"] = self._restore(baseline, pre)
        summary["rows"] = rows
        summary["verdicts"] = verdicts
        summary["dispositions"] = {r["atoms"]: r.get("disposition")
                                   for r in rows}
        summary["n_tested"] = len(rows)
        if not_tested:
            summary["not_tested"] = not_tested
        summary["tree_note"] = (
            f"diagnostic nodes were kept on branches diag/ghost_test/"
            f"{baseline}/<atom> (checkout one to inspect_map its site); "
            f"they are not delivery candidates. Active node is {baseline} "
            f"again ({summary['restore'].get('branch')}).")
        n_real = sum(1 for r in rows if r.get("verdict") == "real")
        n_ripple = sum(1 for r in rows if r.get("verdict") == "ripple")
        summary["ledger_note"] = (
            f"verdicts were written to the project's ghost ledger "
            f"(.crystalpilot/refine/ghost_ledger.json); {n_real} 'real' "
            f"row(s) are now protected: edit_atoms refuses to delete those "
            f"atoms (by label or by site, group members included) unless "
            f"the call carries acknowledge_real={{labels, reason}}. Name "
            f"them, refine them at free occupancy, or delete them with an "
            f"acknowledged reason (e.g. absorbed by the solvent mask)."
            + (f" {n_ripple} row(s) are 'ripple': edit_atoms deletes those "
               f"without acknowledge_real - they are the heavy neighbours' "
               f"truncation artefacts, and a later 'ripple' verdict also "
               f"releases an earlier 'real' one on the same candidate."
               if n_ripple else ""))
        kind_rows = [r for r in rows if r.get("real_kind_hint")]
        if kind_rows:
            summary["real_kind_criterion"] = REAL_KIND_CRITERION
        flagged = [r["atoms"] for r in kind_rows
                   if r["real_kind_hint"] == "possibly_non_atomic"]
        if flagged:
            summary["real_kind_note"] = (
                f"{len(flagged)} of {len(kind_rows)} row(s) carrying a "
                f"real_kind_hint came back possibly_non_atomic ({flagged}): "
                f"the density is genuine, but it may be an average no atom "
                f"label represents (stacking fault / layer offset, "
                f"modulation satellites or a superstructure, diffuse "
                f"scattering). Do NOT name those sites - run the DATA-side "
                f"checks in their non_atomic_note first; the indicators "
                f"behind each hint are in non_atomic_indicators with their "
                f"measured numbers and thresholds.")
        note = _fence_note(rows, (summary["baseline"].get("reference") or {})
                           .get("residual_max"))
        if note:
            summary["fence_note"] = note
        summary["elapsed_s"] = round(_now() - t_start, 1)
        ok = summary["restore"].get("restored", False)
        return ToolResult(ok=ok, summary=summary,
                          error=None if ok else summary["restore"].get("error"))


# ==========================================================================
class ElementScan(_BatchTool):
    name = "element_scan"
    tag = "element_scan"
    description = (
        "Scattering-power scan of ONE site (or a '+'-joined group of "
        "equivalent sites) over a list of candidate elements in one call: "
        "each candidate is refined for a few cycles on a throw-away branch "
        "cut from the baseline, and R1/wR2/GooF, the site's Ueq (and its "
        "ratio to the neighbours), the residual density AT the site "
        "(positive = typed too light, negative = too heavy) and, with "
        "free_occupancy, the refined occupancy and occupancy x Z are "
        "tabulated. free_occupancy costs one EXTRA short refinement per "
        "candidate - the occupancy alone with every site and ADP held, a "
        "one-parameter least squares (occupancy_at_fixed_u) - because "
        "setting the flag and refining everything free leaves the "
        "occupancy at its starting value: the atom's own ADP absorbs the "
        "scattering-power mismatch. The result then reads the electron "
        "count one-directionally (electron_count_reading: 'the site holds "
        "~N e', plus the elements whose Z brackets N), it never picks a "
        "winner. The table opens with a READINESS check - unassigned "
        "residual peaks, no mask on a porous cell, default weights, high "
        "R1 - because on such a model R simply falls with Z and identifies "
        "nothing (pa1 cage-l0-r1, hex-l1-r1). Ranks by evidence, never "
        "picks: elements are assigned by chemistry, not by R. Diagnostic "
        "nodes stay on diag/element_scan/<baseline>/<site>=<El>; the "
        f"baseline is checked out again on return. BUDGET: max "
        f"{MAX_SCAN_ELEMENTS} elements and time_budget_s (default "
        f"{DEFAULT_BUDGET_S} s), checked BEFORE each candidate because an "
        "in-process refinement cannot be interrupted - at the budget you get "
        "the ranked rows that finished plus the named elements that were not "
        "started, so re-issue with just those (the candidate already running "
        "may overrun by one refinement).")
    params_schema = {
        "type": "object",
        "properties": {
            "site": {"type": "string",
                     "description": "atom label of the site; 'ZR1+ZR2' scans "
                                    "several sites together as one group"},
            "elements": {"type": "array", "items": {"type": "string"},
                         "description": "candidate element symbols, e.g. "
                                        "['Zn','Zr','Hf']; the current "
                                        "element is reused from the "
                                        f"reference; max {MAX_SCAN_ELEMENTS}"},
            "cycles": {"type": "integer", "default": 4,
                       "description": "refinement cycles per candidate (1-20)"},
            "node_id": {"type": "string",
                        "description": "baseline node or branch (default: "
                                       "the active node)"},
            "free_occupancy": {
                "type": "boolean", "default": False,
                "description": "also refine the site occupancy (in-process "
                               "engine only): occupancy x Z is the electron "
                               "count the data actually pin down. Adds an "
                               f"occupancy-only stage ({OCC_ONLY_CYCLES} "
                               "cycles, every site and ADP held) per "
                               "candidate, so budget roughly 1.5x the time"},
            "engine": {"type": "string", "enum": ["refine", "shelxl"],
                       "default": "refine",
                       "description": "in-process smtbx refine (default) or "
                                      "run_shelxl(mode='adopt') for twinned "
                                      "/ HKLF5 data or very large models"},
            "time_budget_s": {"type": "integer", "default": DEFAULT_BUDGET_S,
                              "description": f"wall-clock budget ({MIN_BUDGET_S}"
                                             f"-{MAX_BUDGET_S} s); candidates "
                                             "that would overrun it are not "
                                             "started and are listed back"},
        },
        "required": ["site", "elements"],
    }

    @staticmethod
    def _site_row(ses, labels: list[str], ref_nbr_ueq: float | None
                  ) -> dict[str, Any]:
        """Evidence read from the CURRENT (just refined) model at the site.

        No electron count here: occupancy x Z is reported only where the
        occupancy was actually measured (_occupancy_fields). With a fixed
        occupancy the column is just Z, and it reads as an electron count
        that was never measured (ka1 cage 2026-09)."""
        xs = ses.model
        uc = xs.unit_cell()
        want = {lb.upper() for lb in labels}
        scs = [sc for sc in xs.scatterers() if sc.label.upper() in want]
        ueq = [round(float(sc.u_iso_or_equiv(uc)), 4) for sc in scs]
        occ = [round(float(sc.occupancy), 3) for sc in scs]
        residuals = _site_residuals(ses, [tuple(sc.site) for sc in scs])
        signed = [_signed(r) for r in residuals]
        signed_ok = [s for s in signed if s is not None]
        mean_ueq = sum(ueq) / len(ueq) if ueq else None
        row: dict[str, Any] = {
            "ueq_site": ueq if len(ueq) > 1 else (ueq[0] if ueq else None),
            "residual_at_site": residuals,
            "residual_signed": (max(signed_ok, key=abs) if signed_ok
                                else None),
            "occupancy": occ if len(occ) > 1 else (occ[0] if occ else None),
        }
        if mean_ueq is not None and ref_nbr_ueq:
            row["ueq_over_neighbours"] = round(mean_ueq / ref_nbr_ueq, 2)
        return row

    def _scan_refine(self, free_occ: bool, labels: list[str], engine: str,
                     cycles: int, progress, seconds_left: float,
                     baseline: str, candidate: str) -> dict[str, Any]:
        """One candidate's refinement protocol.

        With free_occupancy this is TWO refinements, the way probe_site
        does it and the way it is done by hand: (A) the occupancy alone
        with every site and ADP held - a one-parameter least squares - and
        then (B) the ordinary all-free refinement so dR1/residual stay
        like-for-like with the reference. Without (A) the occupancy never
        moves: its own ADP absorbs the scattering-power mismatch and LM
        damping starves the shift (see _refine_occupancy_only)."""
        stage_a: dict[str, Any] | None = None
        spent = 0.0
        if free_occ:
            stage_a = self._refine_occupancy_only(labels, progress)
            spent = float(stage_a.get("elapsed_s") or 0.0)
            if stage_a.get("ok"):
                self._mark(stage_a.get("node"), baseline, candidate,
                           "refine[occupancy only]")
        res = self._refine_once(engine, cycles, progress,
                                seconds_left - spent)
        res["elapsed_s"] = float(res.get("elapsed_s") or 0.0) + spent
        if stage_a is not None:
            res["stage_a"] = stage_a
        return res

    @staticmethod
    def _occupancy_fields(res: dict[str, Any],
                          z: int | None) -> dict[str, Any]:
        """occupancy_at_fixed_u and occupancy x Z from stage A, or the
        reason there is none. The electron count is built from the stage-A
        occupancy - the one measured under a stated, held ADP - never from
        the all-free refinement, where the ADP and the occupancy trade."""
        stage_a = res.get("stage_a")
        if not stage_a:
            return {}
        if not stage_a.get("ok"):
            return {"free_occupancy_applied": False,
                    "u_held_for_occupancy": stage_a.get("u_held"),
                    "free_occupancy_note": (
                        f"the occupancy-only stage failed "
                        f"({stage_a.get('error')}): the occupancy in this "
                        f"row is whatever the all-free refinement left it "
                        f"at, which on a damped model is its starting "
                        f"value - it is NOT a measured electron count, and "
                        f"no occupancy_x_z is reported for it")}
        occ = stage_a.get("occupancies") or []
        out: dict[str, Any] = {
            "free_occupancy_applied": True,
            "occupancy_at_fixed_u": (occ[0] if len(occ) == 1 else occ),
            "u_held_for_occupancy": stage_a.get("u_held")}
        if z:
            e = [round(o * z, 1) for o in occ]
            out["occupancy_x_z"] = e[0] if len(e) == 1 else e
            if len(e) > 1:
                out["occupancy_x_z_total"] = round(sum(e), 1)
        if stage_a.get("u_reset"):
            out["free_occupancy_note"] = (
                f"the site's own Ueq was below {U_MIN_PHYSICAL} (an atom "
                f"carrying the wrong element drives its U through zero to "
                f"compensate), so the occupancy was measured with the ADP "
                f"held at the model's median Ueq "
                f"{stage_a.get('u_held')} instead")
        return out

    @staticmethod
    def _occupancy_reading(rows: list[dict[str, Any]],
                           ref: dict[str, Any]) -> dict[str, Any]:
        """The ONE-DIRECTIONAL reading of the occupancy column.

        occupancy x Z is an electron count, and a count is one number: it
        says how many electrons sit at the site, never which element they
        belong to. When the candidates' counts cluster - which is what a
        refined occupancy DOES, because occupancy x Z is what the data pin
        down - the result says so and proposes the elements whose Z brackets
        the count, instead of letting the lowest-R1 row look like a winner
        (ka1 cage 2026-09: 'occupancy 1.000 for every candidate' turned into
        'Cl excluded' and shipped an O where the reference has Cl)."""
        def _count(r: dict[str, Any]) -> float | None:
            e = r.get("occupancy_x_z_total", r.get("occupancy_x_z"))
            return e if isinstance(e, (int, float)) else None

        # a row whose comparison refinement failed still counts here if its
        # occupancy-only stage converged - the count was measured
        counts = [(r["element"], _count(r)) for r in rows
                  if r.get("free_occupancy_applied")]
        counts = [(el, e) for el, e in counts if e is not None and e > 0]
        failed = [r["element"] for r in rows
                  if r.get("free_occupancy_applied") is False]
        out: dict[str, Any] = {
            "free_occupancy_applied": bool(counts) and not failed}
        if failed:
            out["free_occupancy_note"] = (
                f"the occupancy-only stage did not run for {failed}: those "
                f"rows' occupancy is NOT a measurement - see each row's "
                f"free_occupancy_note")
        if not counts:
            return out
        values = [e for _el, e in counts]
        lo, hi = min(values), max(values)
        mean = sum(values) / len(values)
        low_biased = count_is_low_biased(ref.get("r1_strong"))
        proposed = bracketing_elements(mean, low_biased=low_biased)
        clustered = hi <= COUNT_CLUSTER_FACTOR * lo
        if clustered:
            reading = (
                f"occupancy x Z clusters at ~{mean:.0f} e across every "
                f"candidate ({lo:.1f}-{hi:.1f} e): the site holds about "
                f"{mean:.0f} electrons. The element CANNOT be told from the "
                f"occupancy - each candidate simply scaled its occupancy to "
                f"the same electron count.")
        else:
            reading = (
                f"occupancy x Z does NOT cluster ({lo:.1f}-{hi:.1f} e "
                f"across the candidates): the occupancies have not "
                f"converged to one electron count, so read them per row "
                f"(occupancy_at_fixed_u is the well-conditioned number) and "
                f"repeat with more cycles on a more complete model before "
                f"concluding anything.")
        out["electron_count_reading"] = reading
        out["electrons_measured"] = round(mean, 1)
        out["electrons_range"] = [round(lo, 1), round(hi, 1)]
        if proposed:
            out["candidates_bracketing_the_count"] = proposed
            out["bracket_note"] = electron_bracket_note(
                mean, proposed, low_biased)
        note = low_count_note(ref.get("r1_strong"))
        if note:
            out["electron_count_calibration"] = note
        return out

    @staticmethod
    def _readiness(ses, ref: dict[str, Any], ref_map: dict[str, Any],
                   packing: float | None) -> list[dict[str, str]]:
        notes: list[dict[str, str]] = []
        peaks = [p for p in ref_map.get("peaks", [])
                 if p["height"] >= UNASSIGNED_PEAK_E
                 and (p.get("nearest_d") or 0.0) >= UNASSIGNED_MIN_D_A]
        if peaks:
            top = "; ".join(
                f"{p['height']} e/A^3 at {p['site']} ({p['nearest_d']} A "
                f"from {p['nearest_atom']})" for p in peaks[:3])
            notes.append({"kind": "incomplete_model", "note": (
                f"model incomplete: {len(peaks)} unassigned residual "
                f"peak(s) >= {UNASSIGNED_PEAK_E} e/A^3 more than "
                f"{UNASSIGNED_MIN_D_A} A from any atom ({top}). R "
                f"differences between elements are NOT meaningful on an "
                f"incomplete model - build the missing atoms or mask the "
                f"solvent, then scan")})
        if (ses.flags.get("f_mask") is None and packing is not None
                and packing < PACKING_VOID_FRACTION):
            notes.append({"kind": "unmasked_void", "note": (
                f"no solvent mask and the model's vdW spheres fill only "
                f"{packing:.0%} of the cell (dense crystals score >~80% on "
                f"this raw measure): unmodelled void density sets the "
                f"scale and R then prefers the LIGHTER element whatever "
                f"the chemistry (pa1 hex-l1-r1: Zn 0.0817 vs Zr 0.0904 on "
                f"identical coordinates with 79% void unmasked). Run "
                f"solvent_mask or model the guests before reading R")})
        w = ses.flags.get("weights") or {}
        if (abs(float(w.get("a", 0.1)) - 0.1) < 1e-9
                and abs(float(w.get("b", 0.0))) < 1e-9):
            notes.append({"kind": "weights_not_adopted", "note": (
                "weights are the SHELX default WGHT 0.1 0 (never adopted): "
                "wR2/GooF differences between candidates are dominated by "
                "the weighting scheme - run_shelxl(mode='adopt_wght') "
                "before trusting them (it loops SHELXL's suggested WGHT to "
                "convergence and adopts it, minutes on a normal model). Do "
                "NOT reach for optimize_weights here: it is an in-process "
                "GooF->1 search that has run for over an hour on a "
                "framework of this size (ka1 cage 2026-09: one call, 65 "
                "min, no result) - it is for cases adopt_wght cannot "
                "cover. R1 (unweighted) is unaffected either way.")})
        goof = ref.get("goof")
        if isinstance(goof, (int, float)) and abs(goof - 1.0) > 0.5:
            notes.append({"kind": "goof_off", "note": (
                f"reference GooF {goof:.2f} is far from 1: the weighting "
                f"scheme does not describe this refinement, so wR2/GooF "
                f"deltas between candidates are not comparable")})
        r1 = ref.get("r1_strong")
        if isinstance(r1, (int, float)) and r1 >= HIGH_R1:
            notes.append({"kind": "high_r1", "note": (
                f"reference R1 {r1:.3f} >= {HIGH_R1}: on a model this far "
                f"from converged an R-vs-Z ladder is monotonic in Z (pa1 "
                f"cage-l0-r1: Cr -> Br fell 0.258 -> 0.247 and identified "
                f"nothing) - complete the model, then scan")})
        return notes

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        progress = getattr(ctx, "progress", None)
        say = _sayer(progress)
        site_labels = _split_group(params.get("site") or "")
        if not site_labels:
            return ToolResult.failure("give the site's atom label in 'site' "
                                      "(e.g. 'ZR1' or 'ZR1+ZR2')")
        elements: list[str] = []
        for e in params.get("elements") or []:
            el = _element_symbol(str(e))
            if el and el not in elements:
                elements.append(el)
        if not elements:
            return ToolResult.failure("give at least one candidate element "
                                      "symbol in 'elements'")
        bad = [e for e in elements if not _valid_scattering_type(e)]
        if bad:
            return ToolResult.failure(
                f"unknown element symbol(s) {bad}: nothing was run. Use "
                f"IT1992 scattering-factor symbols (e.g. 'Zr', 'Zn', 'Hf').")
        if len(elements) > MAX_SCAN_ELEMENTS:
            return ToolResult.failure(
                f"{len(elements)} candidates exceed the per-call maximum of "
                f"{MAX_SCAN_ELEMENTS}: nothing was run. Pre-select by "
                f"chemistry (coordination number, M-O distances, cluster "
                f"motif, wavelength vs absorption edge) - the scan separates "
                f"rows of the periodic table, not neighbours.")
        free_occ = bool(params.get("free_occupancy", False))
        try:
            cycles, engine, budget = self._common_params(params)
            if free_occ and engine == "shelxl":
                raise _Refusal(
                    "free_occupancy is only available with engine='refine' "
                    "(the occupancy is freed in-process): nothing was run - "
                    "free_occupancy_applied would be false and every "
                    "occupancy in the table would come back as its starting "
                    "1.000, which reads as a measured electron count and is "
                    "not one. Re-run with engine='refine', or with SHELXL "
                    "code the sof on a free variable (FVAR) yourself")
            baseline, pre, t_checkout = self._begin(params)
        except _Refusal as e:
            return ToolResult.failure(str(e))
        t_start = _now()
        project = self.project

        labels, missing, close = _resolve_labels(project.session.model,
                                                 site_labels)
        if missing:
            restore = self._restore(baseline, pre, checkout=False)
            return ToolResult.failure(
                f"unknown atom label(s) {missing} in baseline {baseline}: "
                f"nothing was run (close labels: {close}); the baseline "
                f"stays checked out ({restore.get('branch')}).")
        key = "+".join(labels)
        info = _atoms_info(project.session.model, labels)
        current_set = {a["element"] for a in info}
        current = current_set.pop() if len(current_set) == 1 else None
        nbrs: list[dict[str, Any]] = []
        for a in info:
            for nb in a["neighbours"]:
                if all(nb["label"] != x["label"] for x in nbrs):
                    nbrs.append(dict(nb))

        summary: dict[str, Any] = {}
        rows: list[dict[str, Any]] = []
        not_tested: list[str] = []
        try:
            # -- reference: the current assignment under the same protocol
            ref_branch = f"diag/element_scan/{baseline}/reference"
            self._cut(ref_branch, baseline, checkout=False)
            say(f"element_scan: reference refinement of {baseline} "
                f"({key} as {current or 'mixed'}; {engine}, {cycles} "
                f"cycles{', occupancy free' if free_occ else ''}) before "
                f"{len(elements)} candidate(s)")
            ref = self._scan_refine(free_occ, labels, engine, cycles,
                                    progress, budget, baseline,
                                    f"{key}={current or 'mixed'}")
            if not ref["ok"]:
                summary["error_stage"] = "reference"
                return ToolResult(ok=False, summary=summary, error=(
                    f"reference refinement of {baseline} failed "
                    f"({ref['error']}) - nothing to compare against, no "
                    f"candidate was run. Fix the baseline first (twinned / "
                    f"HKLF5 data need engine='shelxl')."))
            self._mark(ref["node"], baseline, f"{key}={current or 'mixed'}",
                       "reference")
            ses_ref = project.session
            ref_ueq = _ueq_table(ses_ref.model)
            nbr_ueq = [ref_ueq[nb["label"].upper()] for nb in nbrs
                       if nb["label"].upper() in ref_ueq]
            ref_nbr_ueq = sum(nbr_ueq) / len(nbr_ueq) if nbr_ueq else None
            for nb in nbrs:
                nb["ueq_reference"] = (round(ref_ueq[nb["label"].upper()], 4)
                                       if nb["label"].upper() in ref_ueq
                                       else None)
            from ..tools.refinement_tools import _difference_map_analysis
            ref_map = _difference_map_analysis(
                ses_ref, ses_ref.model, n_peaks=20,
                f_mask=ses_ref.flags.get("f_mask"))
            packing = _packing_estimate(ses_ref.model)
            readiness = self._readiness(ses_ref, ref, ref_map, packing)
            ref_row = {"element": current or "mixed", "is_current": True,
                       "z": _atomic_number(current) if current else None,
                       "node": ref["node"], "branch": ref_branch,
                       "r1_strong": ref.get("r1_strong"),
                       "wr2": ref.get("wr2"), "goof": ref.get("goof"),
                       "delta_r1": 0.0, "delta_wr2": 0.0, "delta_goof": 0.0,
                       **self._site_row(ses_ref, labels, ref_nbr_ueq),
                       **self._occupancy_fields(
                           ref, _atomic_number(current) if current else None),
                       "elapsed_s": round(ref["elapsed_s"], 1)}

            # -- top of the result: is R even readable on this model?
            if readiness:
                summary["readiness_warning"] = (
                    "R differences between the candidates below are NOT "
                    "decision-grade on this model: "
                    + "; ".join(n["kind"] for n in readiness)
                    + ". Read the residual-at-site / occupancy x Z columns "
                      "as scattering-power evidence only, fix the model, "
                      "and decide by chemistry.")
            summary["readiness"] = readiness
            summary["readiness_ok"] = not readiness
            summary["rule"] = ELEMENT_RULE
            summary["baseline"] = {
                "node": baseline, "branch_before": pre.get("active_branch"),
                "engine": engine, "cycles": cycles,
                "free_occupancy": free_occ,
                "reference": {"node": ref["node"], "branch": ref_branch,
                              "residual_max": ref_map.get("max"),
                              "residual_min": ref_map.get("min"),
                              "solvent_mask": ses_ref.flags.get("f_mask")
                              is not None,
                              "packing_estimate": (round(packing, 2)
                                                   if packing is not None
                                                   else None)},
            }
            summary["site"] = {"atoms": key, "current_element": current,
                               "site_frac": [a["site_frac"] for a in info],
                               "occupancy_baseline": [a["occupancy"]
                                                      for a in info],
                               "neighbours": nbrs}
            if current in elements:
                rows.append(ref_row)

            # -- candidates
            todo = [e for e in elements if e != current]
            t_last = 0.0
            for ei, el in enumerate(todo):
                elapsed = _now() - t_start
                est = max(ref["elapsed_s"] + t_checkout, t_last) * 1.1
                if self._budget_exhausted(elapsed, est, budget):
                    not_tested = todo[ei:]
                    summary["timeout"] = self._timeout_message(
                        "element_scan", len(rows), len(elements), elapsed,
                        max(est / 1.1, 1e-9), budget, not_tested,
                        "elements")
                    break
                tc0 = _now()
                branch = f"diag/element_scan/{baseline}/{key}={el}"
                row: dict[str, Any] = {"element": el, "is_current": False,
                                       "z": _atomic_number(el),
                                       "branch": branch}
                res: dict[str, Any] = {}
                try:
                    self._cut(branch, baseline, checkout=True)
                    r_edit = project.invoke_tool(
                        "edit_atoms", {"operations": [
                            {"action": "reassign", "atoms": labels,
                             "element": el}]}, progress=progress)
                    if not r_edit.ok:
                        raise _Refusal(f"reassign failed: {r_edit.error}")
                    self._mark(r_edit.summary.get("node"), baseline,
                               f"{key}={el}", "reassign")
                    res = self._scan_refine(
                        free_occ, labels, engine, cycles, progress,
                        budget - (_now() - t_start), baseline, f"{key}={el}")
                    if not res["ok"]:
                        raise _Refusal(f"refinement as {el} failed: "
                                       f"{res['error']}")
                    self._mark(res["node"], baseline, f"{key}={el}",
                               "refine")
                    row.update({
                        "node": res["node"],
                        "r1_strong": res.get("r1_strong"),
                        "wr2": res.get("wr2"), "goof": res.get("goof"),
                        "delta_r1": _delta(res.get("r1_strong"),
                                           ref.get("r1_strong")),
                        "delta_wr2": _delta(res.get("wr2"), ref.get("wr2")),
                        "delta_goof": _delta(res.get("goof"),
                                             ref.get("goof")),
                        **self._site_row(project.session, labels,
                                         ref_nbr_ueq),
                        **self._occupancy_fields(res, _atomic_number(el)),
                    })
                except _Refusal as e:
                    row["error"] = str(e)
                except Exception as e:  # noqa: BLE001 - one candidate must not kill the table
                    row["error"] = f"{type(e).__name__}: {e}"
                if "error" in row and (res.get("stage_a") or {}).get("ok"):
                    # the electron count WAS measured (stage A converged);
                    # only the like-for-like comparison refinement failed -
                    # keep the measurement rather than losing it with the row
                    row.update(self._occupancy_fields(res,
                                                      _atomic_number(el)))
                t_last = _now() - tc0
                row["elapsed_s"] = round(t_last, 1)
                rows.append(row)
                say(f"element_scan: {key} as {el} -> R1 "
                    f"{row.get('r1_strong')} (ref {ref.get('r1_strong')}), "
                    f"residual at site {row.get('residual_signed')} e/A^3"
                    f"{', occ ' + str(row.get('occupancy')) if free_occ else ''}"
                    f"; {(_now() - t_start):.0f} s of {budget} s")
        finally:
            summary["restore"] = self._restore(baseline, pre)

        # evidence ranking: |residual at the site| (0 = scattering power
        # matches), Ueq-vs-neighbours as tie-breaker; R1 is listed, not used
        def _rank_key(r: dict[str, Any]) -> tuple:
            s = r.get("residual_signed")
            ratio = r.get("ueq_over_neighbours")
            t = abs(math.log(max(ratio, 1e-3))) if ratio else 9.9
            return (round(abs(s), 1) if s is not None else 99.0, t)
        ranked = sorted([r for r in rows if "error" not in r], key=_rank_key)
        # a free ADP absorbs most of a one-row Z difference (pa1 hex: Zn
        # vs Zr moved R1 by 0.009 and the site residual by well under
        # 1 e/A^3) - say plainly which candidates the scan cannot separate
        ref_site = next((r for r in rows if r.get("is_current")), None)
        ref_abs = (abs(ref_site["residual_signed"])
                   if ref_site and ref_site.get("residual_signed") is not None
                   else 0.0)
        sep = max(0.5, ref_abs)
        tied: list[str] = []
        if ranked and ranked[0].get("residual_signed") is not None:
            best = abs(ranked[0]["residual_signed"])
            tied = [r["element"] for r in ranked
                    if r.get("residual_signed") is not None
                    and abs(r["residual_signed"]) <= best + sep]
        summary["rows"] = rows
        summary["tied_at_top"] = tied
        if len(tied) > 1:
            summary["ranking_note"] = (
                f"{tied} are NOT separated by scattering power here "
                f"(|residual at the site| within {sep:.2f} e/A^3 of the "
                f"best): decide between them by chemistry, not by R1")
        elif tied:
            summary["ranking_note"] = (
                f"only {tied[0]} lies within {sep:.2f} e/A^3 of the best "
                f"residual; the others are separated by scattering power. "
                f"A periodic-table neighbour of {tied[0]} that was not in "
                f"the list would score the same - confirm by chemistry")
        else:
            summary["ranking_note"] = "no candidate could be read"
        summary["evidence_ranking"] = [
            {"element": r["element"], "residual_signed": r.get("residual_signed"),
             "ueq_site": r.get("ueq_site"),
             "ueq_over_neighbours": r.get("ueq_over_neighbours"),
             **({"occupancy": r.get("occupancy"),
                 "occupancy_at_fixed_u": r.get("occupancy_at_fixed_u"),
                 "occupancy_x_z": r.get("occupancy_x_z")}
                if free_occ else {}),
             "r1_strong": r.get("r1_strong")} for r in ranked]
        if free_occ:
            summary.update(self._occupancy_reading(rows, ref))
        summary["how_to_read"] = (
            "residual_signed > 0 at the site = the element is too light for "
            "the density there, < 0 = too heavy; |residual| near the "
            "baseline noise (baseline.reference.residual_max/min) = the "
            "scattering power fits. ueq_over_neighbours >> 1 with a "
            "negative residual = too heavy, << 1 (or negative Ueq) with a "
            "positive residual = too light. With free_occupancy, "
            "occupancy_at_fixed_u is the occupancy refined ALONE (every "
            "site and ADP held at u_held_for_occupancy - the "
            "well-conditioned number) and occupancy_x_z = occupancy x Z is "
            "the electron count the data pin down; candidates with the same "
            "occupancy_x_z are NOT distinguished by this scan - read "
            "electron_count_reading, not the row with the lowest R1. "
            "'occupancy' is the same site after the all-free refinement: "
            "when the two differ the count is trading against the ADP and "
            "neither is pinned down. R1 is the weakest column.")
        summary["n_tested"] = len(rows)
        if not_tested:
            summary["not_tested"] = not_tested
        summary["tree_note"] = (
            f"diagnostic nodes were kept on branches diag/element_scan/"
            f"{baseline}/{key}=<El>; they are not delivery candidates. "
            f"Active node is {baseline} again "
            f"({summary['restore'].get('branch')}).")
        summary["elapsed_s"] = round(_now() - t_start, 1)
        ok = summary["restore"].get("restored", False)
        return ToolResult(ok=ok, summary=summary,
                          error=None if ok else summary["restore"].get("error"))


def register_batch_tools(reg, project) -> None:
    for cls in (GhostTest, ElementScan):
        reg.register(cls(project))
