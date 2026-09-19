"""solvent_mask diagnoses its own failure by diffing against the model of
the last mask that worked.

pa2 cage-l0-r2 / cage-l2-r2: every solvent_mask call on a changing model
returned a different electron count (2342 -> 1304 -> ... -> 694; 2821 ->
... -> 502 -> negative integral). The agents read "NEGATIVE / diverged" as
"the mask is unstable" and delivered unmasked at R1 0.22-0.28 while a
masked node at R1 0.12 sat in their tree. A crystallographer's first move
is to checkout the last converged-mask node and diff the two models; the
tool now does that diff (mask_diagnosis) and says what it means.

Everything here is synthetic (a Cu complex in P21/c, an organic cube in
P1): no element- or crystal-specific constant is exercised.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from cctbx import crystal, xray
from cctbx.array_family import flex

from crystalpilot.tools import mask_diagnosis as md
from crystalpilot.tools.mask_diagnosis import (diagnose, mask_info_of,
                                               model_delta, model_snapshot,
                                               params_diff,
                                               previous_mask_from_store)
from crystalpilot.tools.mask_tools import BypassMask, SolventMask

CELL = (10.0, 11.0, 12.0, 90.0, 95.0, 90.0)
#: a Cu complex fragment, all general positions of P21/c (multiplicity 4)
BASE = [
    ("CU1", "Cu", (0.25, 0.10, 0.30), 1.0, 0.02),
    ("N1", "N", (0.30, 0.20, 0.35), 1.0, 0.03),
    ("C1", "C", (0.35, 0.25, 0.42), 1.0, 0.03),
    ("C2", "C", (0.42, 0.30, 0.48), 1.0, 0.03),
    ("O1", "O", (0.15, 0.05, 0.22), 1.0, 0.04),
    ("O2", "O", (0.12, 0.40, 0.10), 1.0, 0.04),
    ("C3", "C", (0.60, 0.15, 0.70), 1.0, 0.03),
]
#: Z x occupancy x multiplicity, summed over the non-H atoms of BASE
BASE_ELECTRONS = (29 + 7 + 6 * 3 + 8 * 2) * 4


def _structure(atoms=BASE, sg="P 21/c", cell=CELL):
    cs = crystal.symmetry(unit_cell=cell, space_group_symbol=sg)
    xs = xray.structure(crystal_symmetry=cs)
    for lbl, el, site, occ, u in atoms:
        xs.add_scatterer(xray.scatterer(label=lbl, site=site,
                                        scattering_type=el, occupancy=occ,
                                        u=u))
    xs.scattering_type_registry(table="it1992")
    return xs


def _replace(atoms, which, **changes):
    out = []
    for lbl, el, site, occ, u in atoms:
        if lbl == which:
            el = changes.get("el", el)
            site = changes.get("site", site)
            occ = changes.get("occ", occ)
            u = changes.get("u", u)
            lbl = changes.get("label", lbl)
        out.append((lbl, el, site, occ, u))
    return out


# ==========================================================================
# model_delta as a pure function
# ==========================================================================
class TestModelDelta:
    def test_identical_model_is_an_empty_delta(self):
        d = model_delta(_structure(), _structure())
        assert d["is_empty"] is True
        assert d["summary"] == "no model change"
        assert d["n_atoms"] == {"before": 7, "after": 7}
        assert d["matched"]["total"] == 7 and d["matched"]["by_label"] == 7
        e = d["non_h_electrons_per_cell"]
        assert e["before"] == e["after"] == pytest.approx(BASE_ELECTRONS)
        assert e["change_pct"] == 0.0
        assert d["symmetry_changed"] is False

    def test_renamed_atom_is_the_same_atom(self):
        now = _structure(_replace(BASE, "C2", label="C9"))
        d = model_delta(_structure(), now)
        assert d["is_empty"] is True
        assert d["n_atoms_renamed"] == 1
        assert d["atoms_renamed"] == [{"from": "C2", "to": "C9"}]
        assert d["atoms_added"] == [] and d["atoms_removed"] == []
        assert d["matched"]["by_site"] == 1
        assert "1 atom renamed (same sites)" in d["summary"]

    def test_symmetry_image_of_a_site_matches(self):
        """The same atom stored as a symmetry equivalent (and renamed) is
        found under the space group, not treated as removed + added."""
        prev = _structure()
        op = next(o for o in prev.space_group().all_ops()
                  if not o.is_unit_mx())
        image = op * (0.30, 0.20, 0.35)
        assert max(abs(a - b) for a, b in zip(image, (0.30, 0.20, 0.35))) \
            > 0.2                                  # genuinely a different site
        now = _structure(_replace(BASE, "N1", label="N7", site=image))
        d = model_delta(prev, now)
        assert d["is_empty"] is True
        assert d["atoms_renamed"] == [{"from": "N1", "to": "N7"}]
        assert d["n_atoms_removed"] == d["n_atoms_added"] == 0

    def test_added_and_removed_atoms(self):
        now_atoms = [a for a in BASE if a[0] != "O2"]
        now_atoms.append(("N2", "N", (0.70, 0.60, 0.20), 1.0, 0.03))
        d = model_delta(_structure(), _structure(now_atoms))
        assert d["is_empty"] is False
        assert d["atoms_removed"] == [{"label": "O2", "element": "O"}]
        assert d["atoms_added"] == [{"label": "N2", "element": "N"}]
        e = d["non_h_electrons_per_cell"]
        assert e["before"] == pytest.approx(BASE_ELECTRONS)
        assert e["after"] == pytest.approx(BASE_ELECTRONS - 8 * 4 + 7 * 4)
        assert "lost 1 non-H atom (1 O)" in d["summary"]
        assert "gained 1 non-H atom (1 N)" in d["summary"]

    def test_element_reassignment_on_the_same_site(self):
        d = model_delta(_structure(), _structure(_replace(BASE, "C1", el="N")))
        assert d["element_reassigned"] == [{"label": "C1", "from": "C",
                                            "to": "N"}]
        assert d["n_atoms_added"] == d["n_atoms_removed"] == 0
        e = d["non_h_electrons_per_cell"]
        assert e["after"] - e["before"] == pytest.approx(4.0)
        assert "1 element reassignment (C1 C->N)" in d["summary"]
        assert "verify the element reassignment (C1)" in md.next_steps(d)

    def test_occupancy_and_u_changes_beyond_tolerance(self):
        atoms = _replace(_replace(BASE, "O1", occ=0.5), "C3", u=0.08)
        d = model_delta(_structure(), _structure(atoms))
        assert d["occupancy_changed"] == [{"label": "O1", "from": 1.0,
                                           "to": 0.5}]
        assert d["adp"]["u_changed"] == [{"label": "C3", "from": 0.03,
                                          "to": 0.08}]
        assert d["adp"]["iso_to_aniso"] == 0
        e = d["non_h_electrons_per_cell"]
        assert e["before"] - e["after"] == pytest.approx(8 * 0.5 * 4)
        assert "occupancy changed on 1 atom (O1 1.00->0.50)" in d["summary"]
        assert "U changed by > 0.01 A^2 on 1 atom (C3 0.030->0.080)" \
            in d["summary"]
        # drift below the tolerances is not a model change
        drift = _replace(_replace(BASE, "O1", occ=0.98), "C3", u=0.035)
        assert model_delta(_structure(), _structure(drift))["is_empty"]

    def test_iso_to_aniso_is_counted_without_a_u_jump(self):
        now = _structure()
        sc = next(s for s in now.scatterers() if s.label == "CU1")
        sc.convert_to_anisotropic(now.unit_cell())
        d = model_delta(_structure(), now)
        assert d["adp"]["iso_to_aniso"] == 1
        assert d["adp"]["n_u_changed"] == 0
        assert d["is_empty"] is False
        assert "1 atom isotropic -> anisotropic" in d["summary"]
        assert "check the ADPs" in md.next_steps(d)

    def test_hydrogens_are_counted_not_listed(self):
        atoms = list(BASE) + [
            ("H1", "H", (0.37, 0.27, 0.50), 1.0, 0.04),
            ("H2", "H", (0.44, 0.33, 0.55), 1.0, 0.04),
            ("H3", "H", (0.62, 0.17, 0.78), 1.0, 0.04)]
        d = model_delta(_structure(), _structure(atoms))
        assert d["hydrogens"] == {"before": 0, "after": 3, "added": 3,
                                  "removed": 0}
        assert d["atoms_added"] == [] and d["n_atoms_added"] == 0
        assert d["n_atoms"] == {"before": 7, "after": 10}
        assert d["n_non_h_atoms"] == {"before": 7, "after": 7}
        e = d["non_h_electrons_per_cell"]
        assert e["before"] == e["after"]
        assert "H 0 -> 3" in d["summary"]
        assert d["is_empty"] is False

    def test_moved_atom_is_not_a_removal_plus_an_addition(self):
        now = _structure(_replace(BASE, "C3", site=(0.68, 0.15, 0.70)))
        d = model_delta(_structure(), now)
        assert d["n_atoms_removed"] == d["n_atoms_added"] == 0
        assert len(d["atoms_moved"]) == 1
        assert d["atoms_moved"][0]["label"] == "C3"
        assert d["atoms_moved"][0]["d_A"] == pytest.approx(0.8, abs=0.02)
        assert d["matched"]["moved"] == 1
        assert d["is_empty"] is False
        assert "1 atom moved 0.3-1.5 A (C3 0.8 A)" in d["summary"]

    def test_symmetry_change_falls_back_to_labels(self):
        prev = _structure(sg="P 21/c")
        now = _structure(sg="P -1")
        d = model_delta(prev, now)
        assert d["symmetry_changed"] is True
        assert d["matched"]["total"] == 7
        assert d["n_atoms_added"] == d["n_atoms_removed"] == 0
        assert d["summary"].startswith("cell/space group changed")
        assert "-P 2ybc" in d["symmetry"]["before"]

    def test_snapshot_round_trip_is_json_and_diffs_like_the_structure(self):
        snap = model_snapshot(_structure())
        snap = json.loads(json.dumps(snap))
        d = model_delta(snap, _structure(_replace(BASE, "O2", el="N")))
        assert d["element_reassigned"] == [{"label": "O2", "from": "O",
                                            "to": "N"}]
        assert snap["atoms"][0]["mult"] == 4


# ==========================================================================
# the node store: which node was the last successful mask computed on?
# ==========================================================================
def _session(xs):
    from crystalpilot.core.dataset import ReflectionDataset
    from crystalpilot.pipeline.session import SolveSession
    ses = SolveSession(dataset=ReflectionDataset(intensities=None,
                                                 wavelength=0.71073))
    ses.model = xs
    ses.symmetry = xs.crystal_symmetry()
    return ses


def _snapshot(r1: float):
    from crystalpilot.pipeline.session import RefinementSnapshot
    return RefinementSnapshot(label="t", r1_strong=r1, r1_all=r1 + 0.02,
                              wr2=2.5 * r1, goof=1.1, n_params=50,
                              n_reflections=500)


def _mask_flags(xs, electrons=1304.0, mask_id="abc123"):
    f_mask = xs.structure_factors(d_min=1.5).f_calc()
    info = {"mask_id": mask_id, "computed_at": "2026-09-03T10:00:00",
            "n_voids": 1, "n_voids_masked": 1,
            "voids": [{"void": 1, "volume_A3": 500.0,
                       "electrons": electrons, "masked": True}],
            "total_solvent_electrons_per_cell": electrons,
            "solvent_volume_A3": 500.0, "solvent_volume_pct_of_cell": 38.0,
            "solvent_mask_converged": True,
            "bypass": {"cycles_run": 5, "converged": True,
                       "diverged": False}}
    params = {"solvent_radius": 1.2, "shrink_truncation_radius": 1.2,
              "resolution_factor": 0.25, "d_min": None,
              "min_void_volume": 8.0, "max_cycles": 10}
    return {"f_mask": f_mask, "solvent_mask_info": info,
            "solvent_mask_params": params}


def _project_ctx(proj, ses):
    """A ToolContext whose RunStore sits where a project's does, so the
    session-scoped tool finds the node store (as the ghost ledger does)."""
    from crystalpilot.core.events import RunStore
    from crystalpilot.tools.base import ToolContext
    store = RunStore(proj / ".crystalpilot" / "refine" / "runs", run_id="t")
    return ToolContext(store=store, session=ses)


@pytest.fixture()
def masked_tree(tmp_path):
    """n0000 import -> n0001 solvent_mask (1304 e, model = BASE) -> n0002
    edit_atoms (O2 deleted, same mask carried forward) -> n0003 refine
    (R1 0.121 with that mask). The session is left at n0003."""
    from crystalpilot.refine.data_versions import measurement_context
    from crystalpilot.refine.nodes import NodeStore
    proj = tmp_path / "proj"
    proj.mkdir()
    store = NodeStore(proj)
    ses = _session(_structure())
    # since 2026-09-08 a node's metrics count as CURRENT only when the
    # session records a completed measurement against a bound observation
    # revision - what project.invoke_tool notes after a real refine. This
    # bare-store fixture states both the way the project would: a minimal
    # app-managed revision on disk (the store resolves it at every commit)
    # and the measurement marker on the refine commit.
    import json as _json
    rev = proj / ".crystalpilot" / "refine" / "data" / "d000001"
    rev.mkdir(parents=True)
    (rev / "observations.hkl").write_text(
        "   0   0   0    0.00    0.00\n", encoding="ascii")
    (rev / "data.json").write_text(_json.dumps({
        "schema": 1, "id": "d000001", "transaction": None, "sources": [],
        "bytes": 30, "format": "SHELX HKL", "processing": ["test fixture"],
        "scale_applied": 1.0, "input_context": {}}), encoding="utf-8")
    ses._crystalpilot_data_revision = "d000001"
    store.commit(ses, tool="import", params={})
    ses.refinement_history.append(_snapshot(0.20))       # unmasked R1
    ses.flags.update(_mask_flags(ses.model))
    store.commit(ses, tool="solvent_mask", params={"max_cycles": 10})
    ses.model = _structure([a for a in BASE if a[0] != "O2"])
    store.commit(ses, tool="edit_atoms",
                 params={"operations": [{"action": "delete",
                                         "atoms": ["O2"]}]})
    ses.refinement_history.append(_snapshot(0.121))      # masked R1
    ses._crystalpilot_new_measurement = measurement_context(
        ses, "refine", {"solvent_mask_used": True})
    store.commit(ses, tool="refine", params={"n_cycles": 4})
    assert store.state()["active_node"] == "n0003"
    return proj, store, ses


class TestPreviousMaskFromStore:
    def test_finds_the_node_the_mask_was_computed_on(self, masked_tree):
        proj, store, ses = masked_tree
        prev = previous_mask_from_store(store, ses.flags["solvent_mask_info"])
        assert prev["node"] == "n0001"
        assert prev["tool"] == "solvent_mask"
        assert prev["electrons"] == 1304.0
        assert prev["n_voids_masked"] == 1
        assert prev["solvent_volume_A3"] == 500.0
        assert prev["converged"] is True
        assert prev["bypass_cycles"] == 5
        assert prev["timestamp"] and prev["timestamp"][:2] == "20"
        # the mask node's own R1 is the unmasked one from before it
        assert prev["r1"] == 0.20 and prev["r1_is_current"] is False
        assert "before this node" in prev["r1_note"]
        # ...and the best refinement that used this mask is named
        assert prev["best_r1_with_this_mask"] == {"node": "n0003",
                                                  "r1": 0.121}
        assert prev["relation"] == "ancestor of the active node"
        assert prev["commits_since"] == 2
        assert prev["n_nodes_with_this_mask"] == 3
        assert prev["active_node"] == "n0003"
        assert Path(prev["_model_path"]).name == "model.res"
        assert prev["params"]["solvent_radius"] == 1.2
        assert prev["weights"] == {"a": 0.1, "b": 0.0}

    def test_session_without_mask_flags_still_finds_the_ancestor(
            self, masked_tree):
        """A failed re-mask that dropped the flags, or a checkout of a
        pre-mask node: the ancestry still knows where the mask was."""
        proj, store, ses = masked_tree
        assert previous_mask_from_store(store, None)["node"] == "n0001"

    def test_other_branch_fallback(self, masked_tree):
        proj, store, ses = masked_tree
        store.branch("alt", from_ref="n0000")
        prev = previous_mask_from_store(store, None)
        assert prev["node"] == "n0001"
        assert prev["relation"].startswith("another branch")
        assert prev["active_node"] == "n0000"

    def test_no_mask_anywhere_is_none(self, tmp_path):
        from crystalpilot.refine.nodes import NodeStore
        proj = tmp_path / "bare"
        proj.mkdir()
        store = NodeStore(proj)
        store.commit(_session(_structure()), tool="import", params={})
        assert previous_mask_from_store(store, None) is None

    def test_truncated_node_info_is_identified_and_recovered(self, tmp_path):
        """node.json keeps the mask info through nodes._shrink (4000 chars):
        a many-void mask is stored as {'_truncated': prefix}. The identity
        and the scalars are read off the prefix, the full info off the
        node's f_mask.pkl."""
        from libtbx import easy_pickle
        full = _mask_flags(_structure(), electrons=777.0, mask_id="m777")
        info = full["solvent_mask_info"]
        info["voids"] = [dict(info["voids"][0], void=i + 1)
                         for i in range(80)]
        dumped = json.dumps(info, ensure_ascii=False, default=str)
        assert len(dumped) > 4000
        meta = {"id": "n0005", "mask": {"info": {"_truncated": dumped[:4000]},
                                        "params": full["solvent_mask_params"]}}
        assert md._info_key(meta["mask"]["info"]) == "id:m777"
        assert md._scalar(meta["mask"]["info"], "n_voids_masked") == 1
        assert md._scalar(meta["mask"]["info"], "mask_id") == "m777"
        ndir = tmp_path / "n0005"
        ndir.mkdir()
        assert mask_info_of(meta, ndir)["_truncated"]      # no pkl yet
        easy_pickle.dump(str(ndir / "f_mask.pkl"),
                         {"f_mask": full["f_mask"], "info": info,
                          "params": full["solvent_mask_params"]})
        got = mask_info_of(meta, ndir)
        assert got["total_solvent_electrons_per_cell"] == 777.0
        assert len(got["voids"]) == 80
        # a pre-mask_id node (older campaign) is keyed by its text
        old = {"n_voids": 1, "n_voids_masked": 1,
               "total_solvent_electrons_per_cell": 12.0}
        assert md._info_key(old).startswith("txt:")
        assert md._info_key({"n_voids": 0, "n_voids_masked": 0}) is None
        assert md._info_key(None) is None

    def test_diagnosis_assembly_against_the_store(self, masked_tree):
        """The failure block: previous mask node, delta (O2 deleted since
        n0001), electron bookkeeping, and a reading that follows."""
        proj, store, ses = masked_tree
        ctx = _project_ctx(proj, ses)
        params = dict(ses.flags["solvent_mask_params"])
        diag = diagnose(ctx, ses, outcome="negative_dropped",
                        prev_info=ses.flags["solvent_mask_info"],
                        prev_snapshot=None, current_electrons=None,
                        params=params, kept_previous=True)
        assert diag["outcome"] == "negative_dropped"
        assert diag["previous_mask_source"] == "project node store"
        prev = diag["previous_mask"]
        assert prev["node"] == "n0001" and "_model_path" not in prev
        assert diag["active_node"] == "n0003"
        delta = diag["model_delta"]
        assert delta["atoms_removed"] == [{"label": "O2", "element": "O"}]
        assert delta["n_atoms_added"] == 0
        e = delta["non_h_electrons_per_cell"]
        assert e["before"] - e["after"] == pytest.approx(8 * 4)
        assert diag["electron_change_pct"] is None      # no new count
        assert diag["mask_params_changed"] == []
        assert diag["scale_weights"]["changed"] is False
        assert diag["rule"] == md.RULE
        r = diag["reading"]
        assert "node n0001" in r and "1304 e" in r and "R1 0.200" in r
        assert "best R1 with it 0.121 at node n0003" in r
        assert "lost 1 non-H atom (1 O)" in r
        assert "lighter" in r and "not because the void is empty" in r
        assert "The last converged mask (node n0001) is kept" in r
        assert "checkout n0001 and compare_nodes(n0001, n0003)" in r
        assert "restore or explain the 1 removed atom" in r
        assert "do not delete atoms and recompute the mask in the same step" \
            in r

    def test_no_model_change_reads_as_a_parameter_effect(self, masked_tree):
        """The counter-example: same model as the mask node."""
        proj, store, ses = masked_tree
        store.set_active("n0001")            # back on the mask node's model
        ses.model = _structure()
        ctx = _project_ctx(proj, ses)
        params = dict(ses.flags["solvent_mask_params"])
        diag = diagnose(ctx, ses, outcome="negative_dropped",
                        prev_info=ses.flags["solvent_mask_info"],
                        prev_snapshot=None, current_electrons=None,
                        params=params, kept_previous=False)
        assert diag["model_delta"]["is_empty"] is True
        r = diag["reading"]
        assert r.startswith("No model change since node n0001")
        assert "mask-parameter or grid effect" in r
        assert "parameters are identical too" in r
        assert "not evidence of an empty void" in r
        assert "checkout n0001 to continue" in r        # nothing kept
        # ...and with a changed probe radius the reading names it
        diag2 = diagnose(ctx, ses, outcome="converged",
                         prev_info=ses.flags["solvent_mask_info"],
                         prev_snapshot=None, current_electrons=900.0,
                         params={**params, "solvent_radius": 1.0},
                         kept_previous=False)
        assert diag2["mask_params_changed"] == [
            {"param": "solvent_radius", "previous": 1.2, "now": 1.0}]
        assert diag2["electron_change_pct"] == pytest.approx(-31.0, abs=0.1)
        assert "Changed in this call: solvent_radius 1.2 -> 1.0" \
            in diag2["reading"]
        assert "The count moved -31% on an unchanged model - a grid/" \
               "parameter effect" in diag2["reading"]

    def test_success_with_a_big_count_change_names_the_model_change(
            self, masked_tree):
        proj, store, ses = masked_tree
        ctx = _project_ctx(proj, ses)
        diag = diagnose(ctx, ses, outcome="converged",
                        prev_info=ses.flags["solvent_mask_info"],
                        prev_snapshot=None, current_electrons=694.0,
                        params=dict(ses.flags["solvent_mask_params"]),
                        kept_previous=False)
        assert diag["electron_change_pct"] == pytest.approx(-46.8, abs=0.1)
        r = diag["reading"]
        assert "The count moved -47%" in r
        assert "model-change signal, not mask instability" in r
        assert "the mask absorbs whatever the model lost" in r

    def test_no_previous_mask_reads_honestly(self, tmp_path):
        from crystalpilot.refine.nodes import NodeStore
        proj = tmp_path / "bare"
        proj.mkdir()
        ses = _session(_structure())
        NodeStore(proj).commit(ses, tool="import", params={})
        diag = diagnose(_project_ctx(proj, ses), ses,
                        outcome="negative_dropped", prev_info=None,
                        prev_snapshot=None, current_electrons=None,
                        params={}, kept_previous=False)
        assert diag["previous_mask"] is None
        assert diag["model_delta"] is None
        assert diag["reading"].startswith(
            "No earlier successful solvent mask is on record")
        assert "not about the void being empty" in diag["reading"]

    def test_params_diff(self):
        assert params_diff({"solvent_radius": 1.2, "d_min": None},
                           {"solvent_radius": 1.2, "d_min": None}) == []
        assert params_diff({"solvent_radius": 1.2},
                           {"solvent_radius": 1.2, "d_min": 1.0}) == [
            {"param": "d_min", "previous": None, "now": 1.0}]


