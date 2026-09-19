"""Validation tools: crystallographic sanity + chemical plausibility judged
per SYSTEM TYPE (framework / molecular / salt / unknown), aggregated into
alerts and a deterministic confidence score.

pa1 cage-l3-r1 (2026-09-02): the MOF-shaped heuristics - "framework
dimensionality 0 ... structure may be incomplete", every unbonded atom a
ghost, three eta5-Cp rings and the Cl- counter-ions counted as 56 "free"
atoms, confidence 27 - made the agent discard a trial that matched 149/154
published atoms of a discrete Zr6 cage as "chemically invalid". A 0-D
molecule is judged by molecular criteria here; a framework keeps its own.
"""
from __future__ import annotations

import re
from typing import Any

from ..chem.connectivity import analyze_connectivity, fragment_identity
from ..chem.knowledge import is_metal
from ..chem.light_atom_adp import audit_light_atom_elements
from ..chem.metal_bonded_audit import audit_metal_bonded_light_atoms
from .base import Tool, ToolContext, ToolResult

#: audit severities -> alert severities (compute_confidence costs)
_AUDIT_SEVERITY = {"high": "critical", "medium": "warning", "low": "info"}
_RETYPE_ADVICE = ("; retype with edit_atoms reassign, refine, and re-check "
                  "Ueq/residual; do NOT hide it behind add_hydrogens exclude")
_MAX_AUDIT_ALERTS = 12


def _compact_suspect(s: dict) -> dict:
    return {k: s.get(k) for k in ("label", "element", "metal", "d", "severity",
                                  "kind", "n_metals", "n_skeleton_neighbours",
                                  "ueq_over_metal_light_neighbours",
                                  "candidates")}

#: which criteria a system type is judged by - quoted in the tool output so
#: the agent (and the report) can see WHY an alert did or did not fire
CRITERIA_BY_SYSTEM_TYPE: dict[str, str] = {
    "framework": (
        "framework criteria: 2-D/3-D periodicity expected (low dimensionality "
        "= incomplete model or unbonded linker), every lone atom is a ghost "
        "or unmodelled pore solvent, metal CN vs the MOF profile, short "
        "contacts, ADP/ghost signatures, R1/GooF/difference map"),
    "molecular": (
        "molecular criteria: 0-D expected - periodicity is NOT required and "
        "not penalised; fragments are judged by identity (main molecule / "
        "counter-ions / solvent / unrecognised pieces), metal CN counts an "
        "eta-bound ring as one ligand, intramolecular short contacts, "
        "ADP/ghost signatures, R1/GooF/difference map"),
    "salt": (
        "ionic criteria: no periodicity requirement, fragments judged by "
        "identity (ions / solvent / unrecognised pieces), metal CN, short "
        "contacts, ADP/ghost signatures, R1/GooF/difference map"),
    "unknown": (
        "system type undetermined: only type-independent checks applied "
        "(metal CN, short contacts, ADP/ghost signatures, unrecognised lone "
        "atoms, R1/GooF/difference map); periodicity and free-fragment "
        "criteria are withheld until the model shows what it is"),
}


_WATER_LABEL = re.compile(r"O\d*W\d*")


def _parts_from_flags(flags: dict | None) -> dict[str, int]:
    """{label: SHELX PART} from the session's disorder flags (same source
    as refine.nodes.part_connectivity_kwargs) so declared split sites are
    not reported as impossible contacts."""
    flags = flags or {}
    part_of: dict[str, int] = {}
    for g in flags.get("disorder_groups") or []:
        for m in g.get("members", ()):
            part_of[str(m.get("label", "")).upper()] = int(m.get("part") or 0)
    for lbl, p in (flags.get("parts_extra") or {}).items():
        part_of.setdefault(str(lbl).upper(), int(p or 0))
    return part_of


