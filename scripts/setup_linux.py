"""Migrate the checked-in Windows workbench config to this Linux checkout.

Run with .venv/bin/python scripts/setup_linux.py after dependency installation.
Existing provider choices and keys are preserved. No personal config is read.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    if os.name != "posix":
        raise SystemExit("This setup command is for Linux/POSIX hosts.")
    from crystalpilot.workbench.core import CODEX_HOME
    from crystalpilot.workbench.model_catalog import ensure_catalog

    path = CODEX_HOME / "config.toml"
    text = path.read_text(encoding="utf-8")
    original = text
    # Drop historical Windows trust entries, retain any new local projects.
    text = re.sub(r"(?ms)^\[projects\.'[A-Za-z]:\\[^']*'\]\n.*?(?=^\[|\Z)", "", text)
    text = text.replace(r"H:\CrystalPilot\.venv\Scripts\python.exe",
                        str(ROOT / ".venv/bin/python"))
    text = re.sub(r"H:\\CrystalPilot\\([^'\n]*)",
                  lambda match: str(ROOT / match[1].replace("\\", "/")), text)
    tomllib.loads(text)
    if text != original:
        backup = ROOT / "workdir" / "config.before-linux.toml"
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(text, encoding="utf-8")
        path.chmod(0o600)
    (ROOT / "secrets").mkdir(mode=0o700, exist_ok=True)
    (ROOT.parent / "projects").mkdir(exist_ok=True)
    result = ensure_catalog()
    print(f"Isolated workbench config: {path}")
    print(f"Model catalog: {result}")
    print(f"User projects: {ROOT.parent / 'projects'}")
    print("Provider credentials are entered in the workbench Settings dialog.")


if __name__ == "__main__":
    main()
