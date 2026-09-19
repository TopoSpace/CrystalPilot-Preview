"""Checklist item: readonly permission mode server-side hard gate.
Spawns the MCP server with CRYSTALPILOT_MCP_READONLY=1 against a real project
and calls (a) a read tool -> works, (b) a mutating tool -> typed refusal."""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROJECT = REPO / "workbench" / "demo-live-sjtu9"

env = dict(os.environ)
env["PYTHONUTF8"] = "1"
env["CRYSTALPILOT_MCP_READONLY"] = "1"

proc = subprocess.Popen(
    [sys.executable, "-X", "utf8", "-m", "crystalpilot.mcp",
     "--project", str(PROJECT)],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=str(REPO), env=env)


def rpc(id_, method, params):
    msg = {"jsonrpc": "2.0", "id": id_, "method": method, "params": params}
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()


def notify(method, params=None):
    msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()


def read_until(id_):
    while True:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("server died")
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("id") == id_:
            return d


rpc(1, "initialize", {"protocolVersion": "2024-11-05",
                      "capabilities": {},
                      "clientInfo": {"name": "gate-test", "version": "0"}})
read_until(1)
notify("notifications/initialized")

rpc(2, "tools/call", {"name": "list_nodes", "arguments": {}})
r2 = read_until(2)
txt2 = r2["result"]["content"][0]["text"]
ok_read = '"ok": true' in txt2 or '"ok":true' in txt2

rpc(3, "tools/call", {"name": "edit_atoms",
                      "arguments": {"operations": [
                          {"action": "reassign", "atoms": ["ZR02"],
                           "element": "Fe"}]}})
r3 = read_until(3)
txt3 = r3["result"]["content"][0]["text"]
refused = "readonly" in txt3.lower() or "只读" in txt3

print("READ list_nodes ok:", ok_read)
print("MUTATE edit_atoms refused:", refused)
print("refusal payload:", txt3[:260])
proc.kill()
sys.exit(0 if (ok_read and refused) else 1)