class TestReadingFollowsTheDelta:
    """The sentences change with the delta and the outcome, not with a
    script: heavier / lighter / electron-neutral models and the three
    non-success outcomes each get their own second sentence."""

    PREV = {"node": "n0031", "electrons": 1304.0, "r1": 0.121,
            "converged": True, "params": {}}

    def _delta(self, now_atoms):
        return model_delta(_structure(), _structure(now_atoms))

    def test_heavier_model_with_a_negative_integral(self):
        atoms = list(BASE) + [("BR1", "Br", (0.80, 0.80, 0.80), 1.0, 0.05)]
        r = md.compose_reading("negative_dropped", self.PREV,
                               self._delta(atoms), None, True, [], "n0040")
        assert "gained 1 non-H atom (1 Br)" in r
        assert "The model gained scattering, yet the void integral went " \
               "negative" in r
        assert "the void is not empty" in r
        assert "check the 1 added atom against the pre-mask difference map" \
            in r
        assert "compare_nodes(n0031, n0040)" in r

    def test_electron_neutral_change(self):
        atoms = list(BASE) + [("H1", "H", (0.37, 0.27, 0.50), 1.0, 0.04)]
        r = md.compose_reading("negative_dropped", self.PREV,
                               self._delta(atoms), None, False, [], None)
        assert "H 0 -> 1" in r
        assert "The scattering total is unchanged" in r
        assert "not from an empty void" in r
        assert "No mask is stored now - checkout n0031" in r
        assert "check the H placement" in r

    def test_diverged_and_not_converged_outcomes(self):
        lighter = self._delta([a for a in BASE if a[0] != "CU1"])
        r = md.compose_reading("diverged", self.PREV, lighter, -40.0,
                               False, [], "n0040")
        assert "lost 1 non-H atom (1 Cu)" in r
        assert "runaway is the model change speaking, not mask instability" \
            in r
        r2 = md.compose_reading("not_converged", self.PREV, lighter, -40.0,
                                False, [], "n0040")
        assert "did not settle on this changed model" in r2
        assert "restore or explain the 1 removed atom" in r2
        assert r2.endswith("do not delete atoms and recompute the mask in "
                           "the same step.")

    def test_small_change_on_a_changed_model_is_not_alarmed(self):
        moved = self._delta(_replace(BASE, "C3", site=(0.66, 0.15, 0.70)))
        r = md.compose_reading("converged", self.PREV, moved, 4.0, False,
                               [], "n0040")
        assert "The count moved +4%, within the model-change signal " \
               "threshold" in r
        assert "check the 1 moved atom" in r

    def test_model_unavailable_is_said_not_hidden(self):
        r = md.compose_reading("negative_dropped", self.PREV, None, None,
                               True, [], "n0040", why="model.res missing")
        assert "could not be loaded for a diff: model.res missing" in r
        assert "compare_nodes(n0031, n0040)" in r
        assert "is kept in the session" in r


