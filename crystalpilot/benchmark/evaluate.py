"""Benchmark evaluation: compare a solved structure against the human reference."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from cctbx import euclidean_model_matching as emma
from cctbx import xray
from cctbx.array_family import flex

from ..chem.knowledge import is_metal


def _is_heavy(el: str) -> bool:
    from cctbx.eltbx import tiny_pse
    if is_metal(el):
        return True
    try:
        return tiny_pse.table(el).atomic_number() >= 17
    except RuntimeError:
        return False


def _bare_scattering_types(xs):
    """Strip ionic charge suffixes (O-2, C+2, Fe+3...) common in older
    CIF _atom_type loops: element classification (is_metal/_is_heavy)
    and emma label matching need bare element symbols."""
    import re
    for sc in xs.scatterers():
        t = sc.scattering_type.strip()
        # both charge spellings occur in the wild: O-2 / Fe+3 AND O2- / Cu2+
        b = re.sub(r"(?:[+-]\d*|\d*[+-])$", "", t)
        if b and b != t:
            sc.scattering_type = b
    return xs


def tolerant_cif_text(path: str | Path) -> str:
    """CIF text hardened for strict parsers: non-ASCII replaced (CIF 1.1 is
    ASCII-only; a UTF-8 α makes iotbx's lexer slice a char mid-byte) and
    valueless tags patched to '?' (SHELXL copies SADABS .hkl-trailer
    metadata but loses ')'-delimited text values - r13/r14b live-fires)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if any(ord(c) > 126 for c in text):
        text = "".join(c if ord(c) < 127 else "?" for c in text)
    from ..report.publication import _fix_bare_tags
    text, _fixed = _fix_bare_tags(text)
    return text


def load_cif_structure(cif_path: str | Path) -> tuple[Any, dict[str, Any]]:
    """Build a structure from a CIF, BELIEVING ITS OPERATOR LOOP.

    Returns (structure or None, info).  A CIF whose space-group NAME
    contradicts its `_space_group_symop_operation_xyz` loop makes
    iotbx's builder raise `CifBuilderError: Inconsistent symmetry
    information found`; the old code then fell through to gemmi, which
    reads the NAME - so reg1-ext2 hsl (an origin-shifted P2(1)2(1)2(1)
    from SHELXT) was rebuilt with reference-setting operators on shifted
    coordinates and matched 4/13 atoms instead of 13/13.  The operator
    loop is the authoritative symmetry, so when the names disagree we
    correct the NAMES and rebuild - and say so in
    `info['cif_symmetry_inconsistent']` because it is still a real
    delivery defect."""
    from ..io.cif_symmetry import check_cif_symmetry, rewrite_symmetry_tags

    info: dict[str, Any] = {"cif_symmetry_inconsistent": False,
                            "loader": None}
    text = tolerant_cif_text(cif_path)
    try:
        chk = check_cif_symmetry(text)
    except Exception:  # noqa: BLE001 - the check must never block loading
        chk = {}
    if chk.get("consistent") is False:
        info["cif_symmetry_inconsistent"] = True
        info["cif_symmetry_conflicts"] = chk.get("conflicting")
        info["cif_symmetry_note"] = (
            f"the CIF names a space group its own operator loop "
            f"contradicts (operators define {chk.get('ops_setting')}); the "
            "operator loop was believed and the names ignored")
        try:
            text = rewrite_symmetry_tags(text)[0]
        except Exception:  # noqa: BLE001 - keep the original text
            pass
    try:
        import iotbx.cif
        structures = iotbx.cif.reader(
            input_string=text).build_crystal_structures()
        for xs in structures.values():
            if xs.scatterers().size():
                info["loader"] = "iotbx"
                return _bare_scattering_types(xs), info
    except Exception as e:  # noqa: BLE001 - fall through to gemmi
        info["iotbx_error"] = f"{type(e).__name__}: {e}"
    xs = _load_cif_via_gemmi(cif_path)
    info["loader"] = "gemmi" if xs is not None else None
    if xs is not None and info["cif_symmetry_inconsistent"]:
        # gemmi types the group from the NAME: it cannot honour the loop
        info["cif_symmetry_note"] = (
            (info.get("cif_symmetry_note") or "")
            + "; rebuilt by the gemmi fallback, which reads the space-group "
              "NAME - coordinates and symmetry may not correspond")
    return (_bare_scattering_types(xs) if xs is not None else None), info


def load_reference(res_path: str | None, cif_path: str | None):
    """Reference xray.structure from a SHELX .res (preferred) or a CIF."""
    if res_path and Path(res_path).exists():
        try:
            return _bare_scattering_types(xray.structure.from_shelx(
                filename=str(res_path), strictly_shelxl=False))
        except Exception:  # noqa: BLE001 - fall back to cif
            pass
    if cif_path and Path(cif_path).exists():
        return load_cif_structure(cif_path)[0]
    return None


def _load_cif_via_gemmi(cif_path: str):
    """Fallback CIF reader: gemmi is far more tolerant of odd files."""
    import gemmi
    from cctbx import crystal, uctbx

    try:
        small = gemmi.read_small_structure(str(cif_path))
    except Exception:  # noqa: BLE001
        small = None
    if small is None or not small.sites:
        # DDLm dialect (dotted tags)? normalize and retry from a string
        try:
            from ..io.cif_compat import looks_like_ddlm, normalize_ddlm_tags
            text = Path(cif_path).read_text(encoding="utf-8",
                                            errors="replace")
            if not looks_like_ddlm(text):
                return None
            block = gemmi.cif.read_string(
                normalize_ddlm_tags(text)).sole_block()
            small = gemmi.make_small_structure_from_block(block)
        except Exception:  # noqa: BLE001
            return None
    if not small.sites:
        return None
    cell = small.cell
    try:
        sg_symbol = small.spacegroup_hm or "P 1"
        symm = crystal.symmetry(
            unit_cell=uctbx.unit_cell((cell.a, cell.b, cell.c,
                                       cell.alpha, cell.beta, cell.gamma)),
            space_group_symbol=sg_symbol)
    except RuntimeError:
        return None
    sps = crystal.special_position_settings(symm, min_distance_sym_equiv=0.3)
    xs = xray.structure(special_position_settings=sps)
    for i, site in enumerate(small.sites):
        el = site.element.name.capitalize() if site.element else "C"
        if el in ("H", "D"):
            continue
        try:
            xs.add_scatterer(xray.scatterer(
                label=site.label or f"{el}{i}",
                site=(site.fract.x, site.fract.y, site.fract.z),
                scattering_type=el, occupancy=site.occ or 1.0, u=0.03))
        except RuntimeError:
            continue
    return xs if xs.scatterers().size() else None


def _select_elements(xs, predicate):
    sel = flex.bool([predicate(sc.scattering_type.strip().capitalize())
                     for sc in xs.scatterers()])
    return xs.select(sel)


def to_reference_setting(xs):
    """Change basis to the ITA reference setting so equal SG types compare equal."""
    try:
        cb = xs.space_group_info().change_of_basis_op_to_reference_setting()
        return xs.change_basis(cb)
    except Exception:  # noqa: BLE001
        return xs


def same_sg_type(a, b) -> bool:
    try:
        return (a.space_group_info().type().number()
                == b.space_group_info().type().number())
    except Exception:  # noqa: BLE001
        return False


def _emma_match(ref, model, tolerance: float = 0.7) -> dict[str, Any]:
    n_ref = ref.scatterers().size()
    n_model = model.scatterers().size()
    if n_ref == 0 or n_model == 0:
        return {"n_ref": n_ref, "n_model": n_model, "n_matched": 0, "rms": None}
    ref = to_reference_setting(ref)
    model = to_reference_setting(model)
    if ref.space_group() != model.space_group():
        # different symmetry: compare atomic arrangements in P1 (honest fallback)
        ref = ref.expand_to_p1()
        model = model.expand_to_p1()
        if ref.scatterers().size() > 400 or model.scatterers().size() > 400:
            return {"n_ref": n_ref, "n_model": n_model, "n_matched": 0,
                    "rms": None, "note": "sg mismatch, P1 too large to match"}
    recast = None
    if ref.unit_cell().parameters() != model.unit_cell().parameters():
        # same-phase literature references differ by thermal expansion
        # (1-2% on lengths) - emma asserts on unequal cells, so recast the
        # model's fractional coordinates onto the reference cell; the
        # induced positional shifts (<= the cell delta) stay well inside
        # the matching tolerance
        try:
            recast = model.customized_copy(
                crystal_symmetry=ref.crystal_symmetry())
        except Exception:  # noqa: BLE001 - incompatible symmetry: let emma try
            recast = None
    try:
        matches = emma.model_matches(ref.as_emma_model(),
                                     (recast or model).as_emma_model(),
                                     tolerance=tolerance,
                                     break_if_match_with_no_singles=False)
    except AssertionError:
        return {"n_ref": n_ref, "n_model": n_model, "n_matched": 0, "rms": None,
                "note": "emma incompatible settings"}
    if not matches.refined_matches:
        fb = _pseudo_degenerate_match(ref, recast or model, tolerance)
        if fb is not None:
            return fb
        return {"n_ref": n_ref, "n_model": n_model, "n_matched": 0, "rms": None}
    m = matches.refined_matches[0]
    out = {"n_ref": m.ref_model1.size(), "n_model": m.ref_model2.size(),
           "n_matched": len(m.pairs), "rms": round(float(m.rms), 3)}
    # positions matched: now the ELEMENTS on them. emma is element-blind,
    # and that let a Zn-labelled NU-1000 (Zr framework atom-for-atom, rms
    # 0.02 A, R1 0.082) grade as acceptable in pa1 - the CIF's formula,
    # density, F000 and mu were all wrong
    out.update(_element_mismatches(ref, recast or model, m.pairs))
    if out["n_matched"] < 0.5 * max(1, min(n_ref, n_model)):
        fb = _pseudo_degenerate_match(ref, recast or model, tolerance)
        if fb is not None and fb["n_matched"] > out["n_matched"]:
            return fb
    return out


def _atomic_number(scattering_type: str) -> int | None:
    from cctbx.eltbx import tiny_pse
    el = "".join(c for c in scattering_type if c.isalpha())[:2].capitalize()
    try:
        return int(tiny_pse.table(el).atomic_number())
    except Exception:  # noqa: BLE001 - unknown type
        return None


def _element_mismatches(ref, model, pairs, limit: int = 24) -> dict[str, Any]:
    """Element disagreement on emma-paired sites (pairs index the two
    structures handed to emma, in scatterer order)."""
    rs, ms = ref.scatterers(), model.scatterers()
    rows: list[dict[str, Any]] = []
    n_compared = 0
    for i, j in pairs:
        if i >= rs.size() or j >= ms.size():
            continue
        za, zb = _atomic_number(rs[i].scattering_type), \
            _atomic_number(ms[j].scattering_type)
        if za is None or zb is None:
            continue
        n_compared += 1
        if za != zb:
            rows.append({"ref": rs[i].label, "ref_el": rs[i].scattering_type
                         .strip().capitalize(),
                         "model": ms[j].label, "model_el": ms[j]
                         .scattering_type.strip().capitalize(),
                         "dz": zb - za})
    rows.sort(key=lambda r: -abs(r["dz"]))
    return {"n_element_compared": n_compared,
            "n_element_mismatch": len(rows),
            "element_mismatches": rows[:limit]}


def _pseudo_degenerate_match(ref, model, tolerance: float = 0.7):
    """Brute-force fallback for (pseudo)degenerate metrics that defeat emma.

    cctbx emma searches the space group's own Euclidean normalizer, which
    knows nothing about SPECIALIZED metric symmetry: with a ~= b (r14a: an
    orthorhombic Zn-BTC net, a/b within 0.8%), two correct refinements of
    the same data can sit in bases related by an axis-swap / quarter-shift
    element that emma never tries, and a perfectly solved structure grades
    as 0/56 matched. Here we enumerate every signed-permutation basis whose
    transformed cell matches within 1.5% plus a quarter-fraction
    translation grid, anchor-score them on the few heaviest atoms, then
    verify the best candidates on all atoms via per-orbit membership.

    Returns an _emma_match-shaped dict with a note, or None when the
    metric is not degenerate / structures are too large / nothing beats
    a trivial threshold.
    """
    import itertools
    import numpy as np

    n_ref = ref.scatterers().size()
    n_model = model.scatterers().size()
    if n_ref == 0 or n_model == 0 or n_ref * n_model > 250 * 250:
        return None
    uc = ref.unit_cell()
    abc = np.array(uc.parameters()[:3])
    # gate: some axis pair within 1.5% (incl. equal cells that emma already
    # handles - cheap, and equal axes are exactly the degenerate case)
    pairs_close = any(abs(abc[i] - abc[j]) / max(abc[i], abc[j]) < 0.015
                      for i in range(3) for j in range(i + 1, 3))
    if not pairs_close:
        return None
    G = ref.space_group()
    ops = [(np.array(op.r().as_double()).reshape(3, 3),
            np.array(op.t().as_double())) for op in G.all_ops()]
    model_sites = np.array([sc.site for sc in model.scatterers()])
    ref_sites = np.array([sc.site for sc in ref.scatterers()])

    O = np.array(uc.orthogonalization_matrix()).reshape(3, 3)

    def min_dists(ref_subset, mapped):
        """per-ref-atom min distance (A) to any symmetry copy of any
        mapped model atom"""
        best = np.full(len(ref_subset), 9e9)
        for R, t in ops:
            s = mapped @ R.T + t          # n_model x 3
            for k, rp in enumerate(ref_subset):
                d = rp - s
                d -= np.round(d)
                dm = float(np.min(np.linalg.norm(d @ O.T, axis=1)))
                if dm < best[k]:
                    best[k] = dm
        return best

    # anchors: heaviest handful of reference atoms (metals when present)
    organics = {"C", "N", "O", "H", "D", "B", "F"}
    heavy_idx = [i for i, sc in enumerate(ref.scatterers())
                 if sc.scattering_type.strip().capitalize() not in organics]
    anchor_idx = heavy_idx[:6] or list(range(min(6, n_ref)))
    anchors = ref_sites[anchor_idx]

    cands = []
    for perm in itertools.permutations(range(3)):
        if not np.all(np.abs(abc[list(perm)] - abc) / abc < 0.015):
            continue
        for signs in itertools.product((1, -1), repeat=3):
            P = np.zeros((3, 3))
            for i, (p, s) in enumerate(zip(perm, signs)):
                P[i, p] = s
            cands.append(P)
    grid = [np.array(t) for t in
            itertools.product((0.0, 0.25, 0.5, 0.75), repeat=3)]
    scored = []
    for P in cands:
        base = model_sites @ P.T
        for t in grid:
            d = min_dists(anchors, base + t)
            scored.append((float(np.sum(d)), P, t))
    def greedy_pairs(P, t):
        """quasi-bijective pairing (emma semantics): distance matrix over
        model ORBITS, then greedy one-to-one assignment under tolerance"""
        mapped = model_sites @ P.T + t
        dmat = np.full((n_ref, n_model), 9e9)
        for R, tt in ops:
            s = mapped @ R.T + tt
            for k in range(n_ref):
                d = ref_sites[k] - s
                d -= np.round(d)
                dd = np.linalg.norm(d @ O.T, axis=1)
                np.minimum(dmat[k], dd, out=dmat[k])
        order = np.dstack(np.unravel_index(
            np.argsort(dmat, axis=None), dmat.shape))[0]
        used_r: set[int] = set()
        used_m: set[int] = set()
        ds = []
        for k, mzz in order:
            if dmat[k, mzz] > tolerance:
                break
            if k in used_r or mzz in used_m:
                continue
            used_r.add(int(k))
            used_m.add(int(mzz))
            ds.append(float(dmat[k, mzz]))
        return ds

    scored.sort(key=lambda x: x[0])
    best_out = None
    for _score, P, t in scored[:3]:
        ds = greedy_pairs(P, t)
        if not ds:
            continue
        rms = float(np.sqrt(np.mean(np.array(ds) ** 2)))
        out = {"n_ref": n_ref, "n_model": n_model, "n_matched": len(ds),
               "rms": round(rms, 3),
               "note": ("pseudo-degenerate metric fallback: basis "
                        f"{P.astype(int).tolist()} + t={t.tolist()}")}
        if best_out is None or out["n_matched"] > best_out["n_matched"]:
            best_out = out
    if best_out is not None and best_out["n_matched"] >= max(
            1, int(0.5 * min(n_ref, n_model))):
        return best_out
    return None


def _cells_compatible(a_xs, b_xs, tol: float = 0.03) -> bool:
    """Same-setting cells directly similar, or Niggli-reduced cells agree.

    The direct check comes first: Niggli reduction is discontinuous near
    reduction boundaries, so two nearly identical cells can reduce to
    different representatives (angles off by several degrees) - re-reducing
    would then reject cells that already match.
    """
    try:
        if a_xs.unit_cell().is_similar_to(
                b_xs.unit_cell(), relative_length_tolerance=tol,
                absolute_angle_tolerance=3.0):
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        a = a_xs.crystal_symmetry().niggli_cell().unit_cell().parameters()
        b = b_xs.crystal_symmetry().niggli_cell().unit_cell().parameters()
    except Exception:  # noqa: BLE001
        return True
    for x, y in zip(a[:3], b[:3]):
        if abs(x - y) / max(x, y) > tol:
            return False
    return all(abs(x - y) <= 3.0 for x, y in zip(a[3:], b[3:]))


def evaluate_against_reference(model_xs, ref_xs) -> dict[str, Any]:
    """Heavy-atom + non-H framework matching. Reference H atoms are ignored."""
    if not _cells_compatible(model_xs, ref_xs):
        return {"cell_mismatch_with_reference": True, "solved": False,
                "heavy_match_rate": None, "all_match_rate": None,
                "note": "model and reference are indexed on incompatible cells; "
                        "atom matching is not meaningful"}
    ref_nonh = _select_elements(ref_xs, lambda e: e not in ("H", "D"))
    model_nonh = _select_elements(model_xs, lambda e: e not in ("H", "D"))

    # fairness: the engine masks disordered pore solvent instead of modeling it,
    # so recall is computed against the reference's main bonded framework only
    n_ref_solvent = 0
    ref_secondary = None          # the fragments scored apart, kept for precision
    try:
        from ..chem.connectivity import analyze_connectivity
        conn = analyze_connectivity(ref_nonh)
        if len(conn.fragments) > 1:
            main_labels = set(conn.fragments[0]["asu_labels"])
            keep = flex.bool([sc.label in main_labels
                              for sc in ref_nonh.scatterers()])
            n_ref_solvent = keep.count(False)
            if 0 < n_ref_solvent < ref_nonh.scatterers().size():
                ref_secondary = ref_nonh.select(~keep)
                ref_nonh = ref_nonh.select(keep)
    except Exception:  # noqa: BLE001 - fairness filter must never break scoring
        pass
    # second fairness rule: partial-occupancy reference atoms (a
    # post-synthetic guest at occupancy 0.125 bonded to the node, minor
    # disorder components) are not the framework. The group's manual
    # NU-1000 structure carries a 9-atom bromophenylacetate at 0.125 whose
    # Br made every correct P6/mmm framework 'not reproduced' (heavy
    # recall 2/3). They are scored separately as the guest layer.
    n_ref_partial = 0
    guest: dict[str, Any] | None = None
    ref_guest = None
    try:
        occ_keep = flex.bool([float(sc.occupancy) >= 0.5
                              for sc in ref_nonh.scatterers()])
        n_ref_partial = occ_keep.count(False)
        if 0 < n_ref_partial < ref_nonh.scatterers().size():
            ref_guest = ref_nonh.select(~occ_keep)
            ref_nonh = ref_nonh.select(occ_keep)
            gm = _emma_match(ref_guest, model_nonh, tolerance=0.7)
            guest = {"n_ref": gm.get("n_ref"), "n_matched": gm.get("n_matched"),
                     "labels": [sc.label for sc in ref_guest.scatterers()],
                     "recall": (round(gm["n_matched"] / gm["n_ref"], 3)
                                if gm.get("n_ref") else None),
                     "note": ("reference atoms with occupancy < 0.5 - "
                              "guests / minor components - scored apart "
                              "from the framework")}
    except Exception:  # noqa: BLE001 - fairness filter must never break scoring
        pass

    heavy = _emma_match(_select_elements(ref_nonh, _is_heavy),
                        _select_elements(model_nonh, _is_heavy), tolerance=0.7)
    # emma cost explodes combinatorially for large models in high-order groups
    # (observed: >30 min on a P61 MOF). Guard: score heavy atoms only and flag.
    emma_cost = (ref_nonh.scatterers().size() * model_nonh.scatterers().size()
                 * ref_nonh.space_group().order_z())
    if emma_cost > 1_000_000:
        return {
            "heavy": heavy, "all_atoms": None,
            "evaluation_truncated": f"emma cost {emma_cost} > 1e6: heavy-only",
            "heavy_match_rate": (heavy["n_matched"] / heavy["n_ref"])
            if heavy["n_ref"] else None,
            "heavy_precision": (heavy["n_matched"] / heavy["n_model"])
            if heavy["n_model"] else None,
            "all_match_rate": None, "all_precision": None,
            "solved": bool(heavy["n_ref"]
                           and heavy["n_matched"] / heavy["n_ref"] >= 0.99
                           and heavy["n_model"]
                           and heavy["n_matched"] / heavy["n_model"] >= 0.6),
        }
    allatom = _emma_match(ref_nonh, model_nonh, tolerance=0.7)
    heavy_rate = (heavy["n_matched"] / heavy["n_ref"]) if heavy["n_ref"] else None
    all_rate = (allatom["n_matched"] / allatom["n_ref"]) if allatom["n_ref"] else None
    # precision punishes spurious atoms the recall-style rates ignore -
    # but a model atom that reproduces a reference atom scored APART (a
    # counter-ion, a co-former, modelled solvent, a guest) is not spurious.
    # reg7-dbu (2026-09-04): the complete salt with its disorder modelled
    # scored precision 15/29 because the reference had been reduced to one
    # ion and the model rightly kept both. Those atoms leave the
    # denominator; nothing is added to the numerator.
    n_model_apart = 0
    n_heavy_apart = 0
    for ref_apart in (ref_secondary, ref_guest):
        if ref_apart is None or not ref_apart.scatterers().size():
            continue
        try:
            n_model_apart += _emma_match(ref_apart, model_nonh,
                                         tolerance=0.7)["n_matched"]
            ref_apart_heavy = _select_elements(ref_apart, _is_heavy)
            if ref_apart_heavy.scatterers().size():
                n_heavy_apart += _emma_match(
                    ref_apart_heavy, _select_elements(model_nonh, _is_heavy),
                    tolerance=0.7)["n_matched"]
        except Exception:  # noqa: BLE001 - fairness must never break scoring
            pass
    n_model_eff = max(allatom["n_model"] - n_model_apart, allatom["n_matched"])
    n_heavy_eff = max(heavy["n_model"] - n_heavy_apart, heavy["n_matched"])
    heavy_prec = (heavy["n_matched"] / n_heavy_eff) if n_heavy_eff else None
    all_prec = (allatom["n_matched"] / n_model_eff) if n_model_eff else None
    complete = (all_rate or 0) >= 0.75 and (all_prec or 0) >= 0.60
    if heavy["n_ref"] == 0:
        solved = bool(complete)
    else:
        heavy_ok = (heavy_rate or 0) >= 0.99 and (heavy_prec or 0) >= 0.5
        # disorder-split reference metals (partial-occupancy pairs) can leave one
        # heavy site formally unmatched even when the geometry is fully reproduced
        heavy_ok = heavy_ok or ((heavy_rate or 0) >= 0.65
                                and (all_rate or 0) >= 0.95
                                and (all_prec or 0) >= 0.90)
        solved = bool(heavy_ok and complete)
    # metal identity: a heavy-atom pair whose elements differ by more than
    # two in Z is a different chemistry, whatever the coordinates say
    # (Zn for Zr, Cd/Fe/Zn for Zr in the pa1 cage runs). None when the
    # match carried no pairs to compare (fallback matchers).
    metal_ok = None
    if heavy.get("n_element_compared"):
        metal_ok = not any(abs(r["dz"]) > 2
                           for r in heavy.get("element_mismatches") or [])
    return {
        "heavy": heavy, "all_atoms": allatom,
        "metal_identity_ok": metal_ok,
        "n_heavy_element_mismatch": heavy.get("n_element_mismatch"),
        "n_element_mismatch": allatom.get("n_element_mismatch"),
        "n_ref_solvent_excluded": n_ref_solvent,
        "n_ref_partial_excluded": n_ref_partial,
        "n_model_matched_apart": n_model_apart,
        "precision_note": ("precision denominator excludes model atoms "
                           "that reproduce reference atoms scored apart "
                           "(secondary fragments, occupancy < 0.5)"),
        **({"guest": guest} if guest else {}),
        "heavy_match_rate": round(heavy_rate, 3) if heavy_rate is not None else None,
        "heavy_precision": round(heavy_prec, 3) if heavy_prec is not None else None,
        "all_match_rate": round(all_rate, 3) if all_rate is not None else None,
        "all_precision": round(all_prec, 3) if all_prec is not None else None,
        "solved": solved,
    }


def reference_r1(res_path: str | None, cif_path: str | None) -> float | None:
    """Human reference R1, from SHELXL REM lines or CIF refine tags."""
    import re
    for p, pattern in ((res_path, r"REM R1 =\s*([\d.]+)"),
                       (cif_path, r"_refine_ls_R_factor_gt\s+([\d.]+)")):
        if p and Path(p).exists():
            try:
                m = re.search(pattern, Path(p).read_text(encoding="utf-8",
                                                         errors="replace"))
                if m:
                    return float(m.group(1))
            except OSError:
                pass
    return None


def reference_space_group(res_path: str | None, cif_path: str | None) -> str | None:
    ref = load_reference(res_path, cif_path)
    if ref is None:
        return None
    return str(ref.space_group_info())
