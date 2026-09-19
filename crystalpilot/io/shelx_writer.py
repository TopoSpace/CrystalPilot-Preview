"""Full SHELX .ins/.res writer for refinement models.

Why not iotbx.shelx.writer: it asserts fp==0/fdp==0 (our refined structures
carry inelastic form factors), hard-asserts 4-char labels, and cannot emit
AFIX riding-H blocks or restraint cards. This writer follows the same wire
conventions (LATT sign rule, sof = 10 + scatterer.weight() for fixed
occupancies, U_cif order U11 U22 U33 U23 U13 U12 with '=' continuation) and
adds what an agentic refinement workbench needs:

  - AFIX riding-hydrogen blocks driven by AddHydrogens' per_carrier metadata
    (kind -> AFIX code; H written with U = -1.2/-1.5 so SHELXL rides them);
  - arbitrary pre-formatted restraint/instruction cards;
  - label sanitation to SHELX's 4-character limit with a rename map returned
    to the caller (so restraint specs / H metadata can be kept in sync);
  - optional SHELXL command block (L.S./ACTA/FMAP/PLAN/BOND) for running the
    real shelxl.exe on the produced file;
  - DISP cards (Sasaki f'/f'' + NIST mu per SFAC element) whenever the
    wavelength is not one SHELXL carries built-in terms for - see
    disp_cards(): pa1's synchrotron data on the Zr K edge went through
    every run_shelxl job with SHELXL's Mo K-alpha terms.

Output is parseable by xray.structure.from_shelx / smtbx model builders.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from cctbx import adptbx
from cctbx.eltbx import tiny_pse
from .shelx_codes import FREE_LIMIT, unencodable_free_params, wrap_card
from .twin import twin_basf_error

# AddHydrogens kind -> SHELX AFIX code (m*10 + n; n=3 riding, n=7 rotating)
AFIX_OF_KIND = {
    "aromatic_CH": 43,
    "NH_planar": 43,
    "CH2": 23,
    "tertiary_CH": 13,
    "tertiary_NH": 13,
    "CH3": 137,
    "CH3_rotating": 137,
    "vinyl_CH2": 93,
    "NH2_planar": 93,
    "linear_CH": 163,
    "OH": 147,
}
U_MULT_OF_KIND = {k: (1.5 if k in ("CH3", "CH3_rotating", "OH") else 1.2)
                  for k in AFIX_OF_KIND}

# --------------------------------------------------------------------------
# What SHELXL demands of an AFIX pivot's connectivity
#
# ka1 cage-tools-r1 (2026-09-03): 8 of the arm's 16 tool failures were one
# defect - add_hydrogens emitted AFIX groups SHELXL rejects ("** BAD AFIX
# 43 CONNECTIVITY OR PART NUMBERS: CKA BONDS TO CX NF CB Zr3 ... **
# TERMINATING BECAUSE OF BAD HFIX OR AFIX INSTRUCTIONS **"). The error
# surfaces only at the NEXT run_shelxl and names ONE bad carrier per run,
# so the agent sawtoothed through six rounds of add_hydrogens(exclude=[...
# one more ...]) before giving up on hydrogens altogether.
#
# Everything below was MEASURED on vendor/shelx/shelxl.exe (SHELXL
# 2019/3) rather than read off a manual, because the manual does not
# spell out the neighbour counts:
#
#  (a) connectivity: SHELXL prints "Covalent radii and connectivity table"
#      in the .lst and bonds two atoms when d <= r_i + r_j + 0.5 A with
#      the SFAC radii (C-C bonded at 2.00 A, not at 2.05, radii sum 1.54;
#      C-Zr bonded at 2.80, not at 3.00, sum 2.36);
#  (b) the counts per m code, from fragments built with 0/1/2/3/4
#      neighbours (a "max" of None = SHELXL ignores the extra bonds and
#      generates the group anyway);
#  (c) the fallback when the count does not match: SHELXL drops bonds to
#      atoms OUTSIDE Z 6-10 and tries again, saying so ("** Bond(s) to
#      Fe1 ignored in idealizing H-atoms attached to C1 **"), which is
#      how a ferrocene Cp carbon keeps its AFIX 43 with the Fe in the
#      connectivity table. The window was measured element by element: C,
#      N, O, F, Ne are kept; Li, Be, B, Na, Mg, Al, Si, P, S, Cl, Ca, Fe,
#      Zn, As, Se, Br, Zr, Sn, Sb, I, Pb are droppable - metals and heavy
#      main-group alike, so it is not a metal rule. It is keyed on the
#      ELEMENT, not on the SFAC radius: raising oxygen's SFAC radius to
#      0.90 does not make SHELXL drop a C-O bond. It drops only as many
#      as it needs and no more: P-CH2-N and Zr-CH2-C pass AFIX 23
#      untouched (full count already 2), and a C bonded to C + S + Zr
#      passes AFIX 43 by dropping the Zr alone and keeping the S.
#
# So a group is accepted when ANY count between "all bonds" and "all
# bonds minus the droppable ones" fits the m code.
#
# AFIX 93 additionally needs the pivot's neighbour to carry at least one
# further bonded atom - the plane of the =CH2 / planar NH2 comes from it
# (a Zr in that role is enough); with a bare neighbour SHELXL refuses the
# group even at the right count.
SHELXL_BOND_TOLERANCE_A = 0.5
#: atomic-number window SHELXL keeps when it has to drop bonds to make an
#: AFIX group fit (C, N, O, F, Ne); H is never counted at all
SHELXL_H_GEN_Z_RANGE = (6, 10)
#: SHELXL's own default SFAC covalent radii, read back element by element
#: from the "Covalent radii and connectivity table" block of its .lst
#: (vendor/shelx/shelxl.exe, SHELXL 2019/3, 2026-09-04). They are NOT the
#: cctbx/Cordero radii chem.connectivity uses: for light atoms the two
#: agree within ~0.03 A, but for metals they diverge by up to 0.2 A (Zr
#: 1.59 vs 1.75, La 1.87 vs 2.07, Ca 1.97 vs 1.76), which decides whether
#: a long M...C contact is a bond in SHELXL's table - and therefore
#: whether it counts against an AFIX group. Unlisted elements fall back
#: to the cctbx radius.
SHELXL_SFAC_RADII_A: dict[str, float] = {
    "H": 0.32, "He": 1.50, "Li": 1.52, "Be": 1.11, "B": 0.82,
    "C": 0.77, "N": 0.70, "O": 0.66, "F": 0.64, "Ne": 1.50, "Na": 1.86,
    "Mg": 1.60, "Al": 1.25, "Si": 1.17, "P": 1.10, "S": 1.03,
    "Cl": 0.99, "Ar": 1.50, "K": 2.27, "Ca": 1.97, "Sc": 1.61,
    "Ti": 1.45, "V": 1.31, "Cr": 1.24, "Mn": 1.37, "Fe": 1.24,
    "Co": 1.25, "Ni": 1.25, "Cu": 1.28, "Zn": 1.33, "Ga": 1.26,
    "Ge": 1.22, "As": 1.21, "Se": 1.17, "Br": 1.14, "Kr": 1.50,
    "Rb": 2.48, "Sr": 2.15, "Y": 1.78, "Zr": 1.59, "Nb": 1.43,
    "Mo": 1.36, "Tc": 1.35, "Ru": 1.33, "Rh": 1.35, "Pd": 1.38,
    "Ag": 1.44, "Cd": 1.49, "In": 1.44, "Sn": 1.40, "Sb": 1.41,
    "Te": 1.37, "I": 1.33, "Xe": 1.50, "Cs": 2.65, "Ba": 2.17,
    "La": 1.87, "Ce": 1.83, "Pr": 1.82, "Nd": 1.81, "Pm": 1.81,
    "Sm": 1.80, "Eu": 2.00, "Gd": 1.79, "Tb": 1.76, "Dy": 1.75,
    "Ho": 1.74, "Er": 1.73, "Tm": 1.72, "Yb": 1.94, "Lu": 1.72,
    "Hf": 1.56, "Ta": 1.43, "W": 1.37, "Re": 1.37, "Os": 1.34,
    "Ir": 1.36, "Pt": 1.37, "Au": 1.44, "Hg": 1.50, "Tl": 1.64,
    "Pb": 1.60, "Bi": 1.60, "Po": 1.60, "At": 1.60, "Rn": 1.80,
    "Fr": 2.80, "Ra": 2.20, "Ac": 1.90, "Th": 1.85, "Pa": 1.80,
    "U": 1.80, "Np": 1.80, "Pu": 1.80, "Am": 1.80, "Cm": 1.80,
}
#: AFIX code -> (min, max) counted neighbours; max None = no upper bound
AFIX_NEIGHBOUR_RULE: dict[int, tuple[int, int | None]] = {
    13: (3, 3),      # m=1  tertiary CH / NH
    23: (2, 2),      # m=2  secondary CH2
    33: (1, None),   # m=3  methyl, torsion from the neighbour
    43: (2, 2),      # m=4  aromatic / amide CH, NH
    83: (1, 1),      # m=8  hydroxyl OH
    93: (1, None),   # m=9  X=CH2 / planar NH2
    137: (1, None),  # m=13 rotating methyl
    147: (1, 1),     # m=14 rotating hydroxyl
    163: (1, 1),     # m=16 acetylenic CH
}
#: AFIX codes whose pivot's neighbour must carry a further counted
#: substituent (it defines the group's plane)
AFIX_NEEDS_NEIGHBOUR_SUBSTITUENT = frozenset({93})


def shelxl_counts_as_neighbour(element: str) -> bool:
    """Is a bond to `element` one SHELXL will KEEP when it has to drop
    bonds to make an AFIX group fit?

    Element-generic: an atomic-number window, not a list of metals -
    everything outside Z 6-10 (H and Li/Be/B below, Na and everything
    heavier above, metals and heavy main-group alike) is droppable and
    is reported as "Bond(s) to X ignored in idealizing H-atoms".
    """
    from cctbx.eltbx import tiny_pse
    try:
        z = int(tiny_pse.table(element_of(element)).atomic_number())
    except Exception:  # noqa: BLE001 - unknown symbol: treat as ignored
        return False
    lo, hi = SHELXL_H_GEN_Z_RANGE
    return lo <= z <= hi


def shelxl_radius(element: str) -> float:
    """SHELXL's SFAC covalent radius for an element, cctbx's when SHELXL
    has none (Z > 96)."""
    from ..chem.connectivity import covalent_radius
    try:
        el = element_of(element)
    except ValueError:          # unreadable scattering type
        el = "C"
    r = SHELXL_SFAC_RADII_A.get(el)
    return r if r is not None else covalent_radius(el)


def shelxl_bonded(element_i: str, element_j: str, d: float) -> bool:
    """SHELXL's connectivity rule: d <= sum of the covalent radii + 0.5 A,
    with SHELXL's own radii (see SHELXL_SFAC_RADII_A)."""
    return (d <= shelxl_radius(element_i) + shelxl_radius(element_j)
            + SHELXL_BOND_TOLERANCE_A)