# ==========================================================================
# through the solvent_mask tool
# ==========================================================================
def _framework_and_solvent(n_frame=8):
    """A hollow cube of carbons with 'solvent' O atoms in the middle
    (organic, P1): the data carry the O, the model does not."""
    cs = crystal.symmetry(unit_cell=(11.0, 11.0, 11.0, 90, 90, 90),
                          space_group_symbol="P 1")
    full = xray.structure(crystal_symmetry=cs)
    model = xray.structure(crystal_symmetry=cs)
    i = 0
    for x in (0.08, 0.92):
        for y in (0.08, 0.92):
            for z in (0.08, 0.92):
                i += 1
                for xs_ in (full, model):
                    xs_.add_scatterer(xray.scatterer(
                        label=f"C{i}", site=(x, y, z),
                        scattering_type="C", u=0.03))
    for k, site in enumerate(((0.5, 0.5, 0.5), (0.5, 0.5, 0.62),
                              (0.42, 0.55, 0.45))):
        full.add_scatterer(xray.scatterer(
            label=f"O{k + 1}", site=site, scattering_type="O", u=0.08))
    for xs_ in (full, model):
        xs_.scattering_type_registry(table="it1992")
    fc = full.structure_factors(d_min=0.9).f_calc()
    fo_sq = fc.intensities().customized_copy(
        sigmas=flex.double(fc.size(), 1.0)) \
        .set_observation_type_xray_intensity()
    return model, fo_sq


