"""T1.6 acceptance loop for model_disorder: is a PART split real?

The regression this closes (reg1-ext2, 2026-09-03): two organic cases
whose deposited structures carry a PART split were delivered with the
disorder unmodelled - orgdis_dbu_cod2241572 (P2(1)/n, DBU ring segment
C15/C16) and twintrap_nm_cod2229074 (P-1, ethyl C15B/C16B). One agent
declared the segment "anharmonic motion that cannot be reliably modelled
discretely"; the other built a split (`split_o5_trial`) and abandoned it
the moment R1 rose. No tool told either of them whether the split was
supported by the data, and no tool cleaned up the abandoned one.

The synthetic coverage here is a CF3 rotor - a trifluoromethyl group
disordered over two orientations 60 degrees apart, the textbook organic
rotor - built with cctbx, Fo^2 computed from a TWO-COMPONENT truth at
0.7/0.3 with noise on the measured sigmas, and refined by the vendor
SHELXL. The same machinery is then run against an ORDERED truth to prove
the criterion fires in the other direction: a split drawn where there is
no disorder must come back `revoke`, not merely "unsupported".

Nothing here is tuned to fluorine, to P2(1)/c or to a rotor: the criterion
is a pure statement about a refined occupancy and its s.u., and the two
lanes below differ only in what the DATA contain.
"""
from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SHELXL = REPO / "vendor" / "shelx" / "shelxl.exe"

CELL = (10.2, 11.4, 8.6, 90.0, 99.5, 90.0)
SG = "P 21/c"
#: fraction of the major CF3 orientation in the synthetic truth
TRUE_OCC = 0.7


# ======================================================================
# synthetic CF3-rotor organic structure
# ======================================================================
def _cf3_geometry():
    """Benzene ring + CF3, and the CF3 rotated 60 deg about the C1-C7 axis
    (cartesian angstrom; the molecule is dropped into the cell later)."""
    from scitbx import matrix
    ring = [(1.39 * math.cos(math.radians(60 * k)),
             1.39 * math.sin(math.radians(60 * k)), 0.0) for k in range(6)]
    c7 = (1.39 + 1.50, 0.0, 0.0)
    tet = math.radians(70.5)
    f_a = [(c7[0] + 1.33 * math.cos(tet),
            1.33 * math.sin(tet) * math.cos(math.radians(120 * k)),
            1.33 * math.sin(tet) * math.sin(math.radians(120 * k)))
           for k in range(3)]
    axis = matrix.col((1.0, 0.0, 0.0))
    rot = axis.axis_and_angle_as_r3_rotation_matrix(math.radians(60.0))
    f_b = [tuple(matrix.col(c7) + rot * (matrix.col(p) - matrix.col(c7)))
           for p in f_a]
    return ring, c7, f_a, f_b


def _structure(occ_a: float, split: bool):
    from cctbx import crystal, xray
    cs = crystal.symmetry(unit_cell=CELL, space_group_symbol=SG)
    uc = cs.unit_cell()
    ring, c7, f_a, f_b = _cf3_geometry()
    xs = xray.structure(crystal_symmetry=cs)
    shift = (0.30, 0.20, 0.25)

    def add(lbl, el, cart, occ, u):
        fr = uc.fractionalize(cart)
        xs.add_scatterer(xray.scatterer(
            label=lbl, site=tuple(fr[k] + shift[k] for k in range(3)),
            u=u, occupancy=occ, scattering_type=el))

    for i, p in enumerate(ring):
        add(f"C{i + 1}", "C", p, 1.0, 0.035)
    add("C7", "C", c7, 1.0, 0.035)
    for i, p in enumerate(f_a):
        add(f"F{i + 1}", "F", p, occ_a if split else 1.0, 0.05)
    if split:
        for i, p in enumerate(f_b):
            add(f"F{i + 1}B", "F", p, 1.0 - occ_a, 0.06)
    return xs