def afix_count_fits(afix: int, n_bonded: int, n_after_dropping: int) -> bool:
    """Can SHELXL make an AFIX `afix` group out of a pivot with
    `n_bonded` bonded non-H neighbours, `n_after_dropping` of them
    outside the droppable window? It drops as many droppable bonds as it
    needs and no more, so any count in [n_after_dropping, n_bonded] is
    available to it. Unknown codes are not judged (True)."""
    rule = AFIX_NEIGHBOUR_RULE.get(afix)
    if rule is None:
        return True
    lo, hi = rule
    return any(n >= lo and (hi is None or n <= hi)
               for n in range(n_after_dropping, n_bonded + 1))


def afix_connectivity_problems(xray_structure, h_riding,
                               parts: dict[str, int] | None = None
                               ) -> list[dict[str, Any]]:
    """Every riding group whose AFIX code SHELXL's connectivity check
    would refuse for THIS structure.

    Written for the .ins-writing side: h_riding_meta is carried in the
    session and replayed verbatim, so a model that changed after
    add_hydrogens (atoms added from the difference map, a reassigned
    element, a space-group change) can carry AFIX groups that no longer
    match the connectivity - and SHELXL then aborts the whole job
    ("TERMINATING BECAUSE OF BAD HFIX OR AFIX INSTRUCTIONS") instead of
    refining. Returns one row per offender, so a caller can name all of
    them at once.
    """
    from cctbx import crystal as _crystal
    groups = [g for g in (h_riding or []) if g.get("carrier")]
    if not groups:
        return []
    scs = xray_structure.scatterers()
    labels = [sc.label for sc in scs]
    by_upper = {lb.upper(): i for i, lb in enumerate(labels)}
    elems = []
    for sc in scs:
        try:
            elems.append(element_of(sc.scattering_type))
        except ValueError:
            elems.append("C")
    part_of = {str(k).upper(): int(v) for k, v in (parts or {}).items()}
    part = [part_of.get(lb.upper(), 0) for lb in labels]
    radii = [shelxl_radius(e) for e in elems] or [0.77]
    cutoff = 2.0 * max(radii) + SHELXL_BOND_TOLERANCE_A
    uc = xray_structure.unit_cell()
    sites = [tuple(sc.site) for sc in scs]
    asu = xray_structure.asu_mappings(buffer_thickness=cutoff)
    pat = _crystal.pair_asu_table(asu)
    pat.add_all_pairs(distance_cutoff=cutoff)
    pst = pat.extract_pair_sym_table(skip_j_seq_less_than_i_seq=False,
                                     all_interactions_from_inside_asu=True)
    out: list[dict[str, Any]] = []
    for g in groups:
        i = by_upper.get(str(g["carrier"]).upper())
        if i is None:
            continue
        afix = g.get("afix") or AFIX_OF_KIND.get(g.get("kind") or "")
        if afix is None or afix not in AFIX_NEIGHBOUR_RULE:
            continue
        def neighbours(k: int) -> list[tuple[int, float]]:
            hits = []
            for j, ops in pst[k].items():
                if elems[j] == "H":
                    continue
                if part[k] and part[j] and abs(part[k]) != abs(part[j]):
                    continue
                for op in ops:
                    d = uc.distance(sites[k], op * sites[j])
                    if d >= 0.1 and shelxl_bonded(elems[k], elems[j], d):
                        hits.append((j, d))
            return hits

        nbs = neighbours(i)
        bonded = ["%s:%.2f(%s)" % (labels[j], d, elems[j]) for j, d in nbs]
        droppable = ["%s:%.2f(%s)" % (labels[j], d, elems[j])
                     for j, d in nbs if not shelxl_counts_as_neighbour(elems[j])]
        n_all = len(nbs)
        problem = None
        if not afix_count_fits(afix, n_all, n_all - len(droppable)):
            problem = "count"
        elif afix in AFIX_NEEDS_NEIGHBOUR_SUBSTITUENT and nbs:
            # the plane of an =CH2 / planar NH2 comes from a substituent
            # of the pivot's neighbour; a bare neighbour has none
            if not [k for k, _d in neighbours(nbs[0][0]) if k != i]:
                problem = "substituent"
        if problem is None:
            continue
        lo, hi = AFIX_NEIGHBOUR_RULE[afix]
        out.append({
            "atom": labels[i], "afix": afix, "kind": g.get("kind"),
            "problem": problem,
            "expected": ((f"exactly {lo}" if hi == lo else
                          f"at least {lo}" if hi is None else f"{lo}-{hi}")
                         + (" + one further atom on that neighbour"
                            if problem == "substituent" else "")),
            "n_bonded": n_all,
            "n_after_dropping_heavy": n_all - len(droppable),
            "bonded": bonded, "droppable": droppable,
            "h": list(g.get("h") or [])})
    return out


