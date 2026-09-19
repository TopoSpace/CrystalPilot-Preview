"""Heavy-site identity evidence audit (pa1 backflow, P1-10).

pa1 (2026-09, 32 runs, synchrotron data at lambda = 0.68883 A):

* hex-l1-r1 delivered NU-1000 as C44H22O16Zn3 - framework atom-for-atom
  right (rms 0.02 A against the reference), metal typed Zn because two
  R-vs-Z rounds on an unmasked, incomplete model gave Zn 0.0817 < Zr
  0.0904. validate_structure said "Zn CN=8 outside typical [4,6]" twice
  and was ignored; the +2.2/+1.6 e/A^3 residual peaks sitting ON Zn1/Zn2
  were reported by the agent itself and not read as "too light".
* five blind cage runs typed the same Zr6 node Fe / Cd / Zn / Cl / none:
  Zr never entered any candidate set ("common cage metals", "first
  transition row + Ga/Ge/Br"). cage-l0-r1 spent ~100 calls / 25 min on
  three R ladders (seven, then nine elements, R1 falling monotonically to
  Br 0.2473) whose honest conclusion was "R cannot tell".
* audit_element_assignment covers C/N/O only; the heavy sites had no
  evidence tool at all.

Two physics facts every one of those scans ignored:

1. lambda = 0.68883 A sits ON the Zr K edge (0.6889 A): f'(Zr) = -9.0 e
   (Sasaki), so a Zr site scatters like ~31 electrons - i.e. like Zn (30).
   SHELXL carries f'/f'' internally only for the Cu/Mo/Ag K-alpha lines; at
   any other wavelength it prints "DISP instructions may be required" and
   silently uses its Mo K-alpha terms (measured on the real binary: an
   explicit Mo-valued DISP reproduces the card-less job's R1 exactly;
   f' = f'' = 0 does not). Until 2026-09-02 our SHELX writer emitted no
   DISP card, so every pa1 run_shelxl R-vs-Z comparison modelled Zr with
   f'(Mo) = -2.97 e (~37 e) against a crystal scattering ~31 e -
   Zn had to win. In-process refine sets the Sasaki terms
   (tools/refinement_tools.py) and is not biased this way; the two
   engines' R values must never be compared across each other.
2. Delta-R1 < 0.005 between adjacent-Z candidates on a model that is
   incomplete, unmasked, H-less or on default weights is inside the noise
   those omissions produce; such a scan measures the omissions, not Z.

This tool therefore runs NO scan. Per heavy site (Z >= z_min) it collects
the evidence a reviewer asks for - Ueq against the donor atoms, CN and
M-X distances against element-typical windows, residual density on the
site (calibrated by the model's own Fc peak into a sign-only electron
estimate: the scale factor absorbs most of a Z mismatch, so the magnitude
is a loose lower bound), the electrons each candidate swap would add
(Z + f' at lambda), f'/f'' at the project wavelength with the
absorption-edge flag, cluster pattern hints from M...M distances - and
states whether an R-vs-Z comparison would be meaningful right now, with
the concrete blocker when not. Near an edge the Ueq/residual direction
heuristics are voided rather than scored (f' is a central spike in real
space, not an atom shape). Elements are decided by chemistry (AGENTS
rule); the ranked tally is evidence, never a verdict.

Read-only: never mutates the model, never registered in MUTATING_TOOLS.
"""
from __future__ import annotations

import math
from typing import Any

from ..tools.base import ToolContext, ToolResult
from .toolbase import _ProjectTool

_DEFAULT_Z_MIN = 11
_DEFAULT_RADIUS_A = 1.1
_DEFAULT_N_PEAKS = 30

#: |f'| at the project wavelength above which the apparent Z shifts enough
#: to swap the R-vs-Z winner between neighbouring elements
_FP_STRONG_E = 2.0
#: |f'| above which the Ueq / residual DIRECTION heuristics are void: f' is
#: s-independent, so in real space it is a central spike, not an atom
#: shape - a Zr site typed Zn at the Zr edge shows a NEGATIVE central
#: residual although Zr is the heavier element (synthetic check, P1-10)
_FP_DIRECTION_E = 5.0
#: an absorption edge within this fraction of lambda is flagged
_EDGE_REL = 0.01
#: window scanned for an edge (fraction of lambda), its sampling, and the
#: f'' jump between adjacent samples that marks an edge
_EDGE_SCAN_REL = 0.015
_EDGE_SCAN_N = 61
_EDGE_JUMP = 1.8

#: heavy-atom Ueq / mean donor Ueq fences. A metal normally sits at
#: 0.4-1.0 of its donors (heavier, stiffer); the C/N/O fences of
#: tools_chemaudit (0.67/1.5) would flag every normal metal as collapsed.
_RATIO_COLLAPSED = 0.35
_RATIO_BLOATED = 1.3
_UEQ_COLLAPSED_ABS = 0.004

#: residual on the site (e/A^3) that counts as directional evidence
_RHO_DIRECTIONAL = 1.0
#: R1 (strong) above which an R-vs-Z comparison is inside the noise
_R1_ROUGH = 0.20
_R1_CAUTION = 0.12
#: far-from-atom residual peak = unmodelled density (missing atoms or
#: solvent neither masked nor modelled)
_FAR_PEAK_E = 1.5
_FAR_PEAK_D = 1.3
#: non-H atoms per A^3 of non-void ASU volume (situation_report's rule)
_A3_PER_NON_H = 18.0
#: modelled/expected non-H ratio below which the model counts as incomplete
_INCOMPLETE_RATIO = 0.7

#: element-typical M-X windows (A): element -> donor -> (lo, hi, source).
#: These are the DISCRIMINATING windows (typical geometry), deliberately
#: tighter than the generous validation windows in chem.knowledge, which
#: exist to flag the implausible, not to separate neighbours.
#: Sources: UiO-66 (Cavka et al., JACS 2008, 130, 13850); NU-1000
#: (Mondloch et al., JACS 2013, 135, 10294); MOF-5 (Li et al., Nature 1999,
#: 402, 276); HKUST-1 (Chui et al., Science 1999, 283, 1148); ZIF-8/67
#: (Park et al., PNAS 2006, 103, 10186); MIL-88/100/101 (Ferey et al.);
#: Shannon ionic radii (Acta Cryst. 1976, A32, 751) for the rest.
_MX_TYPICAL: dict[str, dict[str, tuple[float, float, str]]] = {
    "Zr": {"O": (2.05, 2.30, "Zr6O4(OH)4 node: mu3-O 2.05-2.10, mu3-OH / "
                             "carboxylate O 2.20-2.30 (UiO-66, NU-1000)")},
    "Hf": {"O": (2.03, 2.28, "Hf6 node = Zr6 analogue (Shannon Hf4+ 0.71 vs "
                             "Zr4+ 0.72 A)")},
    "Zn": {"O": (1.95, 2.10, "tetrahedral Zn4O carboxylate 1.93-1.99 (MOF-5); "
                             "octahedral Zn-O up to ~2.15"),
           "N": (1.98, 2.20, "Zn-N(imidazolate) 1.98-2.02 (ZIF-8); "
                             "octahedral 2.10-2.20")},
    "Cu": {"O": (1.93, 2.00, "Cu2 paddlewheel equatorial 1.95 (HKUST-1); "
                             "Jahn-Teller axial 2.3-2.5 assessed separately"),
           "N": (1.98, 2.10, "Cu-N(py/imidazole) 1.98-2.05")},
    "Fe": {"O": (1.95, 2.15, "Fe3O carboxylate trimers 1.90-2.10 (MIL-88/100); "
                             "high-spin Fe2+ to 2.15"),
           "N": (1.95, 2.25, "Fe-N(py/im) 1.95-2.25 (spin-state dependent)")},
    "Cd": {"O": (2.20, 2.40, "Shannon Cd2+(6) 0.95 + O2- 1.40 = 2.35; "
                             "carboxylate Cd-O 2.2-2.5"),
           "N": (2.25, 2.45, "Cd-N(py) 2.3-2.4")},
    "Co": {"O": (2.00, 2.15, "high-spin Co2+ octahedral 2.05-2.15; "
                             "tetrahedral 1.95-2.00"),
           "N": (1.95, 2.20, "Co-N(im) 1.99 (ZIF-67); octahedral 2.10-2.20")},
    "Ni": {"O": (2.02, 2.12, "octahedral Ni2+ 2.02-2.10"),
           "N": (2.05, 2.15, "octahedral Ni-N 2.05-2.15")},
    "Mn": {"O": (2.10, 2.25, "high-spin Mn2+ 2.10-2.25"),
           "N": (2.20, 2.35, "high-spin Mn-N 2.2-2.35")},
    "Cr": {"O": (1.95, 2.05, "Cr3+ trimers 1.95-2.00 (MIL-101)")},
    "Al": {"O": (1.85, 1.95, "MIL-53 Al-O 1.85-1.95")},
    "Ti": {"O": (1.80, 2.10, "MIL-125 Ti-O 1.8-2.1 (Ti=O ~1.7 excluded)")},
    "V":  {"O": (1.60, 2.10, "vanadyl V=O 1.6, V-O 1.9-2.1 (MIL-47)")},
    "Ga": {"O": (1.90, 2.00, "Shannon Ga3+(6) 0.62 + 1.40")},
    "In": {"O": (2.10, 2.25, "Shannon In3+(6) 0.80 + 1.40")},
    "Sc": {"O": (2.05, 2.20, "Shannon Sc3+(6) 0.745 + 1.40")},
    "Y":  {"O": (2.25, 2.45, "Shannon Y3+(8) 1.02 + 1.40")},
    "Mg": {"O": (2.00, 2.15, "MOF-74 Mg-O 2.0-2.1")},
    "Ca": {"O": (2.30, 2.55, "Shannon Ca2+(7) 1.06 + 1.40")},
    "Ag": {"O": (2.20, 2.60, "Ag+ carboxylate 2.2-2.6"),
           "N": (2.10, 2.35, "Ag-N linear 2.1-2.2")},
    "Pb": {"O": (2.30, 2.80, "hemidirected Pb2+ 2.3-2.8")},
    "La": {"O": (2.45, 2.70, "Shannon La3+(9) 1.216 + 1.40")},
}
#: generic lanthanide window when no specific entry exists
_LN_WINDOW = (2.30, 2.60, "generic Ln3+ (CN 8-9) Shannon + O2-")
_LANTHANIDES = ("La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho",
                "Er", "Tm", "Yb", "Lu")
