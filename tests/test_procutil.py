"""procutil spawn-hygiene helpers."""
import os
import subprocess

from crystalpilot.procutil import NO_WINDOW, hidden_popen_kwargs


def test_hidden_popen_kwargs_shape():
    kw = hidden_popen_kwargs()
    if os.name != "nt":
        assert kw == {}
        return
    assert kw["creationflags"] == NO_WINDOW
    si = kw["startupinfo"]
    assert si.dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert si.wShowWindow == 0          # SW_HIDE


def test_hidden_popen_kwargs_spawns(tmp_path):
    # a real (console) spawn with the kwargs must run and exit cleanly
    r = subprocess.run(
        ["cmd", "/c", "echo hidden"] if os.name == "nt" else
        ["echo", "hidden"],
        capture_output=True, text=True, timeout=30,
        **hidden_popen_kwargs())
    assert r.returncode == 0
    assert "hidden" in r.stdout
