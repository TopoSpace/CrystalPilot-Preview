

class TestShelxtLadderFlags:
    def test_cli_flags_mapping(self):
        from crystalpilot.refine.tools_shelxl import RunShelxt
        assert RunShelxt._cli_flags({}) == []
        assert RunShelxt._cli_flags(
            {"chem_quality": True, "all_space_groups": True}) == ["-y", "-a"]
        # -m is iterations per try: 1000 is clamped to the 500 cap (pa2)
        assert RunShelxt._cli_flags({"n_phase_sets": 1000}) == ["-m500"]
        assert RunShelxt._cli_flags({"n_phase_sets": 300}) == ["-m300"]
        assert RunShelxt._cli_flags({"solve_resolution": 1.2}) == ["-d1.2"]
        assert RunShelxt._cli_flags(
            {"chem_quality": True, "n_phase_sets": 500,
             "solve_resolution": 1.0}) == ["-y", "-m500", "-d1"]

    def test_thread_cap_matches_cpu_budget(self):
        """SHELXT sizes its pool from the machine, not our affinity mask."""
        from crystalpilot.refine.tools_shelxl import RunShelxt
        assert RunShelxt._cli_flags({}, 4) == ["-t4"]
        assert RunShelxt._cli_flags({"chem_quality": True}, 4) == ["-t4", "-y"]
        # cpu_limit_cores() == 0 means "unlimited": leave SHELXT's own
        # default alone rather than passing -t0.
        assert RunShelxt._cli_flags({}, 0) == []


class TestShelxtTimeoutMessage:
    """r25: a bare 'shelxt timed out' twice hid a FINISHED solution.

    Both runs completed dual-space phasing (62 s and 24 s, CFOM 0.745)
    and were killed during the subsequent space-group search. The agent
    read the silence as 'SHELXT cannot handle this cell' and fell back to
    charge flipping - the route its own skill card rates worse on weak
    data. The message has to say which half was running."""

    LXT_PHASED = """\
 Command line parameters:  -m100 -d1 job

 32 threads running in parallel

 -a set to extend space group search because atom heavier than Sc expected

 Laue group identified as number 12:   6/mmm

      32 attempts, solution 10 selected with best CFOM = 0.7450, Alpha0 = 0.224

 Structure solution:      62.020 secs
"""

    def _msg(self, tmp_path, text, elapsed=181.0, limit=180):
        from crystalpilot.refine.tools_shelxl import RunShelxt
        if text is not None:
            (tmp_path / "job.lxt").write_text(text, encoding="utf-8")
        return RunShelxt._timeout_message(tmp_path, elapsed, limit)

    def test_reports_finished_phasing_and_blames_the_search(self, tmp_path):
        m = self._msg(tmp_path, self.LXT_PHASED)
        assert "PHASING HAD ALREADY FINISHED" in m
        assert "62.020" in m
        assert "0.7450" in m
        assert "6/mmm" in m
        assert "180 s limit" in m and "181 s" in m
        # the actionable half: this is a budget problem, not a verdict
        assert "compute budget" in m
        assert "timeout_s" in m
        assert str(tmp_path) in m

    def test_flags_the_auto_enabled_all_space_groups_trap(self, tmp_path):
        """all_space_groups=false is a no-op for a metal-bearing cell."""
        m = self._msg(tmp_path, self.LXT_PHASED)
        assert "heavier than Sc" in m
        assert "all_space_groups=false does not" in m

    def test_no_auto_a_note_when_shelxt_did_not_say_so(self, tmp_path):
        m = self._msg(tmp_path, self.LXT_PHASED.replace(
            " -a set to extend space group search because atom heavier "
            "than Sc expected\n", ""))
        assert "all_space_groups" not in m

    def test_killed_during_phasing_says_so(self, tmp_path):
        cut = self.LXT_PHASED.split(" 32 attempts")[0]
        m = self._msg(tmp_path, cut)
        assert "during phasing" in m
        assert "6/mmm" in m
        assert "PHASING HAD ALREADY FINISHED" not in m

    def test_no_log_at_all(self, tmp_path):
        m = self._msg(tmp_path, None)
        assert "before writing any progress" in m
        assert "job dir" in m


class TestShelxLattSymm:
    def test_cccm_no_centring_translation_in_symm(self):
        # r22 live failure: C-centred groups got X+1/2,Y+1/2,Z as SYMM
        from cctbx import sgtbx
        from crystalpilot.refine.tools_shelxl import shelx_latt_symm
        latt, symm = shelx_latt_symm(
            sgtbx.space_group_info("C c c m").group())
        assert latt == 7                       # C-centred, centric
        joined = " | ".join(symm)
        assert "X+1/2,Y+1/2,Z" not in joined   # centring belongs to LATT
        assert len(symm) == 3                  # three non-trivial reps
        assert "SYMM X,Y,-Z" in joined or "SYMM -X,-Y,Z" in joined

    def test_p21c_and_acentric_groups(self):
        from cctbx import sgtbx
        from crystalpilot.refine.tools_shelxl import shelx_latt_symm
        latt, symm = shelx_latt_symm(
            sgtbx.space_group_info("P 21/c").group())
        assert latt == 1 and len(symm) == 1
        latt2, symm2 = shelx_latt_symm(
            sgtbx.space_group_info("F d d 2").group())
        assert latt2 == -4                     # F-centred, acentric
        assert all("X+1/2,Y+1/2" not in s or "-" in s or "1/4" in s
                   for s in symm2)
        latt3, symm3 = shelx_latt_symm(
            sgtbx.space_group_info("P -1").group())
        assert latt3 == 1 and symm3 == []      # inversion lives in LATT


LST_SNIPPET = """
 Mean shift/esd =   0.036  Maximum =     0.269 for  U33 C13
 blah
 Mean shift/esd =   0.002  Maximum =     0.029 for  U22 C9X
"""

LST_DISAGREE = """
 Disagreeable restraints before cycle    1

   Observed   Target    Error     Sigma     Restraint

                       -0.0411    0.0100    SIMU U11 C1 H6X
                       -0.0523    0.0100    SIMU U22 C1 H6X

 Disagreeable restraints before cycle    2

   Observed   Target    Error     Sigma     Restraint

      1.6288      1.5400    0.0888    0.0200    DFIX C1 C2
                       -0.0317    0.0100    SIMU U33 C1 H6X


 Summary of restraints applied in cycle    2
"""

RES_TWO_WGHT = """TITL x
CELL 0.7 10 10 10 90 90 90
WGHT    0.200000   36.000000
FVAR 1.0
C1 1 0 0 0 11 0.05
WGHT      0.1234      5.0000
FVAR       1.00000
END
"""