#: Cu Jahn-Teller axial window (A); only Cu gets the 4+1/4+2 treatment
_JT_AXIAL = (2.20, 2.60)
#: extra elements scanned for an absorption edge at the project wavelength
#: (beyond the knowledge-table metals and whatever is in the model)
_EDGE_SCAN_EXTRA = ("Nb", "Mo", "Ru", "Rh", "Pd", "Sr", "Ba", "Ce", "Th",
                    "U", "Bi", "Br", "I", "Sb", "Sn", "Te", "Rb", "Cs")


def _sym(el: str) -> str:
    return el.strip().capitalize().rstrip("+-0123456789")


def _z_of(el: str) -> int | None:
    from cctbx.eltbx import tiny_pse
    try:
        return int(tiny_pse.table(el).atomic_number())
    except Exception:  # noqa: BLE001 - unknown symbol
        return None


# --------------------------------------------------------------------------
# anomalous scattering at the project wavelength
# --------------------------------------------------------------------------

def _edge_near(table, wavelength: float) -> tuple[float, float] | None:
    """Locate an absorption edge within +/-_EDGE_SCAN_REL of lambda by
    scanning f'' for a jump. Returns (edge_lambda_A, |edge-lambda|/lambda)
    or None. Table-driven, so no hand-typed edge list can go stale."""
    lo = wavelength * (1.0 - _EDGE_SCAN_REL)
    hi = wavelength * (1.0 + _EDGE_SCAN_REL)
    xs = [lo + (hi - lo) * k / (_EDGE_SCAN_N - 1) for k in range(_EDGE_SCAN_N)]
    try:
        fdp = [float(table.at_angstrom(x).fdp()) for x in xs]
    except Exception:  # noqa: BLE001 - outside the table's range
        return None
    best: tuple[float, float] | None = None
    for k in range(1, _EDGE_SCAN_N):
        a, b = sorted((fdp[k - 1], fdp[k]))
        if a > 0 and b / a >= _EDGE_JUMP:
            edge = 0.5 * (xs[k - 1] + xs[k])
            rel = abs(edge - wavelength) / wavelength
            if best is None or rel < best[1]:
                best = (edge, rel)
    return best


def anomalous_terms(elements, wavelength: float,
                    table: str = "sasaki") -> dict[str, dict[str, Any]]:
    """f', f'' and edge proximity per element at `wavelength` (A)."""
    from cctbx.eltbx import henke, sasaki
    mod = sasaki if table == "sasaki" else henke
    out: dict[str, dict[str, Any]] = {}
    for el in elements:
        z = _z_of(el)
        if z is None:
            continue
        try:
            t = mod.table(el)
            at = t.at_angstrom(wavelength)
            fp, fdp = float(at.fp()), float(at.fdp())
        except Exception:  # noqa: BLE001 - no table for this element
            continue
        row: dict[str, Any] = {"Z": z, "fp": round(fp, 2), "fdp": round(fdp, 2),
                               "z_eff": round(z + fp, 1), "flags": []}
        if abs(fp) >= _FP_STRONG_E:
            row["flags"].append("strong_fp")
        edge = _edge_near(t, wavelength)
        if edge is not None:
            row["edge_A"] = round(edge[0], 5)
            row["edge_offset_pct"] = round(100.0 * edge[1], 2)
            if edge[1] <= _EDGE_REL:
                row["flags"].append("edge_at_lambda")
        out[el] = row
    return out


# --------------------------------------------------------------------------
# EARLY absorption-edge warning (T1.7a)
#
# The physics audit_heavy_sites reports, surfaced at the moment the
# wavelength and the element list are first known (set_experiment,
# get_project_brief) instead of only when a heavy-site audit happens to be
# called. ka1: both arms learned that lambda sat on the Zr K edge only
# from audit_heavy_sites - 12.8 and 18.6 minutes in, after R-vs-Z ladders
# that this one fact would have voided.
#
# ONE implementation: everything below goes through anomalous_terms() /
# _edge_near() above; there is no second edge table anywhere.
#
# The prose here is ENGLISH, unlike the Chinese warnings audit_heavy_sites
# builds further down: these strings are returned by set_experiment and
# get_project_brief, whose result text is English throughout.
# --------------------------------------------------------------------------

#: Sasaki is the reference tabulation (audit_heavy_sites, in-process refine
#: and the DISP writer all use it); Henke fills the elements Sasaki omits
#: (H, He, At, Rn, Ra, Ac, Th - an actinide MOF must not fall through the
#: check silently)
_EDGE_TABLES = (("sasaki", "Sasaki (cctbx.eltbx.sasaki)"),
                ("henke", "Henke (cctbx.eltbx.henke) - Sasaki carries no "
                          "entry for this element"))

#: the criterion, stated once to the agent in every return
EDGE_CRITERION = (
    f"element-generic, no per-element special case: f'/f'' of every element "
    f"the session knows are read from the tabulation at the project "
    f"wavelength, and the element is flagged when an absorption edge lies "
    f"within {100 * _EDGE_REL:.0f}% of lambda (the edge is located by "
    f"scanning f'' for a jump over +/-{100 * _EDGE_SCAN_REL:.1f}% of lambda, "
    f"not from a hand-typed edge list) or when |f'| >= {_FP_STRONG_E:.1f} e, "
    f"i.e. when the apparent electron count moves by at least one element's "
    f"worth")


def _nearest_element(z_eff: float) -> str | None:
    """The element whose atomic number is closest to an apparent electron
    count - how a mistyped site actually presents itself ('Zr on its edge
    scatters like Zn'). A pure Z lookup, no chemistry."""
    from cctbx.eltbx import tiny_pse
    n = int(round(z_eff))
    if n < 1 or n > 103:
        return None
    try:
        return str(tiny_pse.table(n).symbol())
    except Exception:  # noqa: BLE001 - outside the table
        return None


def _edge_terms(elements, wavelength: float
                ) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """anomalous_terms() over both tabulations: Sasaki first, Henke for
    whatever Sasaki does not carry. Returns (rows tagged with the
    tabulation used, symbols no tabulation covers)."""
    want = [e for e in elements if e]
    rows: dict[str, dict[str, Any]] = {}
    for key, label in _EDGE_TABLES:
        missing = [e for e in want if e not in rows]
        if not missing:
            break
        for el, row in anomalous_terms(missing, wavelength, key).items():
            row = dict(row)
            row["table"] = label
            rows[el] = row
    return rows, [e for e in want if e not in rows]


