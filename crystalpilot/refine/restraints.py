"""SHELX-style restraints: spec model, card emit/parse, smtbx proxy building.

A restraint is stored label-based (survives atom reordering between nodes) as
a RestraintSpec dict:

    {"kind": "DFIX", "atoms": [["C1","C2"], ...], "target": 1.39, "sigma": 0.02}
    {"kind": "SADI", "atoms": [["C1","C2"],["C3","C4"]], "sigma": 0.02}
    {"kind": "FLAT", "atoms": ["C1","C2","C3","C4",...], "sigma": 0.1}
    {"kind": "SIMU"|"DELU"|"RIGU"|"ISOR", "atoms": ["C1",...] | None,   # None = all suitable
     "sigma": ..., "sigma_terminal": ...}

Specs resolve to scatterer i_seqs only at refinement time
(build_restraints_manager), so edits between nodes cannot silently corrupt
them: dangling labels produce warnings, never crashes. Geometry restraints are
MVP-limited to direct (same-ASU-copy) pairs - a pair whose bond only exists
through a symmetry operation is skipped with a warning, because
cctbx bond_simple_proxy without rt_mx restrains the plain cartesian distance.
"""
from __future__ import annotations

from typing import Any

GEOMETRY_KINDS = {"DFIX", "DANG", "SADI", "FLAT"}
ADP_KINDS = {"SIMU", "DELU", "RIGU", "ISOR"}
ALL_KINDS = GEOMETRY_KINDS | ADP_KINDS

DEFAULT_SIGMA = {"DFIX": 0.02, "DANG": 0.04, "SADI": 0.02, "FLAT": 0.1,
                 "SIMU": 0.04, "DELU": 0.01, "RIGU": 0.004, "ISOR": 0.1}
DEFAULT_SIGMA_TERMINAL = {"SIMU": 0.08, "ISOR": 0.2}

# a geometry restraint on a pair farther apart than this is chemically absurd
_MAX_DIRECT_DISTANCE = {"DFIX": 3.0, "SADI": 3.5, "DANG": 4.0, "FLAT": None}


def validate_spec(spec: dict[str, Any]) -> str | None:
    """Return an error string or None."""
    kind = str(spec.get("kind", "")).upper()
    if kind not in ALL_KINDS:
        return (f"unsupported restraint kind {kind!r}; supported: "
                f"{sorted(ALL_KINDS)} (EADP/SAME/PART etc. are not available "
                "in this version)")
    atoms = spec.get("atoms")
    if kind in ("DFIX", "DANG", "SADI"):
        if (not isinstance(atoms, list) or not atoms
                or not all(isinstance(p, (list, tuple)) and len(p) == 2 for p in atoms)):
            return f"{kind} needs atoms=[[a,b],...] (list of label pairs)"
        if kind in ("DFIX", "DANG") and not isinstance(spec.get("target"), (int, float)):
            return f"{kind} needs a numeric target distance in angstrom"
        if kind == "SADI" and len(atoms) < 2:
            return "SADI needs at least two pairs to restrain as similar"
    elif kind == "FLAT":
        if not isinstance(atoms, list) or len(atoms) < 4 \
                or not all(isinstance(a, str) for a in atoms):
            return "FLAT needs atoms=[label,...] with at least 4 atom labels"
    else:  # ADP kinds
        if atoms is not None and (not isinstance(atoms, list)
                                  or not all(isinstance(a, str) for a in atoms)):
            return f"{kind} needs atoms=[label,...] or null (= all suitable atoms)"
    return None


def normalize_spec(spec: dict[str, Any]) -> dict[str, Any]:
    kind = str(spec["kind"]).upper()
    out: dict[str, Any] = {"kind": kind}
    atoms = spec.get("atoms")
    if kind in ("DFIX", "DANG", "SADI"):
        out["atoms"] = [[str(a), str(b)] for a, b in atoms]
    elif kind == "FLAT":
        out["atoms"] = [str(a) for a in atoms]
    else:
        out["atoms"] = None if atoms is None else [str(a) for a in atoms]
    if kind in ("DFIX", "DANG"):
        out["target"] = float(spec["target"])
    out["sigma"] = float(spec.get("sigma") or DEFAULT_SIGMA[kind])
    if kind in DEFAULT_SIGMA_TERMINAL:
        # SHELX convention: terminal-atom sigma defaults to 2x the main sigma
        out["sigma_terminal"] = float(spec.get("sigma_terminal")
                                      or 2.0 * out["sigma"])
    if kind in ("DELU", "RIGU"):
        out["sigma_13"] = float(spec.get("sigma_13") or out["sigma"])
    return out


