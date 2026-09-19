"""Round-trip fidelity for special/split-occupancy H (round-7 CD-MOF
failures): '!' inline comments, PART/sof-coded H through write_res, checkout
without the lossy add_hydrogens replay, edit_atoms metadata pruning."""
import textwrap
from pathlib import Path

import pytest

MINI_RES = textwrap.dedent("""\
    TITL split-H test ! title bangs stay
    CELL 0.71073 10.0 10.0 10.0 90.0 90.0 90.0
    ZERR 1 0.001 0.001 0.001 0.0 0.0 0.0
    LATT -1
    SFAC C H O
    UNIT 2 4 2
    FVAR 1.0 0.6
    DFIX 1.40 0.02 C1 O1 ! C1B O1B alternative
    WGHT 0.1
    C1   1  0.100000  0.100000  0.100000  11.00000  0.02000
    AFIX 137
    H1A  2  0.150000  0.100000  0.160000  21.00000 -1.50000
    H1B  2  0.050000  0.140000  0.120000  21.00000 -1.50000
    AFIX 0
    O1   3  0.300000  0.300000  0.300000  11.00000  0.02500
    PART 1
    H1O  2  0.340000  0.330000  0.330000  21.00000  0.03000
    PART 2
    H2O  2  0.260000  0.330000  0.330000 -21.00000  0.03000
    PART 0
    C2   1  0.500000  0.500000  0.500000  11.00000  0.02000
    HKLF 4
    END
    """)


@pytest.fixture()
def parsed(tmp_path):
    from crystalpilot.io.shelx_model import load_res_model
    p = tmp_path / "mini.res"
    p.write_text(MINI_RES, encoding="utf-8")
    return load_res_model(p)


class TestInlineComments:
    def test_restraint_comment_stripped(self, parsed):
        assert parsed.restraint_lines == ["DFIX 1.40 0.02 C1 O1"]

    def test_title_keeps_bang(self, parsed):
        assert "!" in (parsed.title or "")

    def test_comment_then_continuation(self, tmp_path):
        from crystalpilot.io.shelx_model import _logical_lines
        lines = _logical_lines("SADI 0.02 C1 O1 = ! note\n C2 O2\nEND\n")
        assert lines[0] == "SADI 0.02 C1 O1 C2 O2"


class TestSplitHRoundTrip:
    def test_all_h_and_parts_survive(self, parsed, tmp_path):
        from crystalpilot.io.shelx_model import load_res_model
        from crystalpilot.io.shelx_writer import ShelxModel, write_res_text
        txt, rename = write_res_text(ShelxModel(
            xray_structure=parsed.structure, wavelength=0.71073, z=1,
            weights=parsed.weights, h_riding=parsed.h_riding,
            sof_codes=parsed.sof_codes, parts=parsed.parts,
            fvars=parsed.fvar_extra))
        assert rename == {}
        p2path = tmp_path / "rt.res"
        p2path.write_text(txt, encoding="utf-8")
        p2 = load_res_model(p2path)
        assert p2.structure.scatterers().size() == 7
        n_h = sum(1 for sc in p2.structure.scatterers()
                  if sc.scattering_type.strip().upper() == "H")
        assert n_h == 4
        # split-occupancy H keep their PART and FVAR-coded sof
        assert p2.parts.get("H1O") == 1
        assert p2.parts.get("H2O") == 2
        assert p2.sof_codes.get("H2O") == pytest.approx(-21.0)


class TestCheckoutKeepsSpecialH:
    def test_checkout_no_h_loss(self, tmp_path):
        import json

        from crystalpilot.refine.project import RefineProject
        d = tmp_path / "proj"
        d.mkdir()
        (d / "crystal.hkl").write_text(
            "   1   0   0  100.00    5.00\n"
            "   0   1   0   80.00    4.00\n"
            "   0   0   1   60.00    3.00\n"
            "   0   0   0    0.00    0.00\n", encoding="utf-8")
        (d / "start.res").write_text(MINI_RES, encoding="utf-8")
        (d / "context.json").write_text(json.dumps({
            "data": {"hkl": "crystal.hkl", "start_model": "start.res"}}),
            encoding="utf-8")
        p = RefineProject(d)
        p.open()
        n0 = p.session.model.scatterers().size()
        assert n0 == 7, "import must keep the split-occupancy H"
        node = p.nodes.state()["active_node"]
        out = p.checkout(node)
        assert out["n_atoms"] == 7, (
            "checkout must not strip split/special H (was the CD-MOF "
            f"400->345 bug); notes={out['notes']}")
        assert any("verbatim" in n for n in out["notes"])