def element_of(scattering_type: str) -> str:
    """'Zr' -> 'Zr', 'O2-' -> 'O', 'Cu2+' -> 'Cu'."""
    m = re.match(r"([A-Za-z]{1,2})", scattering_type.strip())
    if not m:
        raise ValueError(f"cannot read element from {scattering_type!r}")
    e = m.group(1)
    return e[0].upper() + e[1:].lower() if len(e) == 2 else e.upper()


def sanitize_labels(labels: list[str]) -> dict[str, str]:
    """Return {old: new} making every label <=4 chars and unique (SHELX limit).

    Labels already valid keep their name; offenders get a deterministic
    element-preserving rename. Callers must apply the map to any label-based
    metadata (restraints, H riding info).
    """
    rename: dict[str, str] = {}
    used: set[str] = set()
    for lbl in labels:
        cand = lbl.strip()
        if len(cand) <= 4 and cand.upper() not in used:
            used.add(cand.upper())
            if cand != lbl:
                rename[lbl] = cand
            continue
        head = re.match(r"[A-Za-z]{1,2}", cand)
        stem = (head.group(0) if head else "X")[:2]
        n = 0
        while True:
            tag = _b36(n)
            new = f"{stem}{tag}"[:4]
            if new.upper() not in used:
                break
            n += 1
        used.add(new.upper())
        rename[lbl] = new
    return rename


