"""Ordinary artifact tools may not use immutable archives as output directories."""
import pytest

from crystalpilot.refine.data_versions import DataVersions
from tests.test_data_versions import _project, _inventory


@pytest.mark.parametrize("tool", ["write_outputs", "run_checkcif", "finalize_delivery"])
def test_artifact_destinations_cannot_modify_archives(tmp_path, monkeypatch, tool):
    p = _project(tmp_path)
    version = DataVersions(p.dir).path(p.nodes.state()["active_data_revision"])
    versions_before = _inventory(DataVersions(p.dir).directory)
    nodes_before = _inventory(p.nodes.nodes_dir)
    if tool == "write_outputs":
        params = {"output_dir": str(version.relative_to(p.dir))}
    elif tool == "run_checkcif":
        params = {"cif": str((p.nodes.node_dir("n0000") / "model.cif").relative_to(p.dir))}
    else:
        from crystalpilot.refine import tools_deliver
        monkeypatch.setattr(tools_deliver, "find_newest_delivery", lambda root: version)
        params = {}
    result = p.invoke_tool(tool, params)
    assert not result.ok and "read-only" in result.error
    assert _inventory(DataVersions(p.dir).directory) == versions_before
    assert _inventory(p.nodes.nodes_dir) == nodes_before
