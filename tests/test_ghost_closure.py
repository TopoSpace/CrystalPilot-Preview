"""Ghost-verdict closure: sensitivity floor, dispositions, ledger, guard.

A ghost_test verdict used to be a number in one tool result: the R1 fence
was read as a hard threshold on models where a real atom cannot move R1
by that much, and a 'real' verdict had no consequence - the atom could be
deleted in the next call. Now every row says whether the fence can even
see an atom of that weight (expected_delta_r1_if_real), carries a
disposition, and 'real' verdicts go on a project ledger that edit_atoms
consults before any delete.

All structures here are synthetic: a small organic cell in P21/c, a
heavy-atom framework in P-1, and the five-atom P-1 project with computed
data (in-process refinements run in well under a second).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

cctbx = pytest.importorskip("cctbx")

from cctbx import crystal, xray  # noqa: E402

from crystalpilot.refine import ghost_ledger  # noqa: E402
from crystalpilot.refine.tools_batch import (  # noqa: E402
    DISPOSITION, GHOST_CRITERION, GHOST_PEAK_NONE, GHOST_PEAK_REAL,
    GHOST_R1_RISE, GROUP_REAL_NOTE, _detectability, _ghost_verdict)
from crystalpilot.tools.base import ToolContext  # noqa: E402
from crystalpilot.tools.model_tools import EditAtoms  # noqa: E402


# ==========================================================================
# synthetic structures
# ==========================================================================
def _structure(cell, sg, atoms):
    """atoms: (label, element, site, occupancy)."""
    sps = crystal.special_position_settings(
        crystal.symmetry(unit_cell=cell, space_group_symbol=sg),
        min_distance_sym_equiv=0.5)
    xs = xray.structure(special_position_settings=sps)
    for lbl, el, site, occ in atoms:
        xs.add_scatterer(xray.scatterer(
            label=lbl, site=site, scattering_type=el, u=0.03, occupancy=occ))
    xs.scattering_type_registry(table="it1992")
    return xs


def small_molecule():
    """An organic C8 N O2 molecule plus a half-occupied water in P21/c."""
    atoms = [(f"C{i}", "C", (0.10 + 0.07 * i, 0.12 + 0.03 * i, 0.15), 1.0)
             for i in range(1, 9)]
    atoms += [("N1", "N", (0.30, 0.40, 0.35), 1.0),
              ("O1", "O", (0.60, 0.20, 0.45), 1.0),
              ("O2", "O", (0.70, 0.35, 0.55), 1.0),
              ("O1W", "O", (0.85, 0.75, 0.80), 0.5),
              ("H1", "H", (0.14, 0.15, 0.22), 1.0)]
    return _structure((8.0, 10.0, 12.0, 90.0, 100.0, 90.0), "P 21/c", atoms)


def heavy_framework(zr_general=True):
    """Six Zr and 150 C, every atom on a general position of P-1 (a grid
    that no inversion centre maps onto itself), 20 A cell."""
    atoms = []
    for i in range(6):
        site = ((0.13 + 0.12 * i, 0.31, 0.47) if zr_general
                else (0.0, 0.0, 0.0))
        atoms.append((f"ZR{i + 1}", "Zr", site, 1.0))
    n = 0
    for i in range(6):
        for j in range(6):
            for k in range(6):
                if n >= 150:
                    break
                n += 1
                atoms.append((f"C{n}", "C",
                              (0.05 + i / 6.0, 0.05 + j / 6.0, 0.05 + k / 6.0),
                              1.0))
    return _structure((20.0, 20.0, 20.0, 90.0, 90.0, 90.0), "P -1", atoms)


# ==========================================================================
# (a) the verdict in the floor regime rests on the returning peak
# ==========================================================================
class TestFloorVerdict:
    def test_fence_uninformative_peak_decides(self):
        v, why = _ghost_verdict(+0.0005, 2.5, None, fence_informative=False,
                                expected_delta_r1=0.0009)
        assert v == "real"
        assert "detectability floor" in why and "returning peak" in why
        assert "0.0009" in why and "never delete it silently" in why
        v, why = _ghost_verdict(+0.0005, 0.2, None, fence_informative=False,
                                expected_delta_r1=0.0009)
        assert v == "ghost" and "delete it" in why
        assert "detectability floor" in why and "carries no information" in why
        v, why = _ghost_verdict(-0.0010, 0.7, None, fence_informative=False,
                                expected_delta_r1=0.0009)
        assert v == "inconclusive" and "detectability floor" in why

    def test_fence_uninformative_but_r1_rose_more_than_the_atom_could(self):
        # no peak returns yet R1 rose above the fence: the atom absorbed
        # density that is not localised there - still not a ghost
        v, why = _ghost_verdict(+0.0060, 0.2, None, fence_informative=False,
                                expected_delta_r1=0.0009)
        assert v == "inconclusive" and "not localised" in why

    def test_informative_fence_keeps_the_original_criterion(self):
        assert _ghost_verdict(+0.0005, 2.5, None)[0] == "inconclusive"
        assert _ghost_verdict(+0.0005, 2.5, None, fence_informative=True,
                              expected_delta_r1=0.02)[0] == "inconclusive"
        # None = no reference to judge against: the original criterion too
        assert _ghost_verdict(+0.0005, 2.5, None,
                              fence_informative=None)[0] == "inconclusive"
        assert _ghost_verdict(+0.010, 3.0, None,
                              fence_informative=False)[0] == "real"
        assert _ghost_verdict(None, None, None,
                              fence_informative=False)[0] == "inconclusive"

    def test_ripple_zone_note_survives_the_floor_regime(self):
        metal = {"label": "ZR1", "element": "Zr", "d_A": 0.8}
        v, why = _ghost_verdict(+0.0003, 1.6, metal, fence_informative=False,
                                expected_delta_r1=0.0004)
        assert v == "real" and "ripple zone" in why and "ZR1" in why

    def test_criterion_and_dispositions_spell_out_the_closure(self):
        assert "detectability floor" in GHOST_CRITERION
        assert "r1_fence_informative" in GHOST_CRITERION
        assert "only deletion licence" in GHOST_CRITERION
        assert str(GHOST_PEAK_REAL) in GHOST_CRITERION
        assert str(GHOST_PEAK_NONE) in GHOST_CRITERION
        assert DISPOSITION["ghost"] == "delete"
        assert DISPOSITION["real"].startswith("keep")
        assert "acknowledge_real" in DISPOSITION["real"]
        assert "free occupancy" in DISPOSITION["real"]
        assert DISPOSITION["inconclusive"].startswith("keep for now")
        assert "not a deletion licence" in DISPOSITION["inconclusive"]
        assert "single-member re-tests" in GROUP_REAL_NOTE


# ==========================================================================
# (b) detectability: the model's own scattering distribution, nothing else
# ==========================================================================
class TestDetectability:
    def test_small_molecule_fence_is_always_informative(self):
        xs = small_molecule()
        for r1 in (0.03, 0.08, 0.25):
            d = _detectability(xs, ["C3"], r1)
            assert d["r1_fence_informative"] is True
            assert d["expected_delta_r1_if_real"] > 0.05
        # the half-occupied water is lighter but still well above the fence
        w = _detectability(xs, ["O1W"], 0.06)
        c = _detectability(xs, ["C3"], 0.06)
        assert GHOST_R1_RISE < w["expected_delta_r1_if_real"] < \
            c["expected_delta_r1_if_real"]
        # scattering_fraction: occ*Z over the non-H total (8 C, N, 2 O, 0.5 O)
        total = 8 * 6 + 7 + 2 * 8 + 0.5 * 8
        assert c["scattering_fraction"] == pytest.approx(6 / total, abs=1e-4)
        assert w["scattering_fraction"] == pytest.approx(4 / total, abs=1e-4)

    def test_heavy_framework_at_high_r1_puts_a_carbon_near_the_fence(self):
        xs = heavy_framework()
        d = _detectability(xs, ["C7"], 0.25)
        assert 0.002 <= d["expected_delta_r1_if_real"] <= 0.005
        assert d["r1_fence_informative"] is True
        assert d["scattering_fraction"] == pytest.approx(
            6 / (6 * 40 + 150 * 6), abs=1e-4)
        # the same carbon at a quarter occupancy: below the floor
        for sc in xs.scatterers():
            if sc.label == "C7":
                sc.occupancy = 0.25
        q = _detectability(xs, ["C7"], 0.25)
        assert q["expected_delta_r1_if_real"] < d["expected_delta_r1_if_real"]
        assert q["expected_delta_r1_if_real"] < GHOST_R1_RISE
        assert q["r1_fence_informative"] is False
        # the same model converged: the fence sees a carbon easily
        assert _detectability(xs, ["C8"], 0.05)["expected_delta_r1_if_real"] \
            > 0.01
        # a Zr is seen at any R1; a group adds its members in quadrature
        # (delta_pair = sqrt(2) * delta_single, then expected = sqrt(R1^2
        # + delta^2) - R1 - close to twice the single-atom value here)
        zr = _detectability(xs, ["ZR1"], 0.25)
        assert zr["expected_delta_r1_if_real"] > d["expected_delta_r1_if_real"]
        pair = _detectability(xs, ["C8", "C9"], 0.25)
        delta_single = ((d["expected_delta_r1_if_real"] + 0.25) ** 2
                        - 0.25 ** 2) ** 0.5
        assert pair["expected_delta_r1_if_real"] == pytest.approx(
            (0.25 ** 2 + 2 * delta_single ** 2) ** 0.5 - 0.25, abs=2e-4)
        assert pair["expected_delta_r1_if_real"] > d["expected_delta_r1_if_real"]

    def test_multiplicity_and_hydrogen_are_handled(self):
        # a Zr on an inversion centre (multiplicity 1) weighs half a
        # general-position Zr (multiplicity 2) in the ASU-wide sum
        general = _detectability(heavy_framework(), ["ZR1"], 0.10)
        special = _detectability(heavy_framework(zr_general=False),
                                 ["ZR1"], 0.10)
        assert special["scattering_fraction"] < general["scattering_fraction"]
        # H is neither counted nor detectable: nothing to see, judged by peak
        xs = small_molecule()
        h = _detectability(xs, ["H1"], 0.05)
        assert h["scattering_fraction"] == 0.0
        assert h["expected_delta_r1_if_real"] == 0.0
        assert h["r1_fence_informative"] is False
        # no reference R1: no floor can be stated
        none = _detectability(xs, ["C1"], None)
        assert none["expected_delta_r1_if_real"] is None
        assert none["r1_fence_informative"] is None


# ==========================================================================
# (c) the ledger
# ==========================================================================
def _entry(labels, sites, verdict="real", **extra):
    e = {"labels": labels, "site_frac": sites, "verdict": verdict,
         "delta_r1": 0.0063, "peak_at_site": 1.55, "baseline": "n0031",
         "node": "n0034", "engine": "refine", "cycles": 4,
         "timestamp": "2026-09-02T21:26:31"}
    e.update(extra)
    return e


class TestLedger:
    def test_record_load_roundtrip_and_corrupt_file(self, tmp_path):
        assert ghost_ledger.load(tmp_path) == []
        e = ghost_ledger.record(tmp_path, _entry(["c9"], [[0.1, 0.2, 0.3]]))
        assert e["id"] == "g0001" and e["labels"] == ["c9"]
        assert e["labels_upper"] == ["C9"] and e["group"] is False
        p = ghost_ledger.ledger_path(tmp_path)
        assert p == tmp_path / ".crystalpilot" / "refine" / "ghost_ledger.json"
        assert json.loads(p.read_text(encoding="utf-8"))[0]["id"] == "g0001"
        e2 = ghost_ledger.record(tmp_path, _entry(["O1", "O2"],
                                                  [[0, 0, 0], [0.5, 0, 0]]))
        assert e2["id"] == "g0002" and e2["group"] is True
        assert [x["id"] for x in ghost_ledger.load(tmp_path)] == ["g0001",
                                                                 "g0002"]
        # a damaged file reads as empty and is replaced on the next record
        p.write_text("{not json", encoding="utf-8")
        assert ghost_ledger.load(tmp_path) == []
        e3 = ghost_ledger.record(tmp_path, _entry(["C1"], [[0.2, 0.2, 0.2]]))
        assert e3["id"] == "g0001"
        assert len(ghost_ledger.load(tmp_path)) == 1
        # a timestamp is filled in when the caller gives none
        e4 = ghost_ledger.record(tmp_path, {"labels": ["C2"], "verdict": "ghost"})
        assert e4["timestamp"] and e4["site_frac"] == []

    def test_real_matches_by_label_case_insensitive(self, tmp_path):
        xs = small_molecule()
        c3 = next(sc for sc in xs.scatterers() if sc.label == "C3")
        ghost_ledger.record(tmp_path, _entry(["C3"], [list(c3.site)]))
        ghost_ledger.record(tmp_path, _entry(["C4"], [[0.38, 0.24, 0.15]],
                                             verdict="ghost"))
        ghost_ledger.record(tmp_path, _entry(["C5"], [[0.45, 0.27, 0.15]],
                                             verdict="inconclusive"))
        hits = ghost_ledger.real_matches(tmp_path, xs, ["c3", "C4", "C5", "N1"])
        assert len(hits) == 1
        assert hits[0]["id"] == "g0001"
        assert hits[0]["match"] == [{"label": "c3", "by": "label", "d_A": 0.0,
                                     "ledger_label": "C3"}]
        assert ghost_ledger.real_matches(tmp_path, xs, ["C4", "C5"]) == []
        assert ghost_ledger.real_matches(tmp_path, xs, []) == []

    def test_real_matches_by_site_after_a_rename(self, tmp_path):
        xs = small_molecule()
        o2 = next(sc for sc in xs.scatterers() if sc.label == "O2")
        ghost_ledger.record(tmp_path, _entry(["O2"], [list(o2.site)]))
        # the agent renames it and nudges it by ~0.1 A: still the same site
        o2.label = "CL1"
        o2.site = (o2.site[0] + 0.01, o2.site[1], o2.site[2])
        hits = ghost_ledger.real_matches(tmp_path, xs, ["CL1"])
        assert len(hits) == 1
        m = hits[0]["match"][0]
        assert m["by"] == "site" and m["ledger_label"] == "O2"
        assert 0.0 < m["d_A"] <= ghost_ledger.SITE_MATCH_A
        # a symmetry image of the site matches too (symmetry-aware)
        op = xs.space_group().all_ops()[1]
        o2.site = tuple(op * o2.site)
        assert ghost_ledger.real_matches(tmp_path, xs, ["CL1"])
        # 0.6 A away is another site
        o2.site = (o2.site[0] + 0.075, o2.site[1], o2.site[2])
        assert ghost_ledger.real_matches(tmp_path, xs, ["CL1"]) == []

    def test_recycled_label_far_from_the_ledger_site_does_not_match(
            self, tmp_path):
        xs = small_molecule()
        ghost_ledger.record(tmp_path, _entry(["C3"], [[0.9, 0.9, 0.9]]))
        # the model's C3 sits >1 A from where the tested C3 was: a label
        # rename_atoms recycled, not the atom that was judged
        assert ghost_ledger.real_matches(tmp_path, xs, ["C3"]) == []
        # ...but an entry without a site matches on the label alone
        ghost_ledger.record(tmp_path, _entry(["C4"], []))
        assert ghost_ledger.real_matches(tmp_path, xs, ["C4"])

    def test_group_real_protects_every_member_until_disposed(self, tmp_path):
        xs = small_molecule()
        sites = {sc.label: list(sc.site) for sc in xs.scatterers()}
        ghost_ledger.record(tmp_path, _entry(
            ["C5", "C6", "C7"], [sites["C5"], sites["C6"], sites["C7"]],
            group=True))
        hits = ghost_ledger.real_matches(tmp_path, xs, ["C6"])
        assert len(hits) == 1 and hits[0]["group"] is True
        # a later single-member 'ghost' does not release the group verdict
        ghost_ledger.record(tmp_path, _entry(["C6"], [sites["C6"]],
                                             verdict="ghost"))
        assert ghost_ledger.real_matches(tmp_path, xs, ["C6"])
        # disposing one member leaves the others protected
        n = ghost_ledger.mark_disposed(tmp_path, ["c6"], "absorbed by the mask")
        assert n == 1
        assert ghost_ledger.real_matches(tmp_path, xs, ["C6"]) == []
        assert ghost_ledger.real_matches(tmp_path, xs, ["C5", "C7"])
        entry = ghost_ledger.load(tmp_path)[0]
        assert set(entry["disposed"]) == {"C6"}
        assert "disposition" not in entry
        ghost_ledger.mark_disposed(tmp_path, ["C5", "C7"], "named as guest",
                                   entry_ids=["g0001"])
        entry = ghost_ledger.load(tmp_path)[0]
        assert entry["disposition"] == "named as guest"
        assert ghost_ledger.real_matches(tmp_path, xs, ["C5", "C6", "C7"]) == []

    def test_same_test_repeated_as_ghost_supersedes_the_real(self, tmp_path):
        xs = small_molecule()
        site = [list(sc.site) for sc in xs.scatterers() if sc.label == "O1"]
        ghost_ledger.record(tmp_path, _entry(["O1"], site))
        assert ghost_ledger.real_matches(tmp_path, xs, ["O1"])
        # inconclusive releases nothing...
        ghost_ledger.record(tmp_path, _entry(["O1"], site,
                                             verdict="inconclusive"))
        assert ghost_ledger.real_matches(tmp_path, xs, ["O1"])
        # ...the same candidate judged ghost once the model was better does
        ghost_ledger.record(tmp_path, _entry(["O1"], site, verdict="ghost"))
        assert ghost_ledger.real_matches(tmp_path, xs, ["O1"]) == []

    def test_project_dir_from_ctx(self, tmp_path):
        from types import SimpleNamespace

        from crystalpilot.core.events import RunStore
        proj = tmp_path / "proj"
        store = RunStore(proj / ".crystalpilot" / "refine" / "runs",
                         run_id="s1")
        ctx = SimpleNamespace(store=store)
        assert ghost_ledger.project_dir_from_ctx(ctx) == proj.resolve()
        assert ghost_ledger.project_dir_from_ctx(
            SimpleNamespace(store=SimpleNamespace())) is None
        assert ghost_ledger.project_dir_from_ctx(SimpleNamespace(
            store=RunStore(tmp_path / "runs"))) is None


# ==========================================================================
# (d) the edit_atoms guard on a bare session
# ==========================================================================
def _session(xs):
    from crystalpilot.core.dataset import ReflectionDataset
    from crystalpilot.pipeline.session import SolveSession
    ses = SolveSession(dataset=ReflectionDataset(intensities=None,
                                                 wavelength=0.71073))
    ses.model = xs
    ses.symmetry = xs.crystal_symmetry()
    return ses


def _project_ctx(tmp_path, xs):
    """A ToolContext whose RunStore lives where a project's does, so the
    session-scoped tool can find the ledger."""
    from crystalpilot.core.events import RunStore
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    store = RunStore(proj / ".crystalpilot" / "refine" / "runs", run_id="t")
    return ToolContext(store=store, session=_session(xs)), proj


class TestEditAtomsGuard:
    @staticmethod
    def _seed(proj, xs, labels, **extra):
        sites = {sc.label: list(sc.site) for sc in xs.scatterers()}
        return ghost_ledger.record(proj, _entry(
            labels, [sites[lb] for lb in labels], **extra))

    def test_delete_of_a_real_atom_is_refused_with_evidence(self, tmp_path):
        xs = small_molecule()
        ctx, proj = _project_ctx(tmp_path, xs)
        self._seed(proj, xs, ["O2"])
        n0 = xs.scatterers().size()
        r = EditAtoms().run(ctx, operations=[
            {"action": "reassign", "atoms": ["N1"], "element": "C"},
            {"action": "delete", "atoms": ["o2", "C1"]}])
        assert not r.ok
        msg = r.error
        assert "REAL" in msg and "not a deletion licence" in msg
        # the model's own spelling of the label, the baseline, the time
        assert "O2" in msg and "n0031" in msg and "2026-09-02T21:26:31" in msg
        assert "+0.0063" in msg and "1.55 e/A^3" in msg
        assert "(a)" in msg and "reassign" in msg and "rename" in msg
        assert "(b)" in msg and "free_occupancy" in msg
        assert "(c)" in msg and 'acknowledge_real={"labels": ["O2"]' in msg
        assert "15 characters" in msg
        # nothing at all was applied - not even the reassign of N1
        assert ctx.session.model.scatterers().size() == n0
        n1 = next(sc for sc in xs.scatterers() if sc.label == "N1")
        assert n1.scattering_type.strip() == "N"
        # C1 was not on the ledger: deleting it alone is fine
        r = EditAtoms().run(ctx, operations=[
            {"action": "delete", "atoms": ["C1"]}])
        assert r.ok and "real_atoms_deleted_with_reason" not in r.summary
        assert ctx.session.model.scatterers().size() == n0 - 1

    def test_acknowledgement_must_be_complete(self, tmp_path):
        xs = small_molecule()
        ctx, proj = _project_ctx(tmp_path, xs)
        self._seed(proj, xs, ["O2"])
        self._seed(proj, xs, ["O1"])
        ops = [{"action": "delete", "atoms": ["O1", "O2"]}]
        r = EditAtoms().run(ctx, operations=ops,
                            acknowledge_real={"labels": ["O1", "O2"],
                                              "reason": "mask"})
        assert not r.ok and "at least 15 characters" in r.error
        r = EditAtoms().run(ctx, operations=ops, acknowledge_real={
            "labels": ["O1"], "reason": "absorbed into the solvent mask"})
        assert not r.ok and "does not cover ['O2']" in r.error
        r = EditAtoms().run(ctx, operations=ops, acknowledge_real="yes")
        assert not r.ok and "must be an object" in r.error
        r = EditAtoms().run(ctx, operations=ops, acknowledge_real={
            "reason": "absorbed into the solvent mask"})
        assert not r.ok and "labels must be a non-empty list" in r.error
        assert ctx.session.model.scatterers().size() == 13

    def test_acknowledged_delete_passes_and_is_written_back(self, tmp_path):
        xs = small_molecule()
        ctx, proj = _project_ctx(tmp_path, xs)
        self._seed(proj, xs, ["O2"])
        reason = "absorbed into the solvent mask: diffuse channel density"
        r = EditAtoms().run(ctx, operations=[
            {"action": "delete", "atoms": ["O2", "C8"]}],
            acknowledge_real={"labels": ["o2"], "reason": reason})
        assert r.ok, r.error
        assert r.summary["real_atoms_deleted_with_reason"] == [
            {"label": "O2", "reason": reason}]
        assert "ledger" in r.summary["ledger_note"]
        labels = {sc.label for sc in ctx.session.model.scatterers()}
        assert "O2" not in labels and "C8" not in labels
        entry = ghost_ledger.load(proj)[0]
        assert entry["disposed"]["O2"]["text"].endswith(reason)
        assert entry["disposition"].endswith(reason)
        # the disposed entry blocks nothing any more (e.g. a re-added atom)
        assert ghost_ledger.real_matches(proj, ctx.session.model, ["O2"]) == []

    def test_diagnostic_delete_bypasses_the_guard(self, tmp_path):
        xs = small_molecule()
        ctx, proj = _project_ctx(tmp_path, xs)
        self._seed(proj, xs, ["O2"])
        r = EditAtoms().run(ctx, operations=[
            {"action": "delete", "atoms": ["O2"]}], _diagnostic=True)
        assert r.ok, r.error
        assert "real_atoms_deleted_with_reason" not in r.summary
        # the ledger is untouched: the verdict still stands
        assert ghost_ledger.load(proj)[0]["disposed"] == {}
        assert ghost_ledger.real_matches(proj, small_molecule(), ["O2"])

    def test_group_member_and_renamed_atom_are_protected(self, tmp_path):
        xs = small_molecule()
        ctx, proj = _project_ctx(tmp_path, xs)
        self._seed(proj, xs, ["C5", "C6", "C7"], group=True, delta_r1=0.0058)
        self._seed(proj, xs, ["O1"], r1_fence_informative=False)
        r = EditAtoms().run(ctx, operations=[
            {"action": "delete", "atoms": ["C6"]}])
        assert not r.ok
        assert "group C5+C6+C7" in r.error and GROUP_REAL_NOTE in r.error
        # rename O1 -> CL1 (the density got its identity) then try to delete
        o1 = next(sc for sc in xs.scatterers() if sc.label == "O1")
        o1.label = "CL1"
        r = EditAtoms().run(ctx, operations=[
            {"action": "delete", "atoms": ["CL1"]}])
        assert not r.ok
        assert "matched by site" in r.error and "ledger atom O1" in r.error
        assert "detectability floor" in r.error

    def test_bare_session_without_a_project_has_no_ledger(self, tmp_path):
        class _Store:
            def emit(self, *a, **k):
                return None

        xs = small_molecule()
        ghost_ledger.record(tmp_path, _entry(["O2"], [[0.7, 0.35, 0.55]]))
        ctx = ToolContext(store=_Store(), session=_session(xs))
        r = EditAtoms().run(ctx, operations=[
            {"action": "delete", "atoms": ["O2"]}])
        assert r.ok and ctx.session.model.scatterers().size() == 12


# ==========================================================================
# (e) end to end: ghost_test writes the ledger, edit_atoms reads it
# ==========================================================================
CELL = (7.0, 8.0, 9.0, 85.0, 95.0, 100.0)
TRUE_ATOMS = [("ZR1", "Zr", (0.25, 0.10, 0.15)),
              ("O1", "O", (0.40, 0.20, 0.30)),
              ("O2", "O", (0.10, 0.25, 0.05)),
              ("C1", "C", (0.55, 0.30, 0.40)),
              ("C2", "C", (0.65, 0.42, 0.55))]
GHOST = ("C9G", "C", (0.50, 0.75, 0.10))


def _p1_structure(atoms):
    cs = crystal.symmetry(unit_cell=CELL, space_group_symbol="P -1")
    xs = xray.structure(crystal_symmetry=cs)
    for lbl, el, site in atoms:
        xs.add_scatterer(xray.scatterer(label=lbl, site=site, u=0.02,
                                        scattering_type=el))
    return xs


@pytest.fixture()
def project(tmp_path):
    """Synthetic HKLF4 data from the five true atoms; the start model
    carries the ghost C9G as well."""
    from cctbx.array_family import flex

    from crystalpilot.io.cif_sf import write_hklf4
    from crystalpilot.io.shelx_writer import ShelxModel, write_res
    from crystalpilot.refine.project import RefineProject
    d = tmp_path / "proj"
    d.mkdir()
    truth = _p1_structure(TRUE_ATOMS)
    i_obs = truth.structure_factors(
        d_min=0.75, algorithm="direct").f_calc().as_intensity_array()
    flex.set_random_seed(7)
    noise = 1.0 + 0.01 * (flex.random_double(i_obs.size()) - 0.5)
    data = i_obs.data() * noise
    i_obs = i_obs.customized_copy(data=data, sigmas=0.02 * data + 0.5)
    write_hklf4(i_obs, d / "crystal.hkl")
    write_res(ShelxModel(xray_structure=_p1_structure(TRUE_ATOMS + [GHOST]),
                         wavelength=0.71073, z=2, weights=(0.1, 0.0)),
              d / "start.res")
    (d / "context.json").write_text(json.dumps({
        "data": {"hkl": "crystal.hkl", "start_model": "start.res"}}),
        encoding="utf-8")
    p = RefineProject(d)
    p.open()
    return p


class TestClosureEndToEnd:
    def test_ghost_test_rows_carry_floor_and_disposition(self, project):
        p = project
        r = p.invoke_tool("ghost_test", {"atoms": ["C9G", "C1", "O1+O2"],
                                         "cycles": 4})
        assert r.ok, r.error
        s = r.summary
        assert s["verdicts"] == {"C9G": "ghost", "C1": "real", "O1+O2": "real"}
        assert "detectability floor" in s["criterion"]
        assert "expected_delta_r1_if_real" in s["sensitivity_note"]
        rows = {row["atoms"]: row for row in s["rows"]}
        for row in rows.values():
            assert 0 < row["scattering_fraction"] < 1
            assert row["expected_delta_r1_if_real"] is not None
            assert row["r1_fence_informative"] in (True, False)
            assert row["ledger_id"].startswith("g")
        # a converged five-atom model: the fence sees every candidate
        assert all(row["r1_fence_informative"] for row in rows.values())
        assert rows["C9G"]["disposition"] == "delete"
        assert rows["C1"]["disposition"].startswith("keep")
        assert "group_note" not in rows["C1"]
        assert rows["O1+O2"]["group_note"] == GROUP_REAL_NOTE
        assert s["dispositions"]["C9G"] == "delete"
        assert "protected" in s["ledger_note"] and "2 'real'" in s["ledger_note"]
        entries = ghost_ledger.load(p.dir)
        assert [e["labels"] for e in entries] == [["C9G"], ["C1"], ["O1", "O2"]]
        assert [e["verdict"] for e in entries] == ["ghost", "real", "real"]
        assert entries[1]["baseline"] == s["baseline"]["node"]
        assert entries[1]["engine"] == "refine" and entries[1]["cycles"] == 4
        assert entries[2]["group"] is True and entries[1]["group"] is False
        assert entries[1]["delta_r1"] == rows["C1"]["delta_r1"]
        assert entries[1]["peak_at_site"] == rows["C1"]["peak_at_site"]
        # the diagnostic deletes inside ghost_test never wrote a disposal
        assert all(e["disposed"] == {} for e in entries)
        # the ghost may go; the real atom and the group member may not
        assert p.invoke_tool("edit_atoms", {"operations": [
            {"action": "delete", "atoms": ["C9G"]}]}).ok
        r = p.invoke_tool("edit_atoms", {"operations": [
            {"action": "delete", "atoms": ["C1"]}]})
        assert not r.ok and "judged REAL" in r.error
        assert "single-atom test" in r.error and "(c)" in r.error
        r = p.invoke_tool("edit_atoms", {"operations": [
            {"action": "delete", "atoms": ["O2"]}]})
        assert not r.ok and "group O1+O2" in r.error
        assert GROUP_REAL_NOTE in r.error
        labels = {sc.label for sc in p.session.model.scatterers()}
        assert {"C1", "O1", "O2"} <= labels and "C9G" not in labels
        # with an acknowledged reason the delete goes through and is on file
        reason = "absorbed into the solvent mask after the test model"
        r = p.invoke_tool("edit_atoms", {
            "operations": [{"action": "delete", "atoms": ["C1"]}],
            "acknowledge_real": {"labels": ["C1"], "reason": reason}})
        assert r.ok, r.error
        assert r.summary["real_atoms_deleted_with_reason"] == [
            {"label": "C1", "reason": reason}]
        assert ghost_ledger.load(p.dir)[1]["disposed"]["C1"]["text"].endswith(
            reason)
        assert "C1" not in {sc.label for sc in p.session.model.scatterers()}

    def test_ghost_test_still_deletes_its_own_candidates(self, project):
        """A second ghost_test on an atom already held as real must still
        run (its internal delete is diagnostic), and record again."""
        p = project
        r = p.invoke_tool("ghost_test", {"atoms": ["C1"], "cycles": 2})
        assert r.ok and r.summary["verdicts"] == {"C1": "real"}
        r = p.invoke_tool("ghost_test", {"atoms": ["C1"], "cycles": 2})
        assert r.ok, r.error
        assert r.summary["verdicts"] == {"C1": "real"}
        assert "error" not in r.summary["rows"][0]
        assert len(ghost_ledger.load(p.dir)) == 2
        assert p.session.model.scatterers().size() == 6


# ==========================================================================
# (f) the ghost_atom_suspect advice defers to the three verdicts
# ==========================================================================
def test_asu_sanity_advice_quotes_the_verdicts_not_a_threshold():
    from crystalpilot.chem.asu_sanity import asu_coherence
    atoms = [("C1", "C", (0.10, 0.10, 0.10), 1.0),
             ("C2", "C", (0.25, 0.10, 0.10), 1.0),
             ("O5", "O", (0.40, 0.10, 0.10), 1.0),
             ("O6", "O", (0.10, 0.30, 0.10), 1.0),
             ("O7", "O", (0.10, 0.10, 0.35), 1.0),
             ("O9", "O", (0.60, 0.60, 0.60), 0.5)]
    xs = _structure((10, 11, 12, 90, 100, 90), "P 21/c", atoms)
    for sc in xs.scatterers():
        if sc.label == "O9":
            sc.u_iso = 0.20
    rep = asu_coherence(xs)
    g = next(g for g in rep["ghost_suspects"] if g["label"] == "O9")
    adv = g["advice"]
    assert "ghost_test" in adv and "only deletion licence" in adv
    assert "'real'" in adv and "'inconclusive'" in adv
    assert "never delete a 'real' one silently" in adv
    assert "0.002" not in adv and "R1 rise" not in adv
