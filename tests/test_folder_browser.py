from pathlib import Path

import pytest
from fastapi import HTTPException

from crystalpilot.workbench.routes import list_project_folders


def test_folder_browser_returns_directories_only_and_preserves_case(tmp_path):
    # "Sample" and "sample" are two directories on Linux and one on a
    # case-insensitive filesystem (Windows NTFS, macOS default): create the
    # second only where it is really distinct, and expect what exists
    (tmp_path / "Sample").mkdir()
    (tmp_path / ".hidden").mkdir()
    case_sensitive = not (tmp_path / "sample").exists()
    if case_sensitive:
        (tmp_path / "sample").mkdir()
    (tmp_path / "data.cif").write_text("data_test")
    result = list_project_folders(str(tmp_path))
    expected = {"Sample", "sample"} if case_sensitive else {"Sample"}
    assert {row["name"] for row in result["directories"]} == expected
    assert result["path"] == str(tmp_path)
    assert result["parent"] == str(tmp_path.parent)
    assert not result["truncated"]
    assert (tmp_path / "data.cif").read_text() == "data_test"


def test_folder_browser_rejects_a_file_and_missing_path(tmp_path):
    file = tmp_path / "a.cif"
    file.touch()
    with pytest.raises(HTTPException) as error:
        list_project_folders(str(file))
    assert error.value.status_code == 400
    with pytest.raises(HTTPException) as error:
        list_project_folders(str(tmp_path / "absent"))
    assert error.value.status_code == 404


def test_filesystem_root_has_no_parent():
    root = Path(Path.cwd().anchor)
    assert list_project_folders(str(root))["parent"] is None
