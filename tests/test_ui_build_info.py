"""Build version/time and outdated-source hints, without reading Git internals."""
import json
import os
import time
from pathlib import Path

import pytest


@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    import server.app as app_mod

    (tmp_path / "ui" / "src").mkdir(parents=True)
    (tmp_path / "ui" / "dist").mkdir(parents=True)
    monkeypatch.setattr(app_mod, "ROOT", tmp_path)
    monkeypatch.setattr(app_mod, "UI_DIST", tmp_path / "ui" / "dist")
    return tmp_path


def _touch(p: Path, when: float, text: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    os.utime(p, (when, when))


def test_missing_dist_is_absent(fake_root):
    from server.app import ui_build_info

    assert ui_build_info() == {"present": False}


def test_fresh_bundle(fake_root):
    from server.app import ui_build_info

    now = time.time()
    _touch(fake_root / "ui" / "src" / "a.ts", now - 100)
    _touch(fake_root / "ui" / "index.html", now - 90)
    _touch(fake_root / "ui" / "dist" / "index.html", now - 10)
    info = ui_build_info()
    assert info["present"] is True
    assert info["stale"] is False
    assert info["src_newest_file"] == str(Path("ui") / "index.html")
    assert info["version"] is None
    assert "git_head_at_build" not in info
    assert "head_mismatch" not in info


def test_stale_when_any_input_is_newer(fake_root):
    from server.app import ui_build_info

    now = time.time()
    _touch(fake_root / "ui" / "dist" / "index.html", now - 100)
    _touch(fake_root / "ui" / "src" / "lib" / "deep.tsx", now - 5)
    info = ui_build_info()
    assert info["stale"] is True
    assert info["src_newest_file"] == str(Path("ui") / "src" / "lib" / "deep.tsx")


def test_one_second_slack(fake_root):
    """build.json lands right after index.html; sub-second skew is not staleness."""
    from server.app import ui_build_info

    now = time.time()
    _touch(fake_root / "ui" / "dist" / "index.html", now - 10)
    _touch(fake_root / "ui" / "src" / "a.ts", now - 9.5)
    assert ui_build_info()["stale"] is False


def test_build_version_and_time_are_descriptive(fake_root):
    from server.app import ui_build_info

    now = time.time()
    _touch(fake_root / "ui" / "src" / "a.ts", now - 100)
    _touch(fake_root / "ui" / "dist" / "index.html", now - 10)
    _touch(fake_root / "ui" / "dist" / "build.json", now - 9,
           json.dumps({"version": "0.1.0", "built_at": "2026-09-05T04:00:00Z"}))
    info = ui_build_info()
    assert info["version"] == "0.1.0"
    assert info["built_at"] == "2026-09-05T04:00:00Z"
    assert info["stale"] is False
    assert "git_head_now" not in info


def test_corrupt_stamp_is_ignored(fake_root):
    from server.app import ui_build_info

    now = time.time()
    _touch(fake_root / "ui" / "dist" / "index.html", now - 10)
    _touch(fake_root / "ui" / "dist" / "build.json", now - 9, "{not json")
    info = ui_build_info()
    assert info["present"] is True
    assert info["version"] is None