def _fvar_extras(fvar_value: float):
    """The FVAR-linked PART 1/2 split as serialization kwargs - the same
    shape model_disorder puts in the session flags."""
    return {
        "fvars": [fvar_value],
        "sof_codes": dict({f"F{i}": 21.0 for i in (1, 2, 3)},
                          **{f"F{i}B": -21.0 for i in (1, 2, 3)}),
        "parts": dict({f"F{i}": 1 for i in (1, 2, 3)},
                      **{f"F{i}B": 2 for i in (1, 2, 3)}),
    }


def _make_project(tmp_path: Path, truth_split: bool,
                  start_fvar: float = 0.5) -> Path:
    """Project with HKLF4 data computed from the truth (split or ordered)
    and a start model that ALWAYS carries the two-component split."""
    from cctbx.array_family import flex

    from crystalpilot.io.cif_sf import write_hklf4
    from crystalpilot.io.shelx_writer import ShelxModel, write_res
    d = tmp_path / "cf3"
    d.mkdir(parents=True, exist_ok=True)
    truth = _structure(TRUE_OCC, truth_split)
    i_obs = truth.structure_factors(
        d_min=0.80, algorithm="direct").f_calc().as_intensity_array()
    # measured-like sigmas + matching noise: without noise the residuals
    # vanish, GooF collapses and every esd with it - the s.u. this whole
    # test is about would be an artefact of a noiseless calculation
    flex.set_random_seed(11)
    data = i_obs.data()
    sig = 0.03 * flex.abs(data) + 0.02 * flex.mean(flex.abs(data))
    noise = (flex.random_double(data.size()) - 0.5) * 2.0 * sig
    write_hklf4(i_obs.customized_copy(data=data + noise, sigmas=sig),
                d / "crystal.hkl")
    write_res(ShelxModel(xray_structure=_structure(start_fvar, True),
                         wavelength=0.71073, z=4, weights=(0.1, 0.0),
                         **_fvar_extras(start_fvar)),
              d / "start.res")
    (d / "context.json").write_text(json.dumps({
        "data": {"hkl": "crystal.hkl", "start_model": "start.res"}}),
        encoding="utf-8")
    return d


def _open(d: Path):
    from crystalpilot.refine.project import RefineProject
    p = RefineProject(d)
    p.open()
    return p


@pytest.fixture(scope="module")
def cf3_disordered(tmp_path_factory):
    """Truth = 0.7/0.3 CF3 disorder; the model carries the split."""
    if not SHELXL.exists():
        pytest.skip("vendor shelxl not present")
    return _open(_make_project(tmp_path_factory.mktemp("dis"), True))


@pytest.fixture(scope="module")
def cf3_ordered(tmp_path_factory):
    """Truth = ONE ordered CF3; the model carries a spurious split."""
    if not SHELXL.exists():
        pytest.skip("vendor shelxl not present")
    return _open(_make_project(tmp_path_factory.mktemp("ord"), False))


