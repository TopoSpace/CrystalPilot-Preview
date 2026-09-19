"""Twin Fourier maps must not turn overlapping intensities into ghost peaks."""
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from cctbx import crystal, xray
from cctbx.array_family import flex

from crystalpilot.tools.refinement_tools import difference_map_real
from crystalpilot.tools.twin_maps import detwinned_amplitudes

THREEFOLD = [0, 0, 1, 1, 0, 0, 0, 1, 0]
SHELXL = Path(os.environ.get("CRYSTALPILOT_SHELXL", str(
    Path(__file__).resolve().parents[1] / "vendor/shelx/shelxl.exe")))


def _session(basf=(.2, .15), benzene=False):
    xs = xray.structure(crystal_symmetry=crystal.symmetry(
        unit_cell=(12, 12, 12, 90, 90, 90), space_group_symbol="P 1"))
    if benzene:
        from crystalpilot.refine.ligand import ideal_geometry
        tpl = ideal_geometry("c1ccccc1")
        sites = [xs.unit_cell().fractionalize(tuple(v + 3 for v in p)) for p in tpl["coords"]]
    else:
        sites = [(.13, .22, .31), (.25, .27, .32), (.34, .19, .38), (.46, .68, .75)]
    for i, site in enumerate(sites):
        xs.add_scatterer(xray.scatterer(label=f"C{i+1}", scattering_type="C", site=site, u=.025))
    # Keep the resolution cutoff off an exact lattice shell.
    intensities = xs.structure_factors(d_min=1.03, algorithm="direct").f_calc().norm()
    lookup = {}
    for h, value in zip(intensities.indices(), intensities.data()):
        lookup[tuple(h)] = value
        lookup[tuple(-v for v in h)] = value
    mixed = flex.double([
        (1-sum(basf)) * lookup[(h, k, l)] + basf[0] * lookup[(l, h, k)]
        + basf[1] * lookup[(k, l, h)] for h, k, l in intensities.indices()
    ])
    obs = intensities.customized_copy(data=mixed, sigmas=flex.sqrt(mixed) + 1)
    obs.set_observation_type_xray_intensity()
    return SimpleNamespace(model=xs, fo_sq=obs, flags={
        "twin": {"matrix": THREEFOLD, "n": 3, "basf": list(basf)}})


@pytest.mark.parametrize("basf", [(.2, .15), (.33, .33), (.01, .45)])
def test_complete_twinned_model_has_no_artificial_difference_density(basf):
    ses = _session(basf)
    fft, real, _ = difference_map_real(ses, ses.model)
    assert max(abs(flex.min(real)), abs(flex.max(real))) < 1e-8
    assert fft.crystalpilot_map_provenance["fractions"] == pytest.approx([1-sum(basf), *basf])
    ses.flags = {}
    _, wrong, _ = difference_map_real(ses, ses.model)
    assert flex.max(wrong) - flex.min(wrong) > .1


def test_twin_aware_fragment_fit_restores_a_missing_ring_atom():
    from crystalpilot.refine.tools_extra import FitFragment
    ses = _session(benzene=True)
    ses.model = ses.model.select(flex.bool([True] * 5 + [False]))
    result = FitFragment(None).run(SimpleNamespace(session=ses),
        smiles="c1ccccc1", anchors=[{"atom": f"C{i+1}", "template_index": i} for i in (0, 1, 2)],
        place=[5], min_density=.3)
    assert result.ok, result.error
    assert result.summary["map_provenance"]["twin_included"]
    assert len(result.summary["added"]) == 1, result.summary
    assert ses.model.scatterers().size() == 6


def test_negative_n_includes_inversion_partners():
    ses = _session((.25, .3))
    ses.flags["twin"].update(n=-6, basf=[.15, .1, .05, .1, .2])
    fft, real, _ = difference_map_real(ses, ses.model)
    assert fft.crystalpilot_map_provenance["n_components"] == 6
    assert max(abs(flex.min(real)), abs(flex.max(real))) < 1e-8


def test_inversion_twin_and_fixed_equal_fraction_twin():
    ses = _session((0, 0))
    ses.flags["twin"] = {"matrix": [-1, 0, 0, 0, -1, 0, 0, 0, -1], "n": 2, "basf": [.3]}
    _, real, _ = difference_map_real(ses, ses.model)
    assert max(abs(flex.min(real)), abs(flex.max(real))) < 1e-8
    ses = _session((1/3, 1/3))
    ses.flags["twin"]["basf"] = []
    _, real, _ = difference_map_real(ses, ses.model)
    assert max(abs(flex.min(real)), abs(flex.max(real))) < 1e-8


def test_legacy_peak_table_is_not_reused_for_a_twinned_node(tmp_path):
    from crystalpilot.io.shelx_writer import ShelxModel, write_res
    from crystalpilot.refine.project import RefineProject
    ses = _session()
    write_res(ShelxModel(ses.model, twin=ses.flags["twin"]), tmp_path / "start.res")
    with (tmp_path / "crystal.hkl").open("w") as stream:
        ses.fo_sq.export_as_shelx_hklf(file_object=stream)
    project = RefineProject(tmp_path)
    project.open()
    node = project.nodes.state()["active_node"]
    project.session.flags.update(diff_map_peaks=[{"site": [.1, .2, .3], "height": 2}],
                                  diff_map_peaks_meta={"source": "inspect_map", "node": node})
    project.nodes.save_peaks(node, project.session)
    reopened = RefineProject(tmp_path)
    reopened.open()
    assert not reopened.session.flags.get("diff_map_peaks")
    result = reopened.invoke_tool("inspect_map", {"node": node})
    assert not result.ok and "legacy" in result.error


