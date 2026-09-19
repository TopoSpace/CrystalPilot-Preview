"""Structure renderer + view_structure tool + MCP image encoding."""
from pathlib import Path
from types import SimpleNamespace

from cctbx import crystal, xray

from crystalpilot.report.structviews import render_views
from crystalpilot.refine.tools_analysis import ViewStructure
from crystalpilot.tools.base import ToolContext


def _xs():
    cs = crystal.symmetry(unit_cell=(8.0, 9.0, 10.0, 90, 95, 90),
                          space_group_symbol="P -1")
    xs = xray.structure(crystal_symmetry=cs)
    for lbl, el, site in (("LA1", "La", (0.2, 0.3, 0.4)),
                          ("P1", "P", (0.35, 0.42, 0.31)),
                          ("N1", "N", (0.1, 0.2, 0.5)),
                          ("C1", "C", (0.15, 0.28, 0.45)),
                          ("H1", "H", (0.18, 0.33, 0.47))):
        xs.add_scatterer(xray.scatterer(label=lbl, site=site, u=0.03,
                                        scattering_type=el))
    return xs


def test_render_all_states_and_views(tmp_path):
    for state, min_n in (("asu", 5), ("cell", 10), ("supercell", 40)):
        out = render_views(_xs(), tmp_path, state=state,
                           views=("a", "oblique"), stem=state)
        assert len(out) == 2
        for im in out:
            p = Path(im["path"])
            assert p.exists() and p.stat().st_size > 10_000
            assert im["state"] == state


def test_view_structure_tool(tmp_path):
    ses = SimpleNamespace(model=_xs(), flags={}, dataset=None)
    proj = SimpleNamespace(dir=tmp_path, session=ses)
    t = ViewStructure(proj)
    r = t.run(SimpleNamespace(session=ses), state="cell",
              views=["a", "c"], highlight=["LA1"])
    assert r.ok, r.error
    s = r.summary
    assert len(s["_image_files"]) == 2
    assert all(Path(p).exists() for p in s["_image_files"])
    assert "LOOK" in s["note"]
    r2 = t.run(SimpleNamespace(session=ses), views=["sideways"])
    assert not r2.ok and "sideways" in (r2.error or "")


def test_mcp_image_encoder(tmp_path):
    from crystalpilot.mcp.server import _encode_image
    out = render_views(_xs(), tmp_path, state="asu", views=("a",))
    b64 = _encode_image(out[0]["path"], max_px=256)
    import base64
    raw = base64.b64decode(b64)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(raw) < 400_000


