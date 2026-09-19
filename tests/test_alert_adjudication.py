"""Alert adjudication + in-call mask refresh (process audit T13).

Two boilerplate loops the audit measured: solvent_mask -> refine repeated
by hand after every model edit (13x in r12, 16x in r22), and
validate_structure re-reporting alerts already investigated, run after run.
Both are now one parameter - without letting either weaken the honesty
rules (adjudicated alerts still score, the refresh reuses the recorded
mask parameters instead of picking new ones).
"""
from cctbx import crystal, xray

from crystalpilot.core.dataset import ReflectionDataset
from crystalpilot.pipeline.session import SolveSession
from crystalpilot.tools.base import ToolContext
from crystalpilot.tools.validation_tools import ValidateStructure


class _Store:
    def record(self, *a, **k):
        return None

    def log(self, *a, **k):
        return None


def _session():
    """Two isolated atoms far apart: guarantees an isolated_atoms alert
    (system type unknown - no bonds - so no dimensionality alert), with no
    data needed."""
    cs = crystal.symmetry(unit_cell=(20, 20, 20, 90, 90, 90),
                          space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()
    for label, el, cart in (("ZN1", "Zn", (2.0, 2.0, 2.0)),
                            ("O1", "O", (12.0, 12.0, 12.0))):
        xs.add_scatterer(xray.scatterer(
            label=label, site=uc.fractionalize(cart),
            scattering_type=el, u=0.03, occupancy=1.0))
    xs.scattering_type_registry(table="it1992")
    ses = SolveSession(dataset=ReflectionDataset(
        intensities=None, wavelength=0.71073))
    ses.model = xs
    ses.symmetry = cs
    return ses


def _ctx(ses):
    return ToolContext(store=_Store(), session=ses)


def _codes(alerts):
    return {a["code"] for a in alerts}


class TestAdjudication:
    def test_baseline_reports_the_alerts(self):
        r = ValidateStructure().run(_ctx(_session()))
        assert r.ok, r.error
        assert "isolated_atoms" in _codes(r.summary["alerts"])
        assert "adjudicated" not in r.summary

    def test_settled_alert_moves_out_of_the_open_list(self):
        ses = _session()
        t = ValidateStructure()
        base = t.run(_ctx(ses))
        r = t.run(_ctx(ses), mark_adjudicated=[{
            "code": "isolated_atoms",
            "reason": "both sites confirmed as lattice solvent, disclosed"}])
        assert r.ok, r.error
        assert "isolated_atoms" not in _codes(r.summary["alerts"])
        assert "isolated_atoms" in _codes(r.summary["adjudicated"])
        assert r.summary["n_alerts"] == base.summary["n_alerts"] - 1
        settled = r.summary["adjudicated"][0]
        assert "lattice solvent" in settled["adjudicated_reason"]

    def test_adjudication_persists_across_calls(self):
        # the point of the feature: the next run is quiet too
        ses = _session()
        t = ValidateStructure()
        t.run(_ctx(ses), mark_adjudicated=[{
            "code": "isolated_atoms",
            "reason": "checked against the difference map, real solvent"}])
        again = t.run(_ctx(ses))
        assert "isolated_atoms" not in _codes(again.summary["alerts"])
        assert "isolated_atoms" in _codes(again.summary["adjudicated"])

    def test_confidence_is_unchanged_by_adjudicating(self):
        """Self-declared 'I looked at it' must not raise the score."""
        ses = _session()
        t = ValidateStructure()
        before = t.run(_ctx(ses)).summary["confidence"]
        after = t.run(_ctx(ses), mark_adjudicated=[{
            "code": "isolated_atoms",
            "reason": "confirmed lattice solvent, kept and disclosed"}])
        assert after.summary["confidence"] == before

    def test_subject_targets_one_alert_of_a_code(self):
        ses = _session()
        r = ValidateStructure().run(_ctx(ses), mark_adjudicated=[{
            "code": "isolated_atoms", "subject": "NOSUCHATOM",
            "reason": "this reason should never match anything here"}])
        # subject not in the message -> the alert stays open
        assert "isolated_atoms" in _codes(r.summary["alerts"])

    def test_removal_with_null_reason(self):
        ses = _session()
        t = ValidateStructure()
        t.run(_ctx(ses), mark_adjudicated=[{
            "code": "isolated_atoms", "reason": "settled for now"}])
        r = t.run(_ctx(ses), mark_adjudicated=[{
            "code": "isolated_atoms", "reason": None}])
        assert "isolated_atoms" in _codes(r.summary["alerts"])
        assert "adjudicated" not in r.summary

    def test_placeholder_reason_refused(self):
        r = ValidateStructure().run(_ctx(_session()), mark_adjudicated=[{
            "code": "isolated_atoms", "reason": "ok"}])
        assert not r.ok
        assert "real reason" in r.error

    def test_missing_code_refused(self):
        r = ValidateStructure().run(_ctx(_session()), mark_adjudicated=[
            {"reason": "no code given here at all"}])
        assert not r.ok
        assert "code" in r.error

    def test_validation_state_keeps_every_alert(self):
        """ses.validation feeds the report - nothing may disappear there."""
        ses = _session()
        t = ValidateStructure()
        n_all = len(t.run(_ctx(ses)).summary["alerts"])
        t.run(_ctx(ses), mark_adjudicated=[{
            "code": "isolated_atoms",
            "reason": "confirmed lattice solvent, kept and disclosed"}])
        assert len(ses.validation["alerts"]) == n_all
        assert len(ses.validation["adjudicated"]) == 1


class TestRefreshMaskParam:
    def test_no_mask_is_a_no_op_not_an_error(self):
        from crystalpilot.tools.refinement_tools import RefineLS
        ses = _session()
        out = RefineLS._refresh_mask(_ctx(ses), ses)
        assert out == {"skipped": "no solvent mask stored"}

    def test_param_is_declared(self):
        from crystalpilot.tools.refinement_tools import RefineLS
        props = RefineLS.params_schema["properties"]
        assert props["refresh_mask"]["type"] == "boolean"
        assert props["refresh_mask"]["default"] is False
