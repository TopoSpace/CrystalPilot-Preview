"""The interaction layer on the scene (R2.3 wiring): rows mapped onto the
drawn instances, the boundary rule visible, h_source read off AFIX groups,
cache key extended only when the layer is requested. Synthetic P1 cells,
analytic geometry; no project data."""
from __future__ import annotations

import pytest

# O1-H1...O2 along +x: O-H 0.96, H...O 1.84, D...A 2.80 A, angle 180 deg
WATER_PAIR = (
    "TITL two hydroxyls, primitive cubic\n"
    "CELL 0.71073 10 10 10 90 90 90\n"
    "ZERR 1 0 0 0 0 0 0\n"
    "LATT -1\n"
    "SFAC H O\n"
    "UNIT 1 2\n"
    "O1 2 0.200 0.500 0.500 11 0.05\n"
    "{afix_on}"
    "H1 1 0.296 0.500 0.500 11 0.05\n"
    "{afix_off}"
    "O2 2 {x2:.3f} 0.500 0.500 11 0.05\n"
    "HKLF 4\n"
    "END\n"
)


def _res(tmp_path, x2=0.480, riding=False):
    p = tmp_path / "pair.res"
    p.write_text(WATER_PAIR.format(
        x2=x2, afix_on="AFIX 147\n" if riding else "",
        afix_off="AFIX 0\n" if riding else ""), encoding="ascii")
    return p


def _hbonds(scene):
    return [r for r in scene["interactions"]["rows"] if r["kind"] == "hbond"]


def test_layer_is_absent_unless_requested(tmp_path):
    from crystalpilot.refine.scene import build_scene

    s = build_scene(_res(tmp_path))
    assert "interactions" not in s
    s = build_scene(_res(tmp_path), interactions=True)
    assert set(s["interactions"]) >= {"h_source", "criteria", "counts",
                                      "truncated", "range", "rows", "rings"}


def test_in_range_hbond_maps_to_drawn_atoms(tmp_path):
    """Both ends are drawn in the ASU: the row carries the scene indices of
    donor and acceptor, the H position, the geometry and its verdict."""
    from crystalpilot.refine.scene import build_scene

    s = build_scene(_res(tmp_path), interactions=True)
    labels = [a["label"] for a in s["atoms"]]
    rows = _hbonds(s)
    assert len(rows) == 1
    r = rows[0]
    assert (labels[r["ai"]], labels[r["bi"]]) == ("O1", "O2")
    assert (r["d"], r["h"], r["a"]) == ("O1", "H1", "O2")   # labels
    assert r["boundary"] is False and r["passes"] is True
    assert abs(r["d_DA"] - 2.80) < 1e-3 and abs(r["d_HA"] - 1.84) < 1e-3
    assert abs(r["angle"] - 180.0) < 1e-3
    assert r["p"] == pytest.approx([2.0, 5.0, 5.0], abs=1e-3)
    assert r["q"] == pytest.approx([4.8, 5.0, 5.0], abs=1e-3)
    assert r["h_xyz"] == pytest.approx([2.96, 5.0, 5.0], abs=1e-3)
    assert s["interactions"]["h_source"] == "refined"
    assert s["interactions"]["counts"]["n_boundary"] == 0


def test_partner_across_the_cell_face_is_a_boundary_row(tmp_path):
    """O2 stored at x = 0.92: the acceptor of O1-H1 is its x-1 image, which
    the ASU does not draw. The row is still emitted (at least one end in
    range), with bi = None, boundary = true, the operator, and q at the
    image position - the defect the boundary rule fixes, made visible."""
    from crystalpilot.refine.scene import build_scene

    s = build_scene(_res(tmp_path, x2=0.920), interactions=True)
    labels = [a["label"] for a in s["atoms"]]
    o2 = labels.index("O2")
    # O1...O2(x-1): 2.0 - (-0.8) = 2.8 A -> same geometry, other image.
    # ONE crystallographic hydrogen bond, TWO display rows (as Olex2 shows
    # it): one hangs off the drawn donor O1 (acceptor image off screen), one
    # off the drawn acceptor O2 (donor image off screen); `unique` has one.
    rows = _hbonds(s)
    assert len(rows) == 2
    assert all(r["boundary"] and (r["d"], r["h"], r["a"]) == ("O1", "H1", "O2")
               and abs(r["d_DA"] - 2.80) < 1e-3 for r in rows)
    assert {(r["ai"], r["bi"]) for r in rows} == {(0, None), (None, o2)}
    from_donor = next(r for r in rows if r["ai"] == 0)
    assert from_donor["sym"].replace(" ", "") == "x-1,y,z"
    assert from_donor["q"] == pytest.approx([-0.8, 5.0, 5.0], abs=1e-3)
    from_acceptor = next(r for r in rows if r["bi"] == o2)
    assert from_acceptor["sym_i"].replace(" ", "") == "x+1,y,z"
    assert from_acceptor["p"] == pytest.approx([12.0, 5.0, 5.0], abs=1e-3)
    assert s["interactions"]["counts"]["n_boundary"] == 2
    assert s["interactions"]["counts"]["unique"]["hbond"] == 1
    assert s["interactions"]["range"]["halo_sufficient"] is True
    assert s["interactions"]["range"]["halo_capped"] is False


def test_h_source_is_read_off_afix(tmp_path):
    from crystalpilot.refine.scene import build_scene

    riding = build_scene(_res(tmp_path, riding=True), interactions=True)
    assert riding["interactions"]["h_source"] == "riding"
    assert "0.1" in riding["interactions"]["h_source_note"]   # the bias is stated
    free = build_scene(_res(tmp_path), interactions=True)
    assert free["interactions"]["h_source"] == "refined"


def test_no_hydrogen_degrades_to_d_a_only(tmp_path):
    from crystalpilot.refine.scene import build_scene

    p = tmp_path / "noh.res"
    p.write_text(WATER_PAIR.format(x2=0.480, afix_on="", afix_off="")
                 .replace("H1 1 0.296 0.500 0.500 11 0.05\n", "")
                 .replace("UNIT 1 2", "UNIT 0 2"),
                 encoding="ascii")
    s = build_scene(p, interactions=True)
    assert s["interactions"]["h_source"] == "absent"
    r = _hbonds(s)[0]
    assert r["status"] == "no_H_D···A_only" and r["angle"] is None


def test_cache_key_extends_only_when_requested():
    import inspect

    from crystalpilot.refine import scene as scene_mod

    src = inspect.getsource(scene_mod.cached_scene)
    assert '"_i1"' in src and "if interactions:" in src