def _b36(n: int) -> str:
    digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if n == 0:
        return "0"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return out


# ---- anomalous dispersion (DISP) -----------------------------------------
#: K-alpha lines for which the vendored SHELXL-2019/3 carries built-in
#: f'/f''/mu (International Tables). The manual lists Cr 2.2909 and Fe
#: 1.9373 as well; the binary prints "DISP instructions may be required"
#: for both and computes with its Mo K-alpha table (measured 2026-09-02 on
#: vendor/shelx/shelxl.exe with synthetic anomalous data: at Cr K-alpha the
#: plain job reproduces the R1 of explicit Mo terms, and its .lst Mu is the
#: Mo value). They are deliberately absent here: a wavelength outside this
#: table gets explicit DISP cards, which is harmless where SHELXL would
#: have known it and essential where it would not.
SHELXL_BUILTIN_KALPHA_A = {"Cu": 1.5418, "Mo": 0.7107, "Ag": 0.5608}
#: SHELXL itself accepts +-0.01 A around those lines (0.703-0.720 silent,
#: 0.700 / 0.725 warn) and then uses the K-alpha table whatever the true
#: lambda. Our window is deliberately tight: 0.71073 / 0.71069 / 1.54178 /
#: 1.54184 still count as built-in, but Mo K-alpha1 0.70930 or a synchrotron
#: parked near a lab line gets Sasaki terms at the TRUE wavelength - the
#: numbers the in-process engine uses (tools/refinement_tools.py,
#: set_inelastic_form_factors(lambda, "sasaki")), so the two engines' R
#: values are computed with the same scattering model.
SHELXL_BUILTIN_TOL_A = 0.0005
#: below this the "wavelength" is an electron beam (ParsedShelxModel.
#: is_electron_diffraction uses the same cut): X-ray f'/f'' do not apply
_ELECTRON_LAMBDA_A = 0.1
#: CELL needs a number even when the dataset carries no wavelength; Mo
#: K-alpha is the placeholder every caller used before DISP existed
PLACEHOLDER_WAVELENGTH_A = 0.71073
_BARN_PER_CM2_PER_MOL = 1e24 / 6.02214076e23    # (cm^2/g * g/mol) -> barn
_PHOTOABSORPTION_BARN_PER_A = 2 * 2.8179403e-13 * 1e-8 * 1e24  # 2 r_e * A


def shelxl_builtin_radiation(wavelength: float | None) -> str | None:
    """'Cu' / 'Mo' / 'Ag' when SHELXL has its own f'/f'' for lambda, else None."""
    if wavelength is None:
        return None
    for name, lam in SHELXL_BUILTIN_KALPHA_A.items():
        if abs(float(wavelength) - lam) <= SHELXL_BUILTIN_TOL_A:
            return name
    return None