def _drop_everything(monkeypatch):
    """Force smtbx's negative-density drop on every void."""
    orig = BypassMask.structure_factors

    def dropping(self, max_cycles=10, **kw):
        f = orig(self, max_cycles=max_cycles, **kw)
        for j in range(self.n_voids()):
            self.exclude_void_flags[j] = True
            self.excluded_negative[j] = 0
        return f

    monkeypatch.setattr(BypassMask, "structure_factors", dropping)


def _without(xs, labels):
    keep = flex.bool([sc.label not in labels for sc in xs.scatterers()])
    return xs.select(keep)


class TestToolPath:
    def _session(self):
        model, fo_sq = _framework_and_solvent()
        return SimpleNamespace(model=model, fo_sq=fo_sq, flags={},
                               last_refinement=lambda: None)

    def _ctx(self, ses):
        return SimpleNamespace(session=ses, store=None, progress=None)

    def test_first_call_has_no_diagnosis_unless_it_did_not_settle(self):
        ses = self._session()
        r = SolventMask().run(self._ctx(ses), max_cycles=10)
        assert r.ok, r.error
        s = r.summary
        if s["solvent_mask_converged"]:
            assert "mask_diagnosis" not in s
        else:
            assert s["mask_diagnosis"]["previous_mask"] is None
        # the session now remembers the model it masked
        snap = ses.flags["solvent_mask_model"]
        assert len(snap["atoms"]) == 8 and snap["electrons"] == \
            s["total_solvent_electrons_per_cell"]
        assert ses.flags["solvent_mask_info"]["mask_id"]
        assert list(ses.flags["solvent_mask_info"])[:2] == ["mask_id",
                                                            "computed_at"]

    def test_failure_on_a_fresh_session_says_there_is_nothing_to_diff(
            self, monkeypatch):
        ses = self._session()
        _drop_everything(monkeypatch)
        r = SolventMask().run(self._ctx(ses), max_cycles=5)
        assert not r.ok
        diag = r.summary["mask_diagnosis"]
        assert diag["outcome"] == "negative_dropped"
        assert diag["previous_mask"] is None
        assert "No earlier successful solvent mask" in r.error
        assert diag["rule"] == md.RULE

    def test_failure_diffs_against_the_model_of_the_last_mask(
            self, monkeypatch):
        """pa2 cage-l0-r2 in miniature: mask converges, two framework
        atoms are deleted, the re-mask goes NEGATIVE - the result must
        say what changed, that the model got lighter, and that the last
        mask is kept."""
        ses = self._session()
        first = SolventMask().run(self._ctx(ses), max_cycles=10)
        assert first.ok
        prev_e = first.summary["total_solvent_electrons_per_cell"]
        ses.model = _without(ses.model, {"C7", "C8"})
        _drop_everything(monkeypatch)
        r = SolventMask().run(self._ctx(ses), max_cycles=5)
        assert not r.ok and "NEGATIVE" in r.error
        # every existing key is still there
        assert r.summary["previous_mask_kept"][
            "total_solvent_electrons_per_cell"] == prev_e
        assert ses.flags.get("f_mask") is not None
        diag = r.summary["mask_diagnosis"]
        assert diag["previous_mask_source"] == "session snapshot"
        assert diag["previous_mask"]["node"] is None
        assert diag["previous_mask"]["electrons"] == prev_e
        delta = diag["model_delta"]
        assert delta["n_atoms_removed"] == 2
        assert sorted(a["label"] for a in delta["atoms_removed"]) == \
            ["C7", "C8"]
        assert delta["non_h_electrons_per_cell"] == {
            "before": 48.0, "after": 36.0, "change_pct": -25.0}
        r_txt = diag["reading"]
        assert "lost 2 non-H atoms (2 C)" in r_txt
        assert "lighter" in r_txt and "is kept in the session" in r_txt
        assert "restore or explain the 2 removed atoms" in r_txt
        assert "Model check vs the last mask:" in r.error
        assert "lost 2 non-H atoms (2 C)" in r.error

    def test_same_model_twice_is_reported_as_no_model_change(self):
        ses = self._session()
        first = SolventMask().run(self._ctx(ses), max_cycles=10)
        assert first.ok
        e1 = first.summary["total_solvent_electrons_per_cell"]
        second = SolventMask().run(self._ctx(ses), max_cycles=10)
        assert second.ok
        diag = second.summary["mask_diagnosis"]
        assert diag["previous_mask_source"] == "session snapshot"
        assert diag["model_delta"]["is_empty"] is True
        assert diag["current_electrons"] == \
            second.summary["total_solvent_electrons_per_cell"]
        assert diag["electron_change_pct"] == pytest.approx(
            100.0 * (diag["current_electrons"] - e1) / e1, abs=0.2)
        assert diag["mask_params_changed"] == []
        assert diag["reading"].startswith("No model change since the "
                                          "previous mask of this session")
        assert "mask-parameter or grid effect" in diag["reading"]
        assert "count_change_note" not in second.summary
        # existing keys untouched
        for k in ("n_voids", "n_voids_masked", "voids", "bypass",
                  "electron_count_confidence", "mask_decision_note",
                  "solvent_mask_converged", "count_change_vs_previous_pct"):
            assert k in second.summary
        # a parameter change on the same model is named as such
        third = SolventMask().run(self._ctx(ses), max_cycles=10,
                                  solvent_radius=1.0)
        assert third.ok
        diag3 = third.summary["mask_diagnosis"]
        assert diag3["mask_params_changed"] == [
            {"param": "solvent_radius", "previous": 1.2, "now": 1.0}]
        assert "Changed in this call: solvent_radius 1.2 -> 1.0" \
            in diag3["reading"]

    def test_success_after_a_model_edit_carries_the_delta(self):
        ses = self._session()
        assert SolventMask().run(self._ctx(ses), max_cycles=10).ok
        # reassign one framework atom: an electron-neutral-ish edit the
        # count reacts to - the delta must name it either way
        sc = next(s for s in ses.model.scatterers() if s.label == "C1")
        sc.scattering_type = "N"
        ses.model.scattering_type_registry(table="it1992")   # as edit_atoms does
        r = SolventMask().run(self._ctx(ses), max_cycles=10)
        assert r.ok
        diag = r.summary["mask_diagnosis"]
        delta = diag["model_delta"]
        assert delta["element_reassigned"] == [{"label": "C1", "from": "C",
                                                "to": "N"}]
        assert "1 element reassignment (C1 C->N)" in diag["reading"]
        assert "verify the element reassignment (C1)" in diag["reading"]
        pct = diag["electron_change_pct"]
        assert ("count_change_note" in r.summary) == (
            pct is not None and abs(pct) > md.CHANGE_SIGNAL_PCT)

    def test_store_path_names_the_node_and_loads_its_model(
            self, tmp_path, monkeypatch):
        """With a project node store the diagnosis names the node the
        mask was computed on and diffs against its model.res."""
        from crystalpilot.refine.nodes import NodeStore
        proj = tmp_path / "proj"
        proj.mkdir()
        model, fo_sq = _framework_and_solvent()
        ses = _session(model)
        ses.fo_sq = fo_sq
        ctx = _project_ctx(proj, ses)
        first = SolventMask().run(ctx, max_cycles=10)
        assert first.ok, first.error
        store = NodeStore(proj)
        meta = store.commit(ses, tool="solvent_mask", params={})
        assert meta["id"] == "n0000" and meta["mask"]["info"]["mask_id"]
        assert (store.node_dir("n0000") / "f_mask.pkl").exists()
        ses.model = _without(ses.model, {"C7", "C8"})
        _drop_everything(monkeypatch)
        r = SolventMask().run(ctx, max_cycles=5)
        assert not r.ok
        diag = r.summary["mask_diagnosis"]
        assert diag["previous_mask_source"] == "project node store"
        assert diag["previous_mask"]["node"] == "n0000"
        assert diag["previous_mask"]["tool"] == "solvent_mask"
        assert diag["previous_mask"]["electrons"] == \
            first.summary["total_solvent_electrons_per_cell"]
        assert diag["model_delta"]["n_atoms_removed"] == 2
        assert "node n0000" in diag["reading"]
        assert "checkout n0000 and compare_nodes(n0000, n0000)" \
            in diag["reading"]