# ======================================================================
# 1. pure criterion
# ======================================================================
class TestOccupancyVerdict:
    def test_plan_example_095_10_revokes(self):
        from crystalpilot.refine.disorder_accept import occupancy_verdict
        v = occupancy_verdict(0.95, 0.10, 2)
        assert v["verdict"] == "revoke"
        assert "0.95(10)" in v["informative"]
        assert "1.000" in v["informative"]

    def test_null_at_zero_is_a_different_reading(self):
        from crystalpilot.refine.disorder_accept import occupancy_verdict
        v = occupancy_verdict(0.01, 0.02, 2)
        assert v["verdict"] == "revoke"
        # P13: the direction must be reported, not collapsed
        assert "component B" in v["informative"]
        assert "wrong way round" in v["informative"]

    def test_large_su_is_inconclusive_not_revoke(self):
        """Ordering matters: a ratio that is not measured at all must
        never be reported as a decisive `revoke`, even though 0 and 1 are
        both inside its 2 s.u. window."""
        from crystalpilot.refine.disorder_accept import occupancy_verdict
        v = occupancy_verdict(0.97, 0.40, 2)
        assert v["verdict"] == "inconclusive"
        assert "0.4" in v["informative"] or "0.400" in v["informative"]

    def test_measured_ratio_is_supported(self):
        from crystalpilot.refine.disorder_accept import occupancy_verdict
        v = occupancy_verdict(0.70, 0.02, 2)
        assert v["verdict"] == "supported"
        assert v["sigma_from_1"] == pytest.approx(15.0, abs=0.1)

    def test_no_su_decides_nothing(self):
        from crystalpilot.refine.disorder_accept import occupancy_verdict
        v = occupancy_verdict(0.70, None, 2)
        assert v["verdict"] == "unknown"
        assert "no refined s.u." in v["informative"]

    def test_every_su_verdict_carries_the_underestimation_clause(self):
        from crystalpilot.refine.disorder_accept import occupancy_verdict
        from crystalpilot.refine.shelxl_lst import SU_UNDERESTIMATED
        for v, s in ((0.7, 0.02), (0.999, 0.001), (0.01, 0.005), (0.6, 0.2)):
            assert SU_UNDERESTIMATED in occupancy_verdict(v, s, 2)[
                "informative"]

    def test_value_su_formatting(self):
        from crystalpilot.refine.disorder_accept import format_value_su
        assert format_value_su(0.95, 0.10) == "0.95(10)"
        assert format_value_su(0.70179, 0.0013) == "0.7018(13)"
        assert format_value_su(0.99976, 0.00077) == "0.99976(77)"


# ======================================================================
# 2. .lst read-back
# ======================================================================
class TestFreeVariableReadback:
    LST = """
 Least-squares cycle   1
     N      value        esd    shift/esd  parameter

     1     0.31623     0.00074     0.000    OSF
     2     0.50000     0.09000     3.100   FVAR  2

 Mean shift/esd =   0.900  Maximum =     3.100 for   x  F1

 Least-squares cycle   2
     N      value        esd    shift/esd  parameter

     1     0.31623     0.00074     0.000    OSF
     2     0.70179     0.00130     0.001   FVAR  2
     3     0.31000     0.00420    -0.002   FVAR  3

 Mean shift/esd =   0.000  Maximum =    -0.001 for   z  C5
"""

    def test_last_cycle_wins(self):
        from crystalpilot.refine.shelxl_lst import parse_free_variables
        fv = parse_free_variables(self.LST)
        assert set(fv) == {1, 2, 3}
        assert fv[2]["value"] == pytest.approx(0.70179)
        assert fv[2]["su"] == pytest.approx(0.00130)
        assert fv[3]["su"] == pytest.approx(0.00420)
        assert fv[1]["name"] == "OSF"

    def test_no_listing_returns_none_not_zero(self):
        from crystalpilot.refine.shelxl_lst import parse_free_variables
        assert parse_free_variables("wR2 = 0.1 GooF = S = 1.0") is None

    def test_overflow_field_is_none_not_a_number(self):
        from crystalpilot.refine.shelxl_lst import parse_free_variables
        txt = ("     N      value        esd    shift/esd  parameter\n\n"
               "     2   ******      ******      0.001   FVAR  2\n")
        fv = parse_free_variables(txt)
        assert fv[2]["value"] is None and fv[2]["su"] is None