def anomalous_terms(element: str,
                    wavelength: float) -> tuple[float, float, str] | None:
    """(f', f'', table) in electrons at `wavelength` (A).

    Sasaki first - it is the table the in-process engine sets, so a DISP
    card built from it makes SHELXL and smtbx refine the same scatterer -
    Henke for what Sasaki lacks (H, D). None when neither table covers the
    element or the wavelength (SHELXL then keeps its Mo K-alpha terms and
    the writer says so in a REM)."""
    from cctbx.eltbx import henke, sasaki
    for name, mod in (("sasaki", sasaki), ("henke", henke)):
        try:
            at = mod.table(element).at_angstrom(float(wavelength))
        except Exception:  # noqa: BLE001 - unknown label / out of range
            continue
        if at.is_valid_fp() and at.is_valid_fdp():
            return float(at.fp()), float(at.fdp()), name
    return None


def apply_anomalous_terms(xs, wavelength, table: str = "sasaki"
                          ) -> dict[str, list[float]] | None:
    """Set f'/f'' on every scatterer of `xs` for an X-ray `wavelength` (A).

    The ONE place the in-process engine, the heavy-site maps and every
    session rebuild (import / checkout / branch / viewer recount) take their
    anomalous terms from, so a model refined with them never comes back
    from disk without them. Live Zr-MOF 2026-09-06: the data sit on the
    Zr K edge (0.68883 A, f' = -9.0 e on Zr); the mask refined with the
    terms read 591.6 e/cell, the viewer recount on the same model.res
    rebuilt WITHOUT them read 1193.2 - a factor two that was not chemistry.

    Returns {scattering type: [f', f'']} as set, None when nothing was
    applied: no wavelength, an electron wavelength (X-ray tables do not
    apply) or a table failure - the terms then stay as they were."""
    if not wavelength or float(wavelength) < _ELECTRON_LAMBDA_A:
        return None
    try:
        xs.set_inelastic_form_factors(float(wavelength), table)
    except Exception:  # noqa: BLE001 - exotic wavelength / element tables
        return None
    return anomalous_terms_of(xs)


def anomalous_terms_of(xs) -> dict[str, list[float]]:
    """{scattering type: [f', f'']} currently set on `xs` (3 decimals)."""
    out: dict[str, list[float]] = {}
    for sc in xs.scatterers():
        out.setdefault(sc.scattering_type.strip(),
                       [round(float(sc.fp), 3), round(float(sc.fdp), 3)])
    return out


def atomic_attenuation_barn(element: str, wavelength: float,
                            fdp: float) -> float:
    """SHELXL's DISP `mu`: the atomic attenuation cross-section in barn.

    Measured on vendor/shelx/shelxl.exe (2026-09-02): the .lst "Mu" (mm^-1)
    is sum_i(n_i mu_i) / (10 V[A^3]), i.e. mu_i is 1e-24 cm^2 per atom, and
    it feeds _exptl_absorpt_coefficient_mu in the ACTA CIF (at an unknown
    wavelength SHELXL reports the Mo K-alpha value: 0.35 instead of 2.00
    mm^-1 for a Zr/O test cell on the Zr edge). The manual marks the field
    optional; the 2019/3 binary rejects a card without it ("WRONG NUMBER OF
    NUMERICAL PARAMETERS"). NIST total attenuation (cctbx.eltbx.
    attenuation_coefficient) when the element has a table - it matches
    SHELXL's own International Tables value at the lab lines (Zr at Mo
    K-alpha: 2475 vs ~2490 barn) - else the photoabsorption part 2 r_e
    lambda f'' (a few % low: no scattering contribution)."""
    try:
        from cctbx.eltbx import attenuation_coefficient
        mu_rho = attenuation_coefficient.get_table(
            element).mu_rho_at_angstrom(float(wavelength))       # cm^2/g
        return float(mu_rho) * float(tiny_pse.table(element).weight()) \
            * _BARN_PER_CM2_PER_MOL
    except Exception:  # noqa: BLE001 - no NIST table (Z > 92)
        return _PHOTOABSORPTION_BARN_PER_A * float(wavelength) * float(fdp)


def _f3(v: float) -> str:
    return "%.3f" % (round(v, 3) + 0.0)     # + 0.0: never '-0.000' (H)


def _rem_disp(text: str, width: int = 78) -> list[str]:
    """`REM DISP ...` lines, word-wrapped: every line carries the tag (so a
    grep finds the whole note) and stays inside SHELXL's classic 80 columns."""
    lines: list[str] = []
    cur = "REM DISP"
    for word in text.split():
        if len(cur) + 1 + len(word) > width and cur != "REM DISP":
            lines.append(cur)
            cur = "REM DISP"
        cur += " " + word
    lines.append(cur)
    return lines