def absorption_edge_brief(elements, wavelength: float | None, *,
                          wavelength_source: str | None = None,
                          elements_source: str | None = None,
                          ) -> dict[str, Any]:
    """Standing X-ray absorption-edge statement for (element list, lambda).

    Never asserts an element is present: every flagged element is phrased
    "IF <El> is present as declared ...", because the list is a
    declaration (SFAC / current scattering types), not evidence. When the
    check cannot run (no wavelength, no elements) or finds nothing, it
    SAYS so - staying silent would read as "no edge here", which is the
    failure this warning exists to prevent.
    """
    els: list[str] = []
    for e in elements or ():
        s = _sym(str(e))
        if s and s not in els:
            els.append(s)
    out: dict[str, Any] = {
        "wavelength_A": round(float(wavelength), 5) if wavelength else None,
        "wavelength_source": wavelength_source,
        "elements_considered": els,
        "elements_source": elements_source,
        "criterion": EDGE_CRITERION,
    }
    if not wavelength:
        out.update({
            "applies": False,
            "status": "wavelength_unknown",
            "statement": (
                "absorption-edge check NOT run: this project has no "
                "wavelength yet (no CELL / export wavelength, no "
                "context.json experiment wavelength). That is 'unknown', "
                "NOT 'no edge here'. Record the radiation - "
                "set_experiment(experiment={'instrument': {'source': "
                "'... lambda = X A'}}, provenance=...) - or ingest data "
                "that carries it, then read this field again."),
        })
        return out
    out["energy_keV"] = round(12.398419843 / float(wavelength), 3)
    if not els:
        out.update({
            "applies": False,
            "status": "elements_unknown",
            "statement": (
                f"absorption-edge check NOT run at lambda = "
                f"{out['wavelength_A']} A: this session knows no element "
                f"list yet (no SFAC/UNIT from an ingested ins, no atoms in "
                f"the model). That is 'unknown', NOT 'no edge here'. It "
                f"resolves itself as soon as a start model or a solution "
                f"exists; until then treat every electron-count argument "
                f"about a heavy element as uncalibrated."),
        })
        return out

    rows, untabulated = _edge_terms(els, float(wavelength))
    flagged: list[dict[str, Any]] = []
    for el in els:
        row = rows.get(el)
        if not row or not row["flags"]:
            continue
        item: dict[str, Any] = {
            "element": el, "Z": row["Z"], "fp": row["fp"], "fdp": row["fdp"],
            "z_eff": row["z_eff"], "flags": list(row["flags"]),
            "table": row["table"]}
        looks_like = _nearest_element(row["z_eff"])
        if looks_like and looks_like != el:
            item["scatters_like"] = looks_like
        if "edge_at_lambda" in row["flags"]:
            item["edge_A"] = row["edge_A"]
            item["edge_offset_pct"] = row["edge_offset_pct"]
            where = (f"lambda = {out['wavelength_A']} A sits "
                     f"{row['edge_offset_pct']:.2f}% from an absorption edge "
                     f"of {el} at {row['edge_A']:.5f} A")
        elif "edge_A" in row:
            item["edge_A"] = row["edge_A"]
            item["edge_offset_pct"] = row["edge_offset_pct"]
            where = (f"the nearest {el} edge in the scan window is at "
                     f"{row['edge_A']:.5f} A, {row['edge_offset_pct']:.2f}% "
                     f"from lambda = {out['wavelength_A']} A")
        else:
            where = (f"no {el} edge inside +/-"
                     f"{100 * _EDGE_SCAN_REL:.1f}% of lambda = "
                     f"{out['wavelength_A']} A, but the dispersion tail of a "
                     f"nearby edge still reaches it")
        item["statement"] = (
            f"IF {el} is present as declared, its scattering is anomalous "
            f"here: {where}. f'({el}) = {row['fp']:+.2f} e, f''({el}) = "
            f"{row['fdp']:.2f} e, so a {el} site scatters like "
            f"~{row['z_eff']:.0f} electrons instead of Z = {row['Z']}"
            + (f" - the electron count of {looks_like} "
               f"(Z = {int(round(row['z_eff']))}), so a Z-only comparison "
               f"picks the wrong element"
               if looks_like and looks_like != el else "") + ".")
        flagged.append(item)

    out["flagged"] = flagged
    out["no_anomalous_effect"] = [e for e in els
                                  if e in rows and not rows[e]["flags"]]
    if untabulated:
        out["no_tabulation"] = {
            "elements": untabulated,
            "note": ("neither Sasaki nor Henke covers these symbols at this "
                     "wavelength - their anomalous terms were NOT checked; "
                     "said out loud rather than read as 'no edge'"),
        }
    if flagged:
        on_edge = [f["element"] for f in flagged
                   if "edge_at_lambda" in f["flags"]]
        out["applies"] = True
        out["status"] = "edge_at_lambda" if on_edge else "strong_fp"
        out["statement"] = " ".join(f["statement"] for f in flagged)
        out["consequence"] = (
            "f' is negative for every element flagged above, so its "
            "APPARENT electron count is LOWER than its atomic number: an "
            "element_scan / peak-height / occupancy-times-Z argument that "
            "reasons in Z compares the wrong numbers. Use the "
            "anomalous-corrected count z_eff = Z + f' printed above. "
            "audit_heavy_sites is the tool that computes it - per element "
            "(anomalous.elements[El].z_eff) and per site "
            "(sites[].electrons.modelled_occ_x_z_eff) - and it also says "
            "whether an R-vs-Z comparison is meaningful on the current "
            "model at all. In-process refine sets these f'/f'' every "
            "cycle; run_shelxl carries them only through the DISP cards "
            "the writer emits, so R values must never be compared across "
            "the two engines.")
        if on_edge:
            out["consequence"] += (
                " ON an edge the Ueq and residual-density DIRECTION "
                "heuristics are void as well: f' is s-independent, a "
                "central spike in real space rather than an atom shape.")
    else:
        out["applies"] = True
        out["status"] = "no_edge_nearby"
        out["statement"] = (
            f"No absorption-edge problem at lambda = {out['wavelength_A']} A "
            f"for the elements this session knows ({', '.join(els)}): no "
            f"edge within {100 * _EDGE_REL:.0f}% of lambda and |f'| < "
            f"{_FP_STRONG_E:.1f} e for every one of them, so Z and the "
            f"apparent electron count agree to better than one element - "
            f"electron-count and element_scan arguments may use plain "
            f"atomic numbers here. The statement covers the declared "
            f"elements only; it says nothing about an element nobody has "
            f"declared yet.")
    return out


def project_absorption_edge_brief(project, session=None, *,
                                  wavelength: float | None = None,
                                  wavelength_source: str | None = None,
                                  ) -> dict[str, Any]:
    """absorption_edge_brief() for a project: resolve the wavelength and
    the declared element list from whatever the project already knows.

    Wavelength: the data's own (CELL / export metadata) first - that is
    what the CIF and both engines use - then the context.json experiment
    block (numeric key, then the free text an instrument.source carries,
    e.g. 'synchrotron lambda = 0.68883 A'). A caller that has just parsed
    a wavelength itself (set_experiment's import branch) passes it in.

    Elements: the start.ins SFAC list ingest recorded (a declaration, not
    evidence) plus any scattering type the current model carries that the
    ins did not name - a solver-invented Br/I has to be checked too.
    """
    wl_source: str | None = wavelength_source if wavelength else None
    ds = getattr(session, "dataset", None) if session is not None else None
    if not wavelength and ds is not None and getattr(ds, "wavelength", None):
        try:
            wavelength = float(ds.wavelength)
            wl_source = "dataset (CELL / export metadata)"
        except (TypeError, ValueError):
            wavelength = None
    if not wavelength:
        exp: dict[str, Any] = {}
        exp_fn = getattr(project, "experiment", None)
        if callable(exp_fn):
            try:
                exp = dict(exp_fn() or {})
            except Exception:  # noqa: BLE001 - metadata is best-effort
                exp = {}
        for key in ("wavelength_A", "wavelength"):
            if exp.get(key):
                try:
                    wavelength = float(exp[key])
                    wl_source = "context.json experiment"
                    break
                except (TypeError, ValueError):
                    continue
        if not wavelength and exp:
            from .tools_ingest import _wavelength_hint
            hint = _wavelength_hint(exp)
            if hint:
                wavelength = float(hint)
                wl_source = ("context.json experiment free text "
                             "(instrument.source / radiation)")

    ctx = getattr(project, "context", None)
    ctx = ctx if isinstance(ctx, dict) else {}
    flags = getattr(session, "flags", None) if session is not None else None
    ins_el = flags.get("ins_elements") if isinstance(flags, dict) else None
    if not ins_el:
        ins_el = (ctx.get("data") or {}).get("ins_elements")
    elements: list[str] = []
    sources: list[str] = []
    if isinstance(ins_el, dict) and ins_el.get("elements"):
        elements += [str(e) for e in ins_el["elements"]]
        sources.append(f"{ins_el.get('source') or 'start.ins SFAC/UNIT'} "
                       f"(a vendor/cold-start declaration, not evidence)")
    model = getattr(session, "model", None) if session is not None else None
    extra: list[str] = []
    if model is not None:
        try:
            for sc in model.scatterers():
                s = _sym(sc.scattering_type)
                if s and s not in elements and s not in extra:
                    extra.append(s)
        except Exception:  # noqa: BLE001 - a model we cannot read is no model
            extra = []
    if extra:
        elements += extra
        sources.append("current model scattering types"
                       + (f" (beyond the ins list: {', '.join(extra)})"
                          if ins_el else ""))
    return absorption_edge_brief(
        elements, wavelength, wavelength_source=wl_source,
        elements_source="; ".join(sources) if sources else None)


