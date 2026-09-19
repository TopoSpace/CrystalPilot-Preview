"""Codex probes an MCP server for resources, resource templates and prompts
before/while using its tools. Every probe must get an empty list, never
-32601 "Method not found": on 2026-09-05 (resumed thread after a server
restart) the resources/templates/list probe failed that way and the agent
concluded the crystallography tools were gone. Drives the REAL stdio
server on a synthetic project."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

CELL = (7.1, 8.3, 9.7, 90.0, 95.0, 90.0)
ATOMS = [("O1", "O", (0.10, 0.20, 0.30)), ("N1", "N", (0.40, 0.15, 0.55)),
         ("C1", "C", (0.25, 0.45, 0.60))]


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    from test_probe_site import make_project
    return make_project(tmp_path_factory.mktemp("mcpprobe"), CELL, "P 1 21/c 1",
                        ATOMS, ATOMS, 4, d_min=0.9)


class Stdio:
    def __init__(self, project_dir: Path):
        self.p = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-m", "crystalpilot.mcp", "--project", str(project_dir)],
            cwd=str(REPO), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env={**os.environ, "CRYSTALPILOT_CPU_CORES": "1"})
        self._id = 0

    def send(self, obj):
        self.p.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
        self.p.stdin.flush()

    def call(self, method, params=None, timeout_lines=50):
        self._id += 1
        self.send({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        for _ in range(timeout_lines):
            line = self.p.stdout.readline()
            if not line:
                break
            msg = json.loads(line)
            if msg.get("id") == self._id:
                return msg
        raise AssertionError(f"no response to {method}")

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=20)
        except Exception:  # noqa: BLE001
            self.p.kill()


def test_every_startup_probe_answers_with_an_empty_list(project):
    s = Stdio(project)
    try:
        init = s.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                     "clientInfo": {"name": "probe", "version": "0"}})
        assert "result" in init, init
        s.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = s.call("tools/list")
        names = [t["name"] for t in tools["result"]["tools"]]
        assert len(names) > 50 and "crystalpilot_error" not in names, names[:5]
        for method, key in (("resources/list", "resources"),
                            ("resources/templates/list", "resourceTemplates"),
                            ("prompts/list", "prompts")):
            r = s.call(method)
            assert "error" not in r, f"{method}: {r}"
            assert r["result"][key] == [], f"{method}: {r}"
    finally:
        s.close()
