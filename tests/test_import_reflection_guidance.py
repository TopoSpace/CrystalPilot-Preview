"""Real CIF import must distinguish paired originals from published SF scaling."""
from pathlib import Path

import pytest

from crystalpilot.refine.project import RefineProject

SOURCE = Path(__file__).resolve().parents[1] / "benchmark" / "public" / "sucrose"


@pytest.mark.parametrize("use_sf", [False, True])
def test_real_import_discloses_reflection_comparison_preconditions(tmp_path, use_sf):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    project = RefineProject(project_dir)
    project.open()
    params = {"cif_path": str(SOURCE / "ref_cif.cif")}
    if use_sf:
        params["hkl_path"] = str(SOURCE / "sf.cif")
    result = project.invoke_tool("import_cif_model", params)
    assert result.ok, result.error
    assert result.summary["imported_atoms"] == 45
    assert result.summary["imported_via"] == "embedded_shelx_res"
    from crystalpilot.refine.data_versions import DataVersions
    _, manifest = DataVersions(project.dir).resolve(project.nodes.state()["active_data_revision"])
    assert manifest["processing"] == (["structure-factor CIF converted to HKLF4"] if use_sf
                                      else ["CIF embedded _shelx_hkl_file extracted"])
    notes = " ".join(result.summary["conversion_notes"])
    if use_sf:
        assert "overall scale" in notes and "zero-cycle R1" in notes
        assert "do not silently alter" in notes
    else:
        assert "embedded _shelx_hkl_file" in notes
        assert "overall scale" not in notes
    assert "matching reflection data" in result.summary["next"]
    assert "should reproduce" not in result.summary["next"]