# --------------------------------------------------------------------------
# geometry windows
# --------------------------------------------------------------------------

def _window(el: str, donor: str) -> tuple[float, float, str, str] | None:
    """(lo, hi, kind, source) for an el-donor bond; kind = typical |
    generic | covalent."""
    typ = _MX_TYPICAL.get(el, {}).get(donor)
    if typ:
        return typ[0], typ[1], "typical", typ[2]
    if el in _LANTHANIDES and donor == "O":
        return _LN_WINDOW[0], _LN_WINDOW[1], "typical", _LN_WINDOW[2]
    from ..chem.knowledge import profile_for
    prof = profile_for(el)
    if prof is not None:
        if donor == "O":
            return (prof.m_o_range[0], prof.m_o_range[1], "generic",
                    "chem.knowledge validation window (generous)")
        if donor == "N" and prof.m_n_range:
            return (prof.m_n_range[0], prof.m_n_range[1], "generic",
                    "chem.knowledge validation window (generous)")
    from ..chem.connectivity import covalent_radius
    r = covalent_radius(el) + covalent_radius(donor)
    return (round(r - 0.15, 2), round(r + 0.20, 2), "covalent",
            "covalent radii sum (cctbx) -0.15/+0.20 A")


def _geometry_verdict(el: str, cn: int, donors: list[tuple[str, float]]
                      ) -> dict[str, Any]:
    """How the observed coordination sphere sits in `el`'s windows.
    donors: [(element, d)] sorted by d. Cu gets the Jahn-Teller split:
    the four shortest are equatorial, longer ones axial."""
    from ..chem.knowledge import is_metal, profile_for
    out: dict[str, Any] = {"per_donor": {}}
    status = "fits"
    worst_delta = 0.0
    axial: list[float] = []
    eq = donors
    if el == "Cu" and cn >= 5:
        eq = donors[:4]
        axial = [d for _, d in donors[4:]]
    groups: dict[str, list[float]] = {}
    for e, d in eq:
        groups.setdefault(e, []).append(d)
    for donor, ds in groups.items():
        w = _window(el, donor)
        mean = sum(ds) / len(ds)
        if w is None:
            out["per_donor"][donor] = {"mean": round(mean, 3), "window": None}
            continue
        lo, hi, kind, src = w
        delta = 0.0 if lo <= mean <= hi else (lo - mean if mean < lo
                                              else mean - hi)
        fit = "fits" if delta == 0 else ("borderline" if delta <= 0.06
                                         else "outside")
        out["per_donor"][donor] = {
            "mean": round(mean, 3), "n": len(ds),
            "window": [lo, hi], "window_kind": kind, "fit": fit,
            **({"delta_A": round(delta, 3)} if delta else {})}
        if fit == "outside":
            status = "outside"
        elif fit == "borderline" and status != "outside":
            status = "borderline"
        worst_delta = max(worst_delta, delta)
    if axial:
        ok = all(_JT_AXIAL[0] <= d <= _JT_AXIAL[1] for d in axial)
        out["jahn_teller_axial"] = {"d": [round(d, 3) for d in axial],
                                    "window": list(_JT_AXIAL),
                                    "fit": "fits" if ok else "outside"}
        if not ok and status == "fits":
            status = "borderline"
    if is_metal(el):
        prof = profile_for(el)
        if prof is not None:
            lo_cn, hi_cn = prof.cn_range
            cn_fit = ("fits" if lo_cn <= cn <= hi_cn else
                      "borderline" if lo_cn - 1 <= cn <= hi_cn + 1
                      else "outside")
            out["cn"] = {"observed": cn, "window": [lo_cn, hi_cn],
                         "fit": cn_fit}
            if cn_fit == "outside":
                status = "outside"
            elif cn_fit == "borderline" and status == "fits":
                status = "borderline"
    out["status"] = status
    out["worst_delta_A"] = round(worst_delta, 3)
    return out


def _cluster_hint(cn: int, donors: list[tuple[str, float]],
                  mm: list[float]) -> tuple[str | None, list[str]]:
    """Cluster-pattern hint from the M...M contacts of one site; returns
    (hint, implied candidate elements). Hints only - the agent looks."""
    o_only = donors and all(e == "O" for e, _ in donors)
    short_mm = [d for d in mm if d <= 2.85]
    mid_mm = [d for d in mm if 2.95 <= d <= 3.75]
    if cn >= 7 and len(mid_mm) >= 3 and o_only:
        return ("M6(mu3-O)8 node pattern: CN>=7 O-only sphere with >=3 "
                "M...M 3.3-3.7 A (Zr6/Hf6 UiO/NU/PCN; also Ce6/Th6)",
                ["Zr", "Hf", "Ce", "Th"])
    if len(short_mm) == 1 and 4 <= cn <= 6:
        return ("M2 paddlewheel pattern: one M...M 2.5-2.85 A with 4 "
                "carboxylate O (Cu2 2.62; Zn2/Co2/Mo2/Rh2/Ru2 2.6-3.0)",
                ["Cu", "Zn", "Co", "Mo", "Rh", "Ru"])
    if len(mid_mm) >= 2 and o_only and cn <= 6:
        return ("M3O trimer / M4O tetramer pattern: >=2 M...M 3.1-3.5 A "
                "around a shared oxo (Fe3O/Cr3O/Al3O/V3O/Sc3O/In3O; Zn4O)",
                ["Fe", "Cr", "Al", "V", "Sc", "In", "Zn"])
    return None, []


# --------------------------------------------------------------------------
# the tool
# --------------------------------------------------------------------------

