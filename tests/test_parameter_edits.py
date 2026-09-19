"""Typed ADP/FVAR/AFIX changes with real constrained, twinned SHELXL jobs."""

from __future__ import annotations

import copy
import math
import os
from pathlib import Path

import pytest
from cctbx import crystal, xray
from cctbx.array_family import flex

from crystalpilot.io.shelx_model import load_res_model
from crystalpilot.io.shelx_writer import ShelxModel, apply_anomalous_terms, write_res
from crystalpilot.refine.project import RefineProject

SHELXL = Path(
    os.environ.get(
        "CRYSTALPILOT_SHELXL", str(Path(__file__).resolve().parents[1] / "vendor/shelx/shelxl.exe")
    )
)
METALS = ["FE", "FE00", "FE1", "FE04"]
LAW = [-1, 0, -1, 0, 1, 0, 1, 0, 0]


def make_project(path):
    xs = xray.structure(
        crystal_symmetry=crystal.symmetry(
            unit_cell=(20, 22, 20, 90, 120, 90), space_group_symbol="P 1 2 1"
        )
    )
    groups = []
    for ring, center in enumerate(((0.2, 0.2, 0.2), (0.6, 0.35, 0.5), (0.35, 0.7, 0.7))):
        labels = []
        for i in range(6):
            angle, tilt = i * math.pi / 3 + 0.17 * (ring + 1), 0.31 * (ring + 1)
            label = f"C{ring * 6 + i + 1}"
            labels.append(label)
            origin = xs.unit_cell().orthogonalize(center)
            site = xs.unit_cell().fractionalize(
                (
                    origin[0] + 1.39 * math.cos(angle),
                    origin[1] + 1.39 * math.sin(angle) * math.cos(tilt),
                    origin[2] + 1.39 * math.sin(angle) * math.sin(tilt),
                )
            )
            xs.add_scatterer(xray.scatterer(label=label, scattering_type="C", site=site, u=0.025))
        groups.append({"afix": 66, "card": "AFIX 66", "atoms": labels})
    for label, site in zip(
        METALS, ((0.11, 0.41, 0.32), (0.32, 0.15, 0.57), (0.46, 0.61, 0.31), (0, 0.42, 0))
    ):
        xs.add_scatterer(
            xray.scatterer(
                label=label,
                scattering_type="Fe",
                site=site,
                u=0.025,
                occupancy=0.62 if label == "FE04" else 1,
            )
        )
    xs.scattering_type_registry(table="it1992")
    apply_anomalous_terms(xs, 0.71073)
    intensities = (
        xs.structure_factors(d_min=1.45, anomalous_flag=True, algorithm="direct").f_calc().norm()
    )
    rotate = lambda h: (-h[0] - h[2], h[1], h[0])
    indices1 = flex.miller_index([rotate(h) for h in intensities.indices()])
    indices2 = flex.miller_index([rotate(h) for h in indices1])
    fc1 = (
        intensities.customized_copy(indices=indices1)
        .structure_factors_from_scatterers(xray_structure=xs, algorithm="direct")
        .f_calc()
        .norm()
    )
    fc2 = (
        intensities.customized_copy(indices=indices2)
        .structure_factors_from_scatterers(xray_structure=xs, algorithm="direct")
        .f_calc()
        .norm()
    )
    mixed = 0.35 * intensities.data() + 0.35 * fc1.data() + 0.3 * fc2.data()
    # Small deterministic measurement noise keeps printed esds distinguishable
    # from SHELXL's five-decimal zero on perfectly synthetic observations.
    mixed *= flex.double([1 + 0.003 * math.sin(i * 1.7) for i in range(mixed.size())])
    obs = intensities.customized_copy(
        data=mixed, sigmas=flex.sqrt(mixed) + 1
    ).set_observation_type_xray_intensity()
    with (path / "crystal.hkl").open("w") as out:
        obs.export_as_shelx_hklf(file_object=out)
    write_res(
        ShelxModel(xs, afix_groups=groups, twin={"matrix": LAW, "n": 3, "basf": [0.35, 0.3]}),
        path / "start.res",
    )
    project = RefineProject(path)
    project.open()
    return project


