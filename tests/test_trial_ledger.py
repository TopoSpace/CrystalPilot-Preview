"""Round-3 WP7: the trial ledger - "this exact call already ran on this
node".

Live-demo Zr-MOF forensic: 27 fit_fragment calls, 15 of them adding
nothing, several the same anchors on the same node; read-only probes left
no trace at all. The ledger records every completed TRIALED call against
the node it read and attaches `tool_status.prior_trial` when the identical
call (normalised inputs) comes back on the same node; ancestors are
informational; other branches are ignored. It informs, never refuses.
"""
from __future__ import annotations

import json

import pytest

from crystalpilot.refine import trial_ledger as tl
from tests.test_probe_site import ATOMS_A, CELL_A, _open, make_project  # noqa: E402

IDD = {"site_frac": [0.5, 0.5, 0.5], "radius_A": 1.5, "mask": "off"}


@pytest.fixture()
def proj(tmp_path):
    return _open(make_project(tmp_path, CELL_A, "P -1", ATOMS_A, ATOMS_A,
                              z=2, d_min=0.75))


def _active(p):
    return p.nodes.state()["active_node"]


# ---------------------------------------------------------------------------
class TestKey:
    def test_label_order_case_and_float_noise_do_not_make_a_new_trial(self):
        a = tl.trial_key("fit_fragment", {
            "anchors": [{"atom": "c1", "template_index": 0, "range_A": [1.3, 1.6]},
                        {"atom": "O2", "template_index": 3, "range_A": [2.0, 2.6]}],
            "atoms": ["o2", "C1"], "occupancy": 0.30000001,
            "timeout_s": 30, "_diagnostic": True, "reason": "try again"})
        b = tl.trial_key("fit_fragment", {
            "atoms": ["C1", "O2"], "occupancy": 0.3, "timeout_s": 900,
            "anchors": [{"range_A": [2.0, 2.6], "template_index": 3, "atom": "o2"},
                        {"range_A": [1.3, 1.6], "template_index": 0, "atom": "C1"}]})
        assert a == b
        norm = tl.normalize_params({"atoms": ["o2", "C1"], "site_frac": [0.3, 0.1, 0.2],
                                    "timeout_s": 5, "_x": 1})
        assert norm == {"atoms": ["C1", "O2"], "site_frac": [0.3, 0.1, 0.2]}

    def test_coordinates_keep_their_order_and_real_input_changes_matter(self):
        assert (tl.trial_key("probe_site", {"site_frac": [0.1, 0.2, 0.3]})
                != tl.trial_key("probe_site", {"site_frac": [0.3, 0.2, 0.1]}))
        assert (tl.trial_key("search_fragment_pose", {"smiles": "c1ccccc1", "occupancy_hypothesis": 0.3})
                != tl.trial_key("search_fragment_pose", {"smiles": "c1ccccc1", "occupancy_hypothesis": 0.5}))
        assert tl.trial_key("a", {"x": 1}) != tl.trial_key("b", {"x": 1})

    def test_lookup_ignores_other_branches(self, tmp_path):
        class R:
            ok = True
            summary = {"tool_status": {"execution": "ran"}}
            error = None
        tl.record(tmp_path, "probe_site", {"site_frac": [0.1, 0.2, 0.3]}, "n0007", None, R())
        # n0007 is a sibling of n0008 (both children of n0006): not on the line
        hit = tl.lookup(tmp_path, "probe_site", {"site_frac": [0.1, 0.2, 0.3]},
                        "n0008", ["n0006", "n0005"])
        assert hit["same_node"] == [] and hit["ancestors"] == []
        # ... but it IS on the line of its own descendant
        hit = tl.lookup(tmp_path, "probe_site", {"site_frac": [0.1, 0.2, 0.3]},
                        "n0009", ["n0007", "n0006"])
        assert hit["same_node"] == []
        assert [a["distance"] for a in hit["ancestors"]] == [1]

    def test_damaged_ledger_reads_empty(self, tmp_path):
        p = tl.ledger_path(tmp_path)
        p.parent.mkdir(parents=True)
        p.write_text("{not json", encoding="utf-8")
        assert tl.load(tmp_path) == []
        p.write_text(json.dumps({"entries": [1, {"tool": "x"}]}), encoding="utf-8")
        assert tl.load(tmp_path) == [{"tool": "x"}]