# ======================================================================
# 3. end-to-end with the vendor SHELXL: supported
# ======================================================================
class TestSupportedSplit:
    """Truth IS a 0.7/0.3 CF3 disorder; the refinement must find it."""

    def test_shelxl_adopt_reports_supported_with_the_true_ratio(
            self, cf3_disordered):
        p = cf3_disordered
        assert p.session.flags["disorder_groups"][0]["fvar_index"] == 2
        r = p.invoke_tool("run_shelxl", {"mode": "adopt", "l_s": 12,
                                         "timeout_s": 300})
        assert r.ok, r.error
        fv = r.summary["shelxl"]["free_variables"]["fvar2"]
        assert fv["su"] is not None and fv["su"] > 0
        blk = r.summary["disorder_acceptance"][0]
        assert blk["verdict"] == "supported", blk["free_variable"]
        # the refined share must agree with the truth within its own s.u.
        v, su = fv["value"], fv["su"]
        assert abs(v - TRUE_OCC) <= max(3.0 * su, 0.02), (v, su)
        assert blk["free_variable"]["su"] == pytest.approx(su)
        assert "SADI" in " ".join(blk["restraint_suggestion"]["cards"])
        assert r.summary["disorder_verdict"]["verdicts"]["supported"] == 1
        # the group record itself now carries the s.u. and the verdict, so
        # inspect_model / checkout / node.json all see it
        g = p.session.flags["disorder_groups"][0]
        assert g["free_variable"]["su"] == pytest.approx(su)
        assert g["verdict"] == "supported"

    def test_restraint_suggestion_names_the_component_atoms(
            self, cf3_disordered):
        p = cf3_disordered
        from crystalpilot.refine.disorder_accept import restraint_suggestion
        g = p.session.flags["disorder_groups"][0]
        sug = restraint_suggestion(p.session.model, g)
        cards = " ".join(sug["cards"])
        comps = {m["label"] for m in g["members"]}
        assert comps == {"F1", "F2", "F3", "F1B", "F2B", "F3B"}
        simu = next(s for s in sug["restraints"] if s["kind"] == "SIMU")
        assert set(simu["atoms"]) == comps
        # SAME between the two orientations, expressed as SADI: the F-F
        # distances of one orientation tied to the other's, plus the
        # shared C7 pivot
        sadi = [s for s in sug["restraints"] if s["kind"] == "SADI"]
        assert sadi, sug["cards"]
        flat = {a for s in sadi for pair in s["atoms"] for a in pair}
        assert comps <= flat and "C7" in flat
        # every SADI card ties exactly one A distance to its B counterpart
        for s in sadi:
            assert len(s["atoms"]) == 2
        assert "C7" in cards and "F1B" in cards
        # a suggestion, never applied behind the agent's back
        assert not p.session.flags.get("restraints")
        assert sug["apply_with"]["tool"] == "set_restraints"

    def test_suggestion_is_accepted_by_set_restraints(self, cf3_disordered):
        """The cards must be applicable as returned - a suggestion the
        real tool rejects is worse than none."""
        p = cf3_disordered
        from crystalpilot.refine.disorder_accept import restraint_suggestion
        sug = restraint_suggestion(p.session.model,
                                   p.session.flags["disorder_groups"][0])
        r = p.invoke_tool("set_restraints", sug["apply_with"]["params"])
        assert r.ok, r.error
        assert r.summary["added"] == len(sug["restraints"])
        p.invoke_tool("set_restraints", {"action": "clear"})