def atom_state(xs):
    return {
        s.label: (
            tuple(s.site),
            s.occupancy,
            s.scattering_type,
            bool(s.flags.use_u_aniso()),
            tuple(s.u_star),
            s.u_iso,
        )
        for s in xs.scatterers()
    }


def test_selected_adp_conversion_keeps_every_other_parameter(tmp_path):
    p = make_project(tmp_path)
    before = atom_state(p.session.model)
    groups, twin = (
        copy.deepcopy(p.session.flags["afix_groups"]),
        copy.deepcopy(p.session.flags["twin"]),
    )
    result = p.invoke_tool("set_adp", {"atoms": METALS, "mode": "anisotropic"})
    assert result.ok, result.error
    after = atom_state(p.session.model)
    for label in before:
        assert after[label][:3] == before[label][:3]
        if label in METALS:
            assert after[label][3]
        else:
            assert after[label] == before[label]
    assert p.session.flags["afix_groups"] == groups and p.session.flags["twin"] == twin
    fe04 = next(r for r in result.summary["atoms"] if r["atom"] == "FE04")
    assert fe04["multiplicity"] == 1
    assert fe04["u_cif"][3] == pytest.approx(0, abs=1e-12)
    assert fe04["u_cif"][5] == pytest.approx(0, abs=1e-12)
    reopened = RefineProject(tmp_path)
    reopened.open()
    assert all(
        s.flags.use_u_aniso() for s in reopened.session.model.scatterers() if s.label in METALS
    )
    assert reopened.session.flags["twin"] == twin


def test_zero_cycles_and_zero_free_parameters_are_explicit(tmp_path):
    p = make_project(tmp_path)
    for i in (2, 1, 0):
        assert p.invoke_tool(
            "set_afix",
            {"action": "remove", "group_index": i, "reason": "isolated engine precondition test"},
        ).ok
    assert p.invoke_tool("set_twin", {"law": "remove"}).ok
    before = p.nodes.state()["active_node"]
    r = p.invoke_tool("refine", {"mode": "aniso_heavy", "n_cycles": 0})
    assert not r.ok and "n_cycles >= 1" in r.error
    r = p.invoke_tool(
        "refine", {"n_cycles": 1, "fix_atoms": [s.label for s in p.session.model.scatterers()]}
    )
    assert not r.ok and "no independent" in r.error
    assert p.nodes.state()["active_node"] == before


def test_parameter_preflights_preserve_state_and_special_positions(tmp_path):
    p = make_project(tmp_path)
    before = atom_state(p.session.model)
    node = p.nodes.state()["active_node"]
    bad = p.invoke_tool("set_adp", {"atoms": ["FE", "missing"], "mode": "anisotropic"})
    assert not bad.ok and atom_state(p.session.model) == before
    bad = p.invoke_tool(
        "set_afix",
        {
            "action": "create",
            "afix": 6,
            "atoms": ["FE", "FE1", "FE04"],
            "reason": "special-position compatibility test",
        },
    )
    assert not bad.ok and "special position" in bad.error
    assert p.nodes.state()["active_node"] == node and atom_state(p.session.model) == before


def test_fixing_one_site_does_not_repoint_another_fvar(tmp_path):
    p = make_project(tmp_path)
    for label, value in (("FE04", 0.5), ("FE1", 0.9)):
        r = p.invoke_tool("set_site_occupancy", {"atom": label, "mode": "free", "value": value})
        assert r.ok, r.error
    fixed = p.invoke_tool("set_site_occupancy", {"atom": "FE04", "mode": "fixed", "value": 0.5})
    assert fixed.ok, fixed.error
    parsed = load_res_model(p.nodes.node_dir(fixed.summary["node"]) / "model.res")
    assert parsed.sof_codes["FE1"] == pytest.approx(21)
    atoms = {s.label: s for s in parsed.structure.scatterers()}
    assert atoms["FE1"].occupancy == pytest.approx(0.9)
    assert atoms["FE04"].occupancy == pytest.approx(0.5)
    assert len(parsed.afix_groups) == 3 and parsed.twin["n"] == 3