class TestEditAtomsPrunesHMeta:
    def test_delete_prunes_riding_meta(self, parsed):
        from crystalpilot.core.dataset import ReflectionDataset
        from crystalpilot.pipeline.session import SolveSession
        from crystalpilot.tools.base import ToolContext
        from crystalpilot.tools.model_tools import EditAtoms

        class _Store:
            def record(self, *a, **k):
                return None

            def log(self, *a, **k):
                return None

        ses = SolveSession(dataset=ReflectionDataset(
            intensities=None, wavelength=0.71073))
        ses.model = parsed.structure
        ses.symmetry = parsed.structure.crystal_symmetry()
        ses.flags["h_riding_meta"] = {"per_carrier": parsed.h_riding}
        ses.flags["h_constraints"] = ["sentinel"]
        ctx = ToolContext(store=_Store(), session=ses)
        r = EditAtoms().run(ctx, operations=[
            {"action": "delete", "atoms": ["H1B"]}])
        assert r.ok
        groups = ses.flags["h_riding_meta"]["per_carrier"]
        hs = [h for g in groups for h in g["h"]]
        assert "H1B" not in hs and "H1A" in hs
        assert "h_constraints" not in ses.flags
        assert r.summary["h_metadata_pruned"] >= 1


class TestCommitRenameSyncsLiveModel:
    def test_long_label_rename_reaches_model_and_flags(self, tmp_path):
        # round-10 #13: write_res renames >4-char labels but only the
        # FLAGS were remapped - the live model kept old labels and every
        # label-keyed lookup (PART membership) missed from then on
        import json

        from crystalpilot.refine.project import RefineProject
        d = tmp_path / "proj"
        d.mkdir()
        (d / "crystal.hkl").write_text(
            "   1   0   0  100.00    5.00\n"
            "   0   1   0   80.00    4.00\n"
            "   0   0   0    0.00    0.00\n", encoding="utf-8")
        (d / "start.res").write_text(MINI_RES, encoding="utf-8")
        (d / "context.json").write_text(json.dumps({
            "data": {"hkl": "crystal.hkl", "start_model": "start.res"}}),
            encoding="utf-8")
        p = RefineProject(d)
        p.open()
        ses = p.session
        # fabricate the round-4 situation: a 5-char H label in a PART
        for sc in ses.model.scatterers():
            if sc.label == "H2O":
                sc.label = "H25BA"
        ses.flags["disorder_groups"] = [{
            "fvar_index": 2, "value": 0.6,
            "members": [{"label": "H25BA", "part": 2, "sign": -1,
                         "mult": 1.0}]}]
        p.nodes.commit(ses, tool="test", params={})
        model_labels = {sc.label for sc in ses.model.scatterers()}
        assert "H25BA" not in model_labels          # live model renamed
        mem = ses.flags["disorder_groups"][0]["members"][0]
        assert mem["label"] in model_labels          # flags stay in sync
        assert len(mem["label"]) <= 4


class TestEditAtomsLabelMatching:
    """Process-audit T7: silent no-op on label mismatch burned two
    campaigns (r10 fake-Mg refinement, r22 wasted Cu branch)."""

    @staticmethod
    def _ctx(parsed):
        from crystalpilot.core.dataset import ReflectionDataset
        from crystalpilot.pipeline.session import SolveSession
        from crystalpilot.tools.base import ToolContext

        class _Store:
            def record(self, *a, **k):
                return None

            def log(self, *a, **k):
                return None

        ses = SolveSession(dataset=ReflectionDataset(
            intensities=None, wavelength=0.71073))
        ses.model = parsed.structure
        ses.symmetry = parsed.structure.crystal_symmetry()
        return ToolContext(store=_Store(), session=ses)

    def test_case_fold_matches_unambiguous(self, parsed):
        from crystalpilot.tools.model_tools import EditAtoms
        ctx = self._ctx(parsed)
        n0 = ctx.session.model.scatterers().size()
        r = EditAtoms().run(ctx, operations=[
            {"action": "delete", "atoms": ["h1b"]}])
        assert r.ok, r.error
        assert ctx.session.model.scatterers().size() == n0 - 1
        assert r.summary["case_folded"] == ["h1b->H1B"]
        assert not r.summary["unknown_labels"]

    def test_all_unknown_fails_loud(self, parsed):
        from crystalpilot.tools.model_tools import EditAtoms
        ctx = self._ctx(parsed)
        n0 = ctx.session.model.scatterers().size()
        r = EditAtoms().run(ctx, operations=[
            {"action": "reassign", "atoms": ["NOPE9"], "element": "N"}])
        assert not r.ok
        assert "NOPE9" in r.error and "nothing was changed" in r.error
        assert ctx.session.model.scatterers().size() == n0

    def test_partial_miss_warns_but_applies(self, parsed):
        from crystalpilot.tools.model_tools import EditAtoms
        ctx = self._ctx(parsed)
        n0 = ctx.session.model.scatterers().size()
        r = EditAtoms().run(ctx, operations=[
            {"action": "delete", "atoms": ["H1A", "GHOST1"]}])
        assert r.ok
        assert ctx.session.model.scatterers().size() == n0 - 1
        assert r.summary["unknown_labels"] == ["GHOST1"]
        assert "SKIPPED" in r.summary["warning"]