# ======================================================================
# 4. end-to-end with the vendor SHELXL: revoke + undo
# ======================================================================
class TestRevokedSplit:
    """Truth is ONE ordered CF3; the model splits it anyway."""

    def test_spurious_split_comes_back_revoke(self, cf3_ordered):
        p = cf3_ordered
        r = p.invoke_tool("run_shelxl", {"mode": "adopt", "l_s": 12,
                                         "timeout_s": 300})
        assert r.ok, r.error
        blk = r.summary["disorder_acceptance"][0]
        fv = blk["free_variable"]
        assert blk["verdict"] == "revoke", fv
        # the occupancy ran to a single site, within 2 s.u. of it
        assert min(abs(fv["value"]), abs(1.0 - fv["value"])) \
            <= 2.0 * fv["su"]
        assert "undo" in blk["disposition"]
        assert r.summary["disorder_verdict"]["verdicts"]["revoke"] == 1

    def test_undo_restores_a_single_site(self, tmp_path):
        p = _open(_make_project(tmp_path, False))
        ses = p.session
        n_before = ses.model.scatterers().size()
        assert ses.flags.get("disorder_groups")
        # the imported .res split has no pre-split state on record - undo
        # must refuse rather than invent one
        refused = p.invoke_tool("model_disorder", {"undo": "fvar2"})
        assert not refused.ok
        assert "not created by model_disorder" in refused.error
        # a failed invocation rebuilds the live session from the published
        # node (2026-09-08: nothing half-done may survive a failure), so the
        # session object held from before the refusal is stale
        ses = p.session
        assert ses.model.scatterers().size() == n_before

        # a split this tool made, undone by naming its B component
        r = p.invoke_tool("model_disorder", {
            "atoms": ["C4"], "occupancy": 0.6,
            "second_sites": {"C4": list(_shifted(ses, "C4", 0.7))}})
        assert r.ok, r.error
        assert r.summary["fvar_index"] == 3      # FVAR2 still taken
        assert ses.model.scatterers().size() == n_before + 1
        assert r.summary["acceptance"]["verdict"] == "pending"

        u = p.invoke_tool("model_disorder", {"undo": "C4B"})
        assert u.ok, u.error
        assert u.summary["undone"] == "fvar3"
        assert u.summary["deleted_atoms"] == ["C4B"]
        assert ses.model.scatterers().size() == n_before
        labels = {sc.label for sc in ses.model.scatterers()}
        assert "C4B" not in labels and "C4" in labels
        c4 = next(sc for sc in ses.model.scatterers() if sc.label == "C4")
        assert c4.weight() == pytest.approx(1.0)
        assert not c4.flags.use_u_aniso()
        merged = u.summary["merged"][0]
        assert merged["kept"] == "C4" and merged["deleted"] == "C4B"
        assert merged["weights"] == [pytest.approx(0.6), pytest.approx(0.4)]
        # the merged site is the occupancy-weighted mean of the two: A
        # keeps its site in a second_sites split, B sits 0.7 A away, so
        # the 0.6:0.4 mean lands 0.4 x 0.7 A from A
        assert merged["moved_A"] == pytest.approx(0.4 * 0.7, abs=0.02)
        # the other split is untouched and keeps its own variable
        assert [g["fvar_index"] for g in ses.flags["disorder_groups"]] == [2]
        # ... and no FVAR/PART debris for the removed atom in the .res
        node = u.summary["node"]
        res = (p.nodes.node_dir(node) / "model.res").read_text(
            encoding="utf-8", errors="replace")
        assert "C4B" not in res
        assert len(next(ln for ln in res.splitlines()
                        if ln.startswith("FVAR")).split()) == 3

    def test_undo_renumbers_the_surviving_free_variables(self, tmp_path):
        """Removing FVAR3 while FVAR4 still codes its sofs on 4x.xx would
        silently re-point every one of them: the FVAR card is positional."""
        p = _open(_make_project(tmp_path, True))
        ses = p.session
        for lbl in ("C4", "C5"):
            r = p.invoke_tool("model_disorder", {
                "atoms": [lbl], "occupancy": 0.6,
                "second_sites": {lbl: list(_shifted(ses, lbl, 0.7))}})
            assert r.ok, r.error
        assert [g["fvar_index"] for g in ses.flags["disorder_groups"]] == \
            [2, 3, 4]
        u = p.invoke_tool("model_disorder", {"undo": "fvar3"})
        assert u.ok, u.error
        assert u.summary["fvar_renumbered"] == {"fvar4": "fvar3"}
        left = ses.flags["disorder_groups"]
        assert [g["fvar_index"] for g in left] == [2, 3]
        assert {m["label"] for m in left[1]["members"]} == {"C5", "C5B"}
        from crystalpilot.refine.nodes import serialization_extras
        extras = serialization_extras(ses.flags)
        assert extras["sof_codes"]["C5"] == pytest.approx(31.0)
        assert extras["sof_codes"]["C5B"] == pytest.approx(-31.0)
        assert len(extras["fvars"]) == 2
        # the undo record follows the renumbering, so C5's split is still
        # undoable under its NEW variable
        assert [o["fvar_index"] for o in ses.flags["disorder_origins"]] == [3]
        # and a SHELXL job on the renumbered model still runs and reads back
        if not SHELXL.exists():
            pytest.skip("vendor shelxl not present")
        rs = p.invoke_tool("run_shelxl", {"mode": "check", "l_s": 2,
                                          "timeout_s": 300})
        assert rs.ok, rs.error
        fvs = rs.summary["shelxl"].get("free_variables") or {}
        assert set(fvs) >= {"osf", "fvar2", "fvar3"}
        assert [b["fvar_index"] for b in
                rs.summary["disorder_acceptance"]] == [2, 3]


