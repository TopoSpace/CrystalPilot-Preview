"""Soft caller gate on the model-provider auth command: shells (and thus
agent commands) must be refused; only the codex.exe ancestor chain may
read the token. Verified live 2026-08-29: codex chain is
python(real) <- python(venv stub) <- codex.exe, agent chain goes through
bash/cmd - the gate walks past python launcher layers and judges the
first non-python ancestor."""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _run_print_token(tmp_path, cred_text="Key: FAKE_TOKEN_123"):
    cred = tmp_path / "cred.txt"
    cred.write_text(cred_text, encoding="utf-8")
    env = dict(os.environ)
    env["CRYSTALPILOT_CRED_FILE"] = str(cred)
    return subprocess.run(
        [sys.executable,
         str(REPO / "crystalpilot" / "workbench" / "print_token.py")],
        capture_output=True, text=True, env=env, cwd=str(REPO))


class TestCallerGate:
    def test_shell_descendant_refused_and_prints_nothing(self, tmp_path):
        # this test process descends from a shell/IDE, not codex.exe -
        # exactly the replay path an agent command would take
        r = _run_print_token(tmp_path)
        assert r.returncode == 2, (r.returncode, r.stderr)
        assert r.stdout == ""            # token must NOT leak
        assert "refused" in r.stderr

    def test_cred_file_override_is_honored_when_gate_passes(self,
                                                            tmp_path,
                                                            monkeypatch):
        # bypass the gate in-process to test the read path (no subprocess,
        # no real testAPI.txt involved)
        import importlib
        monkeypatch.setenv("CRYSTALPILOT_CRED_FILE",
                           str(tmp_path / "cred.txt"))
        (tmp_path / "cred.txt").write_text("Key：FAKE_XYZ", encoding="utf-8")
        sys.path.insert(0, str(REPO))
        import crystalpilot.workbench.print_token as pt
        importlib.reload(pt)
        monkeypatch.setattr(pt, "_caller_looks_legitimate", lambda: True)
        import io
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buf)
        assert pt.main() == 0
        assert buf.getvalue() == "FAKE_XYZ"

    def test_ui_saved_bare_key_is_parsed_when_gate_passes(self, tmp_path, monkeypatch):
        """The settings writer stores a bare token, not a ``Key:`` note."""
        import io
        import crystalpilot.workbench.print_token as pt

        cred = tmp_path / "managed.txt"
        cred.write_text("DUMMY_UI_SAVED_TOKEN\n", encoding="utf-8")
        monkeypatch.setenv("CRYSTALPILOT_CRED_FILE", str(cred))
        monkeypatch.setattr(pt, "_caller_looks_legitimate", lambda: True)
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", buf)

        assert pt.main(["--cred", str(cred)]) == 0
        assert buf.getvalue() == "DUMMY_UI_SAVED_TOKEN"