def compute_confidence(stats: dict[str, Any], alerts: list[dict],
                       framework_dim: int, system_type: str = "framework"
                       ) -> dict[str, Any]:
    """Deterministic 0-100 score from refinement stats, residuals and chemistry.

    Calibration anchors: a publication-quality small-molecule/MOF refinement
    (R1<0.05, clean chemistry) ~ 90+; a correct framework with imperfect solvent/
    disorder treatment (R1 0.10-0.15, minor alerts) ~ 55-70; a chemically broken
    or badly fitting model < 35.

    The chemistry part is whatever alerts the per-system-type criteria
    raised: a 0-D molecule no longer pays for "low dimensionality" or for
    counter-ions/solvent it legitimately contains. The breakdown is
    returned so a low score is read for what drove it (pa1 cage-l3-r1:
    27/100 was 45 points of R1 0.27 plus the capped alert cost, not
    "chemically invalid").
    """
    score = 100.0
    breakdown: dict[str, float] = {}
    r1 = stats.get("r1_strong")
    if r1 is None:
        breakdown["r1"] = -45.0
    elif r1 <= 0.05:
        breakdown["r1"] = 0.0
    elif r1 <= 0.10:
        breakdown["r1"] = -(r1 - 0.05) * 300          # up to -15
    elif r1 <= 0.20:
        breakdown["r1"] = -(15 + (r1 - 0.10) * 200)   # up to -35
    else:
        breakdown["r1"] = -min(50.0, 35 + (r1 - 0.20) * 150)
    goof = stats.get("goof")
    breakdown["goof"] = -5.0 if goof is not None and (goof < 0.5 or goof > 4.0) else 0.0
    dmax = stats.get("diff_map_max")
    breakdown["diff_map"] = (-min(12.0, (dmax - 2.0) * 2.5)
                             if dmax is not None and dmax > 2.0 else 0.0)
    severity_cost = {"critical": 12.0, "warning": 4.0, "info": 0.0}
    alert_cost = sum(severity_cost.get(a.get("severity", "info"), 0.0)
                     for a in alerts)
    breakdown["alerts"] = -min(28.0, alert_cost)
    score += sum(breakdown.values())
    score = max(0.0, min(100.0, score))
    grade = ("high" if score >= 75 else "medium" if score >= 50 else "low")
    return {"score": round(score, 1), "grade": grade,
            "system_type": system_type,
            "criteria": CRITERIA_BY_SYSTEM_TYPE.get(
                system_type, CRITERIA_BY_SYSTEM_TYPE["unknown"]),
            "breakdown": {k: round(v, 1) for k, v in breakdown.items()}}