def disp_cards(elements: Iterable[str],
               wavelength: float | None) -> tuple[list[str], list[str]]:
    """`DISP $El f' f'' mu` cards for the SFAC elements at `wavelength`, and
    the REM lines that explain whatever got none. Both go between SFAC and
    UNIT - the only place SHELXL accepts DISP ("DISP MUST COME BETWEEN SFAC
    AND UNIT"); SHELXL echoes them into its .res, so the adopt_wght loop
    and the CIF's _shelx_res_file keep them.

    Why: SHELXL knows f'/f'' only for SHELXL_BUILTIN_KALPHA_A. At any other
    CELL wavelength it prints "DISP instructions may be required" and
    silently refines with its Mo K-alpha table. pa1 (synchrotron, 0.68883 A
    = the Zr K edge, f'(Zr) = -9.0 e) ran every run_shelxl R-vs-Z ladder
    that way: Zr modelled as ~37 e against a crystal scattering ~31 e, Zn
    had to win, and hex-l1-r1 delivered NU-1000 as a Zn3 framework
    (workbench/pa1/hex-l1-r1/.../job_20260902_030659/job.lst line 123).
    The in-process engine had the Sasaki terms all along, so the two
    engines' R values disagreed without anyone noticing."""
    cards: list[str] = []
    rems: list[str] = []
    if wavelength is None:
        rems += _rem_disp(
            "not written: the dataset carries no wavelength; CELL holds the "
            "Mo K-alpha placeholder %.5f. ingest_vendor_data(wavelength=...) "
            "or import_cif_model(wavelength=...) puts the true lambda on CELL"
            % PLACEHOLDER_WAVELENGTH_A)
        return cards, rems
    wl = float(wavelength)
    if wl < _ELECTRON_LAMBDA_A:
        rems += _rem_disp("not written: lambda %g A is an electron beam, "
                          "X-ray f'/f'' do not apply" % wl)
        return cards, rems
    if shelxl_builtin_radiation(wl):
        return cards, rems      # SHELXL's own International Tables terms
    tables: dict[str, list[str]] = {}
    missing: list[str] = []
    for el in elements:
        terms = anomalous_terms(el, wl)
        if terms is None:
            missing.append(el)
            continue
        fp, fdp, table = terms
        mu = atomic_attenuation_barn(el, wl, fdp)
        cards.append("DISP $%s %s %s %.2f" % (el, _f3(fp), _f3(fdp), mu))
        tables.setdefault(table, []).append(el)
    if cards:
        used = "; ".join("%s: %s" % (t, " ".join(els))
                         for t, els in tables.items())
        rems += _rem_disp(
            "lambda %.5f A is not a SHELXL built-in line (Cu/Mo/Ag K-alpha): "
            "f'/f'' from cctbx (%s), mu = NIST attenuation in barn/atom"
            % (wl, used))
    if missing:
        rems += _rem_disp("not written for %s: no f'/f'' table at this "
                          "wavelength" % " ".join(missing))
    return cards, rems


@dataclass
class ShelxModel:
    """Everything needed to serialize one model state as .ins/.res text."""
    xray_structure: Any                      # cctbx xray.structure
    #: None = unknown: CELL gets PLACEHOLDER_WAVELENGTH_A and a REM says so
    #: instead of DISP cards (disp_cards); callers used to coerce with
    #: `or 0.71073`, which made an unknown wavelength look like Mo K-alpha
    wavelength: float | None = 0.71073
    z: int | None = None                     # formula units for ZERR
    title: str = "CrystalPilot"
    rem_lines: list[str] = field(default_factory=list)
    instruction_cards: list[str] = field(default_factory=list)   # L.S. etc.
    restraint_cards: list[str] = field(default_factory=list)     # DFIX/SADI/...
    weights: tuple[float, float] = (0.1, 0.0)
    scale: float | None = None               # FVAR overall scale
    h_riding: list[dict] | None = None       # AddHydrogens per_carrier entries
    afix_groups: list[dict] = field(default_factory=list)  # non-H rigid groups
    hklf: int = 4
    cell_esd: tuple | None = None            # ZERR esds (a b c al be ga)
    fvars: list[float] = field(default_factory=list)  # FVAR 2..n (disorder)
    #: label -> raw SHELX sof to write instead of weight()+10
    #: (FVAR coding: +(10k+p)=p*fv(k), -(10k+p)=p*(1-fv(k)))
    sof_codes: dict[str, float] | None = None
    parts: dict[str, int] | None = None      # label -> PART number
    #: {"matrix": [9 floats], "n": int, "basf": [floats]} -> TWIN/BASF cards
    twin: dict | None = None
    #: verbatim SHEL/OMIT/MERG/EXTI/SWAT cards (reflection-set/Fc-affecting)
    data_cards: list[str] = field(default_factory=list)