class TestSetRestraintsGhostLabels:
    def test_add_with_ghost_atom_refused(self, parsed):
        from types import SimpleNamespace
        from crystalpilot.refine.tools_extra import SetRestraints
        ses = SimpleNamespace(model=parsed.structure, flags={})
        ctx = SimpleNamespace(session=ses)
        r = SetRestraints(None).run(
            ctx, action="add",
            restraints=[{"kind": "DFIX", "target": 0.98,
                         "atoms": [["O1", "H53"]]}])
        assert not r.ok
        assert "H53" in r.error and "not in the model" in r.error
        assert not ses.flags.get("restraints")

    def test_add_case_insensitive_labels_pass(self, parsed):
        from types import SimpleNamespace
        from crystalpilot.refine.tools_extra import SetRestraints
        ses = SimpleNamespace(model=parsed.structure, flags={})
        ctx = SimpleNamespace(session=ses)
        r = SetRestraints(None).run(
            ctx, action="add",
            restraints=[{"kind": "DFIX", "target": 1.40,
                         "atoms": [["c1", "o1"]]}])
        assert r.ok, r.error
        assert len(ses.flags["restraints"]) == 1


class TestAddAtomsLabelCollision:
    """Process-audit T13/r22: count-based labels collided with a SURVIVING
    atom after deletions (two C29X in one model -> delivered CIF invalid,
    res round-trip silently collapsed the pair)."""

    def test_new_label_skips_taken_names(self):
        from types import SimpleNamespace

        from cctbx import crystal, xray
        from crystalpilot.core.dataset import ReflectionDataset
        from crystalpilot.pipeline.session import SolveSession
        from crystalpilot.tools.base import ToolContext
        from crystalpilot.tools.model_tools import AddAtomsFromDifferenceMap

        cs = crystal.symmetry(unit_cell=(20, 20, 20, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        # 3 C atoms but one is already named C4X: the count heuristic
        # (existing=3 -> next label C4X) would collide
        for lbl, site in (("C1", (0.1, 0.1, 0.1)),
                          ("C2", (0.2, 0.1, 0.1)),
                          ("C4X", (0.3, 0.1, 0.1))):
            xs.add_scatterer(xray.scatterer(
                label=lbl, site=site, scattering_type="C", u=0.03))
        ses = SolveSession(dataset=ReflectionDataset(
            intensities=None, wavelength=0.71073))
        ses.model = xs
        ses.symmetry = cs
        ses.flags["diff_map_peaks"] = [
            {"height": 3.0, "site": (0.5, 0.5, 0.5)},
            {"height": 2.5, "site": (0.6, 0.5, 0.5)}]

        class _Store:
            def record(self, *a, **k):
                return None

            def log(self, *a, **k):
                return None

        ctx = ToolContext(store=_Store(), session=ses)
        r = AddAtomsFromDifferenceMap().run(ctx, peak_indices=[0, 1],
                                            element="C")
        assert r.ok, r.error
        new = [a["label"] for a in r.summary["added"]]
        assert len(new) == 2
        labels = [sc.label for sc in ses.model.scatterers()]
        assert len(labels) == len(set(labels)), f"duplicate labels: {labels}"
        assert "C4X" not in new           # collision skipped
        assert new == ["C5X", "C6X"]