@pytest.mark.skipif(not SHELXL.exists(), reason="licensed SHELXL not installed")
def test_special_position_occupancy_and_anisotropic_adopt(tmp_path, monkeypatch):
    p = make_project(tmp_path)
    monkeypatch.setenv("CRYSTALPILOT_SHELXL", str(SHELXL))
    assert p.invoke_tool("set_adp", {"atoms": METALS, "mode": "anisotropic"}).ok
    before = atom_state(p.session.model)
    r = p.invoke_tool("set_site_occupancy", {"atom": "FE04", "mode": "free", "value": 0.5})
    assert r.ok, r.error
    after = atom_state(p.session.model)
    for label in before:
        if label != "FE04":
            assert after[label] == before[label]
        else:
            assert after[label][0] == before[label][0] and after[label][2:] == before[label][2:]
    parsed = load_res_model(p.nodes.node_dir(r.summary["node"]) / "model.res")
    assert parsed.sof_codes["FE04"] == pytest.approx(20.5)
    assert next(
        s for s in parsed.structure.scatterers() if s.label == "FE04"
    ).occupancy == pytest.approx(0.5)
    refined = p.invoke_tool("run_shelxl", {"mode": "adopt", "l_s": 8})
    assert refined.ok, refined.error
    site = next(row for row in refined.summary["site_occupancies"] if row["atom"] == "FE04")
    assert site["occupancy"] == pytest.approx(0.62, abs=0.025)
    assert site["su"] is not None and site["su"] > 0
    assert "correlation" in site["note"]
    assert site["reported_adp_correlations"]
    assert all(
        abs(row["occupancy_adp_correlation"]) <= 1 for row in site["reported_adp_correlations"]
    )
    assert len(p.session.flags["afix_groups"]) == 3
    assert p.session.flags["twin"]["n"] == 3 and len(p.session.flags["twin"]["basf"]) == 2
    node = refined.summary["node"]
    saved = load_res_model(p.nodes.node_dir(node) / "model.res")
    live = {s.label: s for s in p.session.model.scatterers()}
    for sc in saved.structure.scatterers():
        if sc.label in METALS:
            assert sc.flags.use_u_aniso()
            assert sc.u_star == pytest.approx(live[sc.label].u_star, abs=1e-7)
    import gemmi
    from cctbx import adptbx

    tags = ["_atom_site_aniso_label"] + [
        "_atom_site_aniso_U_" + ij for ij in ("11", "22", "33", "12", "13", "23")
    ]
    for file in (
        p.nodes.node_dir(node) / "model.cif",
        Path(refined.summary["job_dir"]) / "job.cif",
    ):
        block = gemmi.cif.read_file(str(file)).sole_block()
        rows = {
            str(row[0]).upper(): [gemmi.cif.as_number(row[i]) for i in range(1, 7)]
            for row in block.find(tags)
        }
        for label in METALS:
            assert rows[label] == pytest.approx(
                adptbx.u_star_as_u_cif(p.session.model.unit_cell(), live[label].u_star), abs=1e-4
            )
    reopened = RefineProject(tmp_path)
    reopened.open()
    assert len(reopened.session.flags["afix_groups"]) == 3
    assert reopened.session.flags["disorder_groups"][0]["free_variable"]["su"] > 0
    check = reopened.invoke_tool("run_shelxl", {"mode": "check", "l_s": 0})
    assert check.ok, check.error
    assert all(row["su"] is None for row in check.summary["site_occupancies"])
    errors = []
    for value in (1.0, 0.5):
        fixed = reopened.invoke_tool(
            "set_site_occupancy", {"atom": "FE04", "mode": "fixed", "value": value}
        )
        assert fixed.ok, fixed.error
        checked = reopened.invoke_tool("run_shelxl", {"mode": "check", "l_s": 0})
        assert checked.ok, checked.error
        errors.append(checked.summary["shelxl"]["r1_strong"])
    assert all(r > refined.summary["shelxl"]["r1_strong"] for r in errors)


def test_correlation_readback_handles_both_column_orders():
    from crystalpilot.refine.tools_parameters import occupancy_adp_correlations

    rows = occupancy_adp_correlations("""Largest correlation matrix elements
       0.647 U11 FE04 / FVAR 2      -0.720 FVAR 3 / Uiso O1
       0.900 x FE04 / y FE04
    """)
    assert rows == [
        {"atom": "FE04", "adp": "U11", "fvar_index": 2, "fvar_adp_correlation": 0.647},
        {"atom": "O1", "adp": "Uiso", "fvar_index": 3, "fvar_adp_correlation": -0.720},
    ]