def _shifted(ses, label: str, angstrom: float):
    """A site `angstrom` away from `label` along a - a plain second site
    for a split trial (the atom is isotropic after an adopt)."""
    xs = ses.model
    sc = next(s for s in xs.scatterers() if s.label == label)
    d = xs.unit_cell().fractionalize((angstrom, 0.0, 0.0))
    return tuple(sc.site[k] + d[k] for k in range(3))


# ======================================================================
# 5. plumbing that must survive a round trip
# ======================================================================
class TestPlumbing:
    def test_undo_record_survives_checkout(self, tmp_path):
        """A checkout that loses the pre-split state makes every split
        permanent - undo could then only refuse."""
        p = _open(_make_project(tmp_path, True))
        ses = p.session
        r = p.invoke_tool("model_disorder", {
            "atoms": ["C4"], "occupancy": 0.6,
            "second_sites": {"C4": list(_shifted(ses, "C4", 0.7))}})
        assert r.ok, r.error
        node = r.summary["node"]
        meta = json.loads((p.nodes.node_dir(node) / "node.json").read_text(
            encoding="utf-8"))
        assert meta["disorder_origins"], "undo record must reach node.json"
        p.invoke_tool("model_disorder", {"undo": "fvar3"})
        chk = p.invoke_tool("checkout", {"node": node})
        assert chk.ok, chk.error
        assert p.session.flags.get("disorder_origins")
        u = p.invoke_tool("model_disorder", {"undo": "fvar3"})
        assert u.ok, u.error
        assert u.summary["deleted_atoms"] == ["C4B"]

    def test_inspect_model_lists_the_group_with_its_verdict(self, tmp_path):
        p = _open(_make_project(tmp_path, True))
        r = p.invoke_tool("inspect_model", {})
        assert r.ok, r.error
        dis = r.summary["disorder_groups"]
        assert len(dis) == 1
        # no SHELXL job yet: pending, never "supported"
        assert dis[0]["verdict"] == "pending"
        assert dis[0]["fvar_index"] == 2
        assert set(dis[0]["components"]["A"]) == {"F1", "F2", "F3"}
        assert dis[0]["undo"] == "model_disorder(undo='fvar2')"
        assert dis[0]["closest_A_B_A"] and dis[0]["closest_A_B_A"] < 2.0

    def test_undo_prunes_restraints_naming_deleted_atoms(self, tmp_path):
        """Same-fate hygiene: a spec left pointing at a deleted component
        rides into the next SHELXL job and aborts it."""
        p = _open(_make_project(tmp_path, True))
        ses = p.session
        r = p.invoke_tool("model_disorder", {
            "atoms": ["C4"], "occupancy": 0.6,
            "second_sites": {"C4": list(_shifted(ses, "C4", 0.7))}})
        assert r.ok, r.error
        from crystalpilot.refine.disorder_accept import restraint_suggestion
        grp = next(g for g in ses.flags["disorder_groups"]
                   if g["fvar_index"] == 3)
        sug = restraint_suggestion(ses.model, grp)
        assert p.invoke_tool("set_restraints",
                             sug["apply_with"]["params"]).ok
        u = p.invoke_tool("model_disorder", {"undo": "fvar3"})
        assert u.ok, u.error
        assert u.summary.get("restraints_pruned")
        left = {a for s in ses.flags.get("restraints") or []
                for item in (s.get("atoms") or [])
                for a in (item if isinstance(item, list) else [item])}
        assert "C4B" not in left

    def test_delta_r1_is_measured_against_the_pre_split_refinement(
            self, tmp_path):
        """The number the reg1-ext2 twintrap agent acted on without a rule.
        A split C4 into a place where there is no second component: R1
        cannot improve, and the block must say so in the same breath as
        the caveat that a drop would not have been evidence either."""
        if not SHELXL.exists():
            pytest.skip("vendor shelxl not present")
        p = _open(_make_project(tmp_path, True))
        ses = p.session
        base = p.invoke_tool("run_shelxl", {"mode": "adopt", "l_s": 8,
                                            "timeout_s": 300})
        assert base.ok, base.error
        r1_before = base.summary["shelxl"]["r1_strong"]
        r = p.invoke_tool("model_disorder", {
            "atoms": ["C4"], "occupancy": 0.6,
            "second_sites": {"C4": list(_shifted(ses, "C4", 0.7))}})
        assert r.ok, r.error
        assert r.summary["acceptance"]["delta_r1"]["r1_before_split"] == \
            pytest.approx(r1_before, abs=1e-4)
        after = p.invoke_tool("run_shelxl", {"mode": "adopt", "l_s": 8,
                                             "timeout_s": 300})
        assert after.ok, after.error
        blk = next(b for b in after.summary["disorder_acceptance"]
                   if b["fvar_index"] == 3)
        d = blk["delta_r1"]
        assert d["r1_before_split"] == pytest.approx(r1_before, abs=1e-4)
        assert d["delta_r1"] == pytest.approx(
            d["r1_now"] - r1_before, abs=1e-4)
        assert "is NOT evidence for the split" in d["rule"]
        assert d["n_atoms_added"] == 1
        # and the split itself is not supported - there is no second C4
        assert blk["verdict"] in ("revoke", "inconclusive"), blk[
            "free_variable"]

    def test_undo_needs_a_target_that_exists(self, tmp_path):
        p = _open(_make_project(tmp_path, True))
        r = p.invoke_tool("model_disorder", {"undo": "fvar9"})
        assert not r.ok
        assert "matches no disorder group" in r.error
        assert "fvar2" in r.error

    def test_no_atoms_and_no_undo_is_an_explained_refusal(self, tmp_path):
        p = _open(_make_project(tmp_path, True))
        r = p.invoke_tool("model_disorder", {})
        assert not r.ok
        assert "atoms=[...]" in r.error and "undo=" in r.error