def test_map_cache_rebuilds_after_algorithm_change(tmp_path, monkeypatch):
    from crystalpilot.io.shelx_writer import ShelxModel, write_res
    from crystalpilot.refine import scene
    from crystalpilot.refine.data_versions import reflection_cache_source
    from crystalpilot.refine.nodes import atomic_write_json
    from crystalpilot.refine.project import RefineProject
    ses = _session()
    write_res(ShelxModel(ses.model, twin=ses.flags["twin"]), tmp_path / "start.res")
    with (tmp_path / "crystal.hkl").open("w") as stream:
        ses.fo_sq.export_as_shelx_hklf(file_object=stream)
    project = RefineProject(tmp_path)
    project.open()
    node = project.nodes.state()["active_node"]
    path = scene.cache_dir(tmp_path, node) / "fofc.ccp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"old map")
    atomic_write_json(path.with_suffix(".ccp4.source.json"), reflection_cache_source(project.nodes, node))
    calls = []
    def rebuild(project_dir, node_id, out_path, kind):
        calls.append(node_id)
        out_path.write_bytes(b"new map")
    monkeypatch.setattr(scene, "build_fofc_ccp4", rebuild)
    assert scene.cached_fofc(tmp_path, node).read_bytes() == b"new map"
    scene.cached_fofc(tmp_path, node)
    assert calls == [node]


@pytest.mark.parametrize("flags,reason", [
    ({"hklf": 5}, "HKLF5"),
    ({"twin": {"matrix": THREEFOLD, "n": 3, "basf": [.2]}}, "2 BASF"),
    ({"twin": {"matrix": THREEFOLD, "n": 3, "basf": [-.1, .2]}}, "not physical"),
    ({"twin": {"matrix": [.5, 0, 0, 0, 2, 0, 0, 0, 1], "n": 2, "basf": [.2]}}, "integral"),
])
def test_unsupported_maps_are_unavailable_not_negative_evidence(flags, reason):
    ses = _session()
    ses.flags = flags
    with pytest.raises(ValueError, match=reason):
        difference_map_real(ses, ses.model)


def test_mask_is_applied_to_all_domains_and_missing_coefficients_refuse():
    ses = _session()
    calc = ses.fo_sq.structure_factors_from_scatterers(xray_structure=ses.model, algorithm="direct").f_calc()
    mask = calc.customized_copy(data=calc.data() * .1)
    # A mask proportional to Fc scales every domain identically.
    masked, info = detwinned_amplitudes(ses, ses.model, calc.customized_copy(data=calc.data()*1.1), mask)
    unmasked, _ = detwinned_amplitudes(ses, ses.model, calc)
    assert list(masked.data()) == pytest.approx(list(unmasked.data()))
    assert info["twin_included"]
    with pytest.raises(ValueError, match="mask coefficients are missing"):
        detwinned_amplitudes(ses, ses.model, calc, mask.select(flex.size_t([0])))


@pytest.mark.skipif(not SHELXL.exists(), reason="licensed SHELXL not installed")
def test_map_amplitudes_agree_with_shelxl_list6_detwinning(tmp_path):
    import gemmi

    from crystalpilot.io.shelx_writer import ShelxModel, write_res
    ses = _session()
    # Imperfect trial model: agreement must hold beyond the zero-residual case.
    atom = ses.model.scatterers()[1]
    atom.site = (atom.site[0] + .015, atom.site[1], atom.site[2])
    calc = ses.fo_sq.structure_factors_from_scatterers(xray_structure=ses.model, algorithm="direct").f_calc()
    detwinned, _ = detwinned_amplitudes(ses, ses.model, calc)
    write_res(ShelxModel(ses.model, twin=ses.flags["twin"],
        instruction_cards=["L.S. 0", "LIST 6", "FMAP 2", "PLAN 20"]), tmp_path / "job.ins")
    with (tmp_path / "job.hkl").open("w") as stream:
        ses.fo_sq.export_as_shelx_hklf(file_object=stream)
    subprocess.run([str(SHELXL), "-t1", "job"], cwd=tmp_path,
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=30, check=True)
    block = gemmi.cif.read_file(str(tmp_path / "job.fcf")).sole_block()
    ours, raw = {}, {}
    for h, f, intensity in zip(detwinned.indices(), detwinned.data(), ses.fo_sq.data()):
        for index in (tuple(h), tuple(-v for v in h)):
            ours[index] = f * f
            raw[index] = intensity
    predictions, raw_predictions, total = [], [], []
    for row in block.find(["_refln_index_h", "_refln_index_k", "_refln_index_l", "_refln_F_squared_meas"]):
        h = tuple(int(row[i]) for i in range(3))
        observed = float(row[3])
        predictions.append(ours[h])
        raw_predictions.append(raw[h])
        total.append(abs(observed))
    assert len(predictions) > 1000
    # LIST 6 also places observations on SHELXL's fitted absolute scale.
    # Compare intensity allocation after removing that one overall scale.
    scale = sum(total) / sum(predictions)
    raw_scale = sum(total) / sum(raw_predictions)
    assert sum(abs(scale * a - b) for a, b in zip(predictions, total)) / sum(total) < .005
    assert sum(abs(raw_scale * a - b) for a, b in zip(raw_predictions, total)) / sum(total) > .05