class ValidateStructure(Tool):
    name = "validate_structure"
    description = (
        "Full validation of the current model: bonded-graph connectivity, metal "
        "coordination plausibility, system type (framework / molecular / salt) "
        "with the criteria that follow from it, isolated atoms and fragment "
        "identity (counter-ions, solvent, unrecognised pieces), eta-bound "
        "Cp/arene rings recognised as ligands, short contacts, ADP anomalies, "
        "model-vs-expected composition, refinement stats, and a geometry audit "
        "of every light atom bonded to a metal (a C/N with no carbon skeleton "
        "at an M-O distance is a mislabelled O/halide - alert "
        "metal_bonded_light_atom; N-N or carbonyl-length C-C bonds outside "
        "azide/azole/alkyne chemistry - suspect_nn_bond / suspect_cc_bond; "
        "metal CN counts an eta-ring as one ligand and never counts H). "
        "After refinement it also checks every light atom's ELEMENT against "
        "its own ADP (light_atom_element_check): a label with too few "
        "electrons refines to a Ueq clearly below the median of its bonded "
        "neighbours (too_light_label - a nitrogen labelled C), too many gives "
        "one clearly above (too_heavy_label), and a planar X(O)2 site is read "
        "as carboxylate or nitro from the same numbers "
        "(nitro_vs_carboxylate_candidates) because geometry cannot separate "
        "them. Hints with the numbers, never automatic relabelling. "
        "SHELXT labels from a placeholder composition are not element "
        "evidence: retype by geometry, do not hide such atoms in "
        "add_hydrogens exclude. A 0-D molecule/cage "
        "is judged by molecular criteria (no periodicity penalty); a framework "
        "keeps the MOF criteria. Produces alerts and the deterministic "
        "confidence score with its breakdown. Alerts you have investigated and "
        "settled can be moved to an 'adjudicated' section with mark_adjudicated "
        "so repeat runs surface only what is still open - they are NOT deleted, "
        "keep counting towards the confidence score, and their reasons travel "
        "into the delivery disclosure.")
    params_schema = {"type": "object", "properties": {
        "expect_framework": {"type": "boolean",
                             "description": "omit to infer the system type from "
                                            "the bonded graph (recommended); true "
                                            "forces framework (MOF) criteria, "
                                            "false forces molecular criteria"},
        "mark_adjudicated": {
            "type": "array", "default": [],
            "items": {"type": "object", "properties": {
                "code": {"type": "string",
                         "description": "alert code, e.g. metal_cn"},
                "subject": {"type": "string",
                            "description": "atom label or text identifying WHICH "
                                           "alert of that code; omit to adjudicate "
                                           "every alert with this code"},
                "reason": {"type": "string",
                           "description": "why it is settled (goes into the "
                                          "report); null removes a previous "
                                          "adjudication"}}},
            "description": "record alerts as investigated-and-settled, e.g. "
                           "[{'code':'metal_cn','subject':'Dy1','reason':'CN=9 is "
                           "normal for Dy(III), confirmed against CSD'}]. Persists "
                           "for the session."}}}

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        if ses.model is None:
            return ToolResult.failure("no model to validate")
        adj_err = self._update_adjudications(
            ses, params.get("mark_adjudicated") or [])
        if adj_err:
            return ToolResult.failure(adj_err)
        xs = ses.model
        conn = analyze_connectivity(xs, parts=_parts_from_flags(ses.flags))
        alerts: list[dict] = []
        # metal-bonded light atoms: symmetry-aware, element-generic (pa2:
        # 10-13 Zr-C, 18 Zr-N and 30 N-N "bonds" went into deliveries
        # unremarked); the audit must never take validation down with it
        mba_error = None
        try:
            mba = audit_metal_bonded_light_atoms(
                xs, parts=_parts_from_flags(ses.flags))
        except Exception as e:  # noqa: BLE001
            mba = None
            mba_error = f"{type(e).__name__}: {e}"

        # The system type decides which criteria apply. expect_framework is
        # an explicit override; omitted = inferred from the bonded graph.
        forced = params.get("expect_framework")
        if forced is True:
            system_type, type_source = "framework", "expect_framework=true (forced)"
        elif forced is False:
            system_type, type_source = "molecular", "expect_framework=false (forced)"
        else:
            system_type, type_source = conn.system_type, "inferred from the bonded graph"
        framework_mode = system_type == "framework"
        criteria = CRITERIA_BY_SYSTEM_TYPE[system_type]
        type_label = conn.system_type_evidence.get("label", system_type)
        el_of_label = {sc.label: sc.scattering_type.strip().capitalize()
                       for sc in xs.scatterers()}

        # ASU-graph sanity (expert-review red flags, 2026-08-29): detached
        # fragments look disconnected in Olex2 even when symmetry links them;
        # lone partial atoms with inflated Ueq are the added-to-lower-R1
        # ghost signature. P1 connectivity above cannot see either.
        try:
            from ..chem.asu_sanity import asu_coherence
            asu = asu_coherence(xs)
        except Exception:  # noqa: BLE001 - sanity must never block validation
            asu = None
        ghost_labels: set[str] = set()
        if asu:
            for g in asu["ghost_suspects"]:
                alerts.append({
                    "severity": "critical", "code": "ghost_atom_suspect",
                    "message": (f"{g['label']} ({g['element']}, occ "
                                f"{g['occupancy']}, Ueq {g['ueq']}): "
                                + "; ".join(g["reasons"])
                                + ". " + g["advice"])})
            ghost_labels = {g["label"] for g in asu["ghost_suspects"]}
            plain_detached = [d for d in asu["detached"]
                              if not set(d["labels"]) <= ghost_labels]
            if not framework_mode:
                # a 0-D crystal's counter-ions and solvent are not bonded
                # to anything, by symmetry or otherwise - they are judged
                # by identity in the fragment census below, not told to
                # "assemble"; only pieces that DO bond via symmetry belong here
                plain_detached = [d for d in plain_detached
                                  if d["attachment"] == "symmetry"]
            if plain_detached:
                frag_txt = "; ".join(
                    f"[{', '.join(d['labels'][:6])}]"
                    + ("..." if len(d["labels"]) > 6 else "")
                    + f" via {d['attachment']}"
                    for d in plain_detached[:5])
                alerts.append({
                    "severity": "warning", "code": "asu_detached",
                    "message": (f"{len(plain_detached)} fragment(s) not "
                                f"directly bonded to the main ASU fragment "
                                f"(refined into a symmetry image): {frag_txt}. "
                                "Run assemble_asu before delivering - viewers "
                                "draw these as floating pieces.")})

        # eta-bound rings (Cp / arene): a ligand, not five short contacts or
        # five ghosts (pa1 cage: five C at 2.4-2.6 A around each Zr)
        pi_seen: set[tuple] = set()
        for ring in conn.pi_ligands[:8]:
            pi_seen.add((ring["metal"].upper(),
                         frozenset(a.upper() for a in ring["ring_atoms"])))
            alerts.append({
                "severity": "info", "code": "pi_ligand",
                "message": (f"eta{ring['hapticity']}-C{ring['ring_size']} ring "
                            f"[{', '.join(ring['ring_atoms'])}] bound side-on to "
                            f"{ring['metal']} ({ring['metal_element']}; M-C "
                            f"{ring['m_c_range'][0]}-{ring['m_c_range'][1]} A, "
                            f"centroid {ring['centroid_d']} A, plane rms "
                            f"{ring['plane_rms']} A): recognised as a Cp/arene "
                            "ligand, counted as ONE ligand in the metal CN and "
                            "kept in the metal's fragment. Geometric call only - "
                            "confirm the ring chemistry (Cp-/arene) yourself.")})
        if len(conn.pi_ligands) > 8:
            alerts.append({"severity": "info", "code": "pi_ligand",
                           "message": f"... {len(conn.pi_ligands) - 8} more eta-bound "
                                      "rings not listed (see pi_ligands)"})
        # the audit sees rings the P1 graph does not (open fragments of a
        # broken Cp, rings with mislabelled N members, other ring sizes);
        # one alert per physical ring, never a duplicate of the above
        for ring in (mba["pi_ligands"] if mba else [])[:8]:
            key = (ring["metal"].upper(),
                   frozenset(a.upper() for a in ring["ring_labels"]))
            if key in pi_seen:
                continue
            pi_seen.add(key)
            kind = "ring" if ring["ring_closed"] else "open fragment"
            alerts.append({
                "severity": "info", "code": "pi_ligand",
                "message": (f"eta{ring['hapticity']}-"
                            f"{'C/N' if ring['n_members_labelled_N'] else 'C'}"
                            f"{ring['ring_size']} {kind} "
                            f"[{', '.join(ring['ring_labels'])}] bound face-on to "
                            f"{ring['metal']} ({ring['metal_element']}; M-C "
                            f"{ring['m_c_range'][0]}-{ring['m_c_range'][1]} A, "
                            f"centroid {ring['centroid_d']} A): counted as ONE "
                            f"ligand ({ring['sites']} coordination sites) in the "
                            "metal CN"
                            + (f". {ring['note']}" if ring.get("note") else ""))})

        if mba is not None:
            # CN from the audit: eta-rings count once (3 sites), H never
            # counted (pa2 hex-l0-r1: three O-H hydrogens at 2.6 A made Zr2
            # "CN=11"), suspect donors named
            impossible_of = {e["atom"].upper(): e.get("impossible_contacts")
                             for e in conn.coordination}
            for env in mba["metal_environments"]:
                if env["cn_plausible"] is None:
                    # D9: absence of a rule is not a pass - say so
                    alerts.append({
                        "severity": "info", "code": "metal_cn_unchecked",
                        "message": (f"{env['metal']} ({env['element']}) "
                                    f"CN={env['cn_sites']}: no coordination-"
                                    "number window is tabulated for this "
                                    "element, so the CN was NOT checked - "
                                    "judge it by hand; neighbours: "
                                    f"{env['neighbours'][:8]}")})
                    continue
                if env["cn_plausible"]:
                    continue
                imp = impossible_of.get(env["metal"].upper())
                alerts.append({
                    "severity": "warning", "code": "metal_cn",
                    "message": (f"{env['metal']} ({env['element']}) "
                                f"CN={env['cn_sites']} outside typical "
                                f"{env['expected_cn']} (donor atoms "
                                f"{env['cn_atoms']}, ligands {env['cn_ligands']}; "
                                "an eta-ring counts 3 sites, H never counted); "
                                f"neighbours: {env['neighbours'][:8]}"
                                + (f"; suspect donor labels: {env['suspect_donors']}"
                                   if env.get("suspect_donors") else "")
                                + (f"; impossible contacts not counted: {imp}"
                                   if imp else ""))})
        else:
            for env in conn.coordination:
                if env["cn_plausible"] is None:
                    alerts.append({
                        "severity": "info", "code": "metal_cn_unchecked",
                        "message": (f"{env['atom']} ({env['element']}) "
                                    f"CN={env['cn']}: "
                                    + env.get("cn_note", "no CN window "
                                              "tabulated; NOT checked"))})
                elif not env["cn_plausible"]:
                    alerts.append({
                        "severity": "warning",
                        "code": "metal_cn",
                        "message": (f"{env['atom']} ({env['element']}) CN={env['cn']} "
                                    f"outside typical {env['expected_cn']}; neighbors: "
                                    f"{env['neighbors'][:8]}"
                                    + (f"; impossible contacts not counted: "
                                       f"{env['impossible_contacts']}"
                                       if env.get("impossible_contacts") else ""))})

        # metal-bonded light atoms: the label is not the element
        if mba is not None:
            susp = mba["suspect_elements"]
            for s in susp[:_MAX_AUDIT_ALERTS]:
                others = s["metals"][1:]
                alerts.append({
                    "severity": _AUDIT_SEVERITY.get(s["severity"], "warning"),
                    "code": "metal_bonded_light_atom",
                    "message": (f"{s['label']} ({s['element']}) {s['d']:.2f} A from "
                                f"{s['metal']} ({s['metal_element']}"
                                + (f"; also {', '.join(others)}" if others else "")
                                + f"): {s['reason']}. Advice: {s['suggestion']}"
                                + _RETYPE_ADVICE)})
            if len(susp) > _MAX_AUDIT_ALERTS:
                alerts.append({
                    "severity": "info", "code": "metal_bonded_light_atom",
                    "message": (f"... {len(susp) - _MAX_AUDIT_ALERTS} more metal-"
                                "bonded light atoms with suspect labels not listed "
                                "(metal_bonded_audit.suspect_elements has them all)")})
            bonds = mba["suspect_bonds"]
            for b in bonds[:_MAX_AUDIT_ALERTS]:
                alerts.append({
                    "severity": _AUDIT_SEVERITY.get(b["severity"], "warning"),
                    "code": ("suspect_nn_bond" if b["kind"] == "N-N"
                             else "suspect_cc_bond"),
                    "message": (f"{b['a']}-{b['b']} {b['d']:.2f} A: {b['reason']}. "
                                f"Advice: {b['suggestion']}; retype with edit_atoms "
                                "reassign and re-refine")})
            if len(bonds) > _MAX_AUDIT_ALERTS:
                alerts.append({
                    "severity": "info", "code": "suspect_nn_bond",
                    "message": (f"... {len(bonds) - _MAX_AUDIT_ALERTS} more suspect "
                                "bonds not listed (metal_bonded_audit.suspect_bonds "
                                "has them all)")})
        elif mba_error:
            alerts.append({"severity": "info", "code": "metal_bonded_audit_failed",
                           "message": (f"metal-bonded light-atom audit did not run "
                                       f"({mba_error}); metal CN falls back to the "
                                       "P1 bonded graph")})

        # light-atom element consistency from the ADPs (reg1-ext2 case rz):
        # geometry cannot tell a nitro from a carboxylate, but a label with
        # the wrong electron count is compensated by Ueq after refinement.
        # Same physics as ueq_over_metal_light_neighbours above, generalised
        # to every light atom by using its OWN bonded neighbours as the
        # reference - so it reaches metal-free organics too.
        try:
            lac = audit_light_atom_elements(
                xs, parts=_parts_from_flags(ses.flags),
                n_refinements=len(ses.refinement_history),
                d_min=(ses.merge_info or {}).get("d_min"))
        except Exception as e:  # noqa: BLE001 - a hint never breaks validation
            lac = {"status": "error", "reason": f"{type(e).__name__}: {e}",
                   "flags": [], "nitro_vs_carboxylate_candidates": []}
            alerts.append({"severity": "info", "code": "light_atom_element_check",
                           "message": ("light-atom ADP element check did not "
                                       f"run ({lac['reason']})")})
        for f in lac.get("flags", [])[:_MAX_AUDIT_ALERTS]:
            nb = [f"{n['label']}:{n['ueq']:.4f}" for n in f["neighbours"]]
            alerts.append({
                "severity": ("warning" if f["confidence"] in ("high", "medium")
                             else "info"),
                "code": "light_atom_element_check",
                "message": (f"{f['kind']}: {f['label']} ({f['element']}) "
                            f"{f['reason']}. Neighbours: {nb}"
                            f". Confidence {f['confidence']}. {f['advice']}")})
        n_lac = len(lac.get("flags", []))
        if n_lac > _MAX_AUDIT_ALERTS:
            alerts.append({
                "severity": "info", "code": "light_atom_element_check",
                "message": (f"... {n_lac - _MAX_AUDIT_ALERTS} more light atoms "
                            "whose Ueq disagrees with their neighbours not "
                            "listed (light_atom_element_check.flags has them "
                            "all)")})
        for m in lac.get("nitro_vs_carboxylate_candidates", []):
            # only when BOTH readings agree: the neighbour-median band flagged
            # the atom AND its own terminal oxygens say the same thing
            if not (m.get("flagged_by_ueq_band") and m.get("suspect")):
                continue
            ox = [f"{o['label']}:{o['ueq']:.4f}"
                  for o in m["terminal_oxygens"]]
            alerts.append({
                "severity": "warning", "code": "nitro_vs_carboxylate",
                "message": (f"{m['label']} ({m['element']}): {m['reading']}. "
                            f"Ueq {m['ueq']} vs terminal O {ox}"
                            f" (median {m['terminal_o_median_ueq']}, ratio "
                            f"{m['ratio_over_terminal_o']}); X-O "
                            f"{m['x_o_distances']} A, angle sum "
                            f"{m['planarity_angle_sum_deg']} deg. "
                            f"{m['geometry_note']}. Confidence "
                            f"{m['confidence']} - a hint with its numbers, "
                            "not a verdict: settle it against the "
                            "composition's N allowance, the H count and an "
                            "omit map before retyping")})

        # lone atoms: in a framework every one is a ghost or pore solvent;
        # in a 0-D crystal a free Cl-/water is normal and only atoms with
        # no recognised identity are a problem
        if conn.isolated_atoms and framework_mode:
            alerts.append({"severity": "warning", "code": "isolated_atoms",
                           "message": f"isolated atoms (ghosts or unmodeled solvent; "
                                      f"system type {system_type}): "
                                      f"{conn.isolated_atoms[:10]}"})
        elif conn.isolated_atoms:
            recognised, unrecognised = [], []
            for lbl in conn.isolated_atoms:
                if lbl in ghost_labels:
                    continue    # carried by ghost_atom_suspect with its advice
                el = el_of_label.get(lbl, "?")
                if el == "O":
                    # the expert rule bans ANONYMOUS atoms: a lone O is
                    # water only when its label says so (O1W) - same rule
                    # as asu_sanity, otherwise the two alerts contradict
                    ident = (("solvent", "water, declared")
                             if _WATER_LABEL.fullmatch(lbl.upper()) else None)
                else:
                    ident = fragment_identity({el: 1})
                (recognised if ident else unrecognised).append(
                    f"{lbl} ({ident[1]})" if ident else lbl)
            if recognised:
                alerts.append({
                    "severity": "info", "code": "lone_ions_solvent",
                    "message": (f"lone atoms consistent with counter-ions / "
                                f"solvent (system type {system_type}, fragment-"
                                f"identity criteria): {recognised[:12]}"
                                + (f" and {len(recognised) - 12} more"
                                   if len(recognised) > 12 else "")
                                + ". Keep and name them (OW for water), check "
                                "Ueq and the charge balance against the "
                                "metal oxidation state.")})
            if unrecognised:
                alerts.append({
                    "severity": "warning", "code": "isolated_atoms",
                    "message": (f"isolated atoms with no recognised counter-ion "
                                f"/ solvent identity (system type {system_type}; "
                                f"a 0-D crystal does not explain these): "
                                f"{unrecognised[:10]}"
                                + (f" and {len(unrecognised) - 10} more"
                                   if len(unrecognised) > 10 else "")
                                + ". Spurious peaks or mislabelled ions (lone "
                                "O/N with collapsed Ueq = halide?) - "
                                "re-identify or delete-and-refine.")})
        if not framework_mode:
            small = [c for c in conn.fragment_census
                     if c["role"] == "small_unrecognised"]
            if small:
                txt = "; ".join(
                    f"[{', '.join(c['asu_labels'][:5])}] "
                    + "".join(f"{e}{n if n > 1 else ''}"
                              for e, n in sorted(c["elements"].items()))
                    for c in small[:5])
                alerts.append({
                    "severity": "warning", "code": "unrecognised_fragments",
                    "message": (f"{len(small)} small fragment(s) of 2-5 atoms "
                                f"matching no ligand, counter-ion or solvent "
                                f"(system type {system_type}): {txt}. Broken "
                                "pieces of a ligand, mislabelled solvent, or "
                                "spurious peaks - complete, re-identify or delete.")})

        for sc_pair in conn.short_contacts[:6]:
            a_el, b_el = (el_of_label.get(lb, "?") for lb in sc_pair["atoms"])
            hint = ""
            if a_el == b_el and sc_pair["d"] < 1.2:
                # pa1 cage-l0-r1: six Fe/Fe pairs at 0.73-0.78 A were split
                # sites never declared as PARTs - they read as bonds before
                hint = (" - two alternatives of one split site? declare "
                        "them as PARTs (model_disorder) so they never see "
                        "each other; if not, one of them is spurious")
            alerts.append({"severity": "critical", "code": "short_contact",
                           "message": f"impossibly short contact {sc_pair['atoms']} "
                                      f"= {sc_pair['d']} A{hint}"})
        if len(conn.short_contacts) > 6:
            alerts.append({"severity": "info", "code": "short_contact",
                           "message": f"... {len(conn.short_contacts) - 6} more "
                                      "impossibly short contacts not listed "
                                      "(connectivity.short_contacts has them all)"})

        # periodicity: a framework must be 2-D/3-D; a molecule is 0-D by
        # nature and is not penalised for it; undetermined = say so
        if framework_mode and conn.framework_dimensionality < 2:
            alerts.append({"severity": "warning", "code": "low_dimensionality",
                           "message": f"framework dimensionality = "
                                      f"{conn.framework_dimensionality} (expected 2-3 "
                                      f"for a MOF; system type {system_type}, "
                                      f"{type_source}); structure may be incomplete "
                                      "or a linker is not bonded at the cutoff. If "
                                      "this is really a discrete molecule/cage, "
                                      "re-run without expect_framework."})
        elif system_type == "unknown":
            alerts.append({"severity": "info", "code": "system_type_undetermined",
                           "message": (f"system type undetermined - "
                                       f"{conn.system_type_evidence.get('rationale', '')}. "
                                       "Periodicity and free-fragment criteria were "
                                       "not applied; they will once the model shows "
                                       "what it is.")})

        # composition check
        comp = ses.dataset.composition
        model_counts: dict[str, float] = {}
        order_z = xs.space_group().order_z()
        for sc in xs.scatterers():
            el = sc.scattering_type.strip().capitalize()
            model_counts[el] = model_counts.get(el, 0.0) + sc.occupancy * sc.multiplicity()
        comp_note = None
        if comp and comp.z:
            expected_cell = {el: n * comp.z for el, n in comp.elements.items() if el != "H"}
            deviations = []
            for el, exp_n in expected_cell.items():
                got = model_counts.get(el, 0.0)
                if exp_n > 0 and abs(got - exp_n) / exp_n > 0.3:
                    deviations.append(f"{el}: model {got:.0f} vs expected {exp_n:.0f} per cell")
            if deviations:
                comp_note = deviations
                alerts.append({"severity": "info", "code": "composition_deviation",
                               "message": "; ".join(deviations[:5])})

        # metal presence sanity
        if comp and any(is_metal(e) for e in comp.elements) and \
                not any(is_metal(e) for e in model_counts):
            alerts.append({"severity": "critical", "code": "no_metal",
                           "message": "expected metal not present in model"})

        last = ses.last_refinement()
        stats = last.as_dict() if last else {}

        # absolute structure: a non-centrosymmetric model with a decent
        # anomalous scatterer (Z >= 14, Si and up, for Mo radiation) should
        # carry a Flack x before delivery - run_shelxl reads it from the lst
        light = {"H", "D", "He", "Li", "Be", "B", "C", "N", "O", "F",
                 "Ne", "Na", "Mg", "Al"}
        if (ses.model is not None
                and not ses.model.space_group().is_centric()
                and any(sc.scattering_type.strip().capitalize() not in light
                        for sc in ses.model.scatterers())
                and stats.get("flack") is None):
            alerts.append({
                "severity": "info", "code": "absolute_structure_undetermined",
                "message": ("non-centrosymmetric structure with anomalous "
                            "scatterers but no Flack x on record - "
                            "run_shelxl reports it; judge ~0 keep / ~1 "
                            "invert_structure / ~0.5 racemic twin / "
                            "su>0.3 disclose as undetermined")})

        # confidence is scored over EVERY alert, adjudicated or not: a
        # self-declared "I looked at it" must not be able to raise the score
        confidence = compute_confidence(stats, alerts, conn.framework_dimensionality,
                                        system_type)
        # where a second position would be (reg4/5/6-dbu: the agent
        # rejected the split with a new hypothesis each time; the numbers
        # answering them were all in the model)
        try:
            from ..refine.disorder_candidates import disorder_candidates
            _split = {str(m.get("label", "")).upper()
                      for g in (ses.flags.get("disorder_groups") or [])
                      for m in (g.get("members") or [])}
            _split |= {str(k).upper()
                       for k in (ses.flags.get("parts_extra") or {})}
            dcs = disorder_candidates(xs, ses.flags.get("diff_map_peaks"),
                                      exclude=_split)
        except Exception as e:  # noqa: BLE001 - a hint never breaks validation
            dcs = {"candidates": [], "error": f"{type(e).__name__}: {e}"}
        for c in dcs.get("candidates", [])[:_MAX_AUDIT_ALERTS]:
            alerts.append({"severity": "info", "code": "disorder_candidate",
                           "message": f"{c['reading']} {c['next']}"})

        open_alerts, adjudicated = self._split_adjudicated(ses, alerts)
        type_evidence = {**conn.system_type_evidence, "source": type_source,
                         "inferred_type": conn.system_type}

        ses.validation = {
            "alerts": alerts,
            "adjudicated": adjudicated,
            "connectivity": conn.summary(),
            "confidence": confidence,
            "system_type": system_type,
            "system_type_evidence": type_evidence,
            "criteria_applied": criteria,
            "pi_ligands": conn.pi_ligands,
            "fragment_census": conn.fragment_census,
            "model_composition_per_cell": {k: round(v, 1) for k, v in model_counts.items()},
            "metal_bonded_audit": mba,
            "light_atom_element_check": lac,
            "disorder_candidates": dcs,
        }
        mba_summary = None
        if mba is not None:
            mba_summary = {
                "summary": mba["summary"], "note": mba["note"],
                "n_suspect_elements": len(mba["suspect_elements"]),
                "suspect_elements": [_compact_suspect(s)
                                     for s in mba["suspect_elements"][:20]],
                "n_suspect_bonds": len(mba["suspect_bonds"]),
                "suspect_bonds": [{k: b[k] for k in ("a", "b", "d", "kind", "severity")}
                                  for b in mba["suspect_bonds"][:20]],
                "metal_environments": [
                    {k: v for k, v in e.items() if k != "cn_convention"}
                    for e in mba["metal_environments"][:12]],
                "cn_convention": (mba["metal_environments"][0]["cn_convention"]
                                  if mba["metal_environments"] else None),
                "pi_ligands": mba["pi_ligands"][:12],
                "plausible_metal_bonds": mba["plausible_metal_bonds"][:12],
            }
        return ToolResult(ok=True, summary={
            "n_alerts": len(open_alerts),
            "alerts": open_alerts,
            **({"n_adjudicated": len(adjudicated),
                "adjudicated": adjudicated,
                "adjudicated_note": (
                    "settled earlier in this session; still counted in the "
                    "confidence score and disclosed in the report")}
               if adjudicated else {}),
            "system_type": system_type,
            "system_type_label": type_label,
            "system_type_evidence": type_evidence,
            "criteria_applied": criteria,
            "framework_dimensionality": conn.framework_dimensionality,
            "largest_fragment": conn.fragments[0] if conn.fragments else None,
            "fragment_census": conn.fragment_census[:12],
            "pi_ligands": conn.pi_ligands[:12],
            "metal_coordination": conn.coordination[:8],
            **({"metal_bonded_audit": mba_summary} if mba_summary else {}),
            "light_atom_element_check": lac,
            "disorder_candidates": dcs,
            "confidence": confidence,
            "composition_deviation": comp_note,
            **({"asu_sanity": {
                "n_detached_atoms": asu["n_detached_atoms"],
                "detached": asu["detached"][:6],
                "ghost_suspects": asu["ghost_suspects"],
            }} if asu else {}),
        })

    # -- adjudication ------------------------------------------------------
    # Repeat validate_structure runs re-report the same settled alerts; the
    # process audit found agents either re-investigating them or (worse)
    # skimming past the whole list. Adjudicated alerts move to their own
    # section WITH the reason - they are never dropped.
    @staticmethod
    def _update_adjudications(ses, entries) -> str | None:
        if not isinstance(entries, list):
            return "mark_adjudicated must be a list of {code, subject, reason}"
        store = dict(ses.flags.get("adjudicated_alerts") or {})
        for e in entries:
            if not isinstance(e, dict) or not str(e.get("code") or "").strip():
                return ("each mark_adjudicated entry needs a 'code' (the "
                        "alert code) and a 'reason'")
            code = str(e["code"]).strip()
            subject = str(e.get("subject") or "").strip()
            # labels are matched case-insensitively: run_shelxl adopt writes
            # them back upper-case (pa2 hex-l0-r1: 'Zr2' stopped matching)
            key = f"{code}|{subject.upper()}"
            if e.get("reason", "") is None:
                store.pop(key, None)
                continue
            reason = str(e.get("reason") or "").strip()
            if len(reason) < 8:
                return (f"adjudicating '{code}' needs a real reason (what you "
                        "checked and what it showed), not a placeholder")
            store[key] = {"code": code, "subject": subject, "reason": reason}
        ses.flags["adjudicated_alerts"] = store
        return None

    @staticmethod
    def _split_adjudicated(ses, alerts: list[dict]) -> tuple[list[dict],
                                                             list[dict]]:
        store = ses.flags.get("adjudicated_alerts") or {}
        if not store:
            return alerts, []
        live, settled = [], []
        for a in alerts:
            hit = None
            for rec in store.values():
                if rec["code"] != a.get("code"):
                    continue
                # empty subject adjudicates every alert of that code;
                # case-insensitive (SHELXL upper-cases labels on adopt)
                if rec["subject"] and rec["subject"].upper() not in str(
                        a.get("message", "")).upper():
                    continue
                hit = rec
                break
            if hit is None:
                live.append(a)
            else:
                settled.append({**a, "adjudicated_reason": hit["reason"]})
        return live, settled