# ======================================================================
# 6. generalization: a different crystal, a different element
# ======================================================================
class TestGeneralization:
    """The criterion must not know anything about CF3 or P2(1)/c. Same
    verdict machinery on a P-1 metal-halide site with a two-position
    split, driven straight from numbers."""

    @staticmethod
    def _p1_session(occ_a: float, u_b: float = 0.04):
        from types import SimpleNamespace

        from cctbx import crystal, xray
        import math

        cs = crystal.symmetry(unit_cell=(8.0, 9.0, 10.0, 88.0, 95.0, 103.0),
                              space_group_symbol="P -1")
        xs = xray.structure(crystal_symmetry=cs)
        # the alternative chloride swings on the Zn coordination sphere:
        # the Zn->Cl vector rotated about z by the angle that puts the two
        # sites 1.0 A apart, so BOTH positions sit at the same Zn-Cl
        # distance - a single-site Zn can be bonded to both, which is
        # what T1.6b checks (and 1.0 A is resolvable at 0.84 A, not 1.6)
        uc = cs.unit_cell()
        zn, cl = (0.20, 0.25, 0.30), (0.38, 0.30, 0.42)
        v = [a - b for a, b in zip(uc.orthogonalize(cl), uc.orthogonalize(zn))]
        d = math.sqrt(sum(x * x for x in v))
        vh = [x / d for x in v]
        # a unit vector perpendicular to Zn->Cl (cross with z), so the
        # rotation is in a plane containing the bond and the chord is
        # exactly 2 d sin(theta/2)
        w = (vh[1], -vh[0], 0.0)
        wn = math.sqrt(w[0] ** 2 + w[1] ** 2)
        w = (w[0] / wn, w[1] / wn, 0.0)
        theta = 2.0 * math.asin(min(1.0, 0.5 / d))
        v2 = [d * (math.cos(theta) * vh[i] + math.sin(theta) * w[i])
              for i in range(3)]
        clb = tuple(uc.fractionalize(tuple(
            a + b for a, b in zip(uc.orthogonalize(zn), v2))))
        for lbl, el, site, occ, u in (
                ("ZN1", "Zn", zn, 1.0, 0.02),
                ("CL1", "Cl", cl, occ_a, 0.04),
                ("CL1B", "Cl", clb, 1.0 - occ_a, u_b)):
            xs.add_scatterer(xray.scatterer(label=lbl, site=site, u=u,
                                            occupancy=occ,
                                            scattering_type=el))
        flags = {"disorder_groups": [{
            "fvar_index": 2, "value": occ_a, "members": [
                {"label": "CL1", "part": 1, "sign": 1, "mult": 1.0},
                {"label": "CL1B", "part": 2, "sign": -1, "mult": 1.0}]}]}
        return SimpleNamespace(model=xs, flags=flags, dataset=None)

    def test_same_verdict_machinery_on_a_metal_halide(self):
        from crystalpilot.refine.disorder_accept import group_acceptance
        ses = self._p1_session(0.65)
        blk = group_acceptance(ses.model, ses.flags["disorder_groups"][0],
                               free_var={"value": 0.652, "su": 0.011},
                               d_min_data=0.84, r1_now=0.041,
                               origin={"r1_before": 0.052, "created": ["CL1B"]})
        assert blk["verdict"] == "supported"
        assert blk["components"] == {"A": ["CL1"], "B": ["CL1B"]}
        assert blk["separation"]["resolvable"] is True
        assert blk["sphere"]["consistent"] is True     # Zn sees one Zn-Cl length
        assert blk["delta_r1"]["delta_r1"] == pytest.approx(-0.011)
        assert "SADI" in " ".join(blk["restraint_suggestion"]["cards"])

    def test_unresolvable_separation_is_flagged_against_the_data(self):
        """The reference is the DATA's own d_min, not a constant: the same
        pair of sites reads differently at 0.84 A and at 1.6 A."""
        from crystalpilot.refine.disorder_accept import group_acceptance
        ses = self._p1_session(0.65)
        grp = ses.flags["disorder_groups"][0]
        fine = group_acceptance(ses.model, grp,
                                free_var={"value": 0.652, "su": 0.011},
                                d_min_data=0.84)
        coarse = group_acceptance(ses.model, grp,
                                  free_var={"value": 0.652, "su": 0.011},
                                  d_min_data=1.60)
        assert fine["separation"]["resolvable"] is True
        assert coarse["separation"]["resolvable"] is False
        assert "not resolved" in coarse["separation"]["reading"]
        assert fine["separation"]["d_A"] == coarse["separation"]["d_A"]

    def test_lopsided_adp_at_similar_occupancy_is_called_out(self):
        from crystalpilot.refine.disorder_accept import group_acceptance
        ses = self._p1_session(0.5, u_b=0.30)
        blk = group_acceptance(ses.model, ses.flags["disorder_groups"][0],
                               free_var={"value": 0.5, "su": 0.02})
        assert blk["verdict"] == "supported"     # the RATIO is measured
        assert "CL1B" in blk["adp"]["reading"]   # ... the ADP is not sane
        assert blk["adp"]["model_median_u_eq"] == pytest.approx(0.02)

    def test_minor_component_with_a_larger_adp_is_not_called_out(self):
        """A minor component is legitimately looser - the criterion must
        not fire on the normal case."""
        from crystalpilot.refine.disorder_accept import group_acceptance
        ses = self._p1_session(0.85, u_b=0.10)
        blk = group_acceptance(ses.model, ses.flags["disorder_groups"][0],
                               free_var={"value": 0.85, "su": 0.02})
        reading = blk["adp"].get("reading", "")
        assert "nearly the same share" not in reading


def test_no_shelxl_binary_is_skipped_not_faked():
    """Documents the skip contract of this module (see the fixtures)."""
    assert SHELXL.name == "shelxl.exe"