class AuditHeavySites(_ProjectTool):
    name = "audit_heavy_sites"
    description = (
        "Identity evidence for every heavy site (Z >= 11) - read-only, runs "
        "NO R-vs-Z scan. Per site: Ueq against its donor atoms (collapsed = "
        "typed too light, bloated = too heavy), CN and M-X distances against "
        "element-typical windows for each candidate (Zr-O 2.05-2.30, Zn-O "
        "1.95-2.10, Cu-O 1.93-2.00 + Jahn-Teller axial, Fe-O 1.95-2.15, "
        "Cd-O 2.2-2.4 ...), residual density ON the site (sign-only electron "
        "estimate) against the electrons each candidate swap would add "
        "(Z+f' at lambda), M...M cluster "
        "pattern hints (Zr6 node, Cu2 paddlewheel, M3O), and f'/f'' at the "
        "project wavelength with an absorption-edge flag (pa1: lambda "
        "0.68883 A = Zr K edge, f'(Zr) = -9 e, so Zr scatters like Zn and "
        "R prefers Zn/Cu/Fe). Also a readiness verdict: whether an R-vs-Z "
        "comparison would mean anything on THIS model (complete? solvent "
        "masked or modelled? H placed? weights adopted? which engine "
        "carries f'?) with the concrete blocker when not. Elements are "
        "decided by chemistry - this is the evidence sheet, not the "
        "decision. Use before any element competition, after a metal "
        "CN/geometry warning, or when a candidate set was built from "
        "habit rather than from the data.")
    params_schema = {
        "type": "object",
        "properties": {
            "node_id": {
                "type": "string",
                "description": "audit that node's model instead of the live "
                               "session (read-only, no checkout). Residual "
                               "maps are computed only when the node shares "
                               "the live data's cell/space group."},
            "candidates": {
                "type": "array", "items": {"type": "string"},
                "description": "candidate elements to tally at every site. "
                               "Default: current element + metals whose "
                               "typical geometry fits the site + cluster-"
                               "pattern implied + absorption-edge flagged "
                               "at the project wavelength."},
            "z_min": {"type": "integer", "default": _DEFAULT_Z_MIN,
                      "description": "audit sites with Z >= z_min"},
            "radius_A": {"type": "number", "default": _DEFAULT_RADIUS_A,
                         "minimum": 0.5, "maximum": 3.0,
                         "description": "sphere around each site for the "
                                        "residual extremes / electron count"},
            "n_peaks": {"type": "integer", "default": _DEFAULT_N_PEAKS},
        },
    }

    # ---------------------------------------------------------------- state
    def _wavelength(self, ses) -> tuple[float | None, str | None]:
        """Project wavelength: dataset (CELL line / vendor export) first,
        then context.json experiment block. Never the 0.71073 default the
        writers fall back to - an assumed wavelength would silently put
        the anomalous block on the wrong edge."""
        ds = getattr(ses, "dataset", None) if ses is not None else None
        wl = getattr(ds, "wavelength", None)
        if wl:
            return float(wl), "dataset (CELL / export metadata)"
        exp_fn = getattr(self.project, "experiment", None)
        if callable(exp_fn):
            try:
                exp = exp_fn() or {}
            except Exception:  # noqa: BLE001
                exp = {}
            for k in ("wavelength_A", "wavelength"):
                if exp.get(k):
                    return float(exp[k]), "context.json experiment"
        return None, None

    def _load_node(self, node_id: str, ses) -> dict[str, Any]:
        """Model + flags of a stored node without touching the live session."""
        from ..io.shelx_model import load_res_model
        nodes = getattr(self.project, "nodes", None)
        if nodes is None:
            raise KeyError("no node store in this project")
        nid = nodes.resolve(str(node_id))
        meta = nodes.node_meta(nid)
        ndir = nodes.node_dir(nid)
        xs = load_res_model(ndir / "model.res").structure
        xs.scattering_type_registry(table="it1992")
        flags: dict[str, Any] = {
            "weights": meta.get("weights") or {},
            "disorder_groups": meta.get("disorder_groups") or [],
            "parts_extra": meta.get("parts_extra") or {},
            "restraints": meta.get("restraints") or [],
        }
        if meta.get("hydrogens", {}).get("present"):
            flags["h_riding_meta"] = {"per_carrier": [None] * int(
                meta["hydrogens"].get("n_groups") or 1)}
        f_mask = None
        mask_meta = meta.get("mask")
        if mask_meta:
            pkl = ndir / "f_mask.pkl"
            if pkl.exists():
                try:
                    from libtbx import easy_pickle
                    blob = easy_pickle.load(str(pkl))
                    f_mask = blob.get("f_mask")
                    flags["solvent_mask_info"] = blob.get("info") or \
                        mask_meta.get("info") or {}
                except Exception:  # noqa: BLE001 - cache only
                    f_mask = None
            if f_mask is None:
                flags["solvent_mask_info"] = mask_meta.get("info") or {}
                flags["_mask_uncached"] = True
            flags["_mask_recorded"] = True
        compatible = False
        if ses is not None and ses.model is not None:
            try:
                compatible = bool(xs.crystal_symmetry().is_similar_symmetry(
                    ses.model.crystal_symmetry()))
            except Exception:  # noqa: BLE001
                compatible = False
        return {"id": nid, "xs": xs, "flags": flags, "f_mask": f_mask,
                "metrics": meta.get("metrics") or {},
                "data_compatible": compatible}

    # ---------------------------------------------------------------- run
    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        import numpy as np
        from cctbx import adptbx

        from ..chem.knowledge import METAL_PROFILES, is_metal
        from .inspect import _neighbor_table, organic_fragments
        from .nodes import part_connectivity_kwargs

        ses = ctx.session or getattr(self.project, "session", None)
        z_min = int(params.get("z_min") or _DEFAULT_Z_MIN)
        radius = float(params.get("radius_A") or _DEFAULT_RADIUS_A)
        if not 0.5 <= radius <= 3.0:
            return ToolResult.failure("radius_A must be 0.5-3.0")
        n_peaks = int(params.get("n_peaks") or _DEFAULT_N_PEAKS)

        # ---- which model ---------------------------------------------
        source: dict[str, Any]
        node_id = params.get("node_id")
        if node_id:
            try:
                node = self._load_node(str(node_id), ses)
            except (KeyError, OSError, ValueError) as e:
                return ToolResult.failure(f"cannot load node {node_id!r}: {e}")
            xs, flags, f_mask = node["xs"], node["flags"], node["f_mask"]
            metrics = node["metrics"]
            maps_allowed = node["data_compatible"]
            source = {"node": node["id"],
                      "residual_maps": ("live data (node shares cell/space "
                                        "group)" if maps_allowed else
                                        "skipped: node cell/space group "
                                        "differs from the live data")}
        else:
            if ses is None or ses.model is None:
                return ToolResult.failure("no model in session")
            xs, flags, f_mask = ses.model, ses.flags, ses.flags.get("f_mask")
            snap = ses.last_refinement() if hasattr(ses, "last_refinement") \
                else None
            metrics = snap.as_dict() if snap is not None else {}
            maps_allowed = True
            source = {"node": "live session"}

        uc = xs.unit_cell()
        scs = list(xs.scatterers())
        if not scs:
            return ToolResult.failure("model has no atoms")
        labels = [sc.label for sc in scs]
        elems = [_sym(sc.scattering_type) for sc in scs]
        zs = [_z_of(e) or 0 for e in elems]
        u_eqs = [float(sc.u_iso_or_equiv(uc)) for sc in scs]
        heavy = [i for i, z in enumerate(zs) if z >= z_min]

        # ---- candidate validation ------------------------------------
        given: list[str] | None = None
        if params.get("candidates"):
            given = []
            for c in params["candidates"]:
                s = _sym(str(c))
                if _z_of(s) is None:
                    return ToolResult.failure(
                        f"unknown element symbol {c!r} in candidates")
                if s not in given:
                    given.append(s)

        # ---- wavelength / anomalous ----------------------------------
        wavelength, wl_source = self._wavelength(ses)
        anomalous: dict[str, Any]
        model_elems = sorted({elems[i] for i in heavy})
        if wavelength:
            scan = set(model_elems) | set(METAL_PROFILES) | \
                set(_EDGE_SCAN_EXTRA) | set(given or [])
            terms = anomalous_terms(sorted(scan), wavelength)
            edge_flagged = sorted(e for e, r in terms.items()
                                  if "edge_at_lambda" in r["flags"])
            strong = sorted(e for e, r in terms.items()
                            if "strong_fp" in r["flags"])
            model_fp = {}
            for i in heavy:
                model_fp[labels[i]] = round(float(scs[i].fp), 2)
            model_has_fp = any(abs(v) > 1e-6 for v in model_fp.values())
            warnings: list[str] = []
            for e in edge_flagged:
                r = terms[e]
                warnings.append(
                    f"λ={wavelength:.5f} Å 距 {e} 吸收边（{r['edge_A']:.5f} Å）"
                    f"仅 {r['edge_offset_pct']:.2f}%：f'({e})={r['fp']:+.1f} e，"
                    f"X 射线把 {e} 看成 ≈{r['z_eff']:.0f} 个电子"
                    f"（Z={r['Z']}）。任何不含 f' 的 R-vs-Z 比较都会把 {e} "
                    f"位点判成更轻的元素。")
            for e in strong:
                if e in edge_flagged:
                    continue
                r = terms[e]
                if e in model_elems or (given and e in given):
                    warnings.append(
                        f"|f'({e})|={abs(r['fp']):.1f} e 在 λ={wavelength:.5f} Å"
                        f"（有效 Z≈{r['z_eff']:.0f}），比较相邻 Z 候选时必须"
                        f"含此项。")
            anomalous = {
                "wavelength_A": round(wavelength, 5),
                "wavelength_source": wl_source,
                "table": "Sasaki (cctbx.eltbx.sasaki)",
                "energy_keV": round(12.398419843 / wavelength, 3),
                "elements": {e: terms[e] for e in sorted(
                    set(model_elems) | set(given or []) | set(edge_flagged))},
                "edge_at_lambda": edge_flagged,
                "strong_fp": strong,
                "model_fp_set": model_fp,
                "engines": {
                    "refine": "in-process smtbx sets Sasaki f'/f'' at the "
                              "dataset wavelength before every cycle - its "
                              "R carries the correction",
                    "run_shelxl": "the written .ins carries DISP $El f' f'' "
                                  "mu cards from the same Sasaki table at any "
                                  "wavelength other than Cu/Mo/Ag Kα (since "
                                  "2026-09-02); if job.ins says 'REM DISP not "
                                  "written' the wavelength was unknown and "
                                  "SHELXL silently used its Mo Kα terms - that "
                                  "R does NOT carry the correction. Never "
                                  "compare R across the two engines",
                },
                "warnings": warnings,
            }
            if not model_has_fp:
                anomalous["model_fp_note"] = (
                    "当前模型散射体上 f'=0（未经进程内 refine 或刚从节点载入）："
                    "本工具的残差图已按 Sasaki 表在模型副本上设置 f'/f''。")
        else:
            anomalous = {
                "wavelength_A": None,
                "skipped": "project wavelength unknown (no CELL/export "
                           "wavelength, no context.json experiment.wavelength_A)"
                           " - anomalous block skipped rather than assumed; "
                           "set_experiment or ingest metadata to enable it",
            }
            terms = {}
            edge_flagged = []

        # ---- connectivity --------------------------------------------
        part_kw = part_connectivity_kwargs(flags, scs)
        nbt = _neighbor_table(xs, part_kw)
        try:
            frags = organic_fragments(xs, nbt)
        except Exception:  # noqa: BLE001 - hint only
            frags = []

        # ---- residual maps (one full-model Fo-Fc, f'/f'' applied) ----
        # plus an Fc map on the same reflections: its height at the site
        # per modelled electron calibrates the residual height into an
        # electron estimate at THIS site's U and resolution. A sphere
        # integral of Fo-Fc with the atom present is not usable for that:
        # the scale factor absorbs part of the mismatch and the series-
        # termination ripples inside ~1 A cancel the central peak.
        peaks: list[dict[str, Any]] = []
        map_info: dict[str, Any] = {}
        real = None
        fc_real = None
        fo_sq = getattr(ses, "fo_sq", None) if ses is not None else None
        if fo_sq is None:
            map_info["skipped"] = "no reflection data in session"
        elif not maps_allowed:
            map_info["skipped"] = source["residual_maps"]
        else:
            from ..tools.refinement_tools import (_difference_map_analysis,
                                                  difference_map_real)
            xs_map = xs.deep_copy_scatterers()
            if wavelength:
                from ..io.shelx_writer import apply_anomalous_terms
                map_info["anomalous_applied"] = (
                    apply_anomalous_terms(xs_map, wavelength) is not None)
            mask_used = f_mask
            if mask_used is not None and mask_used.size() != fo_sq.size():
                mask_used = None
                map_info["mask_note"] = ("stored solvent mask is stale (size "
                                         "mismatch) - residual computed "
                                         "without it")
            map_info["solvent_mask_included"] = mask_used is not None
            try:
                diff = _difference_map_analysis(ses, xs_map, n_peaks=n_peaks,
                                                f_mask=mask_used)
                if "error" in diff:
                    map_info["skipped"] = diff["error"]
                else:
                    peaks = diff["peaks"]
                    map_info["max"] = diff["max"]
                    map_info["min"] = diff["min"]
                    _, real, _ = difference_map_real(ses, xs_map,
                                                     f_mask=mask_used)
                    from cctbx import maptbx
                    f_calc = fo_sq.structure_factors_from_scatterers(
                        xray_structure=xs_map, algorithm="direct").f_calc()
                    if mask_used is not None:
                        f_calc = f_calc.customized_copy(
                            data=f_calc.data() + mask_used.data())
                    fc_map = f_calc.fft_map(
                        symmetry_flags=maptbx.use_space_group_symmetry,
                        resolution_factor=1 / 3)
                    fc_map.apply_volume_scaling()
                    fc_real = fc_map.real_map_unpadded()
            except Exception as e:  # noqa: BLE001 - report, keep auditing
                map_info["skipped"] = f"{type(e).__name__}: {e}"
                real = None
                fc_real = None

        def _sphere(i: int) -> dict[str, Any] | None:
            if real is None:
                return None
            from cctbx import maptbx
            from cctbx.array_family import flex
            site = tuple(scs[i].site)
            cart = uc.orthogonalize(site)
            sel = maptbx.grid_indices_around_sites(
                unit_cell=uc, fft_n_real=real.focus(), fft_m_real=real.all(),
                sites_cart=flex.vec3_double([cart]),
                site_radii=flex.double([radius]))
            vals = real.select(sel)
            if vals.size() == 0:
                return None
            out = {"rho_at_site": round(float(
                real.eight_point_interpolation(site)), 2),
                "max_in_sphere": round(float(flex.max(vals)), 2),
                "min_in_sphere": round(float(flex.min(vals)), 2),
                "radius_A": radius}
            if fc_real is not None:
                out["rho_model_at_site"] = round(float(
                    fc_real.eight_point_interpolation(site)), 2)
            on_site = [p for p in peaks
                       if p.get("nearest_atom") == labels[i]
                       and p.get("nearest_d", 9) <= 1.0]
            if on_site:
                best = max(on_site, key=lambda p: p["height"])
                out["peak_on_site"] = {"height": best["height"],
                                       "d_A": best["nearest_d"]}
            return out

        # ---- per-site rows -------------------------------------------
        rows: list[dict[str, Any]] = []
        site_lines: list[str] = []
        for i in heavy:
            el, z = elems[i], zs[i]
            sc = scs[i]
            nbrs = [n for n in nbt[i] if n["element"] != "H"]
            donors = sorted([(n["element"], float(n["d"])) for n in nbrs
                             if not is_metal(n["element"])],
                            key=lambda t: t[1])
            mm = sorted(float(n["d"]) for n in nbrs if is_metal(n["element"]))
            cn = len(donors) if is_metal(el) else len(nbrs)
            ds = [d for _, d in donors] if is_metal(el) else \
                [float(n["d"]) for n in nbrs]
            row: dict[str, Any] = {
                "label": labels[i], "element": el, "Z": z,
                "occupancy": round(float(sc.occupancy), 3),
                "u_eq": round(u_eqs[i], 4),
                "aniso": bool(sc.flags.use_u_aniso()),
                "cn": cn,
                "neighbours": [f"{n['label']}{'*' if n['sym'] else ''}"
                               f"({n['element']}):{n['d']}" for n in nbrs],
            }
            if ds:
                row["bonds"] = {"mean": round(sum(ds) / len(ds), 3),
                                "min": round(min(ds), 3),
                                "max": round(max(ds), 3),
                                "spread": round(max(ds) - min(ds), 3)}
            if mm:
                row["metal_metal_A"] = [round(d, 3) for d in mm]
            if sc.flags.use_u_aniso() and \
                    not adptbx.is_positive_definite(sc.u_star):
                row["adp_note"] = "NPD：各向异性 ADP 非正定，元素/占有率严重不匹配的典型征象"

            # Ueq vs donors (same PART semantics as the neighbour table)
            evidence_dir_u = 0
            nb_u = [u_eqs[n["j"]] for n in nbrs if n["j"] != i]
            if nb_u:
                mean_nb = sum(nb_u) / len(nb_u)
                if mean_nb > 1e-6:
                    ratio = u_eqs[i] / mean_nb
                    row["u_eq_over_donors"] = round(ratio, 2)
                    if ratio <= _RATIO_COLLAPSED or \
                            u_eqs[i] < _UEQ_COLLAPSED_ABS:
                        row["ueq_note"] = (
                            f"ADP 塌陷（{ratio:.2f}× 配位原子；重原子正常 "
                            f"0.4–1.0×）：真实元素可能比 {el} 重，或占有率偏低")
                        evidence_dir_u = +1
                    elif ratio >= _RATIO_BLOATED:
                        row["ueq_note"] = (
                            f"ADP 膨胀（{ratio:.2f}× 配位原子）：真实元素可能比 "
                            f"{el} 轻，或占有率偏高/位置无序")
                        evidence_dir_u = -1
            elif u_eqs[i] < _UEQ_COLLAPSED_ABS:
                row["ueq_note"] = f"Ueq={u_eqs[i]:.4f} 近零：元素可能比 {el} 重"
                evidence_dir_u = +1

            # residual on the site
            evidence_dir_rho = 0
            sph = _sphere(i)
            if sph is not None:
                row["residual"] = sph
                rho = sph["rho_at_site"]
                if rho >= _RHO_DIRECTIONAL:
                    row["residual_note"] = (
                        f"位点上正残差 {rho:+.2f} e/Å³：模型在此处电子偏少"
                        f"（元素偏轻、占有率偏低，或 f' 未计入）")
                    evidence_dir_rho = +1
                elif rho <= -_RHO_DIRECTIONAL:
                    row["residual_note"] = (
                        f"位点上负残差 {rho:+.2f} e/Å³：模型在此处电子偏多"
                        f"（元素偏重或占有率偏高）")
                    evidence_dir_rho = -1

            # cluster pattern hint
            hint, implied = _cluster_hint(cn, donors, mm)
            if hint:
                row["cluster_hint"] = hint

            # effective electrons: what the model claims at this site
            # (with f' at lambda) and what the residual height says is
            # missing/excess, calibrated by the model's own peak height
            fp_cur = float(terms.get(el, {}).get("fp", 0.0)) if terms else 0.0
            occ = float(sc.occupancy)
            modelled_e = occ * (z + fp_cur)
            delta_e = None
            if sph is not None and sph.get("rho_model_at_site", 0) > 0.5 \
                    and modelled_e > 0:
                e_per_rho = modelled_e / sph["rho_model_at_site"]
                delta_e = sph["rho_at_site"] * e_per_rho
                row["electrons"] = {
                    "modelled_occ_x_z_eff": round(modelled_e, 1),
                    "delta_e_from_residual": round(delta_e, 1),
                    "observed_estimate": round(modelled_e + delta_e, 1),
                    "note": ("Δe = 位点残差高度 × (模型电子 / 模型 Fc 图在该位点的"
                             "高度)。标度因子吸收大部分 Z 失配（单一重原子结构"
                             "尤甚：合成检验里真差 6.7 e 只剩 1.0 e），已精修的 "
                             "ADP 再吸收一部分，只看符号，|Δe| 可低估数倍；"
                             "定量用 integrate_difference_density(labels=[...])"
                             " 的省略图积分")}

            # candidates: given, else current + geometry-compatible metals +
            # cluster-implied + edge-flagged (the last two only when the
            # geometry does not exclude them - the edge warning itself is
            # in the anomalous block regardless)
            cand_set: list[str] = list(given) if given else [el]
            if not given:
                for m in sorted(METAL_PROFILES):
                    if m == el or m in cand_set:
                        continue
                    if donors and _geometry_verdict(
                            m, cn, donors)["status"] in ("fits", "borderline"):
                        cand_set.append(m)
                for m in implied + edge_flagged:
                    if m in cand_set:
                        continue
                    if donors and _geometry_verdict(
                            m, cn, donors)["status"] == "outside":
                        continue
                    cand_set.append(m)
            # direction heuristics are void when the current element or a
            # candidate sits near an edge at lambda (see _FP_DIRECTION_E)
            fp_unreliable = bool(terms) and any(
                abs(float(terms.get(x, {}).get("fp", 0.0))) >= _FP_DIRECTION_E
                for x in set(cand_set) | {el})
            if fp_unreliable and (evidence_dir_u or evidence_dir_rho):
                row["fp_direction_note"] = (
                    "Ueq/残差方向判据在此位点不可靠：候选或当前元素在 λ 处有 "
                    f"|f'| ≥ {_FP_DIRECTION_E:.0f} e，f' 在实空间是中心尖峰而非"
                    "原子形状（边上的 Zr 被判成 Zn 时位点中心反而是负残差）；"
                    "用几何、簇拓扑和含 f' 的比较")
            tally: list[dict[str, Any]] = []
            z_eff_cur = z + fp_cur
            for c in cand_set:
                zc = _z_of(c) or 0
                fp_c = float(terms.get(c, {}).get("fp", 0.0)) if terms else 0.0
                z_eff_c = zc + fp_c
                item: dict[str, Any] = {"element": c, "Z": zc}
                if terms:
                    item["fp"] = round(fp_c, 2)
                    item["z_eff"] = round(z_eff_c, 1)
                score = 0
                ev: list[str] = []
                geo = _geometry_verdict(c, cn, donors) if donors else None
                if geo is not None:
                    item["geometry"] = geo["status"]
                    detail = "; ".join(
                        f"{d}: {v['mean']} vs {v['window'][0]}-{v['window'][1]}"
                        f" ({v.get('fit', '?')})"
                        for d, v in geo["per_donor"].items() if v.get("window"))
                    if geo.get("cn"):
                        detail += (f"; CN {geo['cn']['observed']} vs "
                                   f"{geo['cn']['window'][0]}-"
                                   f"{geo['cn']['window'][1]} "
                                   f"({geo['cn']['fit']})")
                    if geo.get("jahn_teller_axial"):
                        jt = geo["jahn_teller_axial"]
                        detail += f"; JT axial {jt['d']} ({jt['fit']})"
                    item["geometry_detail"] = detail
                    score += {"fits": 2, "borderline": 1, "outside": -2}[
                        geo["status"]]
                    ev.append(f"几何 {geo['status']}")
                dz = z_eff_c - z_eff_cur
                if fp_unreliable:
                    if evidence_dir_u or evidence_dir_rho:
                        ev.append("Ueq/残差方向判据不可靠（λ 处强 f'）")
                else:
                    if evidence_dir_u:
                        if abs(dz) < 2:
                            ev.append("Ueq 方向：与当前元素不可区分")
                        elif (dz > 0) == (evidence_dir_u > 0):
                            score += 1
                            ev.append("Ueq 方向一致")
                        else:
                            score -= 1
                            ev.append("Ueq 方向相反")
                    if evidence_dir_rho:
                        if abs(dz) < 2:
                            ev.append("残差方向：与当前元素不可区分")
                        elif (dz > 0) == (evidence_dir_rho > 0):
                            score += 1
                            ev.append("位点残差方向一致")
                        else:
                            score -= 1
                            ev.append("位点残差方向相反")
                if delta_e is not None:
                    # informational only: the residual understates a Z
                    # mismatch by an unknown factor (scale + ADP absorb it)
                    expected = occ * dz          # electrons this swap adds
                    item["delta_e_expected"] = round(expected, 1)
                    if not fp_unreliable and abs(dz) >= 2:
                        ev.append(f"换 {c} 使位点电子变化 {expected:+.1f} e；"
                                  f"残差估计 Δe={delta_e:+.1f} e（下限，只看符号）")
                if terms and abs(fp_c) >= _FP_STRONG_E:
                    ev.append(f"f'={fp_c:+.1f} e：R 比较必须含 f'"
                              f"（run_shelxl 当前不含）")
                if c in implied:
                    score += 1
                    ev.append("簇模式暗示")
                item["evidence_score"] = score
                item["evidence"] = ev
                tally.append(item)
            tally.sort(key=lambda t: (-t["evidence_score"], t["Z"]))
            row["candidates"] = tally
            if not given:
                row["candidates_note"] = ("默认候选 = 当前元素 + 几何相容的知识表"
                                          "金属 + 簇模式暗示 + λ 处吸收边元素；"
                                          "证据分是计数不是判决")

            # one-line evidence summary per site
            bits = [f"{labels[i]}({el}, Z={z}): CN {cn}"]
            if ds:
                bits[-1] += (f", M–X {row['bonds']['min']}–{row['bonds']['max']}"
                             f" Å")
            top = [t for t in tally if t.get("geometry") == "fits"]
            if top:
                bits.append("几何相容: " + "/".join(t["element"] for t in top[:6]))
            cur = next((t for t in tally if t["element"] == el), None)
            if cur is not None and cur.get("geometry") == "outside":
                bits.append(f"当前元素 {el} 几何不相容（{cur.get('geometry_detail')}）")
            if row.get("ueq_note"):
                bits.append(row["ueq_note"].split("：")[0])
            if row.get("residual_note"):
                bits.append(row["residual_note"].split("：")[0])
            if hint:
                bits.append(hint.split(":")[0])
            if terms and el in terms and abs(terms[el]["fp"]) >= _FP_STRONG_E:
                bits.append(f"f'({el})={terms[el]['fp']:+.1f} e")
            line = "；".join(bits)
            row["evidence_summary"] = line
            site_lines.append(line)
            rows.append(row)

        # ---- readiness: would an R-vs-Z comparison mean anything? -----
        readiness = self._readiness(
            xs=xs, flags=flags, f_mask=f_mask, metrics=metrics, peaks=peaks,
            map_info=map_info, frags=frags, elems=elems, zs=zs, heavy=heavy,
            anomalous=anomalous, rows=rows)

        # ---- statement -----------------------------------------------
        statement: list[str] = []
        if not heavy:
            statement.append(f"模型中没有 Z ≥ {z_min} 的位点。")
        else:
            statement.append(
                f"审计 {len(heavy)} 个重位点（Z ≥ {z_min}）："
                + "，".join(sorted({f"{elems[i]}" for i in heavy})) + "。")
        if anomalous.get("warnings"):
            statement.extend(anomalous["warnings"])
        elif anomalous.get("skipped"):
            statement.append("波长未知：未评估反常散射（不假设 0.71073 Å）。")
        statement.append(readiness["verdict"])
        statement.append(
            "元素身份由化学定（配位数、M–X 距离、簇拓扑、合成先验），R 值差最后看，"
            "且只在就绪模型上、同一引擎内、含 f' 的前提下看；本表是证据不是判决。")

        return ToolResult(ok=True, summary={
            "source": source,
            "n_sites": len(rows),
            "anomalous": anomalous,
            "residual_map": map_info,
            "readiness": readiness,
            "sites": rows,
            "site_summaries": site_lines,
            "statement": statement,
            "caveat": ("三类方向证据（Ueq、位点残差、电子数）各自都有别的解释"
                       "（占有率、无序、数据标度、f'），同向汇证才有分量；几何窗口"
                       "是典型值不是定律。判读规程 read_skill "
                       "element-assignment-audit。"),
        })

    # ---------------------------------------------------------------- readiness
    @staticmethod
    def _readiness(*, xs, flags, f_mask, metrics, peaks, map_info, frags,
                   elems, zs, heavy, anomalous, rows) -> dict[str, Any]:
        blockers: list[str] = []
        cautions: list[str] = []
        checks: dict[str, Any] = {}

        # 1 refinement level
        r1 = (metrics or {}).get("r1_strong")
        checks["refinement"] = {"r1_strong": r1,
                                "source": "last refinement snapshot "
                                          "(stale if the model changed since)"}
        if r1 is None:
            cautions.append("会话里没有精修指标：先 refine/run_shelxl 到收敛再谈 R 比较")
        elif r1 > _R1_ROUGH:
            blockers.append(
                f"R1={r1:.3f}：模型仍在粗调阶段，相邻 Z 候选间 ΔR1<0.005 在此量级"
                f"上是噪声，不是元素证据")
        elif r1 > _R1_CAUTION:
            cautions.append(
                f"R1={r1:.3f}：尚未到精调阶段，候选间 ΔR1 会被其它缺陷主导")

        # 2 completeness: volume expectation (void-corrected) + far residual
        # peaks + ghosts/detached + broken linkers
        n_non_h = sum(1 for e in elems if e not in ("H", "D"))
        mask_info = flags.get("solvent_mask_info") or {}
        void_pct = mask_info.get("solvent_volume_pct_of_cell")
        comp: dict[str, Any] = {"modelled_non_h": n_non_h}
        try:
            vol_asu = xs.unit_cell().volume() / xs.space_group().order_z()
            frac_void = (float(void_pct) / 100.0) if void_pct else 0.0
            expect = vol_asu * (1.0 - frac_void) / _A3_PER_NON_H
            ratio = n_non_h / max(expect, 1e-6)
            comp.update({"asu_volume_A3": round(vol_asu, 0),
                         "void_fraction_used": round(frac_void, 3),
                         "expected_non_h": round(expect, 0),
                         "ratio": round(ratio, 2)})
            if ratio < _INCOMPLETE_RATIO:
                msg = (f"模型只占体积期望非氢原子数的 {100 * ratio:.0f}%"
                       f"（{n_non_h}/{expect:.0f}，按 {_A3_PER_NON_H:.0f} Å³/原子"
                       + ("，已扣除掩膜空腔" if void_pct else "，未扣除任何空腔")
                       + "）")
                if f_mask is None and not flags.get("_mask_recorded"):
                    blockers.append(msg + "：缺原子或溶剂未处理，先补全主体/掩膜")
                else:
                    cautions.append(msg + "：掩膜后仍偏低，检查主体是否完整")
        except Exception:  # noqa: BLE001
            pass
        far = [p for p in peaks if p.get("nearest_d", 0) > _FAR_PEAK_D
               and p.get("height", 0) >= _FAR_PEAK_E]
        if far:
            p0 = max(far, key=lambda p: p["height"])
            comp["largest_far_peak"] = {
                "height": p0["height"], "nearest_atom": p0["nearest_atom"],
                "d_A": p0["nearest_d"], "site": p0["site"]}
            blockers.append(
                f"未建模密度：+{p0['height']:.2f} e/Å³ 距最近原子 "
                f"{p0['nearest_atom']} {p0['nearest_d']:.2f} Å（缺原子，或溶剂既未"
                f"掩膜也未建模），R-vs-Z 会先测这块密度而不是 Z")
        try:
            from ..chem.asu_sanity import asu_coherence
            asu = asu_coherence(xs)
            if asu.get("ghost_suspects"):
                comp["ghost_suspects"] = asu["ghost_suspects"][:8]
                blockers.append(
                    f"幽灵原子嫌疑 {len(asu['ghost_suspects'])} 个：先做删除-精修"
                    f"对照，噪声原子会随元素一起吸收 R")
            if asu.get("n_detached_atoms"):
                comp["n_detached_atoms"] = asu["n_detached_atoms"]
                cautions.append(
                    f"{asu['n_detached_atoms']} 个原子未与主体相连（ASU 未装配）")
        except Exception:  # noqa: BLE001 - advisory
            pass
        dangling = [c for f in frags for c in f.get("dangling_C", [])]
        if dangling:
            comp["dangling_C"] = dangling[:10]
            cautions.append(f"连接体有 {len(dangling)} 个悬空 C（环/羧酸未闭合）")
        checks["completeness"] = comp

        # 3 solvent handling
        solv: dict[str, Any] = {"mask_active": f_mask is not None}
        if f_mask is not None or flags.get("_mask_recorded"):
            solv["mask_recorded"] = True
            if mask_info:
                for k in ("total_solvent_electrons_per_cell",
                          "solvent_volume_pct_of_cell",
                          "solvent_mask_converged"):
                    if k in mask_info:
                        solv[k] = mask_info[k]
                if mask_info.get("solvent_mask_converged") is False:
                    cautions.append("溶剂掩膜未收敛：掩膜电子数未定，R 比较不稳")
            if flags.get("_mask_uncached"):
                cautions.append("该节点记录了掩膜但未缓存 f_mask：残差图未含掩膜")
        else:
            if far or comp.get("ratio", 1.0) < _INCOMPLETE_RATIO:
                blockers.append(
                    "溶剂既未掩膜也未建模（无 f_mask，且有远离原子的残差/体积缺口）"
                    "：掩膜或建模之后再做元素竞争")
                solv["note"] = "unhandled"
            else:
                solv["note"] = ("no mask and no far residual / volume gap - "
                                "dense structure or already modelled")
        checks["solvent"] = solv

        # 4 hydrogens
        n_h = sum(1 for e in elems if e in ("H", "D"))
        has_c = any(e == "C" for e in elems)
        hyd = {"n_h_atoms": n_h,
               "riding_meta": bool(flags.get("h_riding_meta")),
               "constraints": bool(flags.get("h_constraints"))}
        if has_c and n_h == 0 and not hyd["riding_meta"] \
                and not hyd["constraints"]:
            cautions.append(
                "H 未放置：骑乘 H 对 R1 的贡献（0.005–0.01）与相邻 Z 候选间的 ΔR1 "
                "同量级")
        checks["hydrogens"] = hyd

        # 5 weights
        w = flags.get("weights") or {}
        a, b = w.get("a"), w.get("b")
        default_w = (not w) or (abs(float(a or 0.1) - 0.1) < 1e-9
                                and abs(float(b or 0.0)) < 1e-9)
        checks["weights"] = {"a": a, "b": b, "default_scheme": default_w}
        if default_w:
            cautions.append("WGHT 仍是默认 0.1/0：wR2/GooF 未标定，候选间比较用 R1 且"
                            "注意 ΔR1 的噪声底")

        # 6 anomalous scattering in the comparison engine
        if anomalous.get("wavelength_A") and (anomalous.get("strong_fp")
                                              or anomalous.get("edge_at_lambda")):
            checks["anomalous"] = {
                "strong_fp": anomalous.get("strong_fp"),
                "edge_at_lambda": anomalous.get("edge_at_lambda")}
            cautions.append(
                "λ 处有强 f' 元素：只能在含 f' 的引擎里比较（进程内 refine 含；"
                "run_shelxl 无 DISP 卡不含），两种引擎的 R 不可混比")
        elif not anomalous.get("wavelength_A"):
            cautions.append("波长未知：无法判断 f' 是否影响 R 比较")

        # 7 heavy sites isotropic
        iso = [r["label"] for r in rows if not r.get("aniso")]
        if iso and rows:
            checks["heavy_adp"] = {"isotropic": iso[:10]}
            cautions.append(
                f"{len(iso)} 个重位点仍是各向同性 ADP：候选比较前统一 ADP 模型"
                f"（同一 ADP 模型、同一轮次、同一掩膜/权重）")

        ready = not blockers
        if ready:
            verdict = ("就绪：模型完整、溶剂已处理，此时同一引擎内的 R-vs-Z 比较"
                       "才有意义" + (f"（仍有 {len(cautions)} 条注意）"
                                     if cautions else "")
                       + "；即便如此，相邻 Z 候选间 ΔR1 通常 <0.005，不能推翻化学。")
        else:
            verdict = ("未就绪：" + "；".join(blockers)
                       + "。在这种模型上做 R-vs-Z 元素竞争，测到的是模型缺陷不是 Z"
                       "（pa1 hex-l1-r1 / cage-l0-r1 的失败模式）。")
        return {"ready_for_r_vs_z": ready, "blockers": blockers,
                "cautions": cautions, "checks": checks, "verdict": verdict}
