"""get_geometry scope torsions / planes / centroids (round-2 R5): dihedrals
over bonded chains (symmetry-aware, IUPAC sign), least-squares ring planes
with rms and normal, ring centroids, and the CONF / MPLA cards the tool
suggests for run_shelxl(extra_cards=). Analytic checks on a synthetic P1
model plus the public Ca-imidazolate project end to end."""
from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from cctbx import crystal, xray

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "benchmark" / "public" / "Ca_imidazolate"


def _p1(atoms, cell=(20, 20, 20, 90, 90, 90)):
    cs = crystal.symmetry(unit_cell=cell, space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()
    for lb, el, cart in atoms:
        xs.add_scatterer(xray.scatterer(
            label=lb, site=uc.fractionalize(tuple(cart)),
            scattering_type=el, u=0.03))
    return xs


class TestHelpers:
    def test_torsion_sign_and_magnitude(self):
        from crystalpilot.refine.tools_analysis import _torsion_deg
        # butane-like: C1 above, C4 rotated +60 deg about the C2-C3 axis
        p1, p2, p3 = (1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 1.5)
        p4 = (math.cos(math.radians(60)), math.sin(math.radians(60)), 1.5)
        assert abs(_torsion_deg(p1, p2, p3, p4) - 60.0) < 1e-6
        p4m = (math.cos(math.radians(-60)), math.sin(math.radians(-60)), 1.5)
        assert abs(_torsion_deg(p1, p2, p3, p4m) + 60.0) < 1e-6
        assert abs(abs(_torsion_deg(p1, p2, p3, (-1.0, 0.0, 1.5))) - 180.0) < 1e-6
        assert math.isnan(_torsion_deg(p1, p2, p3, (0.0, 0.0, 3.0)))  # linear

    def test_plane_fit(self):
        from crystalpilot.refine.tools_analysis import _plane_fit
        pts = [(math.cos(a), math.sin(a), 0.0)
               for a in [k * math.pi / 3 for k in range(6)]]
        c, n, rms = _plane_fit(pts)
        assert abs(rms) < 1e-9 and abs(abs(n[2]) - 1.0) < 1e-9
        assert all(abs(v) < 1e-9 for v in c)
        pts[0] = (1.0, 0.0, 0.3)
        assert _plane_fit(pts)[2] > 0.05


class TestGeometryScopes:
    def _ctx(self, xs):
        return SimpleNamespace(session=SimpleNamespace(model=xs, flags={}))

    def test_torsions_on_a_chain(self, tmp_path):
        from crystalpilot.refine.tools_analysis import GetGeometry
        # C1-C2-C3-C4 with a 60 deg dihedral, plus one more atom on C4
        xs = _p1([("C1", "C", (1.54, 0.0, 0.0)),
                  ("C2", "C", (0.0, 0.0, 0.0)),
                  ("C3", "C", (0.0, 0.0, 1.54)),
                  ("C4", "C", (0.77, 1.334, 1.54)),
                  ("O1", "O", (0.77, 1.334, 2.97))])
        proj = SimpleNamespace(dir=tmp_path)
        r = GetGeometry(proj).run(self._ctx(xs), scope="torsions")
        assert r.ok, r.error
        s = r.summary
        assert s["scope"] == "torsions" and s["bonds"] == [] and s["angles"] == []
        tors = {(t["a"], t["b"], t["c"], t["d"]): t["deg"] for t in s["torsions"]}
        assert ("C1", "C2", "C3", "C4") in tors or ("C4", "C3", "C2", "C1") in tors
        val = tors.get(("C1", "C2", "C3", "C4"), tors.get(("C4", "C3", "C2", "C1")))
        assert abs(abs(val) - 60.0) < 0.5
        assert s["n_torsions"] == len(s["torsions"]) >= 2
        assert "CONF" in s["suggested_cards"]["cards"]
        assert "CONF" in s["torsion_esd_note"]

    def test_planes_and_centroids_of_a_benzene(self, tmp_path):
        from crystalpilot.refine.tools_analysis import GetGeometry
        ring = [(f"C{k + 1}", "C", (5.0 + 1.39 * math.cos(k * math.pi / 3),
                                   5.0 + 1.39 * math.sin(k * math.pi / 3), 5.0))
                for k in range(6)]
        xs = _p1(ring)
        proj = SimpleNamespace(dir=tmp_path)
        r = GetGeometry(proj).run(self._ctx(xs), scope="planes")
        assert r.ok, r.error
        s = r.summary
        assert s["n_planes"] == 1
        pl = s["planes"][0]
        assert sorted(pl["atoms"]) == [f"C{k}" for k in range(1, 7)]
        assert pl["rms_A"] < 1e-3 and abs(abs(pl["normal"][2]) - 1.0) < 1e-6
        assert [round(v, 2) for v in pl["centroid_cart"]] == [5.0, 5.0, 5.0]
        assert s["suggested_cards"]["cards"][0].startswith("MPLA 6 ")
        assert "MPLA" in s["plane_esd_note"]
        r2 = GetGeometry(proj).run(self._ctx(xs), scope="centroids")
        assert r2.ok and r2.summary["n_centroids"] == 1
        assert [round(v, 3) for v in r2.summary["centroids"][0]["centroid_frac"]] == [0.25, 0.25, 0.25]
        assert "planes" not in r2.summary

    def test_default_scope_unchanged(self, tmp_path):
        from crystalpilot.refine.tools_analysis import GetGeometry
        xs = _p1([("C1", "C", (0.0, 0.0, 0.0)), ("O1", "O", (1.3, 0.0, 0.0))])
        r = GetGeometry(SimpleNamespace(dir=tmp_path)).run(self._ctx(xs))
        assert r.ok and r.summary["n_bonds"] == 1 and "torsions" not in r.summary


@pytest.mark.skipif(not (SRC / "ref_cif.cif").exists(),
                    reason="Ca_imidazolate benchmark not present")
def test_all_scopes_on_the_public_benchmark(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    (d / "context.json").write_text(json.dumps({"chemistry": {"note": "t"}}),
                                    encoding="utf-8")
    from crystalpilot.refine.project import RefineProject
    p = RefineProject(d)
    p.open()
    r = p.invoke_tool("import_cif_model", {
        "cif_path": str(SRC / "ref_cif.cif"), "hkl_path": str(SRC / "sf.cif")})
    assert r.ok, r.error
    r = p.invoke_tool("get_geometry", {"scope": "all"})
    assert r.ok, r.error
    s = r.summary
    assert s["n_bonds"] > 0 and s["n_angles"] > 0 and s["n_torsions"] > 0
    assert s["n_planes"] >= 1 and s["n_centroids"] == s["n_planes"]
    assert all({"a", "b", "c", "d", "deg"} <= set(t) for t in s["torsions"])
    assert "CONF" in s["suggested_cards"]["cards"]