def prune_specs_for_deleted(
        specs: list[dict[str, Any]],
        deleted_labels: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Same-fate hygiene when atoms are deleted (r12 CD-MOF: author
    DFIX/DANG on a deleted H rode into every SHELXL job and aborted it).

    Pair kinds lose only the affected pairs (whole spec goes when none
    remain, or SADI drops below two pairs); FLAT drops entirely (a plane
    minus a member is a different restraint the agent must re-state);
    ADP-list kinds lose the label but are dropped when the list empties -
    NEVER converted to None, which would silently mean 'all atoms'."""
    dl = {str(x).upper() for x in deleted_labels}
    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    for spec in specs:
        kind = str(spec.get("kind", "?")).upper()
        atoms = spec.get("atoms")
        if not atoms:
            kept.append(spec)                 # None/[] = all-suitable kinds
            continue
        if isinstance(atoms[0], (list, tuple)):
            good = [p for p in atoms
                    if not any(str(a).upper() in dl for a in p)]
            if len(good) == len(atoms):
                kept.append(spec)
            elif good and not (kind == "SADI" and len(good) < 2):
                kept.append({**spec, "atoms": good})
                dropped.append(
                    f"{kind}: {len(atoms) - len(good)} pair(s) referencing "
                    "deleted atoms removed")
            else:
                dropped.append(f"{kind} {atoms}")
        else:
            flat = [str(a) for a in atoms]
            good = [a for a in flat if a.upper() not in dl]
            if len(good) == len(flat):
                kept.append(spec)
            elif kind == "FLAT" or not good:
                dropped.append(f"{kind} {flat}")
            else:
                kept.append({**spec, "atoms": good})
                dropped.append(
                    f"{kind}: {len(flat) - len(good)} deleted atom(s) "
                    "removed from list")
    return kept, dropped


def spec_key(spec: dict[str, Any]) -> str:
    atoms = spec.get("atoms")
    if atoms is None:
        a = "*"
    elif atoms and isinstance(atoms[0], (list, tuple)):
        a = ";".join(",".join(p) for p in atoms)
    else:
        a = ",".join(atoms)
    return f"{spec['kind']}:{a}"


# --------------------------------------------------------------------------
# SHELX card emit / parse
# --------------------------------------------------------------------------
def emit_shelx_cards(specs: list[dict[str, Any]]) -> list[str]:
    cards: list[str] = []
    for s in specs:
        kind = s["kind"]
        if kind in ("DFIX", "DANG"):
            for a, b in s["atoms"]:
                cards.append(f"{kind} {s['target']:.4f} {s['sigma']:.3f} {a} {b}")
        elif kind == "SADI":
            pairs = " ".join(f"{a} {b}" for a, b in s["atoms"])
            cards.append(_wrap(f"SADI {s['sigma']:.3f} {pairs}"))
        elif kind == "FLAT":
            cards.append(_wrap(f"FLAT {s['sigma']:.2f} " + " ".join(s["atoms"])))
        elif kind in ("SIMU", "ISOR"):
            tail = "" if s["atoms"] is None else " " + " ".join(s["atoms"])
            cards.append(_wrap(f"{kind} {s['sigma']:.3f} {s['sigma_terminal']:.3f}{tail}"))
        elif kind in ("DELU", "RIGU"):
            tail = "" if s["atoms"] is None else " " + " ".join(s["atoms"])
            cards.append(_wrap(f"{kind} {s['sigma']:.4f} {s['sigma_13']:.4f}{tail}"))
    return cards


def _wrap(line: str, width: int = 76) -> str:
    if len(line) <= width:
        return line
    head = line[:width]
    cut = head.rfind(" ")
    if cut <= 0:
        return line
    return head[:cut] + " =\n " + _wrap(line[cut:].strip(), width)


def parse_shelx_cards(lines: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse restraint card lines (already '='-joined) -> (specs, warnings)."""
    specs: list[dict[str, Any]] = []
    warnings: list[str] = []
    for line in lines:
        tokens = line.split()
        if not tokens:
            continue
        kind = tokens[0].upper()
        if kind not in ALL_KINDS:
            warnings.append(f"unsupported restraint card kept as text: {line!r}")
            continue
        nums: list[float] = []
        rest = tokens[1:]
        while rest:
            try:
                nums.append(float(rest[0]))
            except ValueError:
                break
            rest = rest[1:]
        try:
            if kind in ("DFIX", "DANG"):
                target = nums[0]
                sigma = nums[1] if len(nums) > 1 else DEFAULT_SIGMA[kind]
                pairs = [[rest[i], rest[i + 1]] for i in range(0, len(rest) - 1, 2)]
                specs.append(normalize_spec({"kind": kind, "atoms": pairs,
                                             "target": target, "sigma": sigma}))
            elif kind == "SADI":
                sigma = nums[0] if nums else DEFAULT_SIGMA[kind]
                pairs = [[rest[i], rest[i + 1]] for i in range(0, len(rest) - 1, 2)]
                specs.append(normalize_spec({"kind": kind, "atoms": pairs,
                                             "sigma": sigma}))
            elif kind == "FLAT":
                sigma = nums[0] if nums else DEFAULT_SIGMA[kind]
                specs.append(normalize_spec({"kind": kind, "atoms": rest,
                                             "sigma": sigma}))
            elif kind in ("SIMU", "ISOR"):
                spec = {"kind": kind, "atoms": rest or None,
                        "sigma": nums[0] if nums else None,
                        "sigma_terminal": nums[1] if len(nums) > 1 else None}
                specs.append(normalize_spec(spec))
            elif kind in ("DELU", "RIGU"):
                spec = {"kind": kind, "atoms": rest or None,
                        "sigma": nums[0] if nums else None,
                        "sigma_13": nums[1] if len(nums) > 1 else None}
                specs.append(normalize_spec(spec))
        except (IndexError, ValueError, KeyError) as e:
            warnings.append(f"could not parse restraint card {line!r}: {e}")
    return specs, warnings


# --------------------------------------------------------------------------
# smtbx / cctbx proxy building
# --------------------------------------------------------------------------
def build_restraints_manager(xs, specs: list[dict[str, Any]]):
    """(manager | None, info) - resolve label-based specs against a structure.

    info = {n_geometry, n_adp_groups, warnings[], applied[]}
    """
    from cctbx import adp_restraints as cctbx_adp
    from cctbx import geometry_restraints
    from smtbx.refinement.restraints import adp_restraints as smtbx_adp
    from smtbx.refinement.restraints import manager as restraints_manager_cls

    warnings: list[str] = []
    applied: list[str] = []
    normalized: list[dict[str, Any]] = []
    for s in specs:
        err = validate_spec(s)
        if err:
            warnings.append(f"invalid restraint {s.get('kind')}: {err}")
            continue
        normalized.append(normalize_spec(s))
    specs = normalized
    scatterers = xs.scatterers()
    uc = xs.unit_cell()
    idx = {sc.label.strip().upper(): i for i, sc in enumerate(scatterers)}
    cart = [uc.orthogonalize(sc.site) for sc in scatterers]
    types = [sc.scattering_type.strip().upper() for sc in scatterers]

    def resolve(label: str) -> int | None:
        i = idx.get(label.strip().upper())
        if i is None:
            warnings.append(f"atom {label!r} not in the current model - restraint "
                            "term skipped")
        return i

    def direct_distance(i: int, j: int) -> float:
        a, b = cart[i], cart[j]
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5

    def check_pair(kind: str, a: str, b: str) -> tuple[int, int] | None:
        i, j = resolve(a), resolve(b)
        if i is None or j is None:
            return None
        if "H" in (types[i], types[j]):
            warnings.append(f"{kind} {a}-{b}: geometry restraints on H atoms are "
                            "not supported (H ride via add_hydrogens) - skipped")
            return None
        limit = _MAX_DIRECT_DISTANCE.get(kind)
        if limit is not None:
            d = direct_distance(i, j)
            if d > limit:
                warnings.append(
                    f"{kind} {a}-{b}: direct distance {d:.2f} A is too long - the "
                    "bond probably exists only via a symmetry operation, which this "
                    "version cannot restrain - skipped")
                return None
        return i, j

    bond_proxies = geometry_restraints.shared_bond_simple_proxy()
    bond_sim_proxies = geometry_restraints.shared_bond_similarity_proxy()
    planarity_proxies = geometry_restraints.shared_planarity_proxy()
    adp_sim = cctbx_adp.shared_adp_similarity_proxy()
    rigid_bond = cctbx_adp.shared_rigid_bond_proxy()
    rigu = cctbx_adp.shared_rigu_proxy()
    iso_adp = cctbx_adp.shared_isotropic_adp_proxy()

    from cctbx.array_family import flex

    for s in specs:
        kind = s["kind"]
        n_before = warnings and len(warnings)
        if kind in ("DFIX", "DANG"):
            w = 1.0 / (s["sigma"] ** 2)
            n = 0
            for a, b in s["atoms"]:
                pair = check_pair(kind, a, b)
                if pair is None:
                    continue
                bond_proxies.append(geometry_restraints.bond_simple_proxy(
                    i_seqs=pair, distance_ideal=float(s["target"]), weight=w))
                n += 1
            if n:
                applied.append(f"{kind} {s['target']:.3f} ({n} pair(s))")
        elif kind == "SADI":
            w = 1.0 / (s["sigma"] ** 2)
            pairs = []
            for a, b in s["atoms"]:
                pair = check_pair(kind, a, b)
                if pair is not None:
                    pairs.append(pair)
            if len(pairs) >= 2:
                bond_sim_proxies.append(geometry_restraints.bond_similarity_proxy(
                    i_seqs=pairs, weights=[w] * len(pairs)))
                applied.append(f"SADI ({len(pairs)} pairs similar)")
            elif pairs:
                warnings.append("SADI reduced to <2 valid pairs - skipped")
        elif kind == "FLAT":
            w = 1.0 / (s["sigma"] ** 2)
            i_seqs = [resolve(a) for a in s["atoms"]]
            i_seqs = [i for i in i_seqs if i is not None and types[i] != "H"]
            if len(i_seqs) >= 4:
                planarity_proxies.append(geometry_restraints.planarity_proxy(
                    i_seqs=flex.size_t(i_seqs),
                    weights=flex.double([w] * len(i_seqs))))
                applied.append(f"FLAT ({len(i_seqs)} atoms)")
            else:
                warnings.append("FLAT has <4 valid non-H atoms - skipped")
        else:
            i_seqs = None
            if s["atoms"] is not None:
                i_seqs = [i for i in (resolve(a) for a in s["atoms"]) if i is not None]
                if not i_seqs:
                    warnings.append(f"{kind}: no valid atoms - skipped")
                    continue
            try:
                if kind == "SIMU":
                    r = smtbx_adp.adp_similarity_restraints(
                        xray_structure=xs, i_seqs=i_seqs, sigma=s["sigma"],
                        sigma_terminal=s["sigma_terminal"], proxies=adp_sim)
                elif kind == "DELU":
                    r = smtbx_adp.rigid_bond_restraints(
                        xray_structure=xs, i_seqs=i_seqs, sigma_12=s["sigma"],
                        sigma_13=s["sigma_13"], proxies=rigid_bond)
                elif kind == "RIGU":
                    r = smtbx_adp.rigu_restraints(
                        xray_structure=xs, i_seqs=i_seqs, sigma_12=s["sigma"],
                        sigma_13=s["sigma_13"], proxies=rigu)
                else:  # ISOR
                    n0 = iso_adp.size()
                    r = smtbx_adp.isotropic_adp_restraints(
                        xray_structure=xs, i_seqs=i_seqs, sigma=s["sigma"],
                        sigma_terminal=s["sigma_terminal"], proxies=iso_adp)
                    if iso_adp.size() == n0:
                        warnings.append(
                            "ISOR produced no terms (targets are isotropic already "
                            "- ISOR applies to anisotropic atoms only)")
                _ = r
                applied.append(f"{kind} ({'all suitable' if i_seqs is None else len(i_seqs)} atoms)")
            except Exception as e:  # noqa: BLE001 - surface, don't crash refine
                warnings.append(f"{kind} failed to build: {type(e).__name__}: {e}")
        _ = n_before

    kwargs: dict[str, Any] = {}
    if bond_proxies.size():
        kwargs["bond_proxies"] = bond_proxies
    if bond_sim_proxies.size():
        kwargs["bond_similarity_proxies"] = bond_sim_proxies
    if planarity_proxies.size():
        kwargs["planarity_proxies"] = planarity_proxies
    if adp_sim.size():
        kwargs["adp_similarity_proxies"] = adp_sim
    if rigid_bond.size():
        kwargs["rigid_bond_proxies"] = rigid_bond
    if rigu.size():
        kwargs["rigu_proxies"] = rigu
    if iso_adp.size():
        kwargs["isotropic_adp_proxies"] = iso_adp

    info = {
        "n_geometry": int(bond_proxies.size() + bond_sim_proxies.size()
                          + planarity_proxies.size()),
        "n_adp_groups": int(adp_sim.size() + rigid_bond.size() + rigu.size()
                            + iso_adp.size()),
        "warnings": warnings,
        "applied": applied,
    }
    if not kwargs:
        return None, info
    return restraints_manager_cls(**kwargs), info


# --------------------------------------------------------------------------
# preflight: requested vs actually applied (round-3 WP3)
# --------------------------------------------------------------------------
#: SHELXL applies these within a disorder component: atoms in different
#: non-zero PARTs are separate components and a distance / planarity term
#: written across them is not applied (the .lst restraint count drops it
#: without refusing the job)
PART_SENSITIVE_KINDS = ("DFIX", "DANG", "SADI", "FLAT")


def preflight(xs, specs: list[dict[str, Any]],
              flags: dict | None = None) -> dict[str, Any]:
    """What a restraint list would actually do, before a job carries it
    somewhere the loss is silent.

    - ``applied_in_process``: the terms the smtbx manager builds (same
      resolver as refine()), with its warnings (missing atoms, H atoms,
      SADI below two pairs ...);
    - ``not_representable``: specs the in-process engine cannot express
      at all (EADP / SAME / PART ... are cards, not restraints here);
    - ``shelx_part_conflicts``: DFIX / DANG / SADI / FLAT terms whose atoms
      sit in different non-zero PARTs (looked up the way the PART cards are
      written: group membership, then parts_extra) - SHELXL will not apply
      them. Reported, never refused: putting both atoms in one PART or
      restraining within each component is the caller's decision.
    """
    from .parts import part_of_labels
    specs = list(specs or [])
    part_of = part_of_labels(flags or {})
    not_representable: list[dict[str, Any]] = []
    valid: list[dict[str, Any]] = []
    for s in specs:
        err = validate_spec(s)
        if err:
            not_representable.append(
                {"kind": str((s or {}).get("kind", "?")).upper(), "reason": err})
            continue
        valid.append(normalize_spec(s))
    try:
        _mgr, info = build_restraints_manager(xs, valid)
    except Exception as e:  # noqa: BLE001 - the preflight reports, never blocks
        info = {"n_geometry": None, "n_adp_groups": None, "applied": [],
                "warnings": [f"in-process restraints manager could not be "
                             f"built: {e}"]}
    conflicts: list[dict[str, Any]] = []
    for s in valid:
        kind = s["kind"]
        if kind not in PART_SENSITIVE_KINDS:
            continue
        groups = ([list(s["atoms"])] if kind == "FLAT"
                  else [list(p) for p in s["atoms"]])
        for atoms in groups:
            parts = [int(part_of.get(str(a).upper(), 0)) for a in atoms]
            components = {abs(p) for p in parts if p}
            if len(components) > 1:
                conflicts.append({
                    "kind": kind, "atoms": [str(a) for a in atoms],
                    "parts": parts,
                    "rule": "would_be_ignored_by_shelxl",
                    "note": ("atoms in different non-zero PARTs are separate "
                             "disorder components; SHELXL does not apply a "
                             f"{kind} between them (check the restraint count "
                             "in the .lst) - put both in the same PART or "
                             "restrain within each component")})
    return {
        "requested": len(specs),
        "applied_in_process": list(info.get("applied") or []),
        "n_geometry": info.get("n_geometry"),
        "n_adp_groups": info.get("n_adp_groups"),
        "warnings": list(info.get("warnings") or []),
        "shelx_part_conflicts": conflicts,
        "not_representable": not_representable,
    }


def preflight_applicability(pf: dict[str, Any] | None) -> list[str]:
    """One sentence per finding, for the result envelope's applicability."""
    if not pf:
        return []
    out: list[str] = []
    c = pf.get("shelx_part_conflicts") or []
    if c:
        shown = "; ".join(
            f"{x['kind']} {'-'.join(x['atoms'])} (PART "
            f"{'/'.join(str(p) for p in x['parts'])})" for x in c[:4])
        out.append(f"{len(c)} restraint term(s) span different non-zero "
                   f"PARTs and SHELXL will not apply them: {shown}"
                   + (" ..." if len(c) > 4 else ""))
    nr = pf.get("not_representable") or []
    if nr:
        out.append(f"{len(nr)} restraint(s) the in-process engine cannot "
                   f"represent: " + "; ".join(
                       f"{x['kind']}: {x['reason']}" for x in nr[:3]))
    return out