def test_situation_report_volume_pathology_and_images(tmp_path):
    """The r16 detector: a P1 model holding far fewer non-H atoms than the
    cell volume expects must be called out; images attach by default."""
    from crystalpilot.refine.tools_analysis import SituationReport
    from cctbx import crystal, xray

    cs = crystal.symmetry(unit_cell=(10.0, 12.0, 20.0, 72, 76, 84),
                          space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    for i, site in enumerate(((0.1, 0.2, 0.3), (0.4, 0.5, 0.6),
                              (0.7, 0.1, 0.8), (0.2, 0.8, 0.1))):
        xs.add_scatterer(xray.scatterer(label=f"C{i+1}", site=site, u=0.03,
                                        scattering_type="C"))

    class _Nodes:
        def list_nodes(self, limit=200):
            return [{"id": f"n{i:04d}", "tool": "refine",
                     "r1": 0.20 - 0.001 * i, "wr2": 0.5, "n_atoms": 4}
                    for i in range(6)]

    ses = SimpleNamespace(model=xs, flags={}, dataset=None, fo_sq=None)
    proj = SimpleNamespace(dir=tmp_path, session=ses, nodes=_Nodes(),
                           context={})
    r = SituationReport(proj).run(SimpleNamespace(session=ses))
    assert r.ok, r.error
    s = r.summary
    ve = s["model_side"]["volume_expectation"]
    assert ve["modeled_non_h_per_asu"] == 4
    assert ve["expected_non_h_per_asu"] > 50       # huge cell, 4 atoms
    assert any("体积核算异常" in n for n in s["narrative"])
    assert len(s["trajectory_recent"]) == 6
    assert len(s.get("_image_files") or []) == 2
    assert all(Path(p).exists() for p in s["_image_files"])


def test_situation_report_hklf5_flag_conflict(tmp_path):
    from crystalpilot.refine.tools_analysis import SituationReport

    class _Nodes:
        def list_nodes(self, limit=200):
            return []

    ses = SimpleNamespace(model=None, flags={"hklf": 5}, dataset=None,
                          fo_sq=None)
    proj = SimpleNamespace(dir=tmp_path, session=ses, nodes=_Nodes(),
                           context={})
    r = SituationReport(proj).run(SimpleNamespace(session=ses),
                                  render=False)
    assert r.ok, r.error
    assert any("HKLF5" in c for c in r.summary.get("conflicts", []))


# --------------------------------------------------------------------- #
# situation_report: mask-vs-model cross-checks (PLAN T1.1 item 8)        #
# --------------------------------------------------------------------- #

def _masked_cell(tmp_path, voids, sites=(("C1", (0.5, 0.5, 0.5)),
                                         ("C2", (0.1, 0.1, 0.1)))):
    """A P1 cell with a solvent mask already in the session flags."""
    from crystalpilot.refine.tools_analysis import SituationReport

    cs = crystal.symmetry(unit_cell=(20.0, 20.0, 20.0, 90, 90, 90),
                          space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    for lbl, site in sites:
        xs.add_scatterer(xray.scatterer(label=lbl, site=site, u=0.03,
                                        scattering_type="C"))

    class _Nodes:
        def list_nodes(self, limit=200):
            return []

    ses = SimpleNamespace(
        model=xs, dataset=None, fo_sq=None,
        flags={"f_mask": object(),
               "solvent_mask_info": {"n_voids": len(voids),
                                     "voids": voids}})
    proj = SimpleNamespace(dir=tmp_path, session=ses, nodes=_Nodes(),
                           context={})
    r = SituationReport(proj).run(SimpleNamespace(session=ses),
                                  render=False)
    assert r.ok, r.error
    return r.summary.get("conflicts", [])


#: 500 A^3 -> equal-volume radius 4.9 A, so the check reaches 2.5 A
_VOID_AT_CENTRE = {"void": 1, "centre_frac": [0.5, 0.5, 0.5],
                   "volume_A3": 500.0, "masked": True}


def test_situation_report_flags_a_modelled_atom_inside_a_masked_void(
        tmp_path):
    conflicts = _masked_cell(tmp_path, [_VOID_AT_CENTRE])
    hit = [c for c in conflicts if "模型原子落在当前掩膜的空腔内" in c]
    assert len(hit) == 1
    assert "C1" in hit[0] and "C2" not in hit[0]   # C2 is 13.9 A away
    assert "近似" in hit[0]                         # states its own limit


def test_situation_report_ignores_a_void_the_mask_excluded(tmp_path):
    """Counter-example: a void found but NOT masked is not double
    counting - refinement never applied it."""
    void = dict(_VOID_AT_CENTRE, masked=False)
    assert not [c for c in _masked_cell(tmp_path, [void])
                if "掩膜的空腔" in c]


def test_situation_report_ignores_an_atom_outside_the_void(tmp_path):
    """Counter-example: the same void, but every atom well outside it."""
    conflicts = _masked_cell(tmp_path, [_VOID_AT_CENTRE],
                             sites=(("C1", (0.05, 0.05, 0.05)),))
    assert not [c for c in conflicts if "掩膜的空腔" in c]


def test_situation_report_flags_a_ghost_real_atom_in_a_masked_void(
        tmp_path):
    """The pa2/pa3 failure this exists for: ghost_test says the density
    at a site is a real scatterer, and the mask then swallows the same
    density as unmodelled solvent."""
    from crystalpilot.refine import ghost_ledger

    ghost_ledger.record(tmp_path, {
        "labels": ["Q7"], "site_frac": [[0.5, 0.5, 0.52]],
        "verdict": "real", "delta_r1": -0.004})
    ghost_ledger.record(tmp_path, {
        "labels": ["Q9"], "site_frac": [[0.02, 0.02, 0.02]],
        "verdict": "real", "delta_r1": -0.003})
    ghost_ledger.record(tmp_path, {
        "labels": ["Q8"], "site_frac": [[0.5, 0.5, 0.5]],
        "verdict": "ghost", "delta_r1": 0.0})
    conflicts = _masked_cell(tmp_path, [_VOID_AT_CENTRE])
    hit = [c for c in conflicts if "ghost 台账判为 real" in c]
    assert len(hit) == 1
    assert "Q7" in hit[0]
    assert "Q8" not in hit[0]        # a ghost verdict is not a conflict
    assert "Q9" not in hit[0]        # outside the void


def test_situation_report_without_a_mask_adds_no_mask_conflict(tmp_path):
    from crystalpilot.refine.tools_analysis import SituationReport

    class _Nodes:
        def list_nodes(self, limit=200):
            return []

    ses = SimpleNamespace(model=None, dataset=None, fo_sq=None, flags={})
    proj = SimpleNamespace(dir=tmp_path, session=ses, nodes=_Nodes(),
                           context={})
    r = SituationReport(proj).run(SimpleNamespace(session=ses),
                                  render=False)
    assert r.ok
    assert not [c for c in r.summary.get("conflicts", [])
                if "空腔" in c]


def test_view_structure_accepts_the_singular_view_alias(tmp_path):
    """reg1-ext2 hsl: the agent's first call was view_structure(view='a')
    and the registry refused it as an unknown parameter. The singular is
    now an alias - a string or a list - and `views` still wins when both
    are given."""
    ses = SimpleNamespace(model=_xs(), flags={}, dataset=None)
    proj = SimpleNamespace(dir=tmp_path, session=ses)
    t = ViewStructure(proj)
    assert "view" in t.params_schema["properties"]
    r = t.run(SimpleNamespace(session=ses), view="a")
    assert r.ok, r.error
    assert len(r.summary["_image_files"]) == 1
    r = t.run(SimpleNamespace(session=ses), view=["b", "c"])
    assert r.ok and len(r.summary["_image_files"]) == 2
    r = t.run(SimpleNamespace(session=ses), views=["a"], view=["b", "c"])
    assert r.ok and len(r.summary["_image_files"]) == 1
