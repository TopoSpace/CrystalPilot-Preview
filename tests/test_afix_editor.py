"""Typed AFIX editing uses existing geometry and preserves complete fused groups."""

import copy
import os
from pathlib import Path

import pytest
from cctbx import crystal, xray
from cctbx.array_family import flex

from crystalpilot.io.shelx_model import load_res_model
from crystalpilot.io.shelx_writer import ShelxModel, write_res
from crystalpilot.refine.ligand import ideal_geometry
from crystalpilot.refine.project import RefineProject

SHELXL = Path(
    os.environ.get(
        "CRYSTALPILOT_SHELXL", str(Path(__file__).resolve().parents[1] / "vendor/shelx/shelxl.exe")
    )
)
SMILES = "c1ccc2cc3ccccc3cc2c1"


def project(tmp_path):
    tpl = ideal_geometry(SMILES)
    xs = xray.structure(
        crystal_symmetry=crystal.symmetry(
            unit_cell=(18, 19, 20, 90, 90, 90), space_group_symbol="P 1"
        )
    )
    for i, xyz in enumerate(tpl["coords"]):
        site = xs.unit_cell().fractionalize(tuple(v + 6 for v in xyz))
        xs.add_scatterer(xray.scatterer(label=f"C{i + 1}", scattering_type="C", site=site, u=0.03))
    observations = xs.structure_factors(d_min=1.5, algorithm="direct").f_calc().norm()
    observations = observations.customized_copy(
        sigmas=flex.sqrt(observations.data()) + 1
    ).set_observation_type_xray_intensity()
    with (tmp_path / "crystal.hkl").open("w") as out:
        observations.export_as_shelx_hklf(file_object=out)
    write_res(ShelxModel(xs), tmp_path / "start.res")
    p = RefineProject(tmp_path)
    p.open()
    from rdkit import Chem

    mol = Chem.MolFromSmiles(SMILES)
    rings = [list(r) for r in mol.GetRingInfo().AtomRings()]
    rings = sorted(rings, key=lambda r: sum(len(set(r) & set(s)) for s in rings), reverse=True)
    return p, [[f"C{i + 1}" for i in ring] for ring in rings]


def test_replace_central_ring_with_one_complete_anthracene_group(tmp_path):
    p, rings = project(tmp_path)
    before = {s.label: (tuple(s.site), s.occupancy, s.u_iso) for s in p.session.model.scatterers()}
    created = p.invoke_tool(
        "set_afix",
        {"action": "create", "afix": 66, "atoms": rings[0], "reason": "accepted central ring"},
    )
    assert created.ok, created.error
    node = created.summary["node"]
    overlapping = p.invoke_tool(
        "set_afix",
        {"action": "create", "afix": 66, "atoms": rings[1], "reason": "overlap must be rejected"},
    )
    assert not overlapping.ok and "already belong" in overlapping.error
    assert p.nodes.state()["active_node"] == node
    all_atoms = [s.label for s in p.session.model.scatterers()]
    replaced = p.invoke_tool(
        "set_afix",
        {
            "action": "replace",
            "group_index": 0,
            "afix": 6,
            "atoms": all_atoms,
            "reason": "whole existing data-supported fused core; shared atoms appear once",
        },
    )
    assert replaced.ok, replaced.error
    assert len(replaced.summary["groups"]) == 1 and len(replaced.summary["group"]["atoms"]) == 14
    assert {
        s.label: (tuple(s.site), s.occupancy, s.u_iso) for s in p.session.model.scatterers()
    } == before
    reopened = RefineProject(tmp_path)
    reopened.open()
    assert reopened.session.flags["afix_groups"] == p.session.flags["afix_groups"]
    renamed = reopened.invoke_tool("rename_atoms", {"mode": "map", "map": {"C1": "C99"}})
    assert renamed.ok, renamed.error
    assert "C99" in reopened.session.flags["afix_groups"][0]["atoms"]
    removed = reopened.invoke_tool(
        "set_afix",
        {
            "action": "remove",
            "group_index": 0,
            "reason": "comparison trial without rigid-body constraints",
        },
    )
    assert removed.ok and not reopened.session.flags["afix_groups"]
    checked = reopened.invoke_tool("checkout", {"node": renamed.summary["node"]})
    assert checked.ok and len(reopened.session.flags["afix_groups"][0]["atoms"]) == 14


@pytest.mark.parametrize("change", ["duplicate", "missing", "wrong_order", "part"])
def test_invalid_group_cannot_create_or_move_atoms(tmp_path, change):
    p, rings = project(tmp_path)
    atoms = rings[0][:]
    if change == "duplicate":
        atoms[-1] = atoms[0]
    if change == "missing":
        atoms[-1] = "X404"
    if change == "wrong_order":
        atoms[1], atoms[3] = atoms[3], atoms[1]
    if change == "part":
        assert p.invoke_tool(
            "edit_atoms", {"operations": [{"action": "set_part", "atoms": [atoms[0]], "part": 1}]}
        ).ok
    before = copy.deepcopy(p.nodes.state())
    result = p.invoke_tool(
        "set_afix",
        {"action": "create", "afix": 66, "atoms": atoms, "reason": "invalid candidate test"},
    )
    assert not result.ok
    assert p.nodes.state()["active_node"] == before["active_node"]
    assert p.session.model.scatterers().size() == 14
    assert not p.session.flags.get("afix_groups")


@pytest.mark.skipif(not SHELXL.exists(), reason="licensed SHELXL not installed")
def test_whole_fused_afix_survives_real_refinement_and_delivery(tmp_path, monkeypatch):
    p, _ = project(tmp_path)
    monkeypatch.setenv("CRYSTALPILOT_SHELXL", str(SHELXL))
    labels = [s.label for s in p.session.model.scatterers()]
    result = p.invoke_tool(
        "set_afix",
        {
            "action": "create",
            "afix": 6,
            "atoms": labels,
            "reason": "whole accepted anthracene core",
        },
    )
    assert result.ok, result.error
    native = p.invoke_tool("run_shelxl", {"mode": "adopt", "l_s": 3})
    assert native.ok, native.error
    assert len(p.session.flags["afix_groups"]) == 1
    assert set(p.session.flags["afix_groups"][0]["atoms"]) == set(labels)
    delivered = p.invoke_tool("write_outputs", {"output_dir": "delivery"})
    assert delivered.ok, delivered.error
    parsed = load_res_model(tmp_path / "delivery/final.res")
    assert parsed.afix_groups[0]["afix"] == 6 and len(parsed.afix_groups[0]["atoms"]) == 14