# ---------------------------------------------------------------------------
class TestProjectHook:
    def test_same_call_on_same_node_carries_prior_trial(self, proj):
        p = proj
        n0 = _active(p)
        r1 = p.invoke_tool("integrate_difference_density", dict(IDD))
        assert r1.ok, r1.error
        assert "prior_trial" not in r1.summary["tool_status"]
        assert "prior_trial_note" not in r1.summary
        entries = tl.load(p.dir)
        assert len(entries) == 1
        assert entries[0]["tool"] == "integrate_difference_density"
        assert entries[0]["node"] == n0
        assert entries[0]["outcome"]["ok"] is True
        # same inputs, different spelling: key order, float noise, a budget
        r2 = p.invoke_tool("integrate_difference_density", {
            "mask": "off", "radius_A": 1.5000001,
            "site_frac": [0.5, 0.5, 0.5]})
        assert r2.ok, r2.error
        prior = r2.summary["tool_status"]["prior_trial"]
        assert prior["same_node"] is True and prior["node"] == n0
        assert prior["n"] == 1
        assert "already ran on node " + n0 in r2.summary["prior_trial_note"]
        assert "cannot give a different answer" in r2.summary["prior_trial_note"]
        # the call still ran (informs, never refuses) and was recorded again
        assert r2.summary.get("tool_status", {}).get("execution") == "ran"
        assert len(tl.load(p.dir)) == 2
        assert _active(p) == n0  # read-only tools leave no node

    def test_different_inputs_are_a_new_trial(self, proj):
        p = proj
        assert p.invoke_tool("integrate_difference_density", dict(IDD)).ok
        r = p.invoke_tool("integrate_difference_density",
                          {**IDD, "site_frac": [0.25, 0.5, 0.5]})
        assert r.ok, r.error
        assert "prior_trial" not in r.summary["tool_status"]

    def test_after_a_model_change_the_memo_is_ancestral_only(self, proj):
        p = proj
        n0 = _active(p)
        assert p.invoke_tool("integrate_difference_density", dict(IDD)).ok
        label = ATOMS_A[0][0]
        r = p.invoke_tool("edit_atoms", {"operations": [
            {"action": "set_u_iso", "atoms": [label], "u_iso": 0.03}]})
        assert r.ok, r.error
        n1 = _active(p)
        assert n1 != n0
        r3 = p.invoke_tool("integrate_difference_density", dict(IDD))
        assert r3.ok, r3.error
        ts = r3.summary["tool_status"]
        assert "prior_trial" not in ts
        anc = ts["prior_trials_on_ancestors"]
        assert anc[0]["node"] == n0 and anc[0]["distance"] == 1
        assert "ancestor " + n0 in r3.summary["prior_trial_note"]
        assert "may differ" in r3.summary["prior_trial_note"]
        # a sibling branch off n0 sees neither (its line is n0 only)
        rb = p.invoke_tool("branch", {"name": "alt", "from_node": n0})
        assert rb.ok, rb.error
        assert _active(p) == n0
        r4 = p.invoke_tool("integrate_difference_density", dict(IDD))
        assert r4.ok, r4.error
        # on n0 itself the first call is an exact prior; the n1 trial is on
        # another branch and is not mentioned
        assert r4.summary["tool_status"]["prior_trial"]["node"] == n0
        assert "prior_trials_on_ancestors" not in r4.summary["tool_status"]

    def test_failed_calls_are_not_recorded(self, proj):
        p = proj
        r = p.invoke_tool("integrate_difference_density", {**IDD, "radius_A": 25.0})
        assert not r.ok
        assert tl.load(p.dir) == []

    def test_situation_report_lists_recent_trials(self, proj):
        p = proj
        assert p.invoke_tool("integrate_difference_density", dict(IDD)).ok
        r = p.invoke_tool("situation_report", {})
        assert r.ok, r.error
        recent = r.summary["open_items"]["recent_trials"]
        assert recent[0]["tool"] == "integrate_difference_density"
        assert recent[0]["node"] == _active(p)
        assert "site_frac" in recent[0]["params"]
        assert any("trial_ledger" in line for line in r.summary["narrative"])
