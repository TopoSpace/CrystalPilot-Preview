"""reg8 follow-ups (round-2 R5): an atom-free model renders its cell box,
duplicate-observation consistency is one helper shared by audit and
ingest, situation_report candidates carry tried / adjudicated and the
report names its stage, and a split carrier's riding H are duplicated onto
the second component."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from cctbx import crystal, xray


def _cs(cell=(10, 12, 14, 90, 95, 90), sg="P 21/c"):
    return crystal.symmetry(unit_cell=cell, space_group_symbol=sg)


class TestAtomFreeView:
    def test_render_views_draws_the_cell_box(self, tmp_path):
        from crystalpilot.report.structviews import render_views
        xs = xray.structure(crystal_symmetry=_cs())
        imgs = render_views(xs, tmp_path, state="asu", views=["oblique"])
        assert len(imgs) == 1 and imgs[0]["path"]
        assert imgs[0].get("cell_only") is True

    def test_view_structure_answers_instead_of_failing(self, tmp_path):
        from crystalpilot.refine.tools_analysis import ViewStructure
        xs = xray.structure(crystal_symmetry=_cs())
        ctx = SimpleNamespace(session=SimpleNamespace(model=xs, flags={}))
        r = ViewStructure(SimpleNamespace(dir=tmp_path, session=None)).run(
            ctx, views=["a"])
        assert r.ok, r.error
        assert r.summary["n_atoms_drawn"] == 0
        assert "cell box only" in r.summary["note"]


class TestDuplicateConsistency:
    def _raw(self, rows):
        from cctbx.array_family import flex
        from cctbx import miller
        idx = flex.miller_index([tuple(h) for h, _i, _s in rows])
        ms = miller.set(crystal_symmetry=_cs(sg="P 1"), indices=idx,
                        anomalous_flag=False)
        return miller.array(ms, data=flex.double([i for _h, i, _s in rows]),
                            sigmas=flex.double([s for _h, _i, s in rows]))

    def test_consistent_duplicates(self):
        from crystalpilot.refine.tools_analysis import duplicate_consistency
        raw = self._raw([((1, 0, 0), 100.0, 5.0), ((1, 0, 0), 104.0, 5.0),
                         ((0, 1, 0), 50.0, 3.0)])
        d = duplicate_consistency(raw)
        assert d["n_observations"] == 3 and d["n_duplicate_groups"] == 1
        assert d["n_groups_chi2_above_threshold"] == 0
        assert "reading" not in d and "hint" not in d

    def test_hklf5_export_signature(self):
        """The same hkl up to 4x with intensities disagreeing far beyond
        sigma: the composite-row signature is named, with the R1-floor
        wording, on the helper both audit and ingest read."""
        from crystalpilot.refine.tools_analysis import duplicate_consistency
        rows = []
        for k in range(6):
            h = (k, 0, 0)
            rows += [(h, 100.0, 1.0), (h, 300.0, 1.0), (h, 900.0, 1.0),
                     (h, 50.0, 1.0)]
        d = duplicate_consistency(self._raw(rows))
        assert d["max_multiplicity"] == 4
        assert d["fraction_inconsistent"] == 1.0
        assert "HKLF 5" in d["reading"] and "R1 FLOOR" in d["reading"]
        assert "hint" in d


class TestCandidateTrials:
    def test_history_and_ledger(self, tmp_path):
        from crystalpilot.refine import ghost_ledger
        from crystalpilot.refine.nodes import NodeStore
        from crystalpilot.refine.tools_analysis import _candidate_trials
        store = NodeStore(tmp_path)
        for nid, tool, params in (("n0001", "refine", {"cycles": 4}),
                                  ("n0002", "model_disorder",
                                   {"atoms": ["C15"], "separation": 0.6}),
                                  ("n0003", "edit_atoms",
                                   {"ops": [{"delete": "O3"}]})):
            (store.nodes_dir / nid).mkdir(parents=True)
            (store.nodes_dir / nid / "node.json").write_text(json.dumps(
                {"id": nid, "tool": tool, "params": params, "branch": "main"}),
                encoding="utf-8")
        st = store.state()
        st.update({"seq": 4, "active_node": "n0003",
                   "branches": {"main": "n0003"}})
        store._save_state(st)
        ghost_ledger.record(tmp_path, {"label": "C16", "verdict": "real",
                                       "site": [0.1, 0.2, 0.3]})
        proj = SimpleNamespace(dir=tmp_path)
        t = _candidate_trials(proj, ["C15", "O3", "C16", "N9"])
        assert t["C15"] == ["model_disorder@n0002"]
        assert t["O3"] == ["edit_atoms@n0003"]
        assert t["C16"] == ["ghost_test:real"]
        assert "N9" not in t                 # untried stays absent

    def test_stage_inference(self, tmp_path):
        from crystalpilot.refine.nodes import NodeStore
        from crystalpilot.refine.tools_analysis import _infer_stage
        proj = SimpleNamespace(dir=tmp_path)
        assert _infer_stage(proj, None)["stage"] == "数据"
        empty = SimpleNamespace(model=xray.structure(crystal_symmetry=_cs()))
        assert _infer_stage(proj, empty)["stage"] == "求解"
        xs = xray.structure(crystal_symmetry=_cs())
        xs.add_scatterer(xray.scatterer(label="C1", site=(0.1, 0.2, 0.3),
                                        scattering_type="C", u=0.03))
        ses = SimpleNamespace(model=xs)
        store = NodeStore(tmp_path)
        for nid, tool in (("n0000", "run_shelxt"), ("n0001", "edit_atoms"),
                          ("n0002", "refine")):
            (store.nodes_dir / nid).mkdir(parents=True)
            (store.nodes_dir / nid / "node.json").write_text(json.dumps(
                {"id": nid, "tool": tool, "params": {}, "branch": "main"}),
                encoding="utf-8")
        st = store.state()
        st.update({"seq": 3, "active_node": "n0002",
                   "branches": {"main": "n0002"}})
        store._save_state(st)
        out = _infer_stage(proj, ses)
        assert out["stage"] == "精修" and "不猜" in out["basis"]
        (store.nodes_dir / "n0003").mkdir()
        (store.nodes_dir / "n0003" / "node.json").write_text(json.dumps(
            {"id": "n0003", "tool": "write_outputs", "params": {},
             "branch": "main"}), encoding="utf-8")
        assert _infer_stage(proj, ses)["stage"] == "交付"


class TestSplitRidingH:
    def test_h_copied_onto_b_with_shifted_sites(self):
        from crystalpilot.refine.tools_disorder import (_free_h_label,
                                                        _split_riding_h)
        xs = xray.structure(crystal_symmetry=_cs(sg="P 1"))
        for lb, el, site in (("C15", "C", (0.10, 0.20, 0.30)),
                             ("H15A", "H", (0.15, 0.20, 0.30)),
                             ("H15B", "H", (0.10, 0.26, 0.30)),
                             ("C16", "C", (0.30, 0.20, 0.30))):
            xs.add_scatterer(xray.scatterer(label=lb, site=site,
                                            scattering_type=el, u=0.03))
        per_carrier = [{"carrier": "C15", "afix": 23, "h": ["H15A", "H15B"]},
                       {"carrier": "C16", "afix": 137, "h": []}]
        entry = {"label": "C15", "lbl_b": "C15C",
                 "site_a": (0.10, 0.20, 0.30), "site_b": (0.12, 0.23, 0.30),
                 "occ_b": 0.4}
        new_h = _split_riding_h(xs, per_carrier, entry)
        assert new_h == ["H15C", "H15D"]
        labels = [sc.label for sc in xs.scatterers()]
        assert labels[-2:] == ["H15C", "H15D"]
        h15c = xs.scatterers()[labels.index("H15C")]
        assert [round(x, 3) for x in h15c.site] == [0.17, 0.23, 0.30]
        assert h15c.occupancy == pytest.approx(0.4)
        assert per_carrier[-1] == {"carrier": "C15C", "afix": 23,
                                   "h": ["H15C", "H15D"]}
        # a carrier without riding H adds nothing
        assert _split_riding_h(xs, per_carrier, {
            "label": "C16", "lbl_b": "C16B", "site_a": (0.3, 0.2, 0.3),
            "site_b": (0.32, 0.2, 0.3), "occ_b": 0.5}) == []
        assert _free_h_label({"H15A", "H15B", "H15C", "H15D"}, "H15A") == "H15E"
