"""Round-3 WP2: the instruction cards a SHELXL job refined with are model
state. Forensic thread T-d: EADP/SUMP handed to run_shelxl(extra_cards=)
lived only in the job directory - the node, its model.res and final.res
had none of them, the delivery said "agree", and a restart from final.res
would have refined a different model.

Uses the formate test project and the fake SHELXL of test_shelxl_tools
(job.ins echoed back as job.res), so every card round-trips exactly."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.test_shelxl_tools import _fake_shelxl, _formate_project  # noqa: E402

EADP = "EADP O1 O2"


def _same(a, b):
    return round(a, 6), round(b, 6)


def _adopt(p, monkeypatch, tmp_path, **params):
    _fake_shelxl(monkeypatch, tmp_path, lambda a, b: (a, b))
    r = p.invoke_tool("run_shelxl", {"mode": "adopt", "l_s": 2, **params})
    assert r.ok, r.error
    return r


def _node_meta(p, node):
    return json.loads((p.nodes.node_dir(node) / "node.json").read_text(
        encoding="utf-8"))


def _model_res(p, node):
    return (p.nodes.node_dir(node) / "model.res").read_text(encoding="utf-8")


# ==========================================================================
class TestCardsPersist:
    def test_adopted_cards_become_model_state(self, tmp_path, monkeypatch):
        p = _formate_project(tmp_path)
        r = _adopt(p, monkeypatch, tmp_path, extra_cards=[EADP])
        eff = r.summary["effective_cards"]
        assert eff["cards"] == [EADP] and eff["added_now"] == [EADP]
        assert eff["from_earlier_jobs"] == [] and eff["persisted"] is True
        assert p.session.flags["effective_cards"] == [EADP]
        assert p.session.flags["effective_cards_job"].startswith("job_")
        node = r.summary["node"]
        meta = _node_meta(p, node)
        assert meta["schema"] == 3
        assert meta["data_revision"]
        st = meta["effective_state"]
        assert st["cards"] == [EADP]
        assert st["source"] == {"tool": "run_shelxl",
                                "job": p.session.flags["effective_cards_job"]}
        assert st["weights"]["a"] == pytest.approx(0.1)
        assert st["h_treatment"] == "riding"
        # the node's own .res carries the card - final.res is this text
        assert EADP in _model_res(p, node)
        # ... and the job's .ins did too
        assert EADP in (Path(r.summary["job_dir"]) / "job.ins").read_text(
            encoding="utf-8")

    def test_cards_ride_into_the_next_job_and_survive_refine(self, tmp_path,
                                                             monkeypatch):
        p = _formate_project(tmp_path)
        _adopt(p, monkeypatch, tmp_path, extra_cards=[EADP])
        # any later commit (here an in-process edit) inherits the cards
        r2 = p.invoke_tool("edit_atoms", {"operations": [
            {"action": "set_u_iso", "atoms": ["C1"], "u_iso": 0.03}]})
        assert r2.ok, r2.error
        assert _node_meta(p, r2.summary["node"])["effective_state"]["cards"] == [EADP]
        assert EADP in _model_res(p, r2.summary["node"])
        # a later job with NO extra_cards still refines with the card
        r3 = p.invoke_tool("run_shelxl", {"mode": "check", "l_s": 2})
        assert r3.ok, r3.error
        ins = (Path(r3.summary["job_dir"]) / "job.ins").read_text(encoding="utf-8")
        assert ins.count(EADP) == 1
        eff = r3.summary["effective_cards"]
        assert eff["from_earlier_jobs"] == [EADP] and eff["added_now"] == []
        assert eff["persisted"] is False
        # re-passing the same card is not a duplicate and not an error
        r4 = p.invoke_tool("run_shelxl", {"mode": "check", "l_s": 2,
                                          "extra_cards": [EADP]})
        assert r4.ok, r4.error
        assert (Path(r4.summary["job_dir"]) / "job.ins").read_text(
            encoding="utf-8").count("EADP") == 1
        assert r4.summary["effective_cards"]["added_now"] == []

    def test_check_does_not_persist_and_replace_drops(self, tmp_path,
                                                      monkeypatch):
        p = _formate_project(tmp_path)
        _adopt(p, monkeypatch, tmp_path, extra_cards=[EADP])
        r = p.invoke_tool("run_shelxl", {"mode": "check", "l_s": 2,
                                         "extra_cards": ["EXYZ O1 O2"]})
        assert r.ok, r.error
        assert p.session.flags["effective_cards"] == [EADP]
        r2 = _adopt(p, monkeypatch, tmp_path, replace_cards=True,
                    extra_cards=["EXYZ O1 O2"])
        assert r2.summary["effective_cards"]["replaced"] is True
        assert p.session.flags["effective_cards"] == ["EXYZ O1 O2"]
        assert EADP not in _model_res(p, r2.summary["node"])
        r3 = _adopt(p, monkeypatch, tmp_path, replace_cards=True)
        assert "effective_cards" not in p.session.flags
        assert r3.summary["effective_cards"]["cards"] == []
        assert "EXYZ" not in _model_res(p, r3.summary["node"])

    def test_checkout_restores_the_cards(self, tmp_path, monkeypatch):
        p = _formate_project(tmp_path)
        base = p.nodes.state()["active_node"]
        r = _adopt(p, monkeypatch, tmp_path, extra_cards=[EADP])
        with_cards = r.summary["node"]
        p.checkout(base)
        assert "effective_cards" not in p.session.flags
        p.checkout(with_cards)
        assert p.session.flags["effective_cards"] == [EADP]
        assert p.session.flags["effective_cards_job"].startswith("job_")

    def test_deleting_a_named_atom_prunes_the_card(self, tmp_path, monkeypatch):
        p = _formate_project(tmp_path)
        _adopt(p, monkeypatch, tmp_path, extra_cards=[EADP])
        r = p.invoke_tool("edit_atoms", {"operations": [
            {"action": "delete", "atoms": ["O2"]}]})
        assert r.ok, r.error
        assert r.summary["cards_pruned"] == [EADP]
        assert "effective_cards" not in p.session.flags
        assert _node_meta(p, r.summary["node"])["effective_state"]["cards"] == []

    def test_stale_card_refuses_the_job_by_name(self, tmp_path, monkeypatch):
        p = _formate_project(tmp_path)
        _adopt(p, monkeypatch, tmp_path, extra_cards=[EADP])
        # bypass the hygiene: a card naming an atom that is gone
        p.session.flags["effective_cards"] = ["EADP O1 O9"]
        r = p.invoke_tool("run_shelxl", {"mode": "check", "l_s": 2})
        assert not r.ok
        assert "effective instruction card" in r.error and "O9" in r.error
        assert "replace_cards" in r.error


# ==========================================================================
class TestCardHelpers:
    def test_instruction_cards_of_reads_continuations_and_stops_at_hklf(self):
        from crystalpilot.refine.shelx_cards import instruction_cards_of
        text = ("TITL x\nACTA\nEQIV $1 -x, -y, -z\nHTAB O1 O2_$1\n"
                "EADP  o1   o2\nSUMP 1.0 0.01 1.0 2 =\n 1.0 3\nREM EADP C1 C2\n"
                "HKLF 4\nEADP C9 C8\n")
        assert instruction_cards_of(text) == [
            "EQIV $1 -X, -Y, -Z", "HTAB O1 O2_$1", "EADP O1 O2",
            "SUMP 1.0 0.01 1.0 2 1.0 3"]

    def test_card_coherence_decides_on_constraints(self):
        from crystalpilot.refine.shelx_cards import card_coherence
        ins = "EQIV $1 -x,-y,-z\nHTAB O1 O2_$1\nEADP O1 O2\nHKLF 4\n"
        ok = card_coherence("EADP O1 O2\nHKLF 4\n", ins)
        assert ok["restartable"] is True
        assert ok["missing_measurements"] == ["EQIV $1 -X,-Y,-Z", "HTAB O1 O2_$1"]
        assert "measured tables" in ok["note"]
        bad = card_coherence("HTAB O1 O2_$1\nHKLF 4\n", ins)
        assert bad["restartable"] is False
        assert bad["missing_constraints"] == ["EADP O1 O2"]
        assert "different model" in bad["note"]
        full = card_coherence(ins, ins)
        assert full["restartable"] and full["missing_measurements"] == []
        assert card_coherence("HKLF 4\n", "HKLF 4\n")["restartable"] is True

    def test_prune_and_rename(self):
        from crystalpilot.refine.shelx_cards import (prune_cards_for_deleted,
                                                     rename_cards)
        cards = ["EADP O1 O2", "HTAB N1 O1_$1", "SUMP 1.0 0.01 1.0 2 1.0 3"]
        kept, dropped = prune_cards_for_deleted(cards, {"o1"})
        assert dropped == ["EADP O1 O2", "HTAB N1 O1_$1"]
        assert kept == ["SUMP 1.0 0.01 1.0 2 1.0 3"]
        assert rename_cards(cards, {"O1": "O1A", "N1": "N1X"}) == [
            "EADP O1A O2", "HTAB N1X O1A_$1", "SUMP 1.0 0.01 1.0 2 1.0 3"]

    def test_delivery_coherence_names_the_missing_cards(self, tmp_path):
        from crystalpilot.refine.tools_deliver import WriteOutputs
        from tests.test_delivery_coherence import RES_3ATOMS, _cif
        (tmp_path / "final.res").write_text(RES_3ATOMS, encoding="utf-8")
        (tmp_path / "final.cif").write_text(_cif(), encoding="utf-8")
        report = {"metrics": {"r1_strong": 0.04}}
        assert WriteOutputs._delivery_coherence(tmp_path, report, True) == []
        restart = {"restartable": False, "missing_constraints": ["EADP C1 C2"],
                   "extra_in_res": []}
        issues = WriteOutputs._delivery_coherence(tmp_path, report, True,
                                                  restart=restart)
        assert len(issues) == 1 and "EADP C1 C2" in issues[0]
        assert "restartable" in issues[0]
        assert WriteOutputs._delivery_coherence(
            tmp_path, report, True, restart={"restartable": True}) == []


# ==========================================================================
def test_imported_constraint_cards_are_carried(tmp_path):
    from tests.test_shelxl_tools import FORMATE_RES
    res = FORMATE_RES.replace("FVAR 1.0\n", "EADP O1 O2\nEADP O1 ZZ9\nFVAR 1.0\n")
    p = _formate_project(tmp_path, res_text=res)
    assert p.session.flags["effective_cards"] == [EADP]
    assert p.session.flags["effective_cards_job"] == "import"
    node = p.nodes.state()["active_node"]
    assert _node_meta(p, node)["effective_state"]["cards"] == [EADP]
    assert EADP in _model_res(p, node)
