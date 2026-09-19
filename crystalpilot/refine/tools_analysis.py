"""Structure-analysis tools: geometry tables, symmetry audit, canonical
relabeling, and importing an externally refined CIF as a session start model.

Design rules (same as every refine tool): decision-ready summaries, honest
refusals with reasons, symmetry-aware numerics via cctbx (the LLM never
computes crystallography), and auto-commit through MUTATING_TOOLS for
anything that changes model state.
"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Any

from ..tools.base import ToolContext, ToolResult
from .toolbase import _ProjectTool


def _min_sym_dist(sgtbx, eq, site) -> float | None:
    """Distance from `site` to the nearest symmetry image behind `eq`
    (a sym_equiv_sites of the other point). None when cctbx refuses the
    site - a bad coordinate must never break a read-only report."""
    try:
        return float(
            sgtbx.min_sym_equiv_distance_info(eq, tuple(site)).dist())
    except Exception:  # noqa: BLE001
        return None


def register_analysis_tools(reg, project) -> None:
    from .tools_chemaudit import AuditElementAssignment, AuditGuestEvidence
    from .tools_heavysites import AuditHeavySites
    from .tools_packing import AnalyzePacking
    for cls in (GetGeometry, CheckSymmetry, RenameAtoms, ImportCifModel,
                AuditReflectionData, AuditElementAssignment,
                AuditGuestEvidence, AuditHeavySites, ScreenSpaceGroups,
                ReflectionStatistics, NcsAudit,
                ChangeSpaceGroup, AssembleAsu, SetExperiment,
                SwapReflectionData, ViewStructure, SituationReport,
                AnalyzePacking):
        reg.register(cls(project))


# ==========================================================================
# geometry esds from the newest SHELXL ACTA job.cif
# ==========================================================================

from .toolbase import _VAL_ESD  # noqa: E402 (shared with ingest)


def _latest_shelxl_cif(project) -> Path | None:
    root = project.dir / ".crystalpilot" / "refine" / "shelxl"
    if not root.exists():
        return None
    jobs = sorted(root.glob("job_*/job.cif"))
    return jobs[-1] if jobs else None


def _parse_geom_loops(cif_path: Path) -> tuple[dict, dict]:
    """label-keyed bond/angle values WITH esd strings from _geom_* loops."""
    bonds, angles, _tors = _parse_geom_loops3(cif_path)
    return bonds, angles


def _parse_geom_loops3(cif_path: Path) -> tuple[dict, dict, dict]:
    """bonds, angles AND torsions (`_geom_torsion`, written by SHELXL only
    when the job carried a CONF card) with their esd strings."""
    bonds: dict[tuple, str] = {}
    angles: dict[tuple, str] = {}
    torsions: dict[tuple, str] = {}
    try:
        lines = cif_path.read_text(encoding="utf-8",
                                   errors="replace").splitlines()
    except OSError:
        return bonds, angles, torsions
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if ln == "loop_":
            hdr = []
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith("_"):
                hdr.append(lines[j].strip())
                j += 1
            if any(h.startswith("_geom_bond_distance") for h in hdr):
                cols = {h: k for k, h in enumerate(hdr)}
                while j < len(lines):
                    row = lines[j].split()
                    if len(row) < len(hdr) or row[0].startswith(("_", "#")) \
                            or row[0] == "loop_":
                        break
                    a = row[cols["_geom_bond_atom_site_label_1"]].upper()
                    b = row[cols["_geom_bond_atom_site_label_2"]].upper()
                    bonds[tuple(sorted((a, b)))] = \
                        row[cols["_geom_bond_distance"]]
                    j += 1
            elif any(h.startswith("_geom_angle") and h.endswith("_geom_angle")
                     or h == "_geom_angle" for h in hdr):
                cols = {h: k for k, h in enumerate(hdr)}
                while j < len(lines):
                    row = lines[j].split()
                    if len(row) < len(hdr) or row[0].startswith(("_", "#")) \
                            or row[0] == "loop_":
                        break
                    a = row[cols["_geom_angle_atom_site_label_1"]].upper()
                    b = row[cols["_geom_angle_atom_site_label_2"]].upper()
                    c = row[cols["_geom_angle_atom_site_label_3"]].upper()
                    key = (b,) + tuple(sorted((a, c)))
                    angles[key] = row[cols["_geom_angle"]]
                    j += 1
            elif "_geom_torsion" in hdr:
                cols = {h: k for k, h in enumerate(hdr)}
                while j < len(lines):
                    row = lines[j].split()
                    if len(row) < len(hdr) or row[0].startswith(("_", "#")) \
                            or row[0] == "loop_":
                        break
                    lb = tuple(row[cols[f"_geom_torsion_atom_site_label_{k}"]]
                               .upper() for k in (1, 2, 3, 4))
                    torsions[lb] = row[cols["_geom_torsion"]]
                    torsions[lb[::-1]] = row[cols["_geom_torsion"]]
                    j += 1
            i = j
        else:
            i += 1
    return bonds, angles, torsions


def _torsion_deg(p1, p2, p3, p4) -> float:
    """Dihedral p1-p2-p3-p4 in degrees (IUPAC sign), cartesian."""
    import numpy as np
    b1 = np.subtract(p2, p1)
    b2 = np.subtract(p3, p2)
    b3 = np.subtract(p4, p3)
    n1 = np.cross(b1, b2)
    n2 = np.cross(b2, b3)
    nb2 = np.linalg.norm(b2)
    if nb2 < 1e-9 or np.linalg.norm(n1) < 1e-9 or np.linalg.norm(n2) < 1e-9:
        return float('nan')
    # IUPAC sign: positive when A->D turns clockwise viewed from B to C
    x = float(np.dot(n1, n2))
    y = float(np.dot(np.cross(n1, n2), b2 / nb2))
    return float(math.degrees(math.atan2(y, x)))


def _plane_fit(cart) -> tuple:
    """(centroid, unit normal, rms deviation) of a least-squares plane."""
    import numpy as np
    p = np.asarray(cart, dtype=float)
    c = p.mean(axis=0)
    _u, s, vt = np.linalg.svd(p - c)
    n = vt[-1]
    dev = (p - c) @ n
    return c, n, float(np.sqrt(np.mean(dev ** 2)))


class GetGeometry(_ProjectTool):
    name = "get_geometry"
    description = (
        "Bond-length and angle tables for the current model, symmetry-aware "
        "(includes bonds closed through symmetry operations). When a SHELXL "
        "cross-check job exists, matching values carry the SHELXL esds "
        "(u(x) in parentheses); otherwise plain model distances are reported "
        "and that limitation is stated. Filter with atoms=[labels] (their "
        "full environments) or elements=['Zr','O']. scope='torsions' "
        "(dihedrals over bonded chains, esds from a CONF job), 'planes' "
        "(least-squares planes of rings: rms, normal, centroid; SHELXL "
        "MPLA esds reach only the .lst) and 'centroids' (ring centroids) "
        "return `suggested_cards` (CONF / MPLA) for run_shelxl(extra_cards=). "
        "Use for VALIDATION.md geometry citations and coordination reasoning.")
    params_schema = {
        "type": "object",
        "properties": {
            "atoms": {"type": "array", "items": {"type": "string"},
                      "description": "restrict to these atom labels"},
            "elements": {"type": "array", "items": {"type": "string"}},
            "scope": {"type": "string",
                      "enum": ["bonds", "angles", "both", "torsions",
                               "planes", "centroids", "all"],
                      "default": "both"},
        },
    }

    _MAX_ROWS = 400

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from .inspect import _angle, _neighbor_table
        ses = ctx.session
        if ses is None or ses.model is None:
            return ToolResult.failure("no model loaded")
        xs = ses.model
        scs = list(xs.scatterers())
        labels = [sc.label for sc in scs]
        elems = [sc.scattering_type.strip().capitalize() for sc in scs]
        want = None
        if params.get("atoms"):
            want = {str(a).upper() for a in params["atoms"]}
            unknown = want - {lb.upper() for lb in labels}
            if unknown:
                return ToolResult.failure(
                    f"unknown atom labels: {sorted(unknown)}; "
                    f"model has {labels}")
        want_el = ({str(e).capitalize() for e in params["elements"]}
                   if params.get("elements") else None)
        from .nodes import part_connectivity_kwargs
        nbt = _neighbor_table(
            xs, part_connectivity_kwargs(ses.flags, scs))
        uc = xs.unit_cell()
        scope = params.get("scope", "both")

        cif = _latest_shelxl_cif(self.project)
        esd_bonds, esd_angles, esd_tors = (_parse_geom_loops3(cif) if cif
                                           else ({}, {}, {}))
        want_bonds = scope in ("bonds", "both", "all")
        want_angles = scope in ("angles", "both", "all")

        def keep(i: int) -> bool:
            if want is not None and labels[i].upper() not in want:
                return False
            if want_el is not None and elems[i] not in want_el:
                return False
            return True

        bonds, seen = [], set()
        for i, nbrs in (enumerate(nbt) if want_bonds else ()):
            for nb in nbrs:
                j = nb["j"]
                if not (keep(i) or keep(j)):
                    continue
                key = (min(i, j), max(i, j), round(nb["d"], 3))
                if key in seen:
                    continue
                seen.add(key)
                row = {"a": labels[i], "b": labels[j], "d": nb["d"],
                       "via_symmetry": nb["sym"], "kind": nb.get("kind")}
                esd = esd_bonds.get(
                    tuple(sorted((labels[i].upper(), labels[j].upper()))))
                if esd:
                    row["shelxl"] = esd
                bonds.append(row)
        bonds.sort(key=lambda r: (r["a"], r["d"]))

        angles = []
        if want_angles:
            for i, nbrs in enumerate(nbt):
                if not keep(i) or len(nbrs) < 2:
                    continue
                for x in range(len(nbrs)):
                    for y in range(x + 1, len(nbrs)):
                        a = _angle(uc, scs[i].site,
                                   nbrs[x]["site_frac"], nbrs[y]["site_frac"])
                        row = {"a": nbrs[x]["label"], "b": labels[i],
                               "c": nbrs[y]["label"], "deg": round(a, 1)}
                        esd = esd_angles.get(
                            (labels[i].upper(),) + tuple(sorted((
                                nbrs[x]["label"].upper(),
                                nbrs[y]["label"].upper()))))
                        if esd:
                            row["shelxl"] = esd
                        angles.append(row)

        # ---- torsions: x-i-j-y over bonded chains, symmetry-aware -------
        from cctbx import sgtbx
        torsions: list[dict[str, Any]] = []
        if scope in ("torsions", "all"):
            seen_t: set[tuple] = set()
            for i, nbrs in enumerate(nbt):
                for nb in nbrs:
                    j = nb["j"]
                    if not (keep(i) or keep(j)):
                        continue
                    op_ij = sgtbx.rt_mx(nb["op"])
                    xs_i = [x for x in nbrs if x["j"] != j or x["op"] != nb["op"]]
                    ys_j = []
                    for y in nbt[j]:
                        # y's site in i's frame: op_ij applied to y's site
                        # relative to j
                        y_site = (op_ij.multiply(sgtbx.rt_mx(y["op"]))
                                  * scs[y["j"]].site)
                        if y["j"] == i and uc.distance(y_site, scs[i].site) < 1e-3:
                            continue
                        ys_j.append((y["label"], y_site))
                    for x in xs_i:
                        for yl, ys in ys_j:
                            key = (x["label"], labels[i], labels[j], yl)
                            if key[::-1] in seen_t:
                                continue
                            seen_t.add(key)
                            p = [uc.orthogonalize(x["site_frac"]),
                                 uc.orthogonalize(scs[i].site),
                                 uc.orthogonalize(nb["site_frac"]),
                                 uc.orthogonalize(ys)]
                            tor = _torsion_deg(*p)
                            if tor != tor:            # nan: linear
                                continue
                            row = {"a": x["label"], "b": labels[i],
                                   "c": labels[j], "d": yl,
                                   "deg": round(tor, 1),
                                   "via_symmetry": bool(nb["sym"] or x["sym"])}
                            esd = esd_tors.get(tuple(k.upper() for k in key))
                            if esd:
                                row["shelxl"] = esd
                            torsions.append(row)
            torsions.sort(key=lambda r: (r["b"], r["c"], r["a"], r["d"]))

        # ---- planes / centroids: rings from the interaction engine's ring
        # definitions (find_rings + planarity), least-squares fit here -----
        planes: list[dict[str, Any]] = []
        centroids: list[dict[str, Any]] = []
        cards: list[str] = []
        if scope in ("planes", "centroids", "all"):
            from ..chem.bonding import parts_from_part_kwargs
            from ..chem.interactions import _Model, _ring_defs
            mdl = _Model(xs, parts=parts_from_part_kwargs(
                part_connectivity_kwargs(ses.flags, scs), len(scs)))
            rings, ring_note, _through_symmetry = _ring_defs(mdl)
            for r in rings:
                atoms = [str(a) for a in r["key"].split(",")]
                idxs = [labels.index(a) for a in atoms if a in labels]
                if len(idxs) < 3 or not any(keep(k) for k in idxs):
                    continue
                cart = [uc.orthogonalize(scs[k].site) for k in idxs]
                c, n, rms = _plane_fit(cart)
                cen_frac = uc.fractionalize(tuple(float(v) for v in c))
                entry = {"atoms": atoms, "aromatic": bool(r.get("aromatic")),
                         "centroid_frac": [round(float(v), 4) for v in cen_frac],
                         "centroid_cart": [round(float(v), 3) for v in c]}
                if scope in ("planes", "all"):
                    planes.append({**entry, "rms_A": round(rms, 4),
                                   "normal": [round(float(v), 4) for v in n]})
                    cards.append(f"MPLA {len(atoms)} " + " ".join(atoms))
                if scope in ("centroids", "all"):
                    centroids.append(entry)
            if ring_note:
                summary_ring_note = ring_note
            else:
                summary_ring_note = None
        else:
            summary_ring_note = None

        truncated = (len(bonds) > self._MAX_ROWS or len(angles) > self._MAX_ROWS
                     or len(torsions) > self._MAX_ROWS)
        summary: dict[str, Any] = {
            "scope": scope,
            "n_bonds": len(bonds), "n_angles": len(angles),
            "bonds": bonds[:self._MAX_ROWS] if want_bonds else [],
            "angles": angles[:self._MAX_ROWS] if want_angles else [],
            "esd_source": (str(cif) if cif else None),
            "truncated": truncated,
        }
        if scope in ("torsions", "all"):
            summary["n_torsions"] = len(torsions)
            summary["torsions"] = torsions[:self._MAX_ROWS]
            summary["torsion_esd_note"] = (
                "esds appear only when the SHELXL job carried CONF "
                "(_geom_torsion loop); run_shelxl(extra_cards=['CONF']) "
                "adds them" if not esd_tors else
                f"{len(esd_tors) // 2} torsions carry SHELXL esds (CONF)")
            cards.append("CONF")
        if scope in ("planes", "all"):
            summary["n_planes"] = len(planes)
            summary["planes"] = planes[:self._MAX_ROWS]
            summary["plane_esd_note"] = (
                "least-squares fit here (no esd); SHELXL MPLA writes the "
                "plane esds to the .lst only, never to the CIF")
        if scope in ("centroids", "all"):
            summary["n_centroids"] = len(centroids)
            summary["centroids"] = centroids[:self._MAX_ROWS]
        if summary_ring_note:
            summary["ring_note"] = summary_ring_note
        if cards:
            summary["suggested_cards"] = {
                "cards": sorted(set(cards), key=cards.index),
                "how": "run_shelxl(extra_cards=cards, reason=...)"}
        if not cif:
            summary["note"] = ("no SHELXL job found - distances carry no "
                               "esds; run_shelxl (ACTA) provides them")
        return ToolResult(ok=True, summary=summary)


# ==========================================================================
# difference-peak environment: what could this peak chemically be?
# ==========================================================================

def peak_environment(xs, peak_site, height: float,
                     cutoff_A: float = 3.0) -> dict[str, Any]:
    """Nearest model atoms (symmetry-aware) around a difference peak plus a
    chemical identity hint. Distances are the crystallographer's first
    question about any peak; encode the standard reading so the agent does
    not re-derive it each time."""
    from ..chem.knowledge import is_metal
    uc = xs.unit_cell()
    ops = xs.space_group().all_ops()
    neighbors = []
    for sc in xs.scatterers():
        el = sc.scattering_type.strip().capitalize()
        best = None
        for op in ops:
            s = op * sc.site
            d = uc.distance(
                tuple(peak_site[k] - math.floor(peak_site[k] - s[k] + 0.5)
                      for k in range(3)), s)
            if best is None or d < best:
                best = d
        if best is not None and best <= cutoff_A:
            neighbors.append({"label": sc.label, "element": el,
                              "d": round(best, 2)})
    neighbors.sort(key=lambda n: n["d"])
    neighbors = neighbors[:5]

    hint = "isolated (no atom within 3 A) - lattice solvent or noise"
    if neighbors:
        n0 = neighbors[0]
        el, d = n0["element"], n0["d"]
        if d < 0.45:
            hint = (f"ON {n0['label']} - element too light there (or "
                    f"occupancy/ADP too small)" if height > 0 else
                    f"on {n0['label']}")
        elif d < 0.7:
            hint = (f"{d} A from {n0['label']} - too close for a bonded "
                    f"atom: anisotropy artifact or split-site disorder of "
                    f"{n0['label']}?")
        elif d < 1.25 and not is_metal(el) and el != "H":
            hint = (f"{d} A from {n0['label']} - H-atom range" if height < 1.5
                    else f"{d} A from {n0['label']} - too close for a "
                         f"non-H atom; split site / disorder?")
        elif 1.25 <= d <= 1.75 and el in ("C", "N", "O", "B", "S"):
            hint = (f"bonding distance to {n0['label']} ({d} A) - missing "
                    f"light atom (C/N/O) of the same fragment?")
        elif is_metal(el) and 1.8 <= d <= 2.7:
            hint = (f"coordination distance to {n0['label']} ({d} A) - "
                    f"missing donor atom (O/N) or coordinated solvent?")
        elif d > 2.2:
            hint = "in a void region - unmodelled solvent (consider the mask)"
        else:
            hint = f"{d} A from {n0['label']}"
    return {"environment": neighbors, "hint": hint}


# ==========================================================================
# symmetry audit (ADDSYM-style, deterministic, cctbx only)
# ==========================================================================

class RenameAtoms(_ProjectTool):
    name = "rename_atoms"
    description = (
        "Relabel atoms. mode='canonical' assigns element-encoded sequential "
        "labels (Zr1, O1, C1...; H atoms follow their carrier: C12 -> H12A). "
        "Fixes stale labels from coarse models (e.g. an atom labelled FE01 "
        "that is really Zr - PLATON/checkCIF guess elements from labels and "
        "will mis-audit). mode='map' applies an explicit {old: new} mapping. "
        "Restraint specs and riding-H metadata are updated consistently; "
        "the change commits a node like any model edit.")
    params_schema = {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["canonical", "map"],
                     "default": "canonical"},
            "map": {"type": "object",
                    "description": "old->new labels (mode='map')"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from .nodes import (_apply_rename_to_h_meta, _apply_rename_to_specs)
        ses = ctx.session
        if ses is None or ses.model is None:
            return ToolResult.failure("no model loaded")
        xs = ses.model
        scs = list(xs.scatterers())
        old = [sc.label for sc in scs]
        h_meta = ses.flags.get("h_riding_meta") or {}
        carriers = {e["carrier"]: e.get("h", [])
                    for e in (h_meta.get("per_carrier") or [])}

        mode = params.get("mode", "canonical")
        if mode == "map":
            mapping = {str(k): str(v) for k, v in
                       (params.get("map") or {}).items()}
            if not mapping:
                return ToolResult.failure("mode='map' needs a non-empty map")
            unknown = set(mapping) - set(old)
            if unknown:
                return ToolResult.failure(
                    f"labels not in model: {sorted(unknown)}")
            too_long = [v for v in mapping.values() if len(v) > 4]
            if too_long:
                return ToolResult.failure(
                    f"SHELX labels are max 4 chars: {too_long}")
            new_all = [mapping.get(lb, lb) for lb in old]
            if len(set(x.upper() for x in new_all)) != len(new_all):
                return ToolResult.failure("mapping creates duplicate labels")
        else:
            mapping = _canonical_mapping(scs, carriers)
            new_all = [mapping.get(lb, lb) for lb in old]

        # SHELX serialization uppercases labels; case-only differences are
        # not a real rename (avoid churn on a second canonical pass)
        changed = {a: b for a, b in zip(old, new_all)
                   if a.upper() != b.upper()}
        if not changed:
            return ToolResult(ok=True, summary={
                "no_state_change": True,
                "note": "labels already canonical - nothing to rename"})
        for sc, nb in zip(scs, new_all):
            sc.label = nb
        ses.flags["restraints"] = _apply_rename_to_specs(
            list(ses.flags.get("restraints") or []), changed)
        ses.flags["h_riding_meta"] = _apply_rename_to_h_meta(h_meta, changed)
        # disorder PART membership is label-keyed too: stale labels detach
        # split atoms from their FVAR and ordered atoms can inherit partial
        # occupancies on the next add_hydrogens/serialization (round-10 #10)
        if ses.flags.get("disorder_groups"):
            from .nodes import _apply_rename_to_disorder
            ren = dict(changed)
            ren.update({k.upper(): v for k, v in changed.items()})
            ses.flags["disorder_groups"] = _apply_rename_to_disorder(
                ses.flags["disorder_groups"], ren)
        if ses.flags.get("parts_extra"):
            ren_up = {k.upper(): v for k, v in changed.items()}
            ses.flags["parts_extra"] = {
                str(ren_up.get(lbl, lbl)).upper(): p
                for lbl, p in ses.flags["parts_extra"].items()}
        # the live riding-H fixup stores (index, label) pairs captured at
        # add_hydrogens time; rename relabels IN PLACE (no reorder), so
        # remapping the labels keeps the whole constraint stack valid -
        # otherwise the next refine hits the staleness guard and refuses
        # (r11 case-c: canonical rename -> refine rejected -> forced
        # add_hydrogens re-run)
        ren_any = dict(changed)
        ren_any.update({k.upper(): v for k, v in changed.items()})
        if ses.flags.get("afix_groups"):
            from .nodes import _apply_rename_to_afix_groups
            ses.flags["afix_groups"] = _apply_rename_to_afix_groups(ses.flags["afix_groups"], ren_any)
        for con in (ses.flags.get("h_constraints") or []):
            checks = getattr(con, "checks", None)
            if checks:
                con.checks = [
                    (i, ren_any.get(lbl, ren_any.get(lbl.upper(), lbl)))
                    for i, lbl in checks]
        return ToolResult(ok=True, summary={
            "n_renamed": len(changed),
            "renames": changed,
            "note": ("labels now encode elements; PLATON/checkCIF label "
                     "heuristics and geometry tables will read correctly"),
        })


def _canonical_mapping(scs, carriers: dict[str, list[str]]) -> dict[str, str]:
    """element+ordinal labels, H named after carriers (H12A style)."""
    h_of: dict[str, str] = {}
    for carrier, hs in carriers.items():
        for h in hs:
            h_of[h] = carrier
    counters: dict[str, int] = {}
    mapping: dict[str, str] = {}
    # first pass: non-H in model order
    for sc in scs:
        el = sc.scattering_type.strip().capitalize()
        if el == "H":
            continue
        counters[el] = counters.get(el, 0) + 1
        mapping[sc.label] = f"{el}{counters[el]}"
    # second pass: H follows carrier where known, else sequential
    suffix = "ABCDEFG"
    used_h: dict[str, int] = {}
    n_free_h = 0
    fallback = False
    for sc in scs:
        el = sc.scattering_type.strip().capitalize()
        if el != "H":
            continue
        carrier = h_of.get(sc.label)
        if carrier and carrier in mapping:
            base = mapping[carrier]
            k = used_h.get(base, 0)
            used_h[base] = k + 1
            lbl = f"H{base[len(base.rstrip('0123456789')):]}{suffix[k % 7]}"
            if len(lbl) > 4:
                fallback = True
            mapping[sc.label] = lbl
        else:
            n_free_h += 1
            mapping[sc.label] = f"H{n_free_h}"
    if fallback or len({v.upper() for v in mapping.values()}) != len(mapping):
        # safe fallback: plain sequential H labels
        n = 0
        for sc in scs:
            if sc.scattering_type.strip().capitalize() == "H":
                n += 1
                mapping[sc.label] = f"H{n}"
    return mapping


# ==========================================================================
# import an externally refined CIF as the start model
# ==========================================================================

def _audit_fcf(path: Path, span_threshold: float = 0.02) -> dict[str, Any]:
    """Audit a SHELXL LIST-4 fcf: is Fc^2 a single-valued function of hkl?

    Non-constant Fc^2 within a Friedel/duplicate group proves the model
    behind the file used a multi-component observation model (TWIN scales
    or HKLF5 batches) - converting such data to plain HKLF4 discards it.
    Also recomputes R1 from the file itself (all and Fo^2>2sigma).
    """
    import collections

    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        f = line.split()
        if len(f) not in (6, 7):
            continue
        try:
            h, k, l = int(f[0]), int(f[1]), int(f[2])
            fc2, fo2, sig = float(f[3]), float(f[4]), float(f[5])
        except ValueError:
            continue
        rows.append(((h, k, l), fc2, fo2, sig))
    if not rows:
        return {"error": f"no LIST-4 data rows parsed from {path.name}"}

    def r1(sel):
        den = sum(math.sqrt(max(r[2], 0.0)) for r in sel)
        num = sum(abs(math.sqrt(max(r[2], 0.0)) - math.sqrt(max(r[1], 0.0)))
                  for r in sel)
        return round(num / den, 5) if den else None

    exact = collections.defaultdict(list)
    friedel = collections.defaultdict(list)
    for r in rows:
        exact[r[0]].append(r)
        friedel[min(r[0], tuple(-x for x in r[0]))].append(r)

    # Friedel-mate Fc^2 differences are REAL in non-centrosymmetric
    # structures (anomalous dispersion) - require a relative span too so
    # e.g. 0.44 on Fc^2=1601 (0.03%) does not flag as a twin model.
    fc2_spans = {}
    for k, v in friedel.items():
        if len(v) < 2:
            continue
        hi = max(x[1] for x in v)
        lo = min(x[1] for x in v)
        mean = sum(x[1] for x in v) / len(v)
        if (hi - lo) > span_threshold and (hi - lo) > 0.02 * max(mean, 0.01):
            fc2_spans[k] = hi - lo
    n_nonconstant = len(fc2_spans)
    out: dict[str, Any] = {
        "file": str(path),
        "n_rows": len(rows),
        "n_friedel_groups": len(friedel),
        "n_exact_duplicate_hkl": sum(1 for v in exact.values() if len(v) > 1),
        "r1_from_file_all": r1(rows),
        "r1_from_file_fo2_gt_2sig": r1([r for r in rows if r[2] > 2 * r[3]]),
        "groups_with_nonconstant_fc2": n_nonconstant,
    }
    if fc2_spans:
        worst = max(fc2_spans, key=fc2_spans.get)
        out["max_fc2_span"] = round(fc2_spans[worst], 3)
        out["worst_group"] = {
            "hkl": list(worst),
            "fc2": [round(x[1], 2) for x in friedel[worst]],
            "fo2": [round(x[2], 2) for x in friedel[worst]],
        }
    if n_nonconstant:
        out["interpretation"] = (
            "Fc^2 is NOT single-valued per hkl group: the model behind this "
            "fcf used a multi-component observation model (TWIN/BASF scales "
            "or HKLF5 batches). Its R factors cannot be reproduced from a "
            "plain merged HKLF4 file.")
    else:
        out["interpretation"] = (
            "Fc^2 is single-valued per hkl group - consistent with a plain "
            "single-component HKLF4 refinement.")

    # Systematic sign bias of Fo^2-Fc^2 by intensity band. A healthy
    # refinement is ~50/50 in every band; an unmodelled second twin domain
    # adds intensity to many observations, so the WEAK/MEDIUM bands drift
    # to Fo^2 > Fc^2 (the classic referee tell: "Fo2 > Fc2 for most of the
    # reflections of medium or weak intensity").
    bands = {"weak_lt_2sig": [], "medium_2_10sig": [], "strong_gt_10sig": []}
    for r in rows:
        sig = max(r[3], 1e-9)
        ios = r[2] / sig
        band = ("weak_lt_2sig" if ios < 2.0
                else "medium_2_10sig" if ios < 10.0 else "strong_gt_10sig")
        bands[band].append(r)
    sign_bias: dict[str, Any] = {}
    biased_bands = []
    for name, sel in bands.items():
        if len(sel) < 30:
            continue
        n_hi = sum(1 for r in sel if r[2] > r[1])
        frac = n_hi / len(sel)
        sign_bias[name] = {"n": len(sel), "frac_fo2_gt_fc2": round(frac, 3)}
        if name != "strong_gt_10sig" and frac >= 0.65:
            biased_bands.append((name, frac))
    if sign_bias:
        out["fo2_fc2_sign_bias"] = sign_bias
    if biased_bands:
        desc = ", ".join(f"{n} {f:.0%}" for n, f in biased_bands)
        out["sign_bias_hint"] = (
            f"Fo^2 > Fc^2 for a systematic majority of weak/medium "
            f"reflections ({desc}; healthy is ~50%) - an unmodelled "
            f"contribution inflates the observations. Classic causes: an "
            f"unmodelled twin domain, missed solvent scattering, or an "
            f"inadequate model; check twinning before pushing the model.")

    # Fo^2 >> Fc^2 misfit outliers, clustered by index class (TwinRotMat's
    # core evidence: a second twin domain folds intensity onto specific
    # classes/zones of the first domain's lattice)
    import collections as _c
    mis = [r for r in rows
           if r[2] > 4.0 * max(r[1], 0.01) and r[2] > 10.0 * max(r[3], 1e-6)]
    if mis:
        parity = _c.Counter(
            (h % 2, k % 2, l % 2) for (h, k, l), _, _, _ in mis)
        zones = _c.Counter()
        for (h, k, l), _, _, _ in mis:
            if h == 0:
                zones["h=0"] += 1
            if k == 0:
                zones["k=0"] += 1
            if l == 0:
                zones["l=0"] += 1
            if (h + l) % 2:
                zones["h+l odd"] += 1
            if (h + k) % 2:
                zones["h+k odd"] += 1
        # non-merohedral overlap zones: misfits concentrated at small
        # |index| along one axis (the twin law maps that slab of
        # reciprocal space near-exactly onto the other domain)
        for ax, name in ((0, "|h|<=1"), (1, "|k|<=1"), (2, "|l|<=1")):
            n_small = sum(1 for r in mis if abs(r[0][ax]) <= 1)
            pop = sum(1 for r in rows if abs(r[0][ax]) <= 1)
            pop_frac = pop / len(rows)
            if (n_small >= 0.6 * len(mis)
                    and n_small / len(mis) >= 3.0 * max(pop_frac, 0.01)):
                zones[name] = n_small
        top = sorted(mis, key=lambda r: -r[2] / max(r[1], 0.01))[:8]
        mo: dict[str, Any] = {
            "n": len(mis),
            "criterion": "Fo2 > 4*Fc2 and Fo2 > 10*sigma",
            "parity_classes": {"".join(map(str, k)): v
                               for k, v in parity.most_common(4)},
            "zones": dict(zones.most_common(4)),
            "top": [{"hkl": list(r[0]), "fo2": round(r[2], 1),
                     "fc2": round(r[1], 2)} for r in top],
        }
        out["misfit_outliers"] = mo
        if len(mis) >= 10:
            dom_zone = zones.most_common(1)
            if dom_zone and dom_zone[0][1] >= 0.6 * len(mis):
                mo["cluster_hint"] = (
                    f"{dom_zone[0][1]}/{len(mis)} Fo^2>>Fc^2 outliers fall "
                    f"in the {dom_zone[0][0]} class - a second twin domain "
                    f"likely folds intensity onto this class. Apparent "
                    f"systematic-absence violations restricted to such a "
                    f"class are NOT reliable space-group evidence; consider "
                    f"non-merohedral twinning (two-lattice indexing at the "
                    f"frames stage / PLATON TwinRotMat -> HKLF5) before "
                    f"lowering the symmetry.")
    return out


def duplicate_consistency(raw, thr: float = 10.0) -> dict[str, Any]:
    """Duplicate-observation consistency of an UNMERGED intensity array:
    groups of identical hkl, reduced chi^2 of each against its mean,
    the HKLF5-export signature (same hkl many times, disagreeing far
    beyond sigma, no batch column) as `reading`, and the gross-
    inconsistency hint. Shared by audit_reflection_data (which turns
    `reading` / `hint` into hints) and ingest_vendor_data (reg8: the
    duplicate structure of a file is known the moment it is imported)."""
    import collections

    idx = raw.indices()
    vals = raw.data()
    sigs = raw.sigmas()
    groups: dict[tuple, list] = collections.defaultdict(list)
    for i in range(idx.size()):
        groups[tuple(idx[i])].append(
            (float(vals[i]), float(sigs[i]) if sigs is not None else 0.0))
    multi = {k: v for k, v in groups.items() if len(v) > 1}
    n_bad = 0
    worst: tuple | None = None
    for k, v in multi.items():
        ss = [s for _, s in v if s > 0]
        if len(ss) < len(v):        # unusable sigmas - skip the group
            continue
        m = sum(x for x, _ in v) / len(v)
        chi2 = sum((x - m) ** 2 / (s * s) for x, s in v) / (len(v) - 1)
        if chi2 > thr:
            n_bad += 1
            if worst is None or chi2 > worst[0]:
                worst = (chi2, k, [round(x, 1) for x, _ in v])
    dup: dict[str, Any] = {
        "n_observations": idx.size(),
        "n_duplicate_groups": len(multi),
        "n_groups_chi2_above_threshold": n_bad,
        "chi2_threshold": thr,
    }
    if multi:
        dup["fraction_inconsistent"] = round(n_bad / len(multi), 3)
    if worst:
        dup["worst_group"] = {"hkl": list(worst[1]),
                              "reduced_chi2": round(worst[0], 1),
                              "intensities": worst[2]}
    if multi:
        max_mult = max(len(v) for v in multi.values())
        dup["max_multiplicity"] = max_mult
        if max_mult > 2 and n_bad / len(multi) > 0.2:
            # nm (reg1/reg8, 2026-09-04): a reflection list exported
            # from a TWIN (HKLF 5) refinement - every row an overlapped
            # observation with its own domain mix - reads as HKLF 4
            # with the same hkl up to 8x and intensities that disagree
            # far beyond sigma. Merging averages incompatible
            # composites; the deposited model itself refines to 0.094
            # on it, not its published 0.053
            dup["reading"] = (
                f"the same hkl appears up to {max_mult} times with "
                f"intensities that disagree far beyond their sigmas "
                f"({n_bad}/{len(multi)} groups), and the file carries "
                f"no batch column: this is what a reflection list "
                f"exported from a TWIN (HKLF 5) refinement looks like - "
                f"each row an overlapped observation with a different "
                f"domain mix. Merging them averages incompatible "
                f"composites, so a single-domain model has an R1 FLOOR "
                f"on these data that no modelling lowers (a published "
                f"R1 for such a structure was reached with the twin "
                f"model and the batch-tagged data). State the floor in "
                f"unresolved instead of chasing it, and ask for the "
                f"HKLF 5 file or the frames.")
    if multi and n_bad / len(multi) > 0.05:
        dup["hint"] = (
            f"{n_bad}/{len(multi)} duplicate groups are grossly "
            f"inconsistent (chi2_red>{thr:g}) - twin-composite data or a "
            f"scaling problem, not counting statistics. One physical "
            f"cause worth actively considering when the fraction is "
            f"LARGE: a twin-composite SUPERCELL - indexing absorbed "
            f"both twin domains into one enlarged lattice (an axis "
            f"near 2x a plausible cell edge is the tell), so "
            f"'equivalent' reflections actually mix unrelated "
            f"domain-A and domain-B intensities. Discriminate by "
            f"re-indexing with the HALVED cell as prior and "
            f"max_lattices=2: a genuine composite splits into two "
            f"clean sub-lattices (r17 live case: 25.4 A = 2 x 12.7).")
    return dup


class AuditReflectionData(_ProjectTool):
    name = "audit_reflection_data"
    description = (
        "Audit the reflection data for twin / wrong-symmetry symptoms before "
        "blaming the model: (a) statistical consistency of duplicate "
        "observations (grossly inconsistent duplicates suggest twin-composite "
        "or scaling problems), (b) merging R_int in the current Laue group vs "
        "triclinic (a large gap suggests wrong Laue group or twinning), (c) "
        "systematic-absence violations (strong intensity in extinct classes "
        "suggests wrong space group or twin overlap), (d) optionally audits a "
        "LIST-4 .fcf (default: newest SHELXL job) for non-single-valued Fc^2 "
        "per hkl - the fingerprint of a TWIN/HKLF5 observation model - plus "
        "referee-grade statistics: systematic Fo^2>Fc^2 sign bias in the "
        "weak/medium bands and an R1-vs-R_int mismatch check (R1 far above "
        "R_int with clean data points at twinning/modulation, not noise), "
        "(e) |E^2-1| intensity statistics (twinning flattens the "
        "distribution; <0.68 is the XPREP twin-warning line), (f) lattice "
        "metric vs Laue class (a metric holohedry above the Laue group is "
        "the pseudo-merohedral twin precondition). Fires a twin_alarm "
        "summary when warning signs are present. Read-only; run it when R1 "
        "stalls high or twinning is suspected - and cheaply BEFORE heavy "
        "model work on framework structures.")
    params_schema = {
        "type": "object",
        "properties": {
            "fcf": {"type": "string",
                    "description": "path to a LIST-4 .fcf to audit (absolute "
                                   "or project-relative); default: the newest "
                                   "SHELXL job fcf if one exists"},
            "chi2_threshold": {
                "type": "number", "default": 10.0,
                "description": "reduced-chi^2 above which a duplicate group "
                               "counts as grossly inconsistent"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        import collections

        from cctbx import crystal

        p = self.project
        ses = ctx.session or p.session
        if ses is None or ses.dataset is None:
            return ToolResult(ok=False, summary={},
                              error="no dataset loaded in this project")
        raw = ses.dataset.intensities
        thr = float(params.get("chi2_threshold") or 10.0)
        out: dict[str, Any] = {}
        hints: list[str] = []
        twin_signs: list[str] = []

        # (a) duplicate-observation consistency on the raw (unmerged) data
        dup = duplicate_consistency(raw, thr)
        out["duplicates"] = dup
        if dup.get("reading"):
            hints.append(dup["reading"])
        if dup.get("hint"):
            hints.append(dup["hint"])

        # (b) Laue-group consistency vs triclinic
        cur = ses.symmetry
        if cur is not None:
            work = raw.customized_copy(crystal_symmetry=cur)
            work = work.set_observation_type_xray_intensity()
            tric = raw.customized_copy(crystal_symmetry=crystal.symmetry(
                unit_cell=raw.unit_cell(), space_group_symbol="P -1"))
            tric = tric.set_observation_type_xray_intensity()
            r_cur = work.merge_equivalents().r_int()
            r_tri = tric.merge_equivalents().r_int()
            out["laue_consistency"] = {
                "space_group": str(cur.space_group_info()),
                "r_int_current_laue": round(r_cur, 4),
                "r_int_triclinic": round(r_tri, 4)}
            if r_cur > 2.0 * max(r_tri, 0.01) and r_cur - r_tri > 0.05:
                hints.append(
                    f"R_int jumps from {r_tri:.3f} (triclinic) to {r_cur:.3f} "
                    f"in the current Laue group - the assumed Laue symmetry "
                    f"may be wrong, or a twin relates the domains by exactly "
                    f"that pseudo-symmetry.")

            # (c) systematic-absence violations in the current space group
            flags = work.sys_absent_flags().data()
            absent = work.select(flags)
            absences: dict[str, Any] = {"n_absent_class": absent.size()}
            if absent.size() and absent.sigmas() is not None:
                a_i = absent.data()
                a_s = absent.sigmas()
                viol = []
                for i in range(absent.size()):
                    s = float(a_s[i])
                    if s > 0 and float(a_i[i]) > 3.0 * s:
                        viol.append((float(a_i[i]) / s,
                                     tuple(absent.indices()[i]),
                                     round(float(a_i[i]), 1)))
                viol.sort(reverse=True)
                absences["n_violations_gt_3sig"] = len(viol)
                absences["violation_fraction"] = round(
                    len(viol) / absent.size(), 3)
                absences["top_violators"] = [
                    {"hkl": list(h), "i": i_, "i_over_sig": round(r_, 1)}
                    for r_, h, i_ in viol[:5]]
                if len(viol) > max(5, 0.02 * absent.size()):
                    hints.append(
                        f"{len(viol)}/{absent.size()} extinct-class "
                        f"reflections exceed 3 sigma - wrong space group or a "
                        f"twin folding intensity onto absent positions.")
            out["absences"] = absences

            # (e) |E^2-1| intensity statistics. Twin domains superimpose,
            # flattening the intensity distribution below even the acentric
            # Wilson value; XPREP convention: < 0.68 is a twin warning.
            # Same quasi-normalization as sg_screen's centric hint.
            try:
                from .sg_screen import (E2M1_REFERENCE, e2m1_hint,
                                        e2m1_statistic, hint_usability)
                laue = (cur.space_group()
                        .build_derived_reflection_intensity_group(False))
                e2m1 = e2m1_statistic(work, laue)
                out["e_statistics"] = {
                    "mean_abs_e2_minus_1": round(e2m1, 3),
                    "reference": {**E2M1_REFERENCE,
                                  "twin_warning_below": 0.68,
                                  "pathology_above": 1.1},
                    "usability": hint_usability(e2m1_hint(e2m1))}
                if e2m1 < 0.68:
                    twin_signs.append("flat_e_statistics")
                    hints.append(
                        f"mean |E^2-1| = {e2m1:.3f} is below the 0.68 twin "
                        f"warning line (acentric expects 0.736, centric "
                        f"0.968) - intensity statistics this flat usually "
                        f"mean the observations superimpose twin domains.")
                if e2m1 > 1.1:
                    # r17 live: 1.017-1.02+ went unremarked because the
                    # alarm only taught the 'too flat = twin' direction;
                    # the campaign sank 79 min in a composite supercell
                    # whose merged unrelated intensities pushed the
                    # statistic ABOVE even the centric reference
                    twin_signs.append("hyper_dispersed_e_statistics")
                    hints.append(
                        f"mean |E^2-1| = {e2m1:.3f} is ABOVE the "
                        f"centrosymmetric reference (0.968) - no ordinary "
                        f"crystal does this. Classic causes: a "
                        f"twin-composite SUPERCELL merging unrelated "
                        f"domain intensities as 'equivalents' (check the "
                        f"cell for an axis ~2x a plausible edge / integer "
                        f"volume multiple vs earlier indexing runs), "
                        f"heavy outlier contamination, or a hypersymmetric "
                        f"/ pseudo-translation pathology. Audit the CELL "
                        f"and the data model before any structure work.")
                if e2m1 < 0.85:
                    # r16 live failure: a twinned CENTROSYMMETRIC crystal
                    # read |E^2-1| = 0.72 ("looks acentric"), the agent
                    # dropped to P1 and never recovered. The statistic
                    # cannot settle centro-vs-acentro whenever twinning is
                    # in play - say so, directionally.
                    out["e_statistics"]["centro_acentro_note"] = (
                        "reads acentric-or-flatter, but twin superposition "
                        "SHIFTS |E^2-1| toward acentric values - on any "
                        "twin-suspicious dataset this statistic must NOT "
                        "be used to drop an inversion centre. P1 vs P-1 "
                        "share the Laue class, so R_int cannot decide "
                        "either. Settle centro-vs-acentro by trial: solve/"
                        "refine in the CENTROSYMMETRIC candidate first "
                        "(Marsh discipline) and only keep the acentric "
                        "group if the centric one demonstrably fails; "
                        "after any P1 solve, run check_symmetry - its "
                        "heavy-anchor search finds an inversion centre "
                        "even when light atoms are wrong.")
            except Exception:  # noqa: BLE001 - advisory (needs enough data)
                pass

            # (f) lattice metric vs Laue class, in the primitive Niggli
            # setting (same comparison check_symmetry uses on the model
            # side). A metric holohedry ABOVE the Laue group is the
            # geometric precondition for pseudo-merohedral twinning; the
            # merohedral case (holohedry above the point group but within
            # the Laue class) is invisible to intensities and belongs to
            # Flack / set_twin(law=inversion) instead.
            try:
                from cctbx import sgtbx
                from cctbx.sgtbx import lattice_symmetry
                cb = cur.change_of_basis_op_to_niggli_cell()
                cs_n = cur.change_basis(cb)
                latt = lattice_symmetry.group(cs_n.unit_cell(),
                                              max_delta=1.4)
                latt.expand_inv(sgtbx.tr_vec((0, 0, 0)))
                n_latt = latt.order_z()
                laue_n = (cs_n.space_group()
                          .build_derived_reflection_intensity_group(False))
                n_laue = laue_n.order_z()
                out["metric_vs_laue"] = {
                    "n_lattice_ops_primitive": n_latt,
                    "n_laue_ops_primitive": n_laue,
                    "lattice_group": str(latt.info())}
                if n_latt > n_laue:
                    twin_signs.append("metric_exceeds_laue")
                    hints.append(
                        f"the lattice metric supports {n_latt} symmetry "
                        f"ops in the primitive setting ({latt.info()}) but "
                        f"the current Laue class uses only {n_laue} - the "
                        f"geometric precondition for pseudo-merohedral "
                        f"twinning; the extra ops are candidate twin laws "
                        f"(check_symmetry lists them).")
            except Exception:  # noqa: BLE001 - advisory
                pass

        # HKLF5 disclosure
        if (ses.flags or {}).get("hklf") == 5:
            hints.append(
                "Data are HKLF5 (twin batches): the in-process view keeps "
                "batch>0 rows only and is approximate - judge R factors "
                "through run_shelxl.")

        # (d) fcf audit
        fcf_param = params.get("fcf")
        fcf_path: Path | None = None
        if fcf_param:
            fp = Path(str(fcf_param))
            fcf_path = fp if (fp.is_absolute() or p is None) else (p.dir / fp)
            if not fcf_path.exists():
                return ToolResult(ok=False, summary=out,
                                  error=f"fcf not found: {fcf_path}")
        elif p is not None:
            cif = _latest_shelxl_cif(p)
            if cif is not None and cif.with_name("job.fcf").exists():
                fcf_path = cif.with_name("job.fcf")
        if fcf_path is not None:
            fa = _audit_fcf(fcf_path)
            out["fcf_audit"] = fa
            if fa.get("sign_bias_hint"):
                hints.append("fcf: " + fa["sign_bias_hint"])
            # R1 vs R_int mismatch ("R factors higher than expected given
            # Rint"). Benchmark case CCDC 2416519: Rint 5.25% with R1 7.28%
            # drew a twin-suspicion referee report; the recollected crystal
            # gave Rint 3.26% / R1 3.34%. Good data + right model usually
            # land R1 at or below R_int.
            r1_obs = fa.get("r1_from_file_fo2_gt_2sig")
            lc = out.get("laue_consistency") or {}
            r_int = lc.get("r_int_current_laue")
            if (r1_obs is not None and r_int is not None and r_int > 0.005
                    and r1_obs > 0.05 and r1_obs > 1.3 * r_int):
                out["r1_vs_rint"] = {"r1_obs": r1_obs,
                                     "r_int": r_int,
                                     "ratio": round(r1_obs / r_int, 2)}
                hints.append(
                    f"R1(obs) {r1_obs:.3f} is {r1_obs / r_int:.1f}x R_int "
                    f"{r_int:.3f} - higher than the data quality predicts. "
                    f"With clean data this pairing suggests a data pathology "
                    f"(twinning, modulation, wrong symmetry) or a badly "
                    f"incomplete model rather than noise; if no twin law is "
                    f"found and frames are unavailable, recollecting a "
                    f"better crystal is a legitimate resolution.")
            if fa.get("groups_with_nonconstant_fc2"):
                hints.append(
                    f"fcf: {fa['groups_with_nonconstant_fc2']} hkl groups "
                    f"have non-constant Fc^2 (max span "
                    f"{fa.get('max_fc2_span')}) - that fcf encodes a "
                    f"TWIN/HKLF5 observation model; its R1 "
                    f"({fa.get('r1_from_file_fo2_gt_2sig')}) is not "
                    f"reachable from merged HKLF4 data.")
            ch = (fa.get("misfit_outliers") or {}).get("cluster_hint")
            if ch:
                hints.append("fcf: " + ch)

        if twin_signs:
            out["twin_alarm"] = {"signs": twin_signs}
            hints.append(
                "twin warning signs present (" + ", ".join(twin_signs) +
                ") - read skill 'framework-twin-pseudosymmetry-alarm' "
                "(read_skill) before spending cycles on the model.")
        out["hints"] = hints or ["no twin / symmetry symptoms from these "
                                 "checks - look at the model side instead"]
        return ToolResult(ok=True, summary=out)


# ==========================================================================
# screen_space_groups: absence/E-statistics table on session data
# ==========================================================================

#: Laue-class shorthand -> representative space group whose derived Laue
#: group (in the standard setting) defines the class. Trigonal has two
#: inequivalent classes (-3m1 vs -31m) - the caller must know which axes
#: convention the cell follows.
_LAUE_SHORTHAND = {
    "-1": "P -1",
    "2/m": "P 1 2/m 1",
    "mmm": "P m m m",
    "4/m": "P 4/m",
    "4/mmm": "P 4/m m m",
    "-3": "P -3",
    "-3m1": "P -3 m 1", "-3m": "P -3 m 1", "-31m": "P -3 1 m",
    "6/m": "P 6/m",
    "6/mmm": "P 6/m m m",
    "m-3": "P m -3", "m3": "P m -3",
    "m-3m": "P m -3 m", "m3m": "P m -3 m",
}


def _solver_evidence(project) -> dict[str, Any] | None:
    """The newest SHELXT job's ranked space groups, read from its job.lxt.

    A solver verdict is one of the three independent space-group evidence
    chains (SHELXT works from PHASE relationships and does not use
    systematic absences at all), so a disagreement with the absence table
    or with the E-statistics is real information - and it is nowhere in
    the session state, which is why the screen used to be blind to a
    solution the same project had already produced. Best-effort: any
    problem here silently means 'no solver channel'."""
    if project is None or getattr(project, "dir", None) is None:
        return None
    base = project.dir / ".crystalpilot" / "refine" / "shelxt"
    jobs = sorted(base.glob("job_*/job.lxt")) if base.exists() else []
    if not jobs:
        return None
    lxt = jobs[-1]
    try:
        from cctbx import sgtbx
        sols: list[dict[str, Any]] = []
        in_table = False
        for line in lxt.read_text(encoding="utf-8",
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
            sym = (t[fidx - 2]
                   if t[fidx - 1].replace(".", "", 1).lstrip("-").isdigit()
                   else t[fidx - 1])
            row: dict[str, Any] = {"space_group": sym, "r1": nums[0],
                                   "rweak": nums[1], "alpha": nums[2],
                                   "sys_abs": nums[3]}
            try:
                g = sgtbx.space_group_info(sym.replace("(", "")
                                           .replace(")", "")).group()
                row["number"] = int(g.type().number())
                row["is_centric"] = bool(g.is_centric())
            except Exception:  # noqa: BLE001 - SHELXT prints P2(1)/c forms
                pass
            sols.append(row)
        if not sols:
            return None
        return {"engine": "SHELXT", "source": str(lxt),
                "solutions": sols[:8], "best": sols[0],
                "note": ("SHELXT ranks by CFOM from the P1 phases and "
                         "never uses systematic absences; its alpha is "
                         "its own centrosymmetry indicator (below ~0.3 "
                         "argues centrosymmetric).")}
    except Exception:  # noqa: BLE001 - descriptive channel only
        return None


def _session_evidence(project, ses) -> dict[str, Any]:
    """Evidence channels the screen can disagree with (see
    sg_screen.candidate_conflicts). Descriptive only - none of this
    changes the candidate ranking."""
    ev: dict[str, Any] = {}
    model = getattr(ses, "model", None)
    if model is not None and model.scatterers().size():
        ev["model"] = model
    sym = getattr(ses, "symmetry", None)
    if sym is not None:
        try:
            ev["working_space_group"] = str(sym.space_group_info())
            ev["working_laue_order"] = int(
                sym.space_group().build_derived_laue_group().order_z())
        except Exception:  # noqa: BLE001
            pass
    solver = _solver_evidence(project)
    if solver:
        ev["solver"] = solver
    return ev


def _resolve_laue(symbol: str):
    """sgtbx space group for a Laue-class shorthand or any SG symbol."""
    from cctbx import sgtbx

    sym = _LAUE_SHORTHAND.get(symbol.strip().lower().replace(" ", ""),
                              None) or symbol
    return sgtbx.space_group_info(sym).group().build_derived_laue_group()


class ScreenSpaceGroups(_ProjectTool):
    name = "screen_space_groups"
    description = (
        "Rank candidate space groups against the session's UNMERGED "
        "reflection data by systematic-absence classes + centric/acentric "
        "E-statistics - the same table scale_and_export prints for the "
        "frames route, now available for vendor-hkl projects (works on an "
        "atomless session right after ingest_vendor_data). Candidates are "
        "every tabulated space group in the chosen Laue class compatible "
        "with the cell; a group is 'consistent' when its extinct classes "
        "carry only noise. Default Laue class comes from the LATTICE METRIC "
        "(3 deg tolerance), which can exceed the true symmetry - metric "
        "pseudo-symmetry is exactly the pseudo-merohedral-twin "
        "precondition, so treat the table as evidence, not a verdict; "
        "cross-check with audit_reflection_data. Each candidate also "
        "carries `conflicts`: disagreements between the evidence channels "
        "(absences vs the |E^2-1| hint vs a SHELXT verdict already in the "
        "project vs the Laue class). Conflicts are DESCRIPTIVE - they "
        "never reorder the table and add no supergroup prior - because a "
        "contradiction between channels is usually a wrong cell or "
        "incomplete data, not a group to pick by majority. Cell axes must "
        "follow the "
        "conventional setting for the class (candidates are tabulated "
        "settings). Read-only; adopt the decided group via "
        "change_space_group - with atoms it verifies the added operations, "
        "on an atomless session an explicit space_group= DECLARES it "
        "(data re-merged, solvers emit it, start model rewritten).")
    params_schema = {
        "type": "object",
        "properties": {
            "laue_group": {
                "type": "string",
                "description": "Laue class to screen within, e.g. 'mmm', "
                               "'2/m', '4/mmm', '-3m1', '-31m', 'm-3m' - or "
                               "any space-group symbol whose Laue class is "
                               "taken. Default: derived from the lattice "
                               "metric (disclosed in the summary)."},
            "viol_sigma": {
                "type": "number", "default": 3.0,
                "description": "I/sigma above which an observation in an "
                               "extinct class counts as a violation"},
            "max_out": {"type": "integer", "default": 10,
                        "description": "max candidates listed"},
            "merge_stats": {
                "type": "boolean", "default": False,
                "description": "also merge the data in the Laue class(es) "
                               "screened and report R_int / R_sigma / "
                               "unique / completeness / <I/sigma> - the "
                               "numbers XPREP prints per group. R_int "
                               "depends on the Laue class only: candidates "
                               "within one class differ by their absence "
                               "violations, not by R_int"},
            "d_min": {
                "type": ["number", "null"],
                "description": "resolution cutoff (A) for the screen. "
                               "Default: the session cutoff from "
                               "set_resolution_limit when one is set, else "
                               "the full data. Noise shells dominate the "
                               "absence counts on weak data (pa2 hex: "
                               "180k of 338k observations lay beyond the "
                               "1.0 A cutoff the agent had just set, and "
                               "the screen ignored it); pass null to force "
                               "the full range."},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        import re as _re

        from cctbx import sgtbx

        from .sg_screen import screen_space_groups

        p = self.project
        ses = ctx.session or p.session
        if ses is None or ses.dataset is None:
            return ToolResult(ok=False, summary={},
                              error="no dataset loaded in this project")
        raw = ses.dataset.intensities
        if raw is None:
            return ToolResult(ok=False, summary={},
                              error="session dataset has no intensities")
        raw = raw.set_observation_type_xray_intensity()
        d_min = params.get("d_min")
        res_source = "explicit d_min" if d_min else "full data range"
        if "d_min" not in params:
            for card in (getattr(ses, "flags", None) or {}).get(
                    "data_cards") or []:
                m = _re.match(r"^\s*SHEL\s+\S+\s+([\d.]+)", str(card), _re.I)
                if m:
                    d_min = float(m.group(1))
                    res_source = ("session resolution limit "
                                  "(set_resolution_limit)")
        n_before = raw.size()
        if d_min:
            raw = raw.resolution_filter(d_min=float(d_min))
        res_info = {"d_min_applied": float(d_min) if d_min else None,
                    "resolution_source": res_source,
                    "n_obs_screened": int(raw.size()),
                    "n_obs_total": int(n_before)}
        viol = float(params.get("viol_sigma") or 3.0)
        max_out = int(params.get("max_out") or 10)
        want_merge = bool(params.get("merge_stats"))
        working = None
        if ses.symmetry is not None:
            working = str(ses.symmetry.space_group_info())

        evidence = _session_evidence(p, ses)

        laue_param = params.get("laue_group")
        if laue_param and str(laue_param).strip().lower() == "all":
            # every Laue subgroup of the lattice metric in one call: the
            # hex runs called this tool 5-8 times (-3, -3m1, -31m, 6/m,
            # 6/mmm ...) because laue_group took a single value
            r = self._screen_all(raw, viol, max_out, want_merge, working,
                                 evidence)
            if r.ok:
                r.summary.update(res_info)
            return r
        if laue_param:
            try:
                laue = _resolve_laue(str(laue_param))
            except RuntimeError as e:
                return ToolResult(ok=False, summary={}, error=(
                    f"unrecognized laue_group {laue_param!r}: {e}. Accepted "
                    f"shorthands: {sorted(set(_LAUE_SHORTHAND))}, 'all', or "
                    f"any space-group symbol."))
            laue_source = f"explicit ({laue_param})"
        else:
            # metric lattice symmetry in the SAME basis as the data - the
            # widest defensible screen; may exceed the true Laue class
            from cctbx.sgtbx import lattice_symmetry
            laue = lattice_symmetry.group(
                raw.unit_cell(), max_delta=3.0).build_derived_laue_group()
            laue_source = "lattice metric (max_delta=3 deg)"

        if want_merge:
            merge = _laue_merge_stats(raw, laue)     # asked for: may raise
        else:
            try:      # computed anyway: R_int is the Laue conflict channel
                merge = _laue_merge_stats(raw, laue)
            except Exception:  # noqa: BLE001 - conflicts are descriptive
                merge = None
        if merge and (merge.get("multiplicity") or 0) > 1.1:
            evidence["laue_r_int"] = merge.get("r_int")
        res = screen_space_groups(raw, laue, viol_sigma=viol,
                                  max_out=max_out, evidence=evidence)
        res["laue_class_used"] = str(
            sgtbx.space_group_info(group=laue).type().lookup_symbol())
        res["laue_source"] = laue_source
        res.update(res_info)
        if want_merge:
            res["merge"] = merge
        if evidence.get("solver"):
            res["solver_evidence"] = evidence["solver"]
        res["working_space_group"] = working
        if not laue_param and working not in (None, "P 1", "P -1"):
            res.setdefault("note", "")
            res["note"] += (
                " NB: screened in the METRIC Laue class, which may be "
                "higher than the working symmetry - pass laue_group to "
                "restrict, or laue_group='all' for every metric subgroup.")
        return ToolResult(ok=True, summary=res)

    def _screen_all(self, raw, viol: float, max_out: int, want_merge: bool,
                    working: str | None,
                    evidence: dict[str, Any] | None = None) -> ToolResult:
        from cctbx import sgtbx

        from ..tools.sg_determination import (choose_laue_group,
                                              laue_group_scan)
        from .sg_screen import screen_space_groups

        scan = laue_group_scan(raw, max_delta=3.0)
        if not scan:
            return ToolResult(ok=False, summary={},
                              error="lattice-symmetry scan returned no "
                                    "Laue subgroups")
        chosen, threshold = choose_laue_group(scan)
        laue_rows: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        per_class: dict[str, Any] = {}
        n_screened = 0
        for d in scan[:12]:
            cb = d["cb_op_inp_best"]
            same_basis = cb.is_identity_op()
            row = {
                "laue_group": d["laue_group"],
                "order": int(d["order"]),
                "r_int": round(float(d["r_int"]), 4),
                "n_unique": int(d["n_unique"]),
                "multiplicity": round(float(d["multiplicity"]), 2),
                "max_angular_difference_deg": round(
                    float(d["max_angular_difference"]), 3),
                "accepted_by_r_int": bool(d.get("accepted")),
                "same_basis_as_data": same_basis,
            }
            if not same_basis:
                row["cb_op_to_that_setting"] = str(cb.as_hkl())
                row["cell_in_that_setting"] = [round(float(x), 4)
                                               for x in d["cell"]]
                row["note"] = ("this Laue class needs a reindexed cell; "
                               "screen its absences after change_of_basis "
                               "(the candidates below cover the classes "
                               "in the data's own basis)")
            laue_rows.append(row)
            if not same_basis:
                continue
            laue = d["laue_symmetry"].space_group()
            try:
                # this class's own R_int is the Laue channel of its
                # candidates' conflicts (the scan already measured it)
                ev = dict(evidence or {})
                ev["laue_r_int"] = row["r_int"]
                one = screen_space_groups(raw, laue, viol_sigma=viol,
                                          max_out=max_out, evidence=ev)
            except Exception as e:  # noqa: BLE001 - one class must not sink the table
                row["screen_error"] = f"{type(e).__name__}: {e}"
                continue
            n_screened += 1
            cls = str(sgtbx.space_group_info(group=laue).type()
                      .lookup_symbol())
            row["laue_class"] = cls
            row["n_consistent"] = sum(1 for c in one["candidates"]
                                      if c.get("consistent"))
            row["n_undecidable"] = sum(
                1 for c in one["candidates"]
                if c.get("absence_evidence") in ("undecidable",
                                                  "absence_classes_unobserved"))
            if one.get("e_statistics"):
                row["e_statistics"] = one["e_statistics"]
            if one.get("absence_screening_power"):
                row["absence_screening_power"] = one["absence_screening_power"]
            if want_merge:
                row["merge"] = _laue_merge_stats(raw, laue)
            per_class[cls] = row
            for c in one["candidates"]:
                c = dict(c)
                c["laue_class"] = cls
                c["laue_r_int"] = row["r_int"]
                candidates.append(c)
        from .sg_screen import absence_rank_key
        candidates.sort(key=lambda c: absence_rank_key(c)[:2]
                        + (c.get("laue_r_int", 9.0), c["space_group"]))
        n_und = sum(1 for c in candidates
                    if c.get("absence_evidence") in ("undecidable",
                                                      "absence_classes_unobserved"))
        return ToolResult(ok=True, summary={
            "laue_source": "scan of every Laue subgroup of the lattice "
                           "metric (max_delta=3 deg), merged one by one",
            "laue_scan": laue_rows,
            "laue_r_int_threshold": round(float(threshold), 4),
            "laue_suggested_by_r_int": chosen["laue_group"],
            "n_laue_classes_screened": n_screened,
            "candidates": candidates[:max(max_out, 10) * 2],
            "n_candidates_total": len(candidates),
            "n_undecidable": n_und,
            "working_space_group": working,
            "note": ("one row per Laue class with its R_int (XPREP-style: "
                     "the highest-order class whose R_int stays within "
                     "the threshold of the P-1 value is suggested); the "
                     "candidate table pools every class screened in the "
                     "data's basis, tagged laue_class, ranked by "
                     "absence_evidence - 'absent'/'no_absence_conditions' "
                     "first (more absences explained = earlier), then "
                     "'undecidable' (absent and present classes look "
                     "alike) and 'absence_classes_unobserved' (this class "
                     "carries zero of this file's reflections - typical "
                     "of merged/fcf-derived data) together: neither is "
                     "support for the group, and for a centred lattice a "
                     "declaration would discard those observations from "
                     "every later refinement (see each class's "
                     "absence_screening_power for whether this file can "
                     "distinguish candidates by absences at all), then "
                     "'violated'; lower R_int breaks ties. R_int always "
                     "falls in a lower class (fewer equivalents merged) - "
                     "it is not evidence for the lower class. Metric "
                     "pseudo-symmetry and twinning both make a too-high "
                     "class look acceptable: cross-check with "
                     "audit_reflection_data before declaring."),
        })


def _laue_merge_stats(raw, laue) -> dict[str, Any]:
    """Merge the unmerged data in one Laue class: the per-group numbers
    XPREP prints. Completeness is judged after folding the centring the
    DATA carry (vendor exports omit lattice-absent rows, so a primitive
    expectation halves it - r22 live)."""
    from cctbx import crystal, sgtbx
    from cctbx.array_family import flex

    g = sgtbx.space_group(laue)
    centring, trs = _centring_from_indices(raw.indices())
    for t in trs:
        g.expand_ltr(sgtbx.tr_vec(t))
    cs = crystal.symmetry(unit_cell=raw.unit_cell(), space_group=g,
                          assert_is_compatible_unit_cell=False)
    data = raw.customized_copy(crystal_symmetry=cs,
                               anomalous_flag=False).map_to_asu()
    me = data.merge_equivalents()
    merged = me.array()
    out: dict[str, Any] = {
        "laue_class": str(sgtbx.space_group_info(group=laue).type()
                          .lookup_symbol()),
        "centring_assumed": centring,
        "n_obs": int(data.size()),
        "n_unique": int(merged.size()),
        "multiplicity": round(data.size() / max(1, merged.size()), 2),
        "r_int": round(float(me.r_int()), 4),
        "r_sigma": round(float(me.r_sigma()), 4),
        "d_min": round(float(merged.d_min()), 3) if merged.size() else None,
    }
    try:
        out["completeness"] = round(float(merged.completeness()), 3)
    except Exception:  # noqa: BLE001 - completeness needs a sane cell/group
        pass
    if merged.size() and merged.sigmas() is not None:
        s = merged.sigmas().deep_copy()
        s.set_selected(s <= 0, 1e-9)
        out["mean_i_over_sigma"] = round(float(flex.mean(merged.data() / s)),
                                         2)
    return out


def _centring_from_indices(indices) -> tuple[str, list[tuple[int, int, int]]]:
    """Lattice centring implied by which index classes the file CONTAINS:
    a class that is essentially unmeasured (< 2% of its complement) is
    absent from the export, i.e. the vendor already applied the centring.
    Returns (letter, translation vectors /12)."""
    from ..tools.sg_determination import _CENTERING_TESTS, _CENTERING_VECTORS
    n = indices.size()
    if n == 0:
        return "P", []
    hs = list(indices)
    present: list[str] = []
    for name in ("A", "B", "C", "I", "R_obv"):
        test = _CENTERING_TESTS[name]
        n_class = sum(1 for h in hs if test(h))
        if n_class < 0.02 * max(1, n - n_class):
            present.append(name)
    if {"A", "B", "C"} <= set(present):
        return "F", list(_CENTERING_VECTORS["F"])
    for name in ("I", "A", "B", "C", "R_obv"):
        if name in present:
            return name.replace("_obv", ""), list(_CENTERING_VECTORS[name])
    return "P", []


class ReflectionStatistics(_ProjectTool):
    name = "reflection_statistics"
    description = (
        "Intensity statistics of the session's UNMERGED data in one call, "
        "the numbers agents otherwise script by hand: merging table by "
        "resolution shell in a Laue class (n / unique / completeness / "
        "multiplicity / R_int / R_meas / <I/sigma> / CC1/2), normalized-"
        "intensity statistics (<|E^2-1|> overall AND per resolution "
        "shell, N(z) distribution, fraction E>2) against the centric/"
        "acentric references, the classical moments <I^2>/<I>^2 and "
        "<F>^2/<F^2> plus the Padilla & Yeates L-test - each with a "
        "DIRECTIONAL one-sided verdict (below the acentric reference "
        "argues for twinning; above the centric one for a "
        "pseudo-translation, and only with an independent signature) - "
        "and hint_valid: the five documented conditions under which the "
        "centric/acentric hint must not be read, evaluated against THIS "
        "composition and THESE data, index-parity "
        "classes (mean intensity of odd vs even h, k, l, sums, thirds) as "
        "pseudo-translation / supercell / centring evidence, the centring "
        "the file itself implies, Friedel-pair differences when the data "
        "are anomalous, and a Wilson estimate (B, scale) when a model "
        "supplies the composition. laue_group='all' adds the Laue-group "
        "scan (R_int under every metric Laue subgroup). pa1: 7 runs wrote "
        "their own cctbx E-statistics / parity scripts (12 crashes) for "
        "exactly these. Read-only; absence-based space-group ranking is "
        "screen_space_groups.")
    params_schema = {
        "type": "object",
        "properties": {
            "laue_group": {
                "type": "string",
                "description": "Laue class for merging / E-statistics "
                               "('mmm', '2/m', '-3m1', a space-group "
                               "symbol, or 'all' to add the scan). Default: "
                               "the working symmetry's class, or the "
                               "lattice metric while the working group is "
                               "triclinic"},
            "n_shells": {"type": "integer", "default": 12},
            "d_min": {"type": "number",
                      "description": "optional resolution cutoff (A) "
                                     "applied before every statistic"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        import math

        from cctbx import crystal, sgtbx
        from cctbx.array_family import flex

        from ..tools.sg_determination import _normalized_intensities
        from .sg_screen import (e2m1_by_shell, e2m1_hint,
                                e2m1_hint_validity, e2m1_statistic,
                                intensity_moments, l_test, weak_index_class)

        p = self.project
        ses = ctx.session or (p.session if p is not None else None)
        if ses is None or getattr(ses, "dataset", None) is None:
            return ToolResult(ok=False, summary={},
                              error="no dataset loaded in this project")
        raw = ses.dataset.intensities
        if raw is None:
            return ToolResult(ok=False, summary={},
                              error="session dataset has no intensities")
        raw = raw.set_observation_type_xray_intensity()
        d_cut = params.get("d_min")
        if d_cut:
            raw = raw.resolution_filter(d_min=float(d_cut))
        n_shells = max(3, int(params.get("n_shells") or 12))
        out: dict[str, Any] = {"n_obs": int(raw.size()),
                               "cell": [round(float(x), 4)
                                        for x in raw.unit_cell().parameters()]}
        if d_cut:
            out["d_min_applied"] = float(d_cut)

        # -- Laue class -----------------------------------------------------
        laue_param = params.get("laue_group")
        want_all = bool(laue_param) and str(laue_param).strip().lower() == "all"
        laue = None
        if laue_param and not want_all:
            try:
                laue = _resolve_laue(str(laue_param))
            except RuntimeError as e:
                return ToolResult(ok=False, summary={}, error=(
                    f"unrecognized laue_group {laue_param!r}: {e}. Accepted "
                    f"shorthands: {sorted(set(_LAUE_SHORTHAND))}, 'all', or "
                    f"any space-group symbol."))
            laue_source = f"explicit ({laue_param})"
        else:
            sym = getattr(ses, "symmetry", None)
            sg = sym.space_group() if sym is not None else raw.space_group()
            laue = sg.build_derived_laue_group()
            laue_source = "working symmetry"
            if laue.order_z() <= 2:
                from cctbx.sgtbx import lattice_symmetry
                metric = lattice_symmetry.group(
                    raw.unit_cell(), max_delta=3.0).build_derived_laue_group()
                if metric.order_z() > laue.order_z():
                    laue = metric
                    laue_source = ("lattice metric (working symmetry is "
                                   "triclinic/undecided)")
        out["laue_class"] = str(sgtbx.space_group_info(group=laue).type()
                                .lookup_symbol())
        out["laue_source"] = laue_source

        # -- merging in that class -----------------------------------------
        merge = _laue_merge_stats(raw, laue)
        out["merge"] = merge
        g = sgtbx.space_group(laue)
        for t in _centring_from_indices(raw.indices())[1]:
            g.expand_ltr(sgtbx.tr_vec(t))
        cs = crystal.symmetry(unit_cell=raw.unit_cell(), space_group=g,
                              assert_is_compatible_unit_cell=False)
        data = raw.customized_copy(crystal_symmetry=cs, anomalous_flag=False)
        out["shells"], out["merge_overall"] = _merging_shells(data, n_shells)

        # -- normalized intensities ----------------------------------------
        merged = data.map_to_asu().merge_equivalents().array()
        from .sg_screen import E2M1_REFERENCE
        e_stats: dict[str, Any] = {
            "reference": {
                "centrosymmetric": {
                    "mean_abs_e2_minus_1":
                        E2M1_REFERENCE["centrosymmetric"],
                    "fraction_e_gt_2": 0.046},
                "non_centrosymmetric": {
                    "mean_abs_e2_minus_1":
                        E2M1_REFERENCE["non_centrosymmetric"],
                    "fraction_e_gt_2": 0.018}}}
        try:
            e2m1 = float(e2m1_statistic(raw, laue))
            e_stats["mean_abs_e2_minus_1"] = round(e2m1, 3)
            e_stats["hint"] = e2m1_hint(e2m1)
        except Exception as e:  # noqa: BLE001 - say why, do not vanish
            e_stats["mean_abs_e2_minus_1_error"] = f"{type(e).__name__}: {e}"
        try:
            z, _sz, shell_of, shell_isig = _normalized_intensities(merged)
            good = [zi for zi, s in zip(z, shell_of) if shell_isig[s] >= 1.5]
            if len(good) < 50:
                good = list(z)
            n = max(1, len(good))
            nz = {}
            for zz in (0.1, 0.2, 0.4, 0.6, 0.8, 1.0):
                nz[str(zz)] = {
                    "observed": round(sum(1 for v in good if v <= zz) / n, 3),
                    "centric": round(math.erf(math.sqrt(zz / 2.0)), 3),
                    "acentric": round(1.0 - math.exp(-zz), 3)}
            e_stats["n_z"] = nz
            e_stats["fraction_e_gt_2"] = round(
                sum(1 for v in good if v > 4.0) / n, 4)
            e_stats["n_reflections_used"] = len(good)
            e_stats["note"] = ("N(z) = fraction of unique reflections with "
                               "E^2 <= z; centric data sit ABOVE the "
                               "acentric curve at small z (more weak "
                               "reflections). Pseudo-symmetry, twinning "
                               "and disorder pull the statistics toward "
                               "hyper-centric or toward uniform; read "
                               "with audit_reflection_data")
        except Exception as e:  # noqa: BLE001
            e_stats["n_z_error"] = f"{type(e).__name__}: {e}"

        # -- resolution shells, moments, L-test, hint validity --------------
        # One overall <|E^2-1|> hides the three pictures SADABS reads off
        # the CURVE (uniformly low = twinning, uniformly high =
        # pseudo-translation, drifting with resolution = data reduction),
        # and it cannot separate twinning from a pseudo-translation at all
        # - the moments' SIGN can (Xtriage), and the L-test survives the
        # anisotropy and pseudo-centring that contaminate both.
        readings: list[dict[str, Any]] = []
        weak = None
        try:
            weak = weak_index_class(raw)
        except Exception:  # noqa: BLE001 - advisory
            weak = None
        corrob = ([f"index class '{weak['class']}' carries "
                   f"{weak['mean_i_ratio']:.2f} of the average intensity "
                   f"over {weak['n']} reflections"] if weak else None)
        try:
            shelled = e2m1_by_shell(raw, laue, n_shells=n_shells,
                                    corroboration=corrob)
            e_stats["by_shell"] = shelled
            readings.append(shelled["reading"])
        except Exception as e:  # noqa: BLE001
            e_stats["by_shell_error"] = f"{type(e).__name__}: {e}"
        try:
            moments = intensity_moments(raw, laue, corroboration=corrob)
            readings += [moments[k] for k in
                         ("i2_over_i_sq", "f_sq_over_f2") if k in moments]
            # <|E^2-1|> is the third classical moment, but the shelled
            # block above already reports it with more context - one
            # reading per statistic, not two
            moments.pop("mean_abs_e2_minus_1", None)
            moments["mean_abs_e2_minus_1_note"] = (
                "the third classical moment is reported under "
                "e_statistics.by_shell (shell by shell, with its reading)")
            out["intensity_moments"] = moments
        except Exception as e:  # noqa: BLE001
            out["intensity_moments"] = {"error": f"{type(e).__name__}: {e}"}
        try:
            lt = l_test(raw, laue, corroboration=corrob)
            out["l_test"] = lt
            readings += [lt[k] for k in ("mean_abs_l", "mean_l_sq")
                         if k in lt]
        except Exception as e:  # noqa: BLE001
            out["l_test"] = {"error": f"{type(e).__name__}: {e}"}
        try:
            d_min_data = float(raw.d_max_min()[1])
        except Exception:  # noqa: BLE001
            d_min_data = None
        try:
            se = (e_stats.get("by_shell") or {}).get(
                "reading", {}).get("standard_error")
            validity = e2m1_hint_validity(
                model=getattr(ses, "model", None),
                n_reflections=int(merged.size()), d_min=d_min_data,
                e2m1_standard_error=se, readings=readings,
                weak_class=weak, hint=e_stats.get("hint"))
            e_stats["hint_valid"] = validity["hint_valid"]
            e_stats["hint_validity"] = validity
        except Exception as e:  # noqa: BLE001
            e_stats["hint_validity_error"] = f"{type(e).__name__}: {e}"
        out["e_statistics"] = e_stats

        # -- parity classes (pseudo-translation / supercell / centring) -----
        out["parity_classes"] = _parity_classes(raw)
        if weak:
            out["weak_index_class"] = weak
        centring, _ = _centring_from_indices(raw.indices())
        out["centring_implied_by_file"] = centring

        # -- Friedel pairs -------------------------------------------------
        try:
            anom = raw.customized_copy(crystal_symmetry=cs,
                                       anomalous_flag=True).map_to_asu()
            am = anom.merge_equivalents().array()
            diffs = am.anomalous_differences()
            if diffs.size() >= 10 and diffs.sigmas() is not None:
                s = diffs.sigmas().deep_copy()
                s.set_selected(s <= 0, 1e-9)
                dos = flex.abs(diffs.data()) / s
                out["friedel"] = {
                    "n_pairs": int(diffs.size()),
                    "mean_abs_delta_over_sigma": round(float(flex.mean(dos)),
                                                       3),
                    "fraction_delta_gt_3sigma": round(
                        float((dos > 3.0).count(True)) / diffs.size(), 4),
                    "note": ("<|I+ - I-|/sigma> near 0.8 = no anomalous "
                             "signal beyond noise; clearly above 1 with a "
                             "> 3-sigma fraction well over 1% = usable "
                             "anomalous signal (absolute structure, "
                             "element identity)")}
            else:
                out["friedel"] = None
        except Exception as e:  # noqa: BLE001
            out["friedel"] = {"error": f"{type(e).__name__}: {e}"}

        # -- Wilson (needs a composition) ----------------------------------
        model = getattr(ses, "model", None)
        if model is not None and model.scatterers().size():
            try:
                out["wilson"] = _wilson_estimate(merged, model)
            except Exception as e:  # noqa: BLE001
                out["wilson"] = {"error": f"{type(e).__name__}: {e}"}
        else:
            out["wilson"] = {"skipped": "no model/composition in the "
                                        "session; the shell table's mean "
                                        "intensities are the Wilson-plot "
                                        "ordinates"}

        # -- optional Laue scan --------------------------------------------
        if want_all:
            from ..tools.sg_determination import (choose_laue_group,
                                                  laue_group_scan)
            scan = laue_group_scan(raw, max_delta=3.0)
            chosen, threshold = choose_laue_group(scan)
            out["laue_scan"] = [{
                "laue_group": d["laue_group"], "order": int(d["order"]),
                "r_int": round(float(d["r_int"]), 4),
                "n_unique": int(d["n_unique"]),
                "multiplicity": round(float(d["multiplicity"]), 2),
                "accepted_by_r_int": bool(d.get("accepted")),
                "same_basis_as_data": d["cb_op_inp_best"].is_identity_op(),
            } for d in scan[:12]]
            out["laue_suggested_by_r_int"] = chosen["laue_group"]
            out["laue_r_int_threshold"] = round(float(threshold), 4)
        return ToolResult(ok=True, summary=out)


def _merging_shells(data, n_bins: int) -> tuple[list[dict[str, Any]],
                                                dict[str, Any]]:
    """Resolution-shell merging table via iotbx.merging_statistics, with
    the reduced completeness + I/sigma table when that refuses (already-
    merged input)."""
    rows: list[dict[str, Any]] = []
    overall: dict[str, Any] = {}
    try:
        from iotbx import merging_statistics
        try:
            st = merging_statistics.dataset_statistics(
                i_obs=data, n_bins=n_bins, sigma_filtering=None)
        except TypeError:       # older signature without the kwarg
            st = merging_statistics.dataset_statistics(i_obs=data,
                                                       n_bins=n_bins)

        def _row(b) -> dict[str, Any]:
            return {
                "d_max": round(b.d_max, 3), "d_min": round(b.d_min, 3),
                "n_obs": int(b.n_obs), "n_unique": int(b.n_uniq),
                "multiplicity": round(b.mean_redundancy, 2),
                "completeness": round(b.completeness, 3),
                "i_over_sigma": round(b.i_over_sigma_mean, 2),
                "r_merge": round(b.r_merge, 4),
                "r_meas": round(b.r_meas, 4),
                "cc_one_half": round(b.cc_one_half, 3),
            }
        rows = [_row(b) for b in st.bins]
        overall = _row(st.overall)
    except Exception as e:  # noqa: BLE001 - degrade, don't refuse
        from cctbx.array_family import flex
        merged = data.map_to_asu().merge_equivalents().array()
        merged.setup_binner(n_bins=n_bins)
        comp = merged.completeness(use_binning=True)
        binner = merged.binner()
        for i_bin in binner.range_used():
            frac = comp.data[i_bin]
            sel = binner.selection(i_bin)
            mi = merged.select(sel)
            ios = None
            if mi.size() and mi.sigmas() is not None:
                s = mi.sigmas().deep_copy()
                s.set_selected(s <= 0, 1e-9)
                ios = round(float(flex.mean(mi.data() / s)), 2)
            d_max, d_min = binner.bin_d_range(i_bin)
            rows.append({"d_max": round(d_max, 3), "d_min": round(d_min, 3),
                         "n_unique": mi.size(),
                         "completeness": round(float(frac or 0.0), 3),
                         "i_over_sigma": ios})
        overall = {"note": f"merging_statistics unavailable ({e}); reduced "
                           f"table (no CC1/2 / R_merge)"}
    return rows, overall


def _parity_classes(raw) -> list[dict[str, Any]]:
    """Mean intensity of index classes relative to the whole set. A class
    near zero is a pseudo-translation / centring / doubled axis signal
    (cu-l2-r3 and cu-l3-r3 scripted exactly this by hand). The class
    definitions live in sg_screen.index_class_selections so this table and
    the pseudo-translation failure condition partition the reflections the
    same way."""
    from cctbx.array_family import flex

    from .sg_screen import index_class_selections
    idx = raw.indices()
    data = raw.data()
    if idx.size() == 0:
        return []
    mean_all = float(flex.mean(data)) or 1e-9
    rows = []
    for name, sel in index_class_selections(idx):
        n = sel.count(True)
        if n == 0:
            rows.append({"class": name, "n": 0, "mean_i_ratio": None,
                         "note": "class absent from the file (centring "
                                 "applied by the vendor, or an axis that "
                                 "should be halved)"})
            continue
        m = float(flex.mean(data.select(sel)))
        ratio = m / mean_all
        row = {"class": name, "n": int(n),
               "fraction_of_reflections": round(n / idx.size(), 3),
               "mean_i_ratio": round(ratio, 3)}
        if ratio < 0.10:
            row["note"] = ("systematically weak: pseudo-translation / "
                           "sublattice - the true cell may be smaller, or "
                           "a centring is missing from the declared group")
        rows.append(row)
    return rows


def _wilson_estimate(merged, model) -> dict[str, Any]:
    """ln(<I/eps>/sum f^2) vs sin^2(theta)/lambda^2 - slope -2B."""
    import math
    from cctbx.array_family import flex
    reg = model.scattering_type_registry(table="it1992")
    counts = reg.type_count_dict()
    merged.setup_binner(n_bins=min(10, max(3, merged.size() // 25)))
    binner = merged.binner()
    eps = merged.epsilons().data()
    xs, ys = [], []
    rows = []
    for i_bin in binner.range_used():
        sel = binner.selection(i_bin)
        mi = merged.select(sel)
        if mi.size() < 5:
            continue
        mean_i = float(flex.mean(mi.data() / eps.select(sel).as_double()))
        if mean_i <= 0:
            continue
        d_max, d_min = binner.bin_d_range(i_bin)
        dss = 0.5 * (1.0 / d_max ** 2 + 1.0 / d_min ** 2) if d_max else \
            1.0 / d_min ** 2
        s2 = dss / 4.0                       # sin^2(theta)/lambda^2
        f2 = sum(cnt * reg.gaussian(t).at_d_star_sq(dss) ** 2
                 for t, cnt in counts.items())
        y = math.log(mean_i / max(f2, 1e-9))
        xs.append(s2)
        ys.append(y)
        rows.append({"d_min": round(d_min, 3), "s2": round(s2, 4),
                     "ln_i_over_sum_f2": round(y, 3)})
    if len(xs) < 3:
        return {"skipped": "fewer than three usable shells"}
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / max(sxx, 1e-12)
    intercept = my - slope * mx
    return {"B_wilson": round(-slope / 2.0, 2),
            "scale_k": round(math.exp(intercept), 4),
            "n_shells": n, "points": rows,
            "note": "composition from the current model; a placeholder "
                    "or incomplete model biases K, much less B"}


# ==========================================================================
# assemble_asu: Olex2 "compaq" - reunite the asymmetric unit
# ==========================================================================

class AssembleAsu(_ProjectTool):
    name = "assemble_asu"
    description = (
        "Reassemble the asymmetric unit so every fragment is DIRECTLY bonded "
        "to the main fragment (Olex2 'compaq'). Atoms refined into a symmetry "
        "image of their bonded position look detached in every viewer even "
        "though the lattice is chemically identical; expert review flags this "
        "on delivery. Moves whole identity-bond fragments by the symmetry op "
        "that creates the most direct bonds (aniso ADPs rotated accordingly); "
        "truly lone fragments (solvent) are parked at the closest-contact "
        "image. No-op when the ASU is already coherent. Run before final "
        "refinement/export; diffraction math is invariant under the applied "
        "ops so R factors do not change.")
    params_schema = {"type": "object", "properties": {
        "dry_run": {"type": "boolean", "default": False,
                    "description": "report the plan without applying it"}}}

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from ..chem.asu_sanity import (apply_assembly_plan, asu_assembly_plan,
                                       asu_coherence)
        ses = ctx.session
        if ses is None or ses.model is None:
            return ToolResult.failure("no model loaded")
        before = asu_coherence(ses.model)
        plan = asu_assembly_plan(ses.model)
        if not plan:
            return ToolResult(ok=True, summary={
                "no_state_change": True,
                "note": "ASU already coherent - every fragment directly "
                        "bonded to the main fragment",
                "n_fragments": len(before["fragments"])})
        if params.get("dry_run"):
            return ToolResult(ok=True, summary={
                "no_state_change": True, "dry_run": True, "plan": plan,
                "n_detached_atoms": before["n_detached_atoms"]})
        new_xs, occupancy_rescaled = apply_assembly_plan(ses.model, plan)
        after = asu_coherence(new_xs)
        if after["n_detached_atoms"] >= before["n_detached_atoms"]:
            # nothing changed, so nothing failed (pa1 agents read the old
            # ok:false as a broken tool and retried it in loops)
            return ToolResult(ok=True, summary={
                "no_state_change": True,
                "note": "the assembly plan did not reduce detached atoms "
                        f"({before['n_detached_atoms']} -> "
                        f"{after['n_detached_atoms']}); model left "
                        "unchanged. Atoms that no symmetry image brings "
                        "into bonding distance are separate species "
                        "(guests, counter-ions) or misplaced atoms - "
                        "inspect them (get_geometry / inspect_map) rather "
                        "than re-running assemble_asu",
                "plan_tried": plan,
                "n_detached_atoms": before["n_detached_atoms"],
                "fragments": [f["n"] for f in before["fragments"]]})
        ses.model = new_xs
        # moving atoms invalidates riding-H geometry replay positions; the
        # metadata itself (carrier->H kinds) survives because H atoms moved
        # with their carriers under the same op
        return ToolResult(ok=True, summary={
            "applied": plan,
            "n_detached_atoms_before": before["n_detached_atoms"],
            "n_detached_atoms_after": after["n_detached_atoms"],
            "fragments_after": [f["n"] for f in after["fragments"]],
            **({"occupancy_rescaled": occupancy_rescaled}
               if occupancy_rescaled else {}),
            "ghost_suspects_remaining": after["ghost_suspects"],
            "n_atoms": ses.model.scatterers().size()})

# --------------------------------------------------------------------------
# r12 module split: symmetry and ingest tools live in their own modules now;
# re-exported here so existing imports keep working.
from .tools_symmetry import (ChangeSpaceGroup,            # noqa: E402,F401
                             CheckSymmetry, NcsAudit,
                             _direct_match_fraction,
                             _fit_translation_match, _match_targets)
from .tools_ingest import (ImportCifModel,                # noqa: E402,F401
                           SetExperiment, _cif_experiment_block)


class SwapReflectionData(_ProjectTool):
    name = "swap_reflection_data"
    description = (
        "Replace the project's reflection data (crystal.hkl) with another "
        "hkl file while KEEPING the current model - the twin workflow's "
        "second half: solve against the clean single-domain data, then "
        "swap in the HKLF5 twin file (export_twin_hklf5's twin5.hkl or a "
        "vendor TWINABS file) and refine with run_shelxl. The old file is "
        "backed up, the session dataset/merge is rebuilt under the current "
        "symmetry, and a stale solvent mask (sized to the old data) is "
        "cleared. HKLF5 note: in-process maps/statistics then run on the "
        "positive-batch composite view (approximate); least squares must "
        "go through run_shelxl (BASF refines the twin fractions). A "
        "'reason' is required and lands in the node record - data "
        "swapping is a disclosure-grade decision.")
    params_schema = {
        "type": "object",
        "properties": {
            "hkl": {"type": "string",
                    "description": "bare filename, looked up in the "
                                   "project dir then the frames workdir "
                                   "(e.g. twin5.hkl)"},
            "model_node": {"type": "string", "description": "Explicitly pair this model with supplied matching HKL; creates a new bound child, not a retroactive historical claim"},
            "reason": {"type": "string",
                       "description": "why the data are being swapped - "
                                      "recorded verbatim for the report"},
        },
        "required": ["hkl", "reason"],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        import shutil
        import time as _time

        p = self.project
        ses = ctx.session or p.session
        if ses is None:
            return ToolResult.failure(
                "no active session - swap only makes sense once a project "
                "has data + (usually) a model; ingest or create_start_model "
                "first")
        if ses.symmetry is None:
            return ToolResult.failure("session has no symmetry set")
        reason = str(params.get("reason") or "").strip()
        if not reason:
            return ToolResult.failure("a non-empty reason is required")
        name = str(params.get("hkl") or "").strip()
        if not name or "/" in name or "\\" in name or ".." in name:
            return ToolResult.failure("hkl must be a bare filename")
        cands = [p.dir / name,
                 p.dir / ".crystalpilot" / "frames" / name]
        src = next((c for c in cands if c.exists()), None)
        if src is None:
            return ToolResult.failure(
                f"{name} not found in the project dir or frames workdir")

        from .data_versions import input_directory, capture_source
        src = capture_source(p, src)
        from .tools_frames import hklf5_batch_count
        n_dom = hklf5_batch_count(src)
        hklf = 5 if n_dom >= 2 else 4

        dst = input_directory(p) / "crystal.hkl"
        backup = None
        previous_hkl = getattr(p, "hkl_path", None)
        previous_revision = getattr(ses, "_crystalpilot_data_revision", None)
        old_n = (ses.dataset.intensities.size()
                 if ses.dataset is not None and ses.dataset.intensities is not None else None)
        old_unique = ses.fo_sq.size() if ses.fo_sq is not None else None
        if ses.flags.get("data_binding_required") and not params.get("model_node"):
            return ToolResult.failure("Pass model_node explicitly to bind this legacy model to supplied matching HKL")
        if params.get("model_node"):
            target_node = p.nodes.resolve(params["model_node"])
            capture_source(p, p.nodes.node_dir(target_node) / "model.res")
            p._load_node(target_node, binding_hkl=src)
            ses = p.session

        from ..io.shelx import load_shelx_dataset
        from ..pipeline.session import SolveSession
        try:
            dataset = load_shelx_dataset(
                src,
                cell=ses.symmetry.unit_cell().parameters(),
                wavelength=(ses.dataset.wavelength
                            if ses.dataset is not None else None),
                space_group=ses.symmetry.space_group(),
                hklf_override=hklf)
            prepared = SolveSession(dataset=dataset)
            merge = prepared.set_symmetry(dataset.symmetry_hint)
        except Exception as e:  # noqa: BLE001 - unreadable file must be said
            return ToolResult.failure(
                f"cannot load {name} as SHELX reflection data: "
                f"{type(e).__name__}: {e}")
        import os
        import uuid
        from .nodes import atomic_write_json
        from .transactions import check_cancelled
        check_cancelled(getattr(ctx, "cancel_event", None))
        if not (dst.exists() and src.samefile(dst)):
            token = uuid.uuid4().hex
            staged = input_directory(p) / f".swap-{token}.hkl"
            if dst.exists():
                if getattr(p, "_input_stage", None) is not None:
                    backup = str(previous_hkl) if previous_hkl is not None else None
                else:
                    backup = f"crystal.swapped_{_time.strftime('%Y%m%d_%H%M%S')}_{token[:8]}.hkl"
                    shutil.copy2(dst, p.dir / backup)
            try:
                shutil.copy2(src, staged)
                check_cancelled(getattr(ctx, "cancel_event", None))
                os.replace(staged, dst)
            finally:
                staged.unlink(missing_ok=True)
        previous_context = getattr(p, "context", {})
        context = {**previous_context, "data": {**(previous_context.get("data") or {}),
                                               "hkl": "crystal.hkl"}}
        atomic_write_json(input_directory(p) / "context.json", context, indent=2)
        p.context = context
        p.hkl_path = dst
        if hasattr(p, "_data_cache"):
            p._data_cache.clear()
        ses.flags.pop("data_binding_required", None)
        ses.flags.pop("diff_map_peaks", None)
        ses.flags.pop("diff_map_peaks_meta", None)
        ses.cf_info = None
        ses.refinement_history.clear()
        ses.dataset = dataset
        ses.symmetry, ses.fo_sq = prepared.symmetry, prepared.fo_sq
        ses.merge_info = dict(merge)
        p.merge_stats = dict(merge)
        ses.flags["hklf"] = hklf
        basf_note = None
        if hklf == 5 and not ses.flags.get("twin"):
            # BASF without TWIN is the HKLF5 convention (the law lives in
            # the data); run_shelxl serializes these cards from the flags
            ses.flags["twin"] = {
                "matrix": None, "n": n_dom,
                "basf": [round(1.0 / n_dom, 5)] * (n_dom - 1)}
            basf_note = (f"BASF initialised at equal fractions for "
                         f"{n_dom} batches; SHELXL refines them")

        mask_note = None
        if ses.flags.pop("f_mask", None) is not None:
            mask_note = ("the stored solvent mask was sized to the OLD "
                         "reflection set and has been cleared - rerun "
                         "solvent_mask if masking is still wanted")
            for k in ("solvent_mask_info", "solvent_mask_params"):
                ses.flags.pop(k, None)

        summary: dict[str, Any] = {
            "swapped_to": name,
            "reason": reason,
            "model_node": params.get("model_node"),
            "binding_note": "Explicit supplied-data binding; not proof of an unknown historical pairing",
            "hklf": hklf,
            **({"n_domains": n_dom} if hklf == 5 else {}),
            "n_obs": dataset.intensities.size(),
            "merge": merge,
            "previous": {"n_obs": old_n, "n_unique": old_unique,
                         "data_revision": previous_revision, "backup": backup},
        }
        if hklf == 5:
            summary["hklf5_note"] = (
                "twin-batch data active: smtbx refine will refuse (by "
                "design); refine via run_shelxl - start.ins/job needs "
                "HKLF 5 + BASF (run_shelxl serializes from the session, "
                "so set BASF via its params or the model file). Maps and "
                "merge statistics run on the positive-batch composite "
                "view and are approximate near overlapped reflections.")
        if basf_note:
            summary["basf"] = basf_note
        if mask_note:
            summary["mask_cleared"] = mask_note
        return ToolResult(ok=True, summary=summary)


class ViewStructure(_ProjectTool):
    name = "view_structure"
    description = (
        "SEE the structure: render the current model as images (returned "
        "directly into your context - actually look at them). states: "
        "'asu' (the refined asymmetric unit, metal labels on), 'cell' "
        "(P1-expanded single cell - coordination closes, molecules "
        "complete), 'supercell' (2x2x2 packing - stacking, channels, "
        "voids, and wrong-symmetry pathologies like overlapping or "
        "isolated fragments become obvious). One state and one view can "
        "misrepresent a crystal - look at packing from more than one "
        "direction before drawing conclusions. Use this the way a human "
        "crystallographer uses the viewer: after solving (does the model "
        "look like chemistry or like noise?), before/after big model "
        "decisions (guest? disorder? symmetry doubts?), and before "
        "delivery. highlight= labels atoms of interest in red.")
    params_schema = {
        "type": "object",
        "properties": {
            "state": {"type": "string",
                      "enum": ["asu", "cell", "supercell"],
                      "default": "asu"},
            "views": {"type": "array", "items": {"type": "string"},
                      "description": "directions from a/b/c/oblique "
                                     "(default ['a','c','oblique']; max 4 "
                                     "images per call)"},
            "view": {"type": ["string", "array"], "items": {"type": "string"},
                     "description": "alias of views - one direction or a "
                                    "list (reg1-ext2: the singular was the "
                                    "first thing an agent tried)"},
            "highlight": {"type": "array", "items": {"type": "string"},
                          "description": "atom labels to flag in red "
                                         "(suspects, guests, Q-peak "
                                         "positions under discussion)"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session or self.project.session
        if ses is None or ses.model is None:
            return ToolResult.failure("no model in session - solve or "
                                      "import one first")
        # reg8: an atom-free session (data ingested, nothing solved) gets
        # the cell box instead of a failure - the agent asked to "look"
        empty_model = ses.model.scatterers().size() == 0
        state = str(params.get("state") or "asu")
        raw_views = params.get("views")
        if not raw_views and params.get("view"):
            alias = params.get("view")
            raw_views = [alias] if isinstance(alias, str) else list(alias)
        views = [str(v) for v in (raw_views or ["a", "c", "oblique"])]
        bad = [v for v in views if v not in ("a", "b", "c", "oblique")]
        if bad:
            return ToolResult.failure(
                f"unknown views {bad}; choose from a/b/c/oblique")
        views = views[:4]
        highlight = [str(h) for h in (params.get("highlight") or [])]

        from ..report.structviews import render_views
        from .nodes import part_connectivity_kwargs
        out_dir = self.project.dir / ".crystalpilot" / "views"
        try:
            imgs = render_views(ses.model, out_dir, state=state,
                                views=views, highlight=highlight,
                                stem=f"v{time.strftime('%H%M%S')}",
                                part_kwargs=part_connectivity_kwargs(
                                    ses.flags, ses.model.scatterers()))
        except Exception as e:  # noqa: BLE001 - rendering must not crash a session
            return ToolResult.failure(
                f"rendering failed: {type(e).__name__}: {e}")
        summary: dict[str, Any] = {
            "state": state,
            "views": views,
            "n_atoms_drawn": ses.model.scatterers().size() if state == "asu"
            else None,
            "images": [{"view": im["view"], "path": im["path"]}
                       for im in imgs],
            "note": ("the model has NO atoms: the images show the cell "
                     "box only (cell box only). Solve or import a model "
                     "before judging chemistry." if empty_model else
                     "the images follow this message - LOOK at them. "
                     "Judge like a chemist: are the molecules chemically "
                     "sensible, is the packing physical (no overlaps, no "
                     "floating fragments), do guests/voids look real? "
                     "For packing judgement also render state='supercell' "
                     "from a second direction."),
            "_image_files": [im["path"] for im in imgs],
        }
        return ToolResult(ok=True, summary=summary)


#: tools whose node params name the atoms they acted on: a candidate that
#: appears in one of them has been TRIED (reg8: the agent had to re-read
#: its own history to know which candidates were still untested)
_TRIAL_TOOLS = ("model_disorder", "ghost_test", "element_scan",
                "edit_atoms", "set_restraints", "probe_site")


def _candidate_trials(project, labels) -> dict[str, list[str]]:
    """{LABEL: ["model_disorder@n0012", "ghost_test:ghost", ...]} from the
    node history (committing tools) and the ghost ledger (verdicts). A
    label that never appears is absent - "untried" is the honest reading,
    read-only probes leave no node."""
    import json as _json

    out: dict[str, list[str]] = {}
    want = {str(lb).upper() for lb in labels}
    if not want or project is None or not hasattr(project, "dir"):
        return out
    try:
        from .nodes import NodeStore
        store = NodeStore(project.dir)
        for row in (store.list_nodes(limit=400) or {}).get("nodes") or []:
            nid = row.get("id")
            tool = str(row.get("tool") or "")
            if not nid or tool not in _TRIAL_TOOLS:
                continue
            try:
                blob = _json.dumps(store.node_meta(nid).get("params") or {},
                                   ensure_ascii=False).upper()
            except Exception:  # noqa: BLE001
                continue
            for lb in want:
                if f'"{lb}"' in blob or f"'{lb}'" in blob:
                    out.setdefault(lb, []).append(f"{tool}@{nid}")
    except Exception:  # noqa: BLE001 - advisory only
        pass
    try:
        from . import ghost_ledger
        for e in ghost_ledger.load(project.dir):
            lb = str(e.get("label") or "").upper()
            if lb in want:
                out.setdefault(lb, []).append(
                    f"ghost_test:{e.get('verdict') or '?'}")
    except Exception:  # noqa: BLE001
        pass
    return out


_STAGE_REFINE = {"refine", "run_shelxl", "optimize_weights", "set_weights",
                 "run_olex2", "set_resolution_limit"}
_STAGE_MODEL = {"edit_atoms", "add_atoms_from_difference_map", "fit_fragment",
                "add_hydrogens", "set_restraints", "model_disorder",
                "assemble_asu", "rename_atoms", "solvent_mask", "set_twin",
                "invert_structure", "fourier_complete", "change_space_group",
                "set_z"}
_STAGE_SOLVE = {"solve_charge_flipping", "solve_superflip", "run_shelxt",
                "interpret_peaks", "import_cif_model", "create_start_model"}
_STAGE_DELIVER = {"write_outputs", "finalize_delivery"}


def _packing_summary(project_dir) -> dict[str, Any]:
    """Headline packing numbers of the ACTIVE node from its cached
    analysis.json (round-2 R5) - the same product analyze_packing and the
    workbench 分析 tab read.

    READ ONLY: this never builds the product (the solvent mask of a large
    cell takes minutes and a situation report must stay cheap). When the
    file is absent the report says 未算 and names what builds it."""
    from .analysis import ANALYSIS_CACHE_V
    from .nodes import NodeStore
    from .scene import cache_dir
    try:
        node = NodeStore(project_dir).state().get("active_node")
    except Exception:  # noqa: BLE001 - no node tree yet
        node = None
    if not node:
        return {"status": "未算（尚无活动节点）"}
    path = cache_dir(project_dir, node) / "analysis.json"
    if not path.exists():
        return {"node": node,
                "status": "未算（该节点的 analysis.json 尚未生成：调用 "
                          "analyze_packing，或在工作台打开“分析”页签后生成）"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 - a half-written file
        return {"node": node,
                "status": f"未算（analysis.json 不可读：{type(e).__name__}）"}
    v = data.get("v")
    status = ("已算" if v == ANALYSIS_CACHE_V else
              f"旧版产物（v{v}，当前 v{ANALYSIS_CACHE_V}；analyze_packing 会重建）")
    out: dict[str, Any] = {"node": node, "status": status,
                           "source": "analysis.json（analyze_packing 与工作台"
                                     "分析页签共用的同一份产物）"}
    inter = data.get("interactions") or {}
    counts = inter.get("counts") or {}
    out["interactions"] = {"h_source": inter.get("h_source"),
                           "unique": counts.get("unique"),
                           "passing": counts.get("passing"),
                           "intra": counts.get("intra")}
    pores = data.get("pores") or {}
    voids = pores.get("voids") or []
    big = max(voids, key=lambda x: x.get("volume_A3") or 0.0) if voids else None
    out["pores"] = {
        "n_voids": pores.get("n_voids"),
        "solvent_volume_A3": pores.get("solvent_volume_A3"),
        "solvent_volume_pct_of_cell": pores.get("solvent_volume_pct_of_cell"),
        "largest": ({k: big.get(k) for k in (
            "void", "volume_A3", "dimensionality", "directions", "lcd_A",
            "pld_A", "pld_error_A", "electrons")} if big else None),
    }
    pk = pores.get("packing") or {}
    out["packing"] = ({k: pk.get(k) for k in (
        "packing_index_pct", "packing_index_error_pct",
        "volume_per_non_h_atom_A3")} if pk else None)
    g = data.get("guests")
    if isinstance(g, dict):
        out["guests"] = {"summary": g.get("summary"),
                         "n_guests": len(g.get("guests") or [])}
    else:
        out["guests"] = None
        if data.get("guests_note"):
            out["guests_note"] = data["guests_note"]
    return out


def _packing_sentence(ps: dict[str, Any]) -> str | None:
    """One narrative sentence from `_packing_summary`, only when computed."""
    if not str(ps.get("status", "")).startswith(("已算", "旧版")):
        return None
    bits = []
    inter = ps.get("interactions") or {}
    uq, pa = inter.get("unique") or {}, inter.get("passing") or {}
    names = {"hbond": "氢键", "pipi": "π–π", "chpi": "C–H···π",
             "chx": "C–H···X", "halogen": "卤键", "anion_pi": "阴离子–π"}
    ib = [f"{names.get(k, k)} {uq[k]}（合格 {pa.get(k, 0)}）"
          for k in names if uq.get(k)]
    if ib:
        bits.append("对称唯一相互作用：" + "、".join(ib)
                    + (f"（H 来源 {inter['h_source']}）" if inter.get("h_source") else ""))
    po = ps.get("pores") or {}
    if po.get("n_voids") is not None:
        pb = f"孔 {po['n_voids']} 个"
        if po.get("solvent_volume_A3") is not None:
            pb += f"，溶剂可及 {po['solvent_volume_A3']:.0f} Å³"
            if po.get("solvent_volume_pct_of_cell") is not None:
                pb += f"（{po['solvent_volume_pct_of_cell']:.1f} %）"
        lg = po.get("largest") or {}
        if lg:
            pb += f"，最大孔 {lg.get('volume_A3', 0):.0f} Å³"
            if lg.get("dimensionality") is not None:
                pb += f" 维度 {lg['dimensionality']}"
            if lg.get("lcd_A") is not None:
                pb += f" LCD {lg['lcd_A']:.1f} Å"
            if lg.get("pld_A") is not None:
                pb += f" PLD {lg['pld_A']:.1f}±{lg.get('pld_error_A') or 0:.1f} Å"
        bits.append(pb)
    pk = ps.get("packing") or {}
    if pk.get("packing_index_pct") is not None:
        s = f"堆积指数 {pk['packing_index_pct']:.1f}±{pk.get('packing_index_error_pct') or 0:.1f} %"
        if pk.get("volume_per_non_h_atom_A3") is not None:
            s += f"，{pk['volume_per_non_h_atom_A3']:.1f} Å³/非氢原子"
        bits.append(s)
    g = ps.get("guests") or {}
    if g.get("summary"):
        gs = "、".join(f"{k} {n}" for k, n in g["summary"].items() if n)
        bits.append(f"客体位置 {gs}" if gs else "无客体片段")
    if not bits:
        return None
    return (f"堆积摘要（节点 {ps.get('node')}，读自缓存的分析产物，非本次计算）："
            + "；".join(bits) + "。详表与判据用 analyze_packing。")


def _infer_stage(project, ses) -> dict[str, Any]:
    """数据 / 求解 / 建模 / 精修 / 交付 from the node history and the session;
    定群 and 验证 leave no node (read-only tools), so they are named in
    `basis` as not inferable here rather than guessed."""
    if ses is None or ses.model is None:
        return {"stage": "数据", "basis": "无会话或无模型"}
    if ses.model.scatterers().size() == 0:
        return {"stage": "求解", "basis": "数据已入会话，模型无原子"}
    tools: list[str] = []
    try:
        from .nodes import NodeStore
        rows = list((NodeStore(project.dir).list_nodes(limit=400) or {})
                    .get("nodes") or [])
        rows.sort(key=lambda r: str(r.get("id") or ""))
        tools = [str(r.get("tool") or "") for r in rows]
    except Exception:  # noqa: BLE001
        tools = []
    if any(t in _STAGE_DELIVER for t in tools):
        return {"stage": "交付", "basis": "节点历史含 write_outputs / finalize_delivery"}
    last = tools[-1] if tools else ""
    note = ("按最近一次改模型工具推断；定群与验证由只读工具完成，不留节点，"
            "这里不猜")
    if last in _STAGE_REFINE:
        return {"stage": "精修", "basis": f"最近节点 {last}；{note}"}
    if last in _STAGE_MODEL:
        return {"stage": "建模", "basis": f"最近节点 {last}；{note}"}
    if any(t in _STAGE_REFINE for t in tools):
        return {"stage": "精修", "basis": f"历史含精修节点，最近 {last or '无'}；{note}"}
    if last in _STAGE_SOLVE or not tools:
        return {"stage": "建模", "basis": f"最近节点 {last or '无'}（求解产物）；{note}"}
    return {"stage": "建模", "basis": f"最近节点 {last}；{note}"}


MASK_BLOCK_FIELDS = (
    ("total_solvent_electrons_per_cell", "void_electrons_per_cell"),
    ("solvent_volume_A3", "void_volume_A3"),
    ("solvent_volume_pct_of_cell", "void_volume_pct_of_cell"),
    ("n_voids", "n_voids"),
    ("n_voids_masked", "n_voids_masked"),
    ("solvent_mask_converged", "converged"),
    ("mask_id", "mask_id"),
    ("computed_at", "computed_at"),
)


def solvent_mask_block(flags: dict[str, Any]) -> dict[str, Any] | None:
    """The situation report's mask block, from what solvent_mask actually
    stores (`solvent_mask_info`). Round-3 T-k: the block used to read a
    `mask_meta` key nothing ever wrote, so every report said
    {"active": true} and nothing else - not the volume, not the electron
    count, not whether the series converged."""
    if flags.get("f_mask") is None:
        return None
    info = flags.get("solvent_mask_info") or {}
    block: dict[str, Any] = {"active": True}
    for src, dst in MASK_BLOCK_FIELDS:
        if info.get(src) is not None:
            block[dst] = info[src]
    if not any(k in block for k in ("void_electrons_per_cell",
                                     "void_volume_A3", "converged")):
        block["note"] = ("mask present but its summary is not with the "
                         "session (older node); rerun solvent_mask to "
                         "get volume / electron count / convergence")
    return block


class SituationReport(_ProjectTool):
    name = "situation_report"
    description = (
        "The whole-picture view a human scientist forms before deciding "
        "anything: data side (coverage, merging quality, twin/mask state), "
        "model side (composition vs what the cell volume and priors "
        "expect, ADP health), the refinement TRAJECTORY over recent nodes "
        "(improving / stalled / oscillating), cross-evidence conflicts, "
        "and two rendered views of the structure itself (look at them). "
        "Everything is evidence with context, not verdicts: numbers that "
        "look wrong for one reason are often explained by another part of "
        "the picture - this tool exists so you weigh the WHOLE picture "
        "the way an experienced crystallographer would, instead of "
        "reacting to single indicators. Call it whenever you are about "
        "to make a structural decision, feel lost in branches, or R "
        "factors stop responding. Also returns `stage` (数据/求解/建模/精修/"
        "交付, inferred from the node history) and `packing` (the headline "
        "interactions / pores / packing index / guests of the active node, "
        "read from its cached analysis.json - 未算 until analyze_packing or "
        "the workbench 分析 tab builds it; never computed here).")
    params_schema = {"type": "object", "properties": {
        "render": {"type": "boolean", "default": True,
                   "description": "attach structure images (asu oblique + "
                                  "2x2x2 packing)"},
    }}

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        import numpy as np
        from cctbx import adptbx

        p = self.project
        ses = ctx.session or p.session
        if ses is None:
            return ToolResult.failure(
                "no active session - situation_report reads the reduced-"
                "data + model state; use get_project_brief during the "
                "raw-frames stage")
        s: dict[str, Any] = {}
        narrative: list[str] = []

        # ---- data side ---------------------------------------------------
        data: dict[str, Any] = {}
        if ses.fo_sq is not None:
            fo = ses.fo_sq
            data["n_unique"] = fo.size()
            try:
                data["d_min_A"] = round(fo.d_min(), 3)
                data["completeness"] = round(
                    fo.completeness(d_max=float("inf")), 3)
            except Exception:  # noqa: BLE001
                pass
        hklf = int(ses.flags.get("hklf") or 4)
        data["hklf"] = hklf
        twin = ses.flags.get("twin")
        if twin:
            data["twin"] = {"basf": twin.get("basf"),
                            "matrix_present": bool(twin.get("matrix"))}
        mask_block = solvent_mask_block(ses.flags)
        if mask_block is not None:
            data["solvent_mask"] = mask_block
        fs_path = p.dir / ".crystalpilot" / "frames" / "state.json"
        if fs_path.exists():
            try:
                fstate = json.loads(fs_path.read_text(encoding="utf-8"))
                stages = fstate.get("stages") or {}
                idx = stages.get("index_frames") or {}
                # .get with a default plus a direct index crashed on
                # every vendor-hkl project (no index_frames stage) -
                # r22 live: situation_report failed 5/5 across both arms
                if (idx.get("n_lattices") or 1) > 1:
                    data["frames_note"] = (
                        f"indexing found {idx['n_lattices']} lattices "
                        "(twin/split crystal) - the reduction history "
                        "matters for every data-side judgement here")
                sc_exp = stages.get("scale_and_export") or {}
                for k in ("r_merge", "r_int", "cc_half"):
                    if sc_exp.get(k) is not None:
                        data[f"scaling_{k}"] = sc_exp[k]
            except (OSError, json.JSONDecodeError):
                pass
        s["data_side"] = data

        # ---- model side --------------------------------------------------
        model: dict[str, Any] = {}
        xs = ses.model
        if xs is None or xs.scatterers().size() == 0:
            model["state"] = "no model yet"
            narrative.append("尚无模型，现状即数据侧现状。")
        else:
            counts: dict[str, int] = {}
            n_non_h = 0
            for sc in xs.scatterers():
                el = sc.scattering_type.strip().capitalize() \
                    .rstrip("+-0123456789")
                counts[el] = counts.get(el, 0) + 1
                if el not in ("H", "D"):
                    n_non_h += 1
            model["element_counts"] = dict(sorted(counts.items()))
            model["n_atoms"] = xs.scatterers().size()
            # volume sanity: ~18 A^3 per non-H atom - the wrong-Z'/wrong-
            # group pathology detector (a P1 escape shows up as the model
            # holding half or double what the volume expects)
            try:
                vol_asu = (xs.unit_cell().volume()
                           / xs.space_group().order_z())
                expect = vol_asu / 18.0
                model["volume_expectation"] = {
                    "asu_volume_A3": round(vol_asu, 0),
                    "expected_non_h_per_asu": round(expect, 0),
                    "modeled_non_h_per_asu": n_non_h,
                }
                ratio = n_non_h / max(expect, 1e-6)
                if ratio < 0.6 or ratio > 1.5:
                    narrative.append(
                        f"体积核算异常：按 ~18 Å³/非氢原子，ASU 体积期望约 "
                        f"{expect:.0f} 个非氢原子，模型有 {n_non_h} 个"
                        f"（{ratio:.1f}x）。偏离这么远通常不是化学，而是 "
                        f"Z′/空间群/组成之一错了，值得先想清楚再继续修。")
            except Exception:  # noqa: BLE001
                pass
            # ADP health
            npd, ratios = [], []
            for sc in xs.scatterers():
                if not sc.flags.use_u_aniso():
                    continue
                try:
                    ev = adptbx.eigenvalues(
                        adptbx.u_star_as_u_cart(xs.unit_cell(), sc.u_star))
                    if min(ev) <= 0:
                        npd.append(sc.label)
                    elif max(ev) / max(min(ev), 1e-9) > 6:
                        ratios.append((sc.label,
                                       round(max(ev) / min(ev), 1)))
                except Exception:  # noqa: BLE001
                    continue
            if npd:
                model["npd_atoms"] = npd[:8]
            if ratios:
                ratios.sort(key=lambda t: -t[1])
                model["extreme_adp_ratios"] = ratios[:5]
        s["model_side"] = model

        # ---- trajectory --------------------------------------------------
        traj: list[dict[str, Any]] = []
        try:
            rows = p.nodes.list_nodes(limit=200)
            for r_ in rows[-10:]:
                traj.append({k: r_.get(k) for k in
                             ("id", "tool", "r1", "wr2", "n_atoms")})
        except Exception:  # noqa: BLE001
            pass
        s["trajectory_recent"] = traj
        r1s = [t["r1"] for t in traj if t.get("r1") is not None]
        if len(r1s) >= 3:
            span = max(r1s) - min(r1s)
            last3 = r1s[-3:]
            if max(last3) - min(last3) < 0.003 and len(r1s) >= 5:
                narrative.append(
                    f"精修轨迹：最近 {len(r1s)} 个节点 R1 从 {r1s[0]:.3f} 到 "
                    f"{r1s[-1]:.3f}，最后三个节点在 ±0.003 内，数值上已"
                    "收敛。此时 R1 的高低更多反映数据与模型假设，而不是"
                    "还没修够；如果对现值不满意，方向是重新审视假设"
                    "（对称性/孪晶/组成/客体），不是再加轮次。")
            elif r1s[-1] > r1s[0] + 0.01:
                narrative.append(
                    f"精修轨迹：R1 在走高（{r1s[0]:.3f}→{r1s[-1]:.3f}），"
                    "最近的模型改动让拟合变差，回看这几步改了什么。")

        # ---- cross-evidence conflicts ------------------------------------
        conflicts: list[str] = []
        if hklf == 5 and not twin:
            conflicts.append("数据是 HKLF5 批次而会话无 BASF/twin 标志，"
                             "SHELXL 作业会缺 BASF 卡")
        if twin and hklf == 4 and not twin.get("matrix"):
            conflicts.append("有 BASF 而数据非 HKLF5 且无 TWIN 矩阵，"
                             "BASF 无对象可作用")
        if ses.flags.get("f_mask") is not None and xs is not None:
            # r33 (PLAN T1.1): two cross-checks the mask never got after
            # it was computed. solvent_mask leaves its per-void geometry
            # in ses.flags["solvent_mask_info"]["voids"] (centre of mass +
            # volume + masked flag), so this costs one sym_equiv_sites per
            # void and no map work.
            #
            # NOTE the approximation, and that it is one-directional: the
            # exact test needs the mask GRID, which only exists inside the
            # solvent_mask run (mask_tools._coordination_encroachment does
            # it properly there, for metals only). Here each void is
            # treated as a sphere of its own volume about its centre of
            # mass and only the inner half-radius counts, so a channel-
            # shaped void can hide an atom this check does not see. A hit
            # is evidence; a miss is not a clearance.
            conflicts += self._mask_occupancy_conflicts(p, ses, xs)
        if conflicts:
            s["conflicts"] = conflicts

        # ---- open items ----------------------------------------------
        open_items: dict[str, Any] = {}
        rs = ses.flags.get("restraints") or []
        if rs:
            open_items["n_restraints"] = len(rs)
        dg = ses.flags.get("disorder_groups") or []
        if dg:
            open_items["n_disorder_groups"] = len(dg)
            # T1.6: the acceptance verdict run_shelxl attached to each split
            # (supported / inconclusive / revoke / pending / unknown)
            verdicts: dict[str, int] = {}
            for g in dg:
                v = str((g or {}).get("verdict") or "pending")
                verdicts[v] = verdicts.get(v, 0) + 1
            open_items["disorder_verdicts"] = verdicts
            if verdicts.get("revoke"):
                narrative.append(
                    f"{verdicts['revoke']} 个无序拆分的判词是 revoke（占有率在 2 s.u. 内"
                    f"等于 1 或 0）：数据不支持这个拆分，交付前用 "
                    f"model_disorder(undo=<group>) 合并回单点，或说明保留的理由。")
            if verdicts.get("pending"):
                narrative.append(
                    f"{verdicts['pending']} 个无序拆分尚未经精修验收（verdict pending）："
                    f"先 run_shelxl，再读 disorder_acceptance 决定去留。")
        # where a second position would be, before anyone draws it
        try:
            from .disorder_candidates import disorder_candidates
            _split = {str(m.get("label", "")).upper() for g in dg
                      for m in (g.get("members") or [])}
            _split |= {str(k).upper()
                       for k in (ses.flags.get("parts_extra") or {})}
            dcs = disorder_candidates(xs, ses.flags.get("diff_map_peaks"),
                                      exclude=_split)
        except Exception:  # noqa: BLE001 - advisory only
            dcs = {"candidates": []}
        if dcs.get("candidates"):
            cands = dcs["candidates"][:6]
            # reg8: tried / adjudicated travel with every candidate, so the
            # report itself says "C15 未试" instead of listing settled ones
            adj_store = ses.flags.get("adjudicated_alerts") or {}
            trials = _candidate_trials(p, [c["atom"] for c in cands])
            for c in cands:
                lb = str(c["atom"]).upper()
                c["tried"] = trials.get(lb) or []
                c["adjudicated"] = [
                    {"code": v.get("code"), "reason": v.get("reason")}
                    for v in adj_store.values()
                    if str(v.get("subject") or "").upper() == lb]
            open_items["disorder_candidates"] = [
                {k: c.get(k) for k in ("atom", "peak_height", "peak_d",
                                       "u_eq_over_median", "adp_max_over_min",
                                       "nearest_h", "tried", "adjudicated")}
                for c in cands]
            bits = []
            for c in cands:
                b = (f"{c['atom']} 峰 {c['peak_height']:.2f} e/Å³ 距 "
                     f"{c['peak_d']:.2f} Å")
                if c["adjudicated"]:
                    b += "，已裁决（" + "；".join(
                        f"{a['code']}: {a['reason']}" for a in c["adjudicated"]) + "）"
                b += ("，已试 " + "、".join(c["tried"])) if c["tried"] else "，未试"
                if c.get("u_eq_over_median") is not None:
                    b += f"，U_eq 为中位数 {c['u_eq_over_median']:.1f}×"
                if c.get("adp_max_over_min") is not None:
                    b += f"，ADP 比 {c['adp_max_over_min']}"
                if c.get("nearest_h"):
                    b += f"，最近氢 {c['nearest_h']['d']:.2f} Å"
                bits.append(b)
            narrative.append(
                "无序候选（差值图在原子旁 0.4–1.6 Å 处有残余峰，且不在任何已建原子"
                "或氢的位置上）：" + "；".join(bits)
                + "。无序由精修裁决：model_disorder（B 落在峰上）→ set_restraints"
                  "（restraint_suggestion）→ 该分支 run_shelxl(adopt) → 读 "
                  "disorder_acceptance 的 s.u. 判词；在精修之前不要用假设否决。")
        # round-3 WP7: the research goal and what has been tried on this
        # line - a failed route rules out a configuration, not the goal
        try:
            from . import investigation as _inv
            from . import trial_ledger as _tl
            inv = _inv.load(p.dir)
            if _inv.is_set(inv):
                open_items["investigation"] = _inv.summary_block(inv)
                narrative.append(_inv.narrative(inv))
            _active = p.nodes.state().get("active_node")
            _chain = _tl.ancestor_chain(p.nodes, _active)
            _recent = _tl.recent(p.dir, _active, _chain, n=6)
            if _recent:
                open_items["recent_trials"] = _recent
                narrative.append(
                    "本线上最近的试验（trial_ledger；同一调用在同一节点原样重跑不会有"
                    "新答案）：" + "；".join(
                        f"{t['tool']}@{t['node']}（{t['params']}）→ "
                        f"{t['outcome_text']}" for t in _recent) + "。")
        except Exception:  # noqa: BLE001 - advisory only
            pass
        if open_items:
            s["open_items"] = open_items
        s["stage"] = _infer_stage(p, ses)
        try:
            s["packing"] = _packing_summary(p.dir)
        except Exception as e:  # noqa: BLE001 - advisory only
            s["packing"] = {"status": f"未算（读取失败：{type(e).__name__}）"}
        ps_line = _packing_sentence(s["packing"])
        if ps_line:
            narrative.append(ps_line)

        if not narrative:
            narrative.append(
                "各项证据之间未发现显眼的相互矛盾。照常保持怀疑：单项指标"
                "的好坏都要放回全局解释，重要决定前看一眼结构图。")
        s["narrative"] = narrative

        # ---- the look ----------------------------------------------------
        if params.get("render", True) and xs is not None \
                and xs.scatterers().size():
            try:
                from ..report.structviews import render_views
                from .nodes import part_connectivity_kwargs
                out_dir = p.dir / ".crystalpilot" / "views"
                pk = part_connectivity_kwargs(ses.flags, xs.scatterers())
                imgs = render_views(xs, out_dir, state="asu",
                                    views=("oblique",), stem="sit",
                                    part_kwargs=pk)
                imgs += render_views(xs, out_dir, state="supercell",
                                     views=("c",), stem="sit",
                                     part_kwargs=pk)
                s["images"] = [im["path"] for im in imgs]
                s["_image_files"] = [im["path"] for im in imgs]
                s["look_note"] = ("附图：ASU 斜视 + 2x2x2 堆积。像化学家"
                                  "一样看：分子合不合理、堆积是否物理、"
                                  "有没有悬空碎片/重叠，图比数字先暴露"
                                  "大方向错误。")
            except Exception as e:  # noqa: BLE001 - vision is best-effort
                s["render_error"] = f"{type(e).__name__}: {e}"
        return ToolResult(ok=True, summary=s)

    # ---- mask cross-checks ------------------------------------------
    @staticmethod
    def _void_spheres(ses) -> list[tuple[int, list[float], float]]:
        """(void id, centre_frac, half of the equal-volume radius) for the
        voids the CURRENT mask actually applies. Reads only what
        solvent_mask already left in the session flags."""
        info = ses.flags.get("solvent_mask_info") or {}
        out: list[tuple[int, list[float], float]] = []
        for v in info.get("voids") or []:
            if not v.get("masked"):
                continue          # found but excluded: refinement ignores it
            c, vol = v.get("centre_frac"), v.get("volume_A3")
            if not c or len(c) != 3 or not vol or vol <= 0:
                continue
            r_eq = (3.0 * float(vol) / (4.0 * math.pi)) ** (1.0 / 3.0)
            out.append((int(v.get("void") or len(out) + 1),
                        [float(x) for x in c], 0.5 * r_eq))
        return out

    @classmethod
    def _mask_occupancy_conflicts(cls, p, ses, xs) -> list[str]:
        """Modelled atoms, and ghost-ledger 'real' atoms, sitting inside a
        masked void - the same density counted twice.

        The mask's job is to absorb density NO atom models; an atom inside
        a masked void means the electrons there are in the model AND in
        f_mask. One-directional: a hit is evidence to look at the mask and
        the difference map, a clean run says nothing about whether the
        mask is right (P12).
        """
        spheres = cls._void_spheres(ses)
        if not spheres:
            return []
        from cctbx import sgtbx

        conflicts: list[str] = []
        hits: list[str] = []
        ghost_hits: list[str] = []
        try:
            from . import ghost_ledger
            ledger = [e for e in ghost_ledger.load(p.dir)
                      if e.get("verdict") == "real" and not e.get("disposed")]
        except Exception:  # noqa: BLE001 - a broken ledger must not throw
            ledger = []
        for void_id, centre, bar in spheres:
            try:
                eq = xs.sym_equiv_sites(tuple(centre))
            except Exception:  # noqa: BLE001 - a bad centre is skipped
                continue

            for sc in xs.scatterers():
                el = sc.scattering_type.strip().capitalize().rstrip(
                    "+-0123456789")
                if el in ("H", "D"):
                    continue      # riding H follow their carrier
                d = _min_sym_dist(sgtbx, eq, sc.site)
                if d is not None and d < bar:
                    hits.append(f"{sc.label}→空腔{void_id} ({d:.2f} Å)")
            for e in ledger:
                for lb, site in zip(e.get("labels") or [],
                                    e.get("site_frac") or []):
                    if not site:
                        continue
                    d = _min_sym_dist(sgtbx, eq, site)
                    if d is not None and d < bar:
                        ghost_hits.append(
                            f"{lb}（台账 {e.get('id')}）→空腔{void_id} "
                            f"({d:.2f} Å)")
        approx = ("判据是近似的：把每个空腔当成同体积的球、只算半径的一半"
                  "以内，通道形空腔可能漏判；命中是证据，不命中不等于没问题。"
                  "确认请看掩膜图与差值图。")
        if hits:
            conflicts.append(
                "模型原子落在当前掩膜的空腔内：" + "、".join(hits[:6])
                + (" 等" if len(hits) > 6 else "")
                + "，同一处电子密度可能既由原子建模、又被 f_mask 吸收"
                  "（重复计数）。要么这些原子不该在那里，要么这个空腔不该"
                  "被掩膜。" + approx)
        if ghost_hits:
            conflicts.append(
                "ghost 台账判为 real 的原子落在掩膜空腔内："
                + "、".join(ghost_hits[:6])
                + (" 等" if len(ghost_hits) > 6 else "")
                + "，台账说那里有真实散射体，掩膜却把那块密度当成了无模型"
                  "溶剂。两者不可能同时成立：先决定密度归谁，再重算掩膜。"
                + approx)
        return conflicts