def write_res_text(m: ShelxModel) -> tuple[str, dict[str, str]]:
    """Serialize to SHELX text. Returns (text, label_rename_map)."""
    twin_error = twin_basf_error(m.twin)
    if twin_error:
        raise ValueError(twin_error)
    xs = m.xray_structure
    sg = xs.space_group()
    sgi = xs.space_group_info()
    uc = xs.unit_cell()
    if sg.is_centric() and not sg.is_origin_centric():
        raise ValueError("centrosymmetric structure must use an origin-centric "
                         "setting for SHELX output")

    scatterers = list(xs.scatterers())
    rename = sanitize_labels([sc.label for sc in scatterers])
    lbl = {sc.label: rename.get(sc.label, sc.label.strip()) for sc in scatterers}

    # SFAC: C, H first (SHELX convention), then ascending atomic number.
    elements: list[str] = []
    for sc in scatterers:
        e = element_of(sc.scattering_type)
        if e not in elements:
            elements.append(e)
    sfac = [e for e in ("C", "H") if e in elements]
    sfac += sorted((e for e in elements if e not in sfac),
                   key=lambda e: tiny_pse.table(e).atomic_number())
    sf_idx = {e: i + 1 for i, e in enumerate(sfac)}
    uc_content = xs.unit_cell_content()
    unit = [f"{uc_content.get(e, 0.0):.1f}" for e in sfac]

    lines: list[str] = []
    lines.append(f"TITL {m.title} in {sgi.type().lookup_symbol()}")
    for rem in m.rem_lines:
        lines.append(f"REM {rem}")
    cell = uc.parameters()
    wl = (PLACEHOLDER_WAVELENGTH_A if m.wavelength is None
          else float(m.wavelength))
    lines.append("CELL %.5f %.5f %.5f %.5f %.4f %.4f %.4f" % ((wl,) + cell))
    z = m.z if m.z is not None else sg.order_z()
    esd = m.cell_esd if m.cell_esd and len(m.cell_esd) == 6 else (0,) * 6
    lines.append("ZERR %s %.5f %.5f %.5f %.4f %.4f %.4f" % ((z,) + tuple(esd)))
    latt = 1 + "PIRFABC".find(sg.conventional_centring_type_symbol())
    if not sg.is_origin_centric():
        latt = -latt
    lines.append(f"LATT {latt}")
    for i in range(sg.n_smx()):
        rt = sg(0, 0, i)
        if rt.is_unit_mx():
            continue
        lines.append("SYMM %s" % rt.as_xyz(decimal=False, t_first=False,
                                           symbol_letters="XYZ", separator=","))
    lines.append(wrap_card("SFAC " + " ".join(sfac)))
    disp, disp_rem = disp_cards(sfac, m.wavelength)   # SHELXL: SFAC < DISP < UNIT
    lines.extend(disp_rem)
    lines.extend(disp)
    lines.append(wrap_card("UNIT " + " ".join(unit)))
    lines.append("")
    for card in m.instruction_cards:
        lines.append(card)
    if m.instruction_cards:
        lines.append("")
    for card in m.data_cards:
        lines.append(card)
    if m.data_cards:
        lines.append("")
    for card in m.restraint_cards:
        lines.append(card)
    if m.restraint_cards:
        lines.append("")
    if m.twin:
        tw = m.twin
        if tw.get("matrix"):
            mat = " ".join("%g" % float(x) for x in tw["matrix"])
            lines.append(f"TWIN {mat} {int(tw.get('n', 2))}")
        basf = tw.get("basf") or []
        if basf:
            # BASF without TWIN is the HKLF5 case (law lives in the data)
            lines.append(wrap_card("BASF " + " ".join("%.5f" % float(b) for b in basf)))
    lines.append("WGHT %.6f %.6f" % m.weights)
    fvar_vals = [m.scale if m.scale is not None else 1.0] + \
        [float(v) for v in m.fvars]
    lines.append(wrap_card("FVAR " + " ".join("%.5f" % v for v in fvar_vals)))

    # ---- atom cards, with riding H grouped after their carriers -------------
    by_label = {lbl[sc.label]: sc for sc in scatterers}
    afix_first, afix_members = {}, set()
    for block in m.afix_groups:
        members = [rename.get(a, a) for a in block["atoms"]]
        missing = [a for a in members if a not in by_label]
        if missing or not members or len(set(members)) != len(members) or afix_members.intersection(members):
            raise ValueError(f"AFIX {block['afix']} group has missing/duplicate atoms "
                             f"{missing or members}; restore the group before serializing")
        afix_first[members[0]] = {**block, "atoms": members}
        afix_members.update(members)
    riding: dict[str, dict] = {}      # carrier(new label) -> entry
    h_in_riding: set[str] = set()
    for entry in (m.h_riding or []):
        carrier = rename.get(entry["carrier"], entry["carrier"])
        hs = [rename.get(h, h) for h in entry.get("h", [])]
        if (carrier not in by_label or carrier in riding
                or not all(h in by_label for h in hs)):
            continue
        # an H atom rides on ONE carrier - the first entry that names it.
        # A per_carrier list naming one H under two carriers (pa2
        # cage-l0-r2 n0102: eleven of them, from a replay that aliased
        # labels) used to put the atom card in the file twice, and no
        # SHELX reader accepts that; a carrier left with no H of its own
        # is written bare rather than with an empty AFIX block
        own = [h for h in dict.fromkeys(hs) if h not in h_in_riding]
        if not own:
            continue
        riding[carrier] = {"kind": entry.get("kind"), "h": own,
                           "afix": entry.get("afix"),
                           "u_mult": entry.get("u_mult")}
        h_in_riding.update(own)

    sof_codes = m.sof_codes or {}
    parts = m.parts or {}

    def sof_of(sc) -> float:
        code = sof_codes.get(sc.label)
        if code is not None:
            return float(code)
        return sc.weight() + 10.0           # +10: fixed occupancy

    def atom_card(sc) -> str:
        e = element_of(sc.scattering_type)
        u_cif = (adptbx.u_star_as_u_cif(uc, sc.u_star)
                 if sc.flags.use_u_aniso() else None)
        bad = unencodable_free_params(sc.site, u_iso=sc.u_iso, u_cif=u_cif)
        if bad:
            # |value| >= 5 reads back as a free-variable code in every SHELX
            # reader (io.shelx_codes): writing it would commit a file no
            # tool can open again (reg1-mof cage n0152, U33 = 16.6 A^2)
            what = ", ".join(f"{n} = {v:.4g}" for n, v in bad)
            raise ValueError(
                f"{lbl[sc.label]}: {what} cannot be written as a free SHELX "
                f"parameter (|value| >= {FREE_LIMIT:g} reads back as a "
                f"free-variable code) - the refinement diverged for this "
                f"atom; revert or repair it (isotropic ADP, restraints, or "
                f"delete it) before the model is written")
        head = "%-4s %2d %10.6f %10.6f %10.6f %11.5f" % (
            lbl[sc.label], sf_idx[e], *sc.site, sof_of(sc))
        if u_cif is not None:
            u11, u22, u33, u12, u13, u23 = u_cif
            return (head + " %11.5f %11.5f =\n  %11.5f %11.5f %11.5f %11.5f" %
                    (u11, u22, u33, u23, u13, u12))
        return head + " %11.5f" % sc.u_iso

    def h_card(sc, u_mult: float) -> str:
        return "%-4s %2d %10.6f %10.6f %10.6f %11.5f %11.5f" % (
            lbl[sc.label], sf_idx["H"], *sc.site, sof_of(sc), -u_mult)

    emitted: set[str] = set()
    current_part = 0

    def switch_part(sc) -> None:
        nonlocal current_part
        want = int(parts.get(sc.label, 0))
        if want != current_part:
            lines.append(f"PART {want}")
            current_part = want

    for sc in scatterers:
        name = lbl[sc.label]
        if name in emitted or name in h_in_riding or (name in afix_members and name not in afix_first):
            continue
        block = afix_first.get(name)
        members = block["atoms"] if block else [name]
        switch_part(by_label[members[0]])
        if block:
            lines.append(block.get("card") or f"AFIX {block['afix']}")
        for member in members:
            switch_part(by_label[member])
            lines.append(atom_card(by_label[member]))
            emitted.add(member)
            group = riding.get(member)
            if group:
                afix = group.get("afix") or AFIX_OF_KIND[group["kind"]]
                u_mult = group.get("u_mult") or U_MULT_OF_KIND.get(
                    group.get("kind") or "", 1.5 if afix in (137, 127, 147, 83) else 1.2)
                lines.append(f"AFIX {afix}")
                for h in group["h"]:
                    switch_part(by_label[h])
                    lines.append(h_card(by_label[h], u_mult))
                    emitted.add(h)
                # Preserve m as well as n=5: AFIX 66 resumes with AFIX 65,
                # otherwise SHELXL says the fitted hexagon is incomplete.
                if block and member != members[-1]:
                    tail = " ".join((block.get("card") or "").split()[2:])
                    lines.append(f"AFIX {10 * (int(block['afix']) // 10) + 5}"
                                 + (f" {tail}" if tail else ""))
                elif not block:
                    lines.append("AFIX 0")
        if block:
            lines.append("AFIX 0")
    # any H that was in h_riding sets but whose carrier vanished: plain atom
    for sc in scatterers:
        name = lbl[sc.label]
        if name not in emitted:
            switch_part(sc)
            lines.append(atom_card(sc))
            emitted.add(name)
    if current_part != 0:
        lines.append("PART 0")

    lines.append(f"HKLF {m.hklf}")
    lines.append("END")
    return "\n".join(lines) + "\n", rename