class TestRunShelxlSummaryParsers:
    def test_shift_esd_takes_last_cycle(self):
        from crystalpilot.refine.tools_shelxl import parse_shift_esd
        s = parse_shift_esd(LST_SNIPPET)
        assert s["n_cycles_reported"] == 2
        assert s["final_mean"] == 0.002 and s["final_max"] == 0.029
        assert s["converged"] is True
        assert s["final_max_param"] == "U22 C9X"
        assert parse_shift_esd("no such line") is None

    def test_wght_used_vs_suggested(self):
        from crystalpilot.refine.tools_shelxl import parse_wght_lines
        used, sug = parse_wght_lines(RES_TWO_WGHT)
        assert used == [0.2, 36.0]
        assert sug == [0.1234, 5.0]
        one = "TITL\nWGHT 0.1\nFVAR 1\nEND\n"
        u2, s2 = parse_wght_lines(one)
        assert u2 == [0.1, 0.0] and s2 == [0.1, 0.0]
        assert parse_wght_lines("TITL\nEND\n") is None

    def test_disagreeable_restraints_last_section(self):
        from crystalpilot.refine.tools_shelxl import (
            parse_disagreeable_restraints)
        d = parse_disagreeable_restraints(LST_DISAGREE)
        assert d["n"] == 2                      # last section only
        assert any("DFIX C1 C2" in w for w in d["worst"])
        assert parse_disagreeable_restraints("clean lst") is None

    def test_res_zerr_z(self):
        from crystalpilot.refine.tools_shelxl import _res_zerr_z
        assert _res_zerr_z("TITL x\nZERR 4 0.001 0 0 0 0 0\n") == 4
        assert _res_zerr_z("TITL x\nCELL 1 2 3 4 5 6 7\n") is None


class TestSetWeights:
    @staticmethod
    def _ctx(flags=None):
        from types import SimpleNamespace
        return SimpleNamespace(session=SimpleNamespace(
            flags=flags or {}, model=object()))

    def test_writes_session_flags(self):
        from crystalpilot.refine.tools_shelxl import SetWeights
        ctx = self._ctx({"weights": {"a": 0.1, "b": 0.0}})
        r = SetWeights(None).run(ctx, a=0.0523, b=12.5)
        assert r.ok, r.error
        assert ctx.session.flags["weights"] == {"a": 0.0523, "b": 12.5}
        assert r.summary["old"] == {"a": 0.1, "b": 0.0}

    def test_validation_refuses_garbage(self):
        from crystalpilot.refine.tools_shelxl import SetWeights
        assert not SetWeights(None).run(self._ctx(), a=-0.1).ok
        assert not SetWeights(None).run(self._ctx(), a=5.0).ok
        assert not SetWeights(None).run(self._ctx(), a=0.1, b=-1).ok
        r = SetWeights(None).run(self._ctx(), a=0.9)
        assert r.ok and "warning" in r.summary


