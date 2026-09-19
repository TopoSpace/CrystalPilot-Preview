"""Platform-specific paths shared by the workbench and setup tools."""
from __future__ import annotations

import os
from pathlib import Path


def engine_python(root: Path) -> Path:
    """Use this checkout's virtualenv for MCP, provider auth and agent roles."""
    return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
