"""Diagnose MCP server registration inside codex app-server (no LLM turn)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from openai_codex import CodexConfig
from openai_codex.client import CodexClient
from crystalpilot.workbench.core import _gateway_env

PY = str(REPO / ".venv" / "Scripts" / "python.exe")
ECHO = str(REPO / "scripts" / "echo_mcp_server.py")
PROJ = REPO / "workdir" / "mcp-probe"


def main() -> int:
    overrides = (
        f"mcp_servers.cp_echo.command='{PY}'",
        f"mcp_servers.cp_echo.args=['-X','utf8','{ECHO}']",
        "mcp_servers.cp_echo.startup_timeout_sec=60",
    )
    client = CodexClient(config=CodexConfig(env=_gateway_env(), cwd=str(PROJ),
                                            config_overrides=overrides))
    client.start()
    init = client.initialize()
    print("initialized:", type(init).__name__)
    for attempt in range(3):
        try:
            raw = client._request_raw("mcpServerStatus/list", {"detail": "full"})
            print(f"attempt {attempt}: ", json.dumps(raw, ensure_ascii=False, default=str)[:2000])
            if raw and raw.get("data"):
                break
        except Exception as e:  # noqa: BLE001
            print(f"attempt {attempt}: {type(e).__name__}: {e}")
        time.sleep(3.0)
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