class TestSetResolutionLimit:
    """r24 verdict follow-through: uncut 0.58 A data cost ~+0.02 R1 while
    the reference was cut at 0.81 A - the cutoff needed a session-state
    front door (the data_cards channel already round-trips SHEL)."""

    @staticmethod
    def _ctx(flags=None, fo_sq=None):
        from types import SimpleNamespace
        return SimpleNamespace(session=SimpleNamespace(
            flags=flags if flags is not None else {}, fo_sq=fo_sq))

    def test_sets_and_replaces_shel(self):
        from crystalpilot.refine.tools_shelxl import SetResolutionLimit
        ctx = self._ctx({"data_cards": ["SHEL 999 1.200", "OMIT -3 55"]})
        r = SetResolutionLimit(None).run(ctx, d_min=0.81,
                                         reason="CC1/2 shell table")
        assert r.ok, r.error
        cards = ctx.session.flags["data_cards"]
        assert cards == ["OMIT -3 55", "SHEL 999 0.810"]
        assert "run_shelxl" in r.summary["note"]

    def test_null_removes(self):
        from crystalpilot.refine.tools_shelxl import SetResolutionLimit
        ctx = self._ctx({"data_cards": ["SHEL 999 0.810", "OMIT -3 55"]})
        r = SetResolutionLimit(None).run(ctx, d_min=None, reason="undo")
        assert r.ok and r.summary["removed"]
        assert ctx.session.flags["data_cards"] == ["OMIT -3 55"]

    def test_guards(self):
        from crystalpilot.refine.tools_shelxl import SetResolutionLimit
        assert not SetResolutionLimit(None).run(
            self._ctx(), d_min=0.81, reason="  ").ok       # empty reason
        assert not SetResolutionLimit(None).run(
            self._ctx(), d_min=0.2, reason="x").ok         # out of range
        assert not SetResolutionLimit(None).run(
            self._ctx(), d_min=5.0, reason="x").ok

    def test_refuses_cut_beyond_data(self):
        from types import SimpleNamespace
        from crystalpilot.refine.tools_shelxl import SetResolutionLimit
        fo = SimpleNamespace(d_min=lambda: 0.95)
        r = SetResolutionLimit(None).run(self._ctx(fo_sq=fo), d_min=0.81,
                                         reason="x")
        assert not r.ok and "BEYOND the data" in r.error

    def test_shel_serialized_into_res(self, tmp_path):
        from crystalpilot.refine.nodes import serialization_extras
        from crystalpilot.io.shelx_writer import ShelxModel, write_res
        from cctbx import crystal, xray
        cs = crystal.symmetry(unit_cell=(8, 9, 10, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        xs.add_scatterer(xray.scatterer(label="C1", site=(0.1, 0.2, 0.3),
                                        u=0.03, scattering_type="C"))
        extras = serialization_extras(
            {"data_cards": ["SHEL 999 0.810"]})
        out = tmp_path / "t.res"
        write_res(ShelxModel(xray_structure=xs, **extras), out)
        assert "SHEL 999 0.810" in out.read_text(encoding="utf-8")

    def test_refuses_without_model(self):
        from types import SimpleNamespace
        from crystalpilot.refine.tools_shelxl import SetWeights
        ctx = SimpleNamespace(session=SimpleNamespace(flags={}, model=None))
        assert not SetWeights(None).run(ctx, a=0.1).ok


class TestSetZ:
    @staticmethod
    def _ctx_and_project():
        from types import SimpleNamespace
        from cctbx import crystal, xray
        cs = crystal.symmetry(unit_cell=(10, 10, 10, 90, 90, 90),
                              space_group_symbol="P 21/c")
        xs = xray.structure(crystal_symmetry=cs)
        for i, (el, site) in enumerate(
                [("C", (0.1, 0.2, 0.3)), ("C", (0.3, 0.1, 0.2)),
                 ("O", (0.5, 0.5, 0.1))]):
            xs.add_scatterer(xray.scatterer(
                label=f"{el}{i+1}", site=site, scattering_type=el))
        ses = SimpleNamespace(model=xs, flags={})
        proj = SimpleNamespace(_z=27)
        return SimpleNamespace(session=ses), proj

    def test_sets_project_z_with_composition_mirror(self):
        from crystalpilot.refine.tools_shelxl import SetZ
        ctx, proj = self._ctx_and_project()
        r = SetZ(proj).run(ctx, z=4, reason="one molecule per asu, sg order 4")
        assert r.ok, r.error
        assert proj._z == 4
        assert r.summary["old_z"] == 27 and r.summary["new_z"] == 4
        assert r.summary["sg_order"] == 4 and r.summary["z_prime"] == 1.0
        # 3 asu atoms x order 4 / z 4 -> integers, no warning
        assert r.summary["per_formula_non_h"] == {"C": 2.0, "O": 1.0}
        assert "warning" not in r.summary

    def test_fractional_composition_warns(self):
        from crystalpilot.refine.tools_shelxl import SetZ
        ctx, proj = self._ctx_and_project()
        r = SetZ(proj).run(ctx, z=8, reason="test")
        assert r.ok and "warning" in r.summary

    def test_refuses_without_model(self):
        from types import SimpleNamespace
        from crystalpilot.refine.tools_shelxl import SetZ
        ctx = SimpleNamespace(session=SimpleNamespace(model=None))
        r = SetZ(SimpleNamespace()).run(ctx, z=2, reason="x")
        assert not r.ok and "model" in r.error


class TestRescueLostH:
    """Process-audit T3: adopt's riding replay dropped H on classifier
    drift; rescue restores the carrier's H verbatim instead of warning."""

    @staticmethod
    def _session():
        from types import SimpleNamespace
        from cctbx import crystal, xray
        cs = crystal.symmetry(unit_cell=(12, 12, 12, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        for lbl, el, site in (("C1", "C", (0.1, 0.1, 0.1)),
                              ("C2", "C", (0.3, 0.1, 0.1)),
                              # replay placed only H2A for carrier C2
                              ("H2A", "H", (0.34, 0.14, 0.1)),
                              # free diff-map H survives untouched
                              ("H9", "H", (0.7, 0.7, 0.7))):
            xs.add_scatterer(xray.scatterer(
                label=lbl, site=site, scattering_type=el, u=0.03))
        ses = SimpleNamespace(model=xs, flags={
            "h_riding_meta": {"per_carrier": [
                {"carrier": "C2", "h": ["H2A"], "kind": "CH2"}]},
            "h_constraints": ["sentinel"]})
        return ses

    def test_carrier_group_restored_verbatim(self):
        from crystalpilot.refine.tools_shelxl import rescue_lost_h
        ses = self._session()
        # SHELXL model had H2A+H2B on C2 and H1 on C1; replay re-derived
        # only H2A (drifted classifier dropped H2B and H1)
        parsed_groups = [
            {"carrier": "C1", "h": ["H1"], "kind": "CH"},
            {"carrier": "C2", "h": ["H2A", "H2B"], "kind": "CH2"}]
        snapshot = {
            "H1": {"label": "H1", "site": (0.14, 0.1, 0.1),
                   "u_iso": 0.04, "occupancy": 1.0},
            "H2A": {"label": "H2A", "site": (0.33, 0.13, 0.1),
                    "u_iso": 0.04, "occupancy": 1.0},
            "H2B": {"label": "H2B", "site": (0.27, 0.13, 0.1),
                    "u_iso": 0.04, "occupancy": 1.0},
            "H9": {"label": "H9", "site": (0.7, 0.7, 0.7),
                   "u_iso": 0.05, "occupancy": 1.0}}
        out = rescue_lost_h(ses, parsed_groups, snapshot, ["H1", "H2B"])
        labels = sorted(sc.label for sc in ses.model.scatterers())
        assert labels == ["C1", "C2", "H1", "H2A", "H2B", "H9"]
        assert sorted(out["h_replay_rescued"]["carriers"]) == ["C1", "C2"]
        assert "h_replay_lost" not in out
        # meta: rescued carriers carry the PARSED groups (H2A+H2B), the
        # replayed partial group was swapped out
        pc = ses.flags["h_riding_meta"]["per_carrier"]
        c2 = next(g for g in pc if g["carrier"] == "C2")
        assert sorted(c2["h"]) == ["H2A", "H2B"]
        assert "h_constraints" not in ses.flags
        # restored H sits at the SHELXL position, not the replayed one
        h2a = next(sc for sc in ses.model.scatterers()
                   if sc.label == "H2A")
        assert abs(h2a.site[0] - 0.33) < 1e-9

    def test_free_h_restored_and_missing_snapshot_reported(self):
        from crystalpilot.refine.tools_shelxl import rescue_lost_h
        ses = self._session()
        out = rescue_lost_h(ses, [], {
            "H9X": {"label": "H9X", "site": (0.8, 0.8, 0.8),
                    "u_iso": 0.05, "occupancy": 1.0}},
            ["H9X", "HGONE"])
        labels = [sc.label for sc in ses.model.scatterers()]
        assert "H9X" in labels
        assert out["h_replay_lost"] == ["HGONE"]
        assert "do NOT deliver" in out["h_replay_warning"]

    def test_replay_h_on_rescued_carrier_removed_by_replay_label(self):
        """hex-l2-r2: rename_atoms had made the SHELXL model's H 'H4A';
        the replay re-placed 'H4' for the same carrier, the label-keyed
        removal missed it and the verbatim H4A landed next to it (26 -> 32
        atoms in the delivery). The replay's OWN labels must go too."""
        from crystalpilot.refine.tools_shelxl import rescue_lost_h
        ses = self._session()
        # the replay placed H2A on C2; the SHELXL model called it H2X
        parsed_groups = [{"carrier": "C2", "h": ["H2X"], "kind": "CH"}]
        snapshot = {"H2X": {"label": "H2X", "site": (0.33, 0.13, 0.1),
                            "u_iso": 0.04, "occupancy": 1.0}}
        out = rescue_lost_h(ses, parsed_groups, snapshot, ["H2X"])
        labels = sorted(sc.label for sc in ses.model.scatterers())
        assert labels == ["C1", "C2", "H2X", "H9"], labels
        assert out["h_replay_rescued"]["carriers"] == ["C2"]


# ==========================================================================
# P1-8b: WGHT convergence (run_shelxl mode='adopt_wght') and the per-carrier
# riding-H replay (adopt / checkout / import) - pa1 hex-l2-r2 evidence
# ==========================================================================

import textwrap  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

#: formate-like C1(O1)(O2)-H in P1: one aromatic-type CH carrier whose H
#: carries a canonical 'H1A' label (what rename_atoms produces), so any
#: replay that re-derives 'H1' and keeps H1A duplicates it
FORMATE_RES = textwrap.dedent("""\
    TITL formate
    CELL 0.71073 10.0 10.0 10.0 90.0 90.0 90.0
    ZERR 1 0.001 0.001 0.001 0.0 0.0 0.0
    LATT -1
    SFAC C H O
    UNIT 1 1 2
    WGHT 0.1
    FVAR 1.0
    C1   1  0.500000  0.500000  0.500000  11.00000  0.02000
    AFIX 43
    H1A  2  0.500000  0.593000  0.500000  11.00000 -1.20000
    AFIX 0
    O1   3  0.610900  0.442300  0.500000  11.00000  0.02500
    O2   3  0.389100  0.442300  0.500000  11.00000  0.02500
    HKLF 4
    END
    """)

HKL_3 = ("   1   0   0  100.00    5.00\n"
         "   0   1   0   80.00    4.00\n"
         "   0   0   1   60.00    3.00\n"
         "   0   0   0    0.00    0.00\n")


def _formate_project(tmp_path, res_text=FORMATE_RES):
    import json

    from crystalpilot.refine.project import RefineProject
    d = tmp_path / "proj"
    d.mkdir()
    (d / "crystal.hkl").write_text(HKL_3, encoding="utf-8")
    (d / "start.res").write_text(res_text, encoding="utf-8")
    (d / "context.json").write_text(json.dumps({
        "data": {"hkl": "crystal.hkl", "start_model": "start.res"}}),
        encoding="utf-8")
    p = RefineProject(d)
    p.open()
    return p


def _labels(model):
    return sorted(sc.label for sc in model.scatterers())


def _fake_shelxl(monkeypatch, tmp_path, suggest):
    """Stand-in for shelxl.exe: echoes job.ins as job.res with SHELXL's
    REM summary block and the trailing WGHT suggestion suggest(a, b)."""
    import re as _re

    from crystalpilot.refine import tools_shelxl
    calls: list[tuple[float, float]] = []

    def _exec(exe, job, timeout_s):
        ins = (job / "job.ins").read_text(encoding="utf-8")
        m = _re.search(r"^WGHT\s+([\d.]+)\s+([\d.]+)", ins, _re.M)
        a, b = float(m.group(1)), float(m.group(2))
        a2, b2 = suggest(a, b)
        goof = round(1.0 + (a2 - a) * 10, 3)
        rem = ("REM  fake SHELXL\n"
               f"REM wR2 = 0.1200, GooF = S = {goof:.3f}, Restrained GooF = "
               f"{goof:.3f} for all data\n"
               "REM R1 = 0.0500 for 3 Fo > 4sig(Fo) and 0.0600 for all 3 "
               "data\nREM 5 parameters refined using 0 restraints\n")
        # a later round's job.ins is the previous .res copy and already
        # carries a REM block before END: rebuild it every time
        body = [ln for ln in ins.splitlines()
                if not ln.startswith("REM") and ln.strip() != "END"]
        res = "\n".join(body) + "\n\n" + rem + "\nEND\n"
        res += (f"\nWGHT    {a2:.4f}    {b2:.4f}\n\nREM Highest difference "
                "peak  0.100,  deepest hole -0.100,  1-sigma level  0.050\n")
        (job / "job.res").write_text(res, encoding="ascii")
        (job / "job.lst").write_text(
            " Mean shift/esd =   0.001  Maximum =     0.010 for  x C1\n",
            encoding="ascii")
        calls.append((a, b))
        return res, "", None

    monkeypatch.setattr(tools_shelxl, "_execute_shelxl", _exec)
    exe = tmp_path / "fake_shelxl.exe"
    exe.write_text("", encoding="ascii")
    monkeypatch.setenv("CRYSTALPILOT_SHELXL", str(exe))
    return calls


def _toward_018(a, b):
    """SHELXL-like suggestion that halves the distance to a=0.18."""
    return round(0.5 * (a + 0.18), 4), b


class TestWghtHelpers:
    def test_wght_agrees_tolerance(self):
        from crystalpilot.refine.tools_shelxl import wght_agrees
        assert wght_agrees([0.1, 0.0], [0.104, 0.0])
        assert not wght_agrees([0.1, 0.0], [0.11, 0.0])
        assert wght_agrees([0.1, 10.0], [0.1, 10.4])       # 5 % of b
        assert not wght_agrees([0.1, 10.0], [0.1, 11.0])
        assert wght_agrees([0.1, 0.0], [0.1, 0.4])         # 0.5 floor

    def test_next_round_ins_replaces_header_wght_and_drops_trailer(self):
        from crystalpilot.refine.tools_shelxl import next_round_ins_text
        res = ("TITL x\nCELL 0.7 10 10 10 90 90 90\nL.S. 4\nWGHT    0.100000"
               "    0.000000\nFVAR 1.0\nC1 1 0 0 0 11 0.05\nHKLF 4\n\nREM R1 = "
               "0.05 for 3 Fo > 4sig(Fo) and 0.06 for all 3 data\nEND\n\n"
               "WGHT      0.1400      0.0000\n\nREM Highest difference peak\n"
               "Q1    1   0.5000  0.5000  0.2294  11.00000  0.05    0.71\n")
        ins = next_round_ins_text(res, [0.14, 0.0])
        assert "WGHT 0.140000 0.000000" in ins
        assert ins.count("WGHT") == 1
        assert "Q1 " not in ins and ins.rstrip().endswith("END")
        assert "L.S. 4" in ins and "C1 1 0 0 0 11 0.05" in ins
        with pytest.raises(ValueError):
            next_round_ins_text("TITL x\nHKLF 4\nWGHT 0.1\nEND\n", [0.1, 0])


class TestAdoptWghtLoop:
    """pa1: mode='adopt' kept the USED scheme while its note promised
    'takes the suggestion automatically'; every agent then looped
    set_weights + run_shelxl by hand (hex-l2-r2 x3, hex-l0-r1, cu-l3-r1,
    cage-l0-r1) or delivered GooF 1.5-1.7. mode='adopt_wght' is that
    loop, SHELXL-side, with the history in the summary."""

    def test_loop_converges_and_adopts_last_round(self, tmp_path,
                                                  monkeypatch):
        p = _formate_project(tmp_path)
        calls = _fake_shelxl(monkeypatch, tmp_path, _toward_018)
        r = p.invoke_tool("run_shelxl", {"mode": "adopt_wght", "l_s": 4,
                                         "wght_rounds": 4})
        assert r.ok, r.error
        loop = r.summary["wght_loop"]
        # 0.1 -> 0.14 -> 0.16 -> 0.17 -> 0.175 (|d| <= 0.005: converged)
        assert loop["converged"] is True and loop["rounds_run"] == 3
        assert [round(c[0], 3) for c in calls] == [0.1, 0.14, 0.16, 0.17]
        hist = loop["history"]
        assert [h["round"] for h in hist] == [0, 1, 2, 3]
        assert hist[0]["used"] == [0.1, 0.0] and hist[-1]["used"] == [0.17, 0.0]
        assert all(h["goof"] is not None for h in hist)
        assert "converged" in loop["note"] and "GooF" in loop["note"]
        # the adopted session carries the LAST round's scheme, the job_dir
        # is that round (write_outputs pairs the node with it), no stale
        # 'run adopt_wght' pointer survives
        assert p.session.flags["weights"] == {"a": 0.17, "b": 0.0}
        assert r.summary["job_dir"].endswith("_w3")
        assert (Path(r.summary["job_dir"]) / ".ok").exists()
        assert r.summary["shelxl"]["wght_converged"] is True
        assert "wght_note" not in r.summary["shelxl"]
        assert r.summary["adopted"] and r.summary.get("node")
        # round-1 job.ins is the round-0 .res with the suggestion as header
        w1 = Path(r.summary["job_dir"]).parent / (
            Path(r.summary["job_dir"]).name.replace("_w3", "_w1"))
        ins1 = (w1 / "job.ins").read_text(encoding="utf-8")
        assert "WGHT 0.140000 0.000000" in ins1 and ins1.count("WGHT") == 1
        assert (w1 / "job.hkl").exists()

    def test_loop_stops_at_round_budget_and_says_so(self, tmp_path,
                                                    monkeypatch):
        p = _formate_project(tmp_path)
        calls = _fake_shelxl(monkeypatch, tmp_path, _toward_018)
        r = p.invoke_tool("run_shelxl", {"mode": "adopt_wght", "l_s": 4,
                                         "wght_rounds": 1})
        assert r.ok, r.error
        loop = r.summary["wght_loop"]
        assert loop["converged"] is False and loop["rounds_run"] == 1
        assert len(calls) == 2
        assert "still moving" in loop["note"]
        assert p.session.flags["weights"] == {"a": 0.14, "b": 0.0}
        assert "error" not in loop and "warning" not in r.summary

    def test_no_extra_round_when_already_converged(self, tmp_path,
                                                   monkeypatch):
        p = _formate_project(tmp_path)
        calls = _fake_shelxl(monkeypatch, tmp_path, lambda a, b: (a, b))
        r = p.invoke_tool("run_shelxl", {"mode": "adopt_wght", "l_s": 2})
        assert r.ok, r.error
        assert len(calls) == 1
        assert r.summary["wght_loop"]["rounds_run"] == 0
        assert r.summary["wght_loop"]["converged"] is True

    def test_failed_round_keeps_last_completed_and_reports(self, tmp_path,
                                                           monkeypatch):
        from crystalpilot.refine import tools_shelxl
        p = _formate_project(tmp_path)
        calls = _fake_shelxl(monkeypatch, tmp_path, _toward_018)
        good = tools_shelxl._execute_shelxl

        def _flaky(exe, job, timeout_s):
            if job.name.endswith("_w2"):
                return "", "", "shelxl timed out after 1 s (w2)"
            return good(exe, job, timeout_s)

        monkeypatch.setattr(tools_shelxl, "_execute_shelxl", _flaky)
        r = p.invoke_tool("run_shelxl", {"mode": "adopt_wght", "l_s": 4,
                                         "wght_rounds": 4})
        assert r.ok, r.error
        loop = r.summary["wght_loop"]
        assert loop["rounds_run"] == 1 and "timed out" in loop["error"]
        assert "timed out" in r.summary["warning"]
        assert p.session.flags["weights"] == {"a": 0.14, "b": 0.0}
        assert len(calls) == 2

    def test_mode_guards(self, tmp_path, monkeypatch):
        p = _formate_project(tmp_path)
        _fake_shelxl(monkeypatch, tmp_path, _toward_018)
        r = p.invoke_tool("run_shelxl", {"mode": "adopt_wght", "l_s": 0})
        assert not r.ok and "l_s >= 1" in r.error
        r2 = p.invoke_tool("run_shelxl", {"mode": "adopt", "l_s": 4})
        assert r2.ok and "wght_loop" not in r2.summary
        # the adopted structure carries the dataset anomalous terms (Mo K-alpha
        # here: small but not zero) - round-3 2026-09-06 session setter
        assert p.session.dataset.wavelength and any(
            sc.fp != 0.0 for sc in p.session.model.scatterers())
        # plain adopt keeps the scheme it ran with, and its note now points
        # at the loop instead of promising an automatic adoption
        assert p.session.flags["weights"] == {"a": 0.1, "b": 0.0}
        assert "adopt_wght" in r2.summary["shelxl"]["wght_note"]

    def test_check_mode_untouched(self, tmp_path, monkeypatch):
        p = _formate_project(tmp_path)
        _fake_shelxl(monkeypatch, tmp_path, _toward_018)
        r = p.invoke_tool("run_shelxl", {"mode": "check", "l_s": 4})
        assert r.ok and r.summary["no_state_change"]
        assert r.summary["shelxl"]["suggested_wght"] == [0.14, 0.0]

    def test_real_shelxl_res_to_ins_round_trip(self, tmp_path):
        """The loop feeds SHELXL its own .res (3-line TITL echo, ABIN,
        cards) as the next .ins - prove real SHELXL-2019/3 accepts it."""
        import shutil

        from crystalpilot.refine.project import RefineProject
        from crystalpilot.refine.tools_shelxl import DEFAULT_SHELXL
        demo = Path(__file__).resolve().parents[1] / "workbench" / \
            "demo-live-sjtu9"
        if not DEFAULT_SHELXL.exists():
            pytest.skip("vendor shelxl not present")
        if not all((demo / name).is_file() for name in ("start.res", "crystal.hkl")):
            pytest.skip("complete demo project needs start.res and crystal.hkl")
        d = tmp_path / "proj"
        shutil.copytree(demo, d, ignore=shutil.ignore_patterns(
            "uploads", "scene-cache", "checkcif", "runs", "specialists",
            "CrystalPilot Results", ".crystalpilot"))
        p = RefineProject(d)
        p.open()
        r = p.invoke_tool("run_shelxl", {"mode": "adopt_wght", "l_s": 2,
                                         "wght_rounds": 2, "timeout_s": 120})
        assert r.ok, r.error
        loop = r.summary["wght_loop"]
        assert "error" not in loop, loop
        assert 1 <= len(loop["history"]) <= 3
        for row in loop["history"]:
            assert row["used"] and row["goof"] is not None
        job = Path(r.summary["job_dir"])
        assert (job / ".ok").exists() and (job / "job.cif").exists()
        used = r.summary["shelxl"]["wght_used"]
        assert p.session.flags["weights"] == {"a": used[0], "b": used[1]}
        if loop["rounds_run"]:
            assert job.name.endswith(f"_w{loop['rounds_run']}")
            ins = (job / "job.ins").read_text(encoding="utf-8",
                                              errors="replace")
            assert ins.count("\nWGHT") == 1


class TestRidingReplayIdempotent:
    """hex-l2-r2: rename_atoms (H4 -> H4A) + run_shelxl adopt = the replay
    re-derived 'H4', called H4A lost and restored it verbatim next to H4;
    26 -> 32 atoms in a delivery. The replay now replaces per carrier,
    judges loss by count, keeps labels, never resurrects deleted H and
    survives a failing add_hydrogens without losing the model's H."""

    def test_import_keeps_canonical_labels(self, tmp_path):
        p = _formate_project(tmp_path)
        assert _labels(p.session.model) == ["C1", "H1A", "O1", "O2"]
        pc = p.session.flags["h_riding_meta"]["per_carrier"]
        assert pc == [dict(pc[0], carrier="C1", h=["H1A"])]
        assert p.session.flags.get("h_constraints")

    def test_adopt_replay_replaces_not_duplicates(self, tmp_path,
                                                  monkeypatch):
        p = _formate_project(tmp_path)
        _fake_shelxl(monkeypatch, tmp_path, lambda a, b: (a, b))
        r = p.invoke_tool("run_shelxl", {"mode": "adopt", "l_s": 4})
        assert r.ok, r.error
        assert r.summary["n_atoms"] == 4
        assert _labels(p.session.model) == ["C1", "H1A", "O1", "O2"]
        rep = r.summary["h_replay"]
        assert rep["replaced"] == 1 and rep["added"] == 0
        assert rep["kept_verbatim"] == 0 and rep["relabelled"] == 1
        assert rep["n_h_before"] == rep["n_h_after"] == 1
        assert "h_replay_rescued" not in r.summary
        assert "not duplicated" in r.summary["h_replay_note"]
        # a second adopt is a no-op on the H set
        r2 = p.invoke_tool("run_shelxl", {"mode": "adopt", "l_s": 4})
        assert r2.ok and r2.summary["n_atoms"] == 4
        assert _labels(p.session.model) == ["C1", "H1A", "O1", "O2"]

    def test_checkout_replay_keeps_labels_and_count(self, tmp_path):
        p = _formate_project(tmp_path)
        node = p.nodes.state()["active_node"]
        out = p.checkout(node)
        assert out["n_atoms"] == 4
        assert _labels(p.session.model) == ["C1", "H1A", "O1", "O2"]
        assert any("replaced in place" in n for n in out["notes"])

    def test_checkout_keeps_refined_h_coordinates_and_adp(self, tmp_path):
        p = _formate_project(tmp_path)
        h = next(sc for sc in p.session.model.scatterers() if sc.label == "H1A")
        h.site = (0.502, 0.599, 0.506)
        h.u_iso = 0.047
        h.occupancy = 1.0
        node = p.nodes.commit(p.session, tool="test", params={})["id"]
        from crystalpilot.io.shelx_model import load_res_model
        parsed = load_res_model(p.nodes.node_dir(node) / "model.res")
        expected = next(sc for sc in parsed.structure.scatterers() if sc.label == "H1A")
        for _ in range(2):
            p.checkout(node)
            actual = next(sc for sc in p.session.model.scatterers() if sc.label == "H1A")
            assert tuple(actual.site) == pytest.approx(tuple(expected.site), abs=1e-12)
            assert actual.u_iso == pytest.approx(expected.u_iso)
            assert actual.occupancy == pytest.approx(expected.occupancy)

    def test_replay_rebuilds_constraints_without_reidealizing_loaded_atoms(self):
        from crystalpilot.refine.tools_shelxl import replay_riding_h
        reg, ctx, ses = self._direct_session()
        h = next(sc for sc in ses.model.scatterers() if sc.label == "H1A")
        h.site = (0.502, 0.599, 0.506)
        h.u_iso = 0.047
        before = {sc.label: (tuple(sc.site), float(sc.u_iso), float(sc.occupancy))
                  for sc in ses.model.scatterers()}
        parsed = [{"carrier": "C1", "h": ["H1A"], "kind": "aromatic_CH", "afix": 43}]
        ses.flags["h_riding_meta"] = {"per_carrier": parsed}
        for _ in range(2):
            replay_riding_h(reg, ctx, ses, parsed)
            assert ses.flags.get("h_constraints")
            for sc in ses.model.scatterers():
                site, u_iso, occupancy = before[sc.label]
                assert tuple(sc.site) == pytest.approx(site, abs=1e-12)
                assert sc.u_iso == pytest.approx(u_iso)
                assert sc.occupancy == pytest.approx(occupancy)

    def test_replay_does_not_resurrect_deleted_h(self, tmp_path,
                                                 monkeypatch):
        """hex-l2-r2 39:xx: edit_atoms deleted the O5-H (U 0.21 ghost);
        the next adopt brought it back from the stored force_kind."""
        p = _formate_project(tmp_path)
        # protonate C1 through an explicit call whose params get stored
        r0 = p.invoke_tool("add_hydrogens", {"elements": ["C"],
                                             "force_kind": {"C1": "aromatic_CH"}})
        assert r0.ok and r0.summary["n_h_added"] == 1
        # an explicit add_hydrogens names H after the carrier (H1) - only
        # replays preserve labels; delete whatever it placed
        h_lbl = r0.summary["per_carrier"][0]["h"][0]
        rd = p.invoke_tool("edit_atoms", {"operations": [
            {"action": "delete", "atoms": [h_lbl]}]})
        assert rd.ok, rd.error
        assert _labels(p.session.model) == ["C1", "O1", "O2"]
        _fake_shelxl(monkeypatch, tmp_path, lambda a, b: (a, b))
        r = p.invoke_tool("run_shelxl", {"mode": "adopt", "l_s": 4})
        assert r.ok, r.error
        assert _labels(p.session.model) == ["C1", "O1", "O2"], \
            "adopt must not re-protonate a carrier whose H was deleted"

    @staticmethod
    def _direct_session(with_h1b=False, second_formate=False):
        from types import SimpleNamespace
        from cctbx import crystal, xray
        from crystalpilot.core.dataset import ReflectionDataset
        from crystalpilot.pipeline.session import SolveSession
        from crystalpilot.refine.registry import refinement_registry
        from crystalpilot.tools.base import ToolContext
        cs = crystal.symmetry(unit_cell=(10, 10, 10, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        atoms = [("C1", "C", (0.5, 0.5, 0.5)),
                 ("H1A", "H", (0.5, 0.593, 0.5)),
                 ("O1", "O", (0.6109, 0.4423, 0.5)),
                 ("O2", "O", (0.3891, 0.4423, 0.5))]
        if with_h1b:
            atoms.insert(2, ("H1B", "H", (0.56, 0.57, 0.5)))
        if second_formate:
            atoms += [("C2", "C", (0.0, 0.0, 0.0)),
                      ("O3", "O", (0.1109, -0.0577, 0.0)),
                      ("O4", "O", (-0.1109, -0.0577, 0.0))]
        for lbl, el, site in atoms:
            xs.add_scatterer(xray.scatterer(
                label=lbl, site=site, scattering_type=el, u=0.03))
        xs.scattering_type_registry(table="it1992")
        ses = SolveSession(dataset=ReflectionDataset(
            intensities=None, wavelength=0.71073))
        ses.model = xs
        ses.symmetry = cs

        class _Store:
            def emit(self, *a, **k):
                return SimpleNamespace(event_id="e0")

        ctx = ToolContext(store=_Store(), session=ses)
        return refinement_registry(None), ctx, ses

    def test_stale_labels_and_bare_carriers_are_left_alone(self):
        from crystalpilot.refine.tools_shelxl import replay_riding_h
        reg, ctx, ses = self._direct_session(second_formate=True)
        ses.flags["h_riding_meta"] = {
            "per_carrier": [{"carrier": "C1", "h": ["H1A"],
                             "kind": "aromatic_CH"}],
            "params": {"elements": ["C"], "force_kind": {"O007": "OH"},
                       "exclude": ["C0X"]}}
        parsed = [{"carrier": "C1", "h": ["H1A"], "kind": "aromatic_CH",
                   "afix": 43}]
        out = replay_riding_h(reg, ctx, ses, parsed)
        assert out["h_replay"] == {
            "replaced": 1, "added": 0, "kept_verbatim": 0, "relabelled": 1,
            "n_h_before": 1, "n_h_after": 1}, out
        assert _labels(ses.model) == ["C1", "C2", "H1A", "O1", "O2", "O3",
                                      "O4"]
        # the stored params stay the agent's own call, not the derived
        # exclude list
        assert ses.flags["h_riding_meta"]["params"] == {
            "elements": ["C"], "force_kind": {"O007": "OH"},
            "exclude": ["C0X"]}
        assert ses.flags["h_riding_meta"]["per_carrier"][0]["h"] == ["H1A"]

    def test_failed_add_hydrogens_restores_every_h_verbatim(self):
        from crystalpilot.refine.tools_shelxl import replay_riding_h
        reg, ctx, ses = self._direct_session()
        parsed = [{"carrier": "C1", "h": ["H1A"], "kind": "aromatic_CH"}]
        ses.flags["h_riding_meta"] = {"per_carrier": parsed}
        out = replay_riding_h(reg, ctx, ses, parsed,
                              {"elements": ["C"],
                               "force_kind": {"C1": "BOGUS"}})
        assert "BOGUS" in out["h_replay"]["failed"]
        assert "FAILED" in out["h_replay_note"]
        assert _labels(ses.model) == ["C1", "H1A", "O1", "O2"]
        h = next(sc for sc in ses.model.scatterers() if sc.label == "H1A")
        assert abs(h.site[1] - 0.593) < 1e-9
        assert ses.flags["h_riding_meta"]["per_carrier"][0]["h"] == ["H1A"]

    def test_short_carrier_kept_verbatim_without_duplicates(self):
        """the loaded model says C1 carries two H; the classifier derives
        one -> both originals stay, the derived one goes (count-based)."""
        from crystalpilot.refine.tools_shelxl import replay_riding_h
        reg, ctx, ses = self._direct_session(with_h1b=True)
        parsed = [{"carrier": "C1", "h": ["H1A", "H1B"], "kind": "CH2",
                   "afix": 23}]
        ses.flags["h_riding_meta"] = {"per_carrier": parsed}
        out = replay_riding_h(reg, ctx, ses, parsed, {"elements": ["C"]})
        assert _labels(ses.model) == ["C1", "H1A", "H1B", "O1", "O2"]
        rep = out["h_replay"]
        assert rep["replaced"] == 0 and rep["kept_verbatim"] == 2
        assert rep["n_h_before"] == rep["n_h_after"] == 2
        assert out["h_replay_rescued"]["carriers"] == ["C1"]
        assert "kept verbatim" in out["h_replay_note"]

    def test_restrict_replay_params(self):
        from crystalpilot.refine.tools_shelxl import _restrict_replay_params
        _, _, ses = self._direct_session(second_formate=True)
        p = _restrict_replay_params(
            ses.model, [{"carrier": "C1", "h": ["H1A"]}],
            {"elements": ["C", "O"], "force_kind": {"C1": "CH2",
                                                    "GONE": "OH"},
             "exclude": ["O1", "NOPE"]})
        assert p["elements"] == ["C", "O"]
        assert p["force_kind"] == {"C1": "CH2"}
        # every C/O without riding H in the loaded model is excluded
        assert p["exclude"] == ["C2", "O1", "O2", "O3", "O4"]


# ==========================================================================
# D11: run_shelxl(extra_cards=[...]) and the HTAB -> _geom_hbond_* CIF path
# ==========================================================================

class TestExtraCardsChannel:
    """The gate runs BEFORE the model is serialized and SHELXL is started.

    SHELXL's own answer to a card it cannot use is to abort the job and
    leave the reason in the .lst, which reaches the agent as a bare
    'shelxl failed (exit 2)'. The card-level cases live in
    tests/test_shelx_cards.py; these three prove the wiring."""

    def test_a_bad_card_is_refused_without_running_shelxl(self, tmp_path,
                                                          monkeypatch):
        p = _formate_project(tmp_path)
        calls = _fake_shelxl(monkeypatch, tmp_path, _toward_018)
        r = p.invoke_tool("run_shelxl", {"mode": "check", "l_s": 4,
                                         "extra_cards": ["HTAB O1 O9"]})
        assert not r.ok
        assert "'HTAB O1 O9'" in r.error and "'O9'" in r.error
        assert "session is unchanged" in r.error
        assert calls == []                      # SHELXL was never started

    def test_accepted_cards_reach_the_ins_and_the_summary(self, tmp_path,
                                                          monkeypatch):
        p = _formate_project(tmp_path)
        _fake_shelxl(monkeypatch, tmp_path, _toward_018)
        r = p.invoke_tool("run_shelxl", {
            "mode": "check", "l_s": 4,
            # deliberately out of order: EQIV must be emitted first
            "extra_cards": ["HTAB O1 O2_$1", "EQIV $1 x,y+1,z"],
            "reason": "publish the O-H...O table with esds"})
        assert r.ok, r.error
        ins = (Path(r.summary["job_dir"]) / "job.ins").read_text(
            encoding="utf-8", errors="replace")
        i_eqiv = ins.index("EQIV $1 X, Y+1, Z")
        i_htab = ins.index("HTAB O1 O2_$1")
        assert i_eqiv < i_htab < ins.index("\nHKLF")
        extra = r.summary["extra_cards"]
        assert extra["applied"] == ["EQIV $1 X, Y+1, Z", "HTAB O1 O2_$1"]
        assert extra["reason"] == "publish the O-H...O table with esds"
        assert "esds" in extra["note"]

    def test_no_extra_cards_no_extra_summary_block(self, tmp_path,
                                                   monkeypatch):
        p = _formate_project(tmp_path)
        _fake_shelxl(monkeypatch, tmp_path, _toward_018)
        r = p.invoke_tool("run_shelxl", {"mode": "check", "l_s": 4})
        assert r.ok and "extra_cards" not in r.summary


# --- the live SHELXL half --------------------------------------------------

#: P-1, two methanol-like fragments with an O1-H1...O2 bond of exactly
#: 2.750 A and an O-H...O angle of 180 deg inside the asymmetric unit.
#: Nothing here is specific to methanol: the card path only needs a donor
#: carrying an H and an acceptor, and the geometry is built from cartesian
#: distances so the numbers SHELXL must reproduce are exact.
_HB_CELL = (12.0, 13.0, 14.0, 90.0, 97.0, 90.0)
_HB_SHIFT = (0.30, 0.30, 0.30)
_HB_ATOMS = [
    ("O1", "O", (0.00, 0.00, 0.00), 0.03),
    ("C1", "C", (-0.75, 1.24, 0.00), 0.03),
    ("H1", "H", (0.95, 0.00, 0.00), 0.05),
    ("H1A", "H", (-1.55, 1.25, 0.75), 0.06),
    ("H1B", "H", (-1.20, 1.35, -0.99), 0.06),
    ("H1C", "H", (-0.12, 2.11, 0.15), 0.06),
    ("O2", "O", (2.75, 0.00, 0.00), 0.03),
    ("C2", "C", (3.50, 1.24, 0.00), 0.03),
    ("H2", "H", (3.28, -0.70, 0.35), 0.05),
    ("H2A", "H", (4.30, 1.25, 0.75), 0.06),
    ("H2B", "H", (3.95, 1.35, -0.99), 0.06),
    ("H2C", "H", (2.87, 2.11, 0.15), 0.06),
]


def _hbond_structure():
    from cctbx import crystal, xray
    cs = crystal.symmetry(unit_cell=_HB_CELL, space_group_symbol="P -1")
    uc = cs.unit_cell()
    xs = xray.structure(crystal_symmetry=cs)
    for lbl, el, cart, u in _HB_ATOMS:
        fr = uc.fractionalize(cart)
        xs.add_scatterer(xray.scatterer(
            label=lbl, site=tuple(fr[k] + _HB_SHIFT[k] for k in range(3)),
            u=u, occupancy=1.0, scattering_type=el))
    return xs


def _hbond_project(tmp_path):
    """Project whose HKLF4 data are computed from that structure."""
    import json

    from cctbx.array_family import flex

    from crystalpilot.io.cif_sf import write_hklf4
    from crystalpilot.io.shelx_writer import ShelxModel, write_res
    from crystalpilot.refine.project import RefineProject
    d = tmp_path / "hb"
    d.mkdir(parents=True, exist_ok=True)
    xs = _hbond_structure()
    i_obs = xs.structure_factors(
        d_min=1.0, algorithm="direct").f_calc().as_intensity_array()
    flex.set_random_seed(7)
    data = i_obs.data()
    sig = 0.03 * flex.abs(data) + 0.02 * flex.mean(flex.abs(data))
    noise = (flex.random_double(data.size()) - 0.5) * 2.0 * sig
    write_hklf4(i_obs.customized_copy(data=data + noise, sigmas=sig),
                d / "crystal.hkl")
    write_res(ShelxModel(xray_structure=xs, wavelength=0.71073, z=2,
                         weights=(0.1, 0.0), scale=1.0), d / "start.res")
    (d / "context.json").write_text(json.dumps({
        "data": {"hkl": "crystal.hkl", "start_model": "start.res"}}),
        encoding="utf-8")
    p = RefineProject(d)
    p.open()
    return p


def _shelxl_binary():
    """The binary run_shelxl itself would use - env override included, so a
    git worktree without vendor/ can still run these by pointing
    CRYSTALPILOT_SHELXL at the checkout that has it."""
    import os

    from crystalpilot.refine.tools_shelxl import DEFAULT_SHELXL
    return Path(os.environ.get("CRYSTALPILOT_SHELXL", str(DEFAULT_SHELXL)))


def _hbond_rows(cif_text: str) -> list[list[str]]:
    """The data rows of the _geom_hbond_* loop, as token lists."""
    lines = cif_text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines)
                     if ln.strip() == "_geom_hbond_atom_site_label_D")
    except StopIteration:
        return []
    i = start
    while i < len(lines) and lines[i].strip().startswith("_geom_hbond"):
        i += 1
    rows = []
    while i < len(lines):
        s = lines[i].strip()
        if not s or s.startswith("_") or s.startswith("loop_"):
            break
        rows.append(s.split())
        i += 1
    return rows


class TestHtabReachesTheDeliveredCif:
    """D11 end to end with the vendor binary: an HTAB card -> SHELXL's own
    _geom_hbond_* loop WITH esds -> final.cif.

    The point of the whole channel is that CrystalPilot does NOT compute
    these numbers: only SHELXL has the covariance matrix."""

    def test_htab_card_produces_the_hbond_loop_in_cif_and_final_cif(
            self, tmp_path):
        if not _shelxl_binary().exists():
            pytest.skip("vendor shelxl not present")
        p = _hbond_project(tmp_path)
        r = p.invoke_tool("run_shelxl", {
            "mode": "adopt", "l_s": 4, "timeout_s": 300,
            "extra_cards": ["HTAB O1 O2"],
            "reason": "O-H...O table for the delivery"})
        assert r.ok, r.error
        assert r.summary["extra_cards"]["applied"] == ["HTAB O1 O2"]
        assert r.summary["extra_cards"]["hbond_loop_in_cif"] is True
        cif = (Path(r.summary["job_dir"]) / "job.cif").read_text(
            encoding="utf-8", errors="replace")
        rows = _hbond_rows(cif)
        assert len(rows) == 1, cif[cif.find("_geom_hbond"):][:400]
        d, h, a, _dh, ha, da, ang = rows[0][:7]
        assert (d, h, a) == ("O1", "H1", "O2")
        # SHELXL measured them, with esds, from the geometry we built
        assert da.startswith("2.75") and "(" in da
        assert ha.startswith("1.80") and "(" in ha
        assert ang.startswith("179") or ang.startswith("180")

        # ... and the text-level publication assembler carries the loop
        # through to the delivered CIF untouched
        w = p.invoke_tool("write_outputs", {"output_dir": "out"})
        assert w.ok, w.error
        assert w.summary["publication_cif"] is True, w.summary
        final = (p.dir / "out" / "final.cif").read_text(
            encoding="utf-8", errors="replace")
        assert _hbond_rows(final) == rows
        assert "_geom_special_details" in final

    def test_no_htab_card_no_hbond_loop(self, tmp_path):
        """The loop is absent by default - which is exactly defect D11."""
        if not _shelxl_binary().exists():
            pytest.skip("vendor shelxl not present")
        p = _hbond_project(tmp_path)
        r = p.invoke_tool("run_shelxl", {"mode": "check", "l_s": 4,
                                         "timeout_s": 300})
        assert r.ok, r.error
        cif = (Path(r.summary["job_dir"]) / "job.cif").read_text(
            encoding="utf-8", errors="replace")
        assert "_geom_hbond_atom_site_label_D" not in cif

    def test_an_eqiv_card_survives_to_shelxl(self, tmp_path):
        """The symmetry half of the path: SHELXL reads the _$n code and
        reports the image distance (14.49 A here - deliberately too far to
        be a hydrogen bond, so the card is exercised without inventing
        one)."""
        if not _shelxl_binary().exists():
            pytest.skip("vendor shelxl not present")
        p = _hbond_project(tmp_path)
        r = p.invoke_tool("run_shelxl", {
            "mode": "check", "l_s": 2, "timeout_s": 300,
            "extra_cards": ["EQIV $1 -x,-y,-z", "HTAB O2 O1_$1"]})
        assert r.ok, r.error
        job = Path(r.summary["job_dir"])
        lst = (job / "job.lst").read_text(encoding="utf-8", errors="replace")
        assert "O2...O1_$1" in lst
        res = (job / "job.res").read_text(encoding="utf-8", errors="replace")
        assert "EQIV $1 -X, -Y, -Z" in res
