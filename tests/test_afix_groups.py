"""Non-hydrogen AFIX constraints survive import, node storage and SHELXL."""
import math
import os
from pathlib import Path

import pytest
from cctbx import crystal, xray
from cctbx.array_family import flex

from crystalpilot.io.shelx_model import load_res_model
from crystalpilot.io.shelx_writer import ShelxModel, write_res
from crystalpilot.refine.nodes import serialization_extras
from crystalpilot.refine.project import RefineProject

SHELXL = Path(os.environ.get("CRYSTALPILOT_SHELXL", str(
    Path(__file__).resolve().parents[1] / "vendor/shelx/shelxl.exe")))


def make_project(path, hydrogens=False):
    xs = xray.structure(crystal_symmetry=crystal.symmetry(
        unit_cell=(20, 20, 20, 90, 90, 90), space_group_symbol="P 1"))
    groups = []
    for ring, center in enumerate(((.2, .2, .2), (.6, .35, .5), (.35, .7, .7))):
        atoms = []
        for i in range(6):
            angle = i * math.pi / 3 + .17 * (ring + 1)
            tilt = .31 * (ring + 1)
            label = f"C{ring * 6 + i + 1}"
            atoms.append(label)
            site = (center[0] + 1.39 * math.cos(angle) / 20,
                    center[1] + 1.39 * math.sin(angle) * math.cos(tilt) / 20,
                    center[2] + 1.39 * math.sin(angle) * math.sin(tilt) / 20)
            xs.add_scatterer(xray.scatterer(
                label=label, scattering_type="C", site=site, u=.03))
        groups.append({"afix": 66, "card": "AFIX 66", "atoms": atoms})
    riding = []
    if hydrogens:
        for group in groups:
            ring_atoms = list(xs.scatterers())[(int(group["atoms"][0][1:])-1):][:6]
            center = tuple(sum(s.site[k] for s in ring_atoms)/6 for k in range(3))
            for sc in ring_atoms:
                label = "H" + sc.label[1:]
                site = tuple(center[k] + (sc.site[k]-center[k]) * (1.39+.93)/1.39 for k in range(3))
                carrier = sc.label
                xs.add_scatterer(xray.scatterer(label=label, scattering_type="H", site=site, u=.036))
                riding.append({"carrier": carrier, "kind": "aromatic_CH", "afix": 43, "h": [label]})
    observations = xs.structure_factors(d_min=1.8).f_calc().norm()
    observations = observations.customized_copy(
        sigmas=flex.sqrt(observations.data()) + 1).set_observation_type_xray_intensity()
    with (path / "crystal.hkl").open("w") as out:
        observations.export_as_shelx_hklf(file_object=out)
    write_res(ShelxModel(xs, afix_groups=groups, h_riding=riding), path / "start.res")
    return groups


@pytest.mark.parametrize("hydrogens", [False, True])
def test_three_afix66_groups_survive_import_and_reopen(tmp_path, hydrogens):
    expected = make_project(tmp_path, hydrogens)
    parsed = load_res_model(tmp_path / "start.res")
    assert parsed.afix_groups == expected
    project = RefineProject(tmp_path)
    project.open()
    assert project.session.flags["afix_groups"] == expected
    node = project.nodes.state()["active_node"]
    assert load_res_model(project.nodes.node_dir(node) / "model.res").afix_groups == expected
    reopened = RefineProject(tmp_path)
    reopened.open()
    assert reopened.session.flags["afix_groups"] == expected
    result = reopened.invoke_tool("refine", {"n_cycles": 1})
    assert not result.ok and "AFIX" in result.error and "run_shelxl" in result.error
    assert reopened.nodes.state()["active_node"] == node


def test_rename_updates_groups_and_deleting_ring_member_is_atomic(tmp_path):
    make_project(tmp_path)
    project = RefineProject(tmp_path)
    project.open()
    renamed = project.invoke_tool("rename_atoms", {"mode": "map", "map": {"C1": "C99"}})
    assert renamed.ok, renamed.error
    assert project.session.flags["afix_groups"][0]["atoms"][0] == "C99"
    node = renamed.summary["node"]
    removed = project.invoke_tool("edit_atoms", {"operations": [{"action": "delete", "atoms": ["C99"]}]})
    assert not removed.ok and "AFIX" in removed.error
    assert project.nodes.state()["active_node"] == node
    assert project.session.model.scatterers().size() == 18
    assert project.session.flags["afix_groups"][0]["atoms"][0] == "C99"


@pytest.mark.skipif(not SHELXL.exists(), reason="licensed SHELXL not installed")
@pytest.mark.parametrize("hydrogens", [False, True])
def test_real_shelxl_keeps_all_rigid_rings(tmp_path, monkeypatch, hydrogens):
    expected = make_project(tmp_path, hydrogens)
    monkeypatch.setenv("CRYSTALPILOT_SHELXL", str(SHELXL))
    project = RefineProject(tmp_path)
    project.open()
    result = project.invoke_tool("run_shelxl", {"mode": "adopt", "l_s": 2})
    assert result.ok, result.error
    assert len(project.session.flags["afix_groups"]) == 3
    assert [g["atoms"] for g in project.session.flags["afix_groups"]] == [g["atoms"] for g in expected]
    reopened = RefineProject(tmp_path)
    reopened.open()
    xs = reopened.session.model
    atoms = {s.label: s for s in xs.scatterers()}
    for group in expected:
        ring = group["atoms"]
        lengths = [xs.unit_cell().distance(atoms[ring[i]].site, atoms[ring[(i + 1) % 6]].site)
                   for i in range(6)]
        assert lengths == pytest.approx([1.39] * 6, abs=0.002)
    assert len(serialization_extras(reopened.session.flags)["afix_groups"]) == 3