def write_res(m: ShelxModel, path) -> dict[str, str]:
    text, rename = write_res_text(m)
    from pathlib import Path
    Path(path).write_text(text, encoding="ascii", errors="replace")
    return rename


def shelxl_command_block(l_s: int = 10, extra: Iterable[str] = ()) -> list[str]:
    """Standard instruction block for running the real SHELXL.

    SHELXL refuses ACTA with L.S. 0 ("ACTA requires least-squares") - the
    pure R-factor check (l_s=0) hit this in five separate campaigns before
    it was dropped here; a 0-cycle job cannot produce a publication CIF
    anyway.
    """
    cards = [f"L.S. {l_s}", "BOND $H", "CONF"]
    if l_s > 0:
        cards.append("ACTA")
    cards += ["FMAP 2", "PLAN 20"]
    cards.extend(extra)
    return cards


def write_fab(f_mask, path) -> int:
    """Write a SHELXL ABIN .fab file (h k l A B) from a complex miller array.

    SHELXL's ABIN instruction adds these Fourier coefficients to Fcalc -
    the same convention as passing f_mask to smtbx's crystallographic_ls, so
    a solvent mask computed by SolventMask transfers to a SHELXL job.
    """
    from pathlib import Path
    lines = []
    for hkl, f in zip(f_mask.indices(), f_mask.data()):
        lines.append("%d %d %d %.4f %.4f" % (hkl[0], hkl[1], hkl[2],
                                             f.real, f.imag))
    lines.append("0 0 0 0.0 0.0")
    Path(path).write_text("\n".join(lines) + "\n", encoding="ascii")
    return len(lines) - 1
