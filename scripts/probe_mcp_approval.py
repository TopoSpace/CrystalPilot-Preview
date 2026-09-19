"""M0 probe: verify Codex app-server <-> stdio MCP server integration end to end.

Round A (approval_mode=auto): tools visible? tools/call round trip? which
notification methods carry mcpToolCall items?
Round B (approval_mode=prompt): what server-request METHOD does an MCP tool
approval use, what params does it carry, and does {"decision": "accept"}
unblock it?

Findings are written to workbench/MCP_NOTES.md. No secrets are read; the model
provider auth stays behind print_token.py inside the isolated CODEX_HOME.

Usage: .venv\\Scripts\\python.exe -X utf8 scripts\\probe_mcp_approval.py [--round A|B|AB]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from openai_codex import CodexConfig                      # noqa: E402
from openai_codex.api import Thread                       # noqa: E402
from openai_codex.client import CodexClient               # noqa: E402
from openai_codex.generated.v2_all import (               # noqa: E402
    AskForApproval, AskForApprovalValue, SandboxMode, ThreadStartParams)

from crystalpilot.workbench.core import _gateway_env      # noqa: E402

PY = str(REPO / ".venv" / "Scripts" / "python.exe")
ECHO = str(REPO / "scripts" / "echo_mcp_server.py")
PROJ = REPO / "workdir" / "mcp-probe"
NOTES = REPO / "workbench" / "MCP_NOTES.md"


def toml_lit(s: str) -> str:
    """TOML literal string (single quotes, no escaping; backslash-safe)."""
    assert "'" not in s, s
    return f"'{s}'"


def overrides(approval_mode: str) -> tuple[str, ...]:
    return (
        f"mcp_servers.cp_echo.command={toml_lit(PY)}",
        f"mcp_servers.cp_echo.args=['-X','utf8',{toml_lit(ECHO)}]",
        "mcp_servers.cp_echo.env={PYTHONUTF8='1'}",
        "mcp_servers.cp_echo.startup_timeout_sec=60",
        f"mcp_servers.cp_echo.approval_mode={toml_lit(approval_mode)}",
        # trust the probe project without appending to codex-home/config.toml
        f"projects.{toml_lit(str(PROJ).lower())}.trust_level='trusted'",
    )


def run_round(approval_mode: str, prompt: str, max_wait_s: float = 600.0) -> dict:
    PROJ.mkdir(parents=True, exist_ok=True)
    (PROJ / "AGENTS.md").write_text(
        "# Probe project\nThis is a protocol probe. Follow the user's "
        "instructions literally. Never run shell commands.\n", encoding="utf-8")

    events: list[dict] = []
    approvals: list[dict] = []

    def on_approval(method: str, params: dict | None) -> dict:
        rec = {"method": method, "params_keys": sorted((params or {}).keys()),
               "params": params}
        approvals.append(rec)
        print(f"  [approval] method={method} keys={rec['params_keys']}", flush=True)
        if "elicitation" in method:
            # MCP elicitation protocol result (codex wraps MCP tool approvals in it)
            return {"action": "accept", "content": {}}
        return {"decision": "accept"}

    client = CodexClient(
        config=CodexConfig(env=_gateway_env(), cwd=str(PROJ),
                           config_overrides=overrides(approval_mode)),
        approval_handler=on_approval)
    client.start()
    client.initialize()
    result: dict = {"approval_mode": approval_mode, "ok": False,
                    "methods": [], "approvals": approvals, "final_text": "",
                    "mcp_items": [], "error": None}
    try:
        params = ThreadStartParams(
            approval_policy=AskForApproval(root=AskForApprovalValue.on_request),
            approvals_reviewer=None,
            cwd=str(PROJ),
            sandbox=SandboxMode.workspace_write,
            developer_instructions="Protocol probe. Use MCP tools when asked.")
        started = client.thread_start(params)
        thread = Thread(client, started.thread.id)
        t0 = time.time()
        handle = thread.turn(prompt)
        stream = handle.stream()
        try:
            for note in stream:
                if time.time() - t0 > max_wait_s:
                    result["error"] = "timeout"
                    handle.interrupt()
                    break
                m = note.method
                if m not in result["methods"]:
                    result["methods"].append(m)
                payload = note.payload
                item = getattr(payload, "item", None)
                if item is not None and hasattr(item, "root"):
                    item = item.root
                itype = getattr(item, "type", None)
                if itype == "mcpToolCall" or "mcpToolCall" in m:
                    dump = item.model_dump() if hasattr(item, "model_dump") else str(item)
                    result["mcp_items"].append({"method": m, "item": dump})
                    print(f"  [mcp] {m}: {json.dumps(dump, ensure_ascii=False, default=str)[:400]}",
                          flush=True)
                if itype == "agentMessage" and m == "item/completed":
                    result["final_text"] = getattr(item, "text", "")
                if m in ("turn/completed", "turn/failed"):
                    if m == "turn/failed":
                        err = getattr(payload, "error", None)
                        result["error"] = (err.model_dump() if hasattr(err, "model_dump")
                                           else str(err))
                    break
        finally:
            stream.close()
        result["ok"] = result["error"] is None and "PING" in (result["final_text"] or "")
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
    finally:
        client.close()
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default="AB", choices=["A", "B", "AB"])
    args = ap.parse_args()

    out: dict[str, dict] = {}
    if "A" in args.round:
        print("== Round A: approval_mode=auto ==", flush=True)
        out["A"] = run_round(
            "auto",
            "请调用 MCP 工具 cp_echo，参数 message 设为 'PING-AUTO-42'，"
            "然后把工具返回的 JSON 原样写在回复里。不要运行任何 shell 命令。")
        print(json.dumps({k: v for k, v in out["A"].items() if k != "mcp_items"},
                         ensure_ascii=False, indent=2, default=str), flush=True)
    if "B" in args.round:
        print("== Round B: approval_mode=prompt ==", flush=True)
        out["B"] = run_round(
            "prompt",
            "请调用 MCP 工具 cp_echo_write，参数 message 设为 'PING-PROMPT-77'，"
            "然后把工具返回的 JSON 原样写在回复里。不要运行任何 shell 命令。")
        print(json.dumps({k: v for k, v in out["B"].items() if k != "mcp_items"},
                         ensure_ascii=False, indent=2, default=str), flush=True)

    lines = ["# MCP integration probe notes (M0)", "",
             f"probed: {time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"codex config injection: CodexConfig.config_overrides (no config.toml edits)", ""]
    for rnd, res in out.items():
        lines += [f"## Round {rnd} (approval_mode={res['approval_mode']})",
                  f"- ok: {res['ok']}",
                  f"- error: {res['error']}",
                  f"- notification methods seen: {', '.join(res['methods'])}",
                  f"- approval requests: " + (json.dumps(
                      [{'method': a['method'], 'params_keys': a['params_keys']}
                       for a in res['approvals']], ensure_ascii=False) or "[]"),
                  f"- final_text: {res['final_text'][:500]}", ""]
        for it in res["mcp_items"][:6]:
            lines.append(f"- mcp item via `{it['method']}`:")
            lines.append("  ```json")
            lines.append("  " + json.dumps(it["item"], ensure_ascii=False,
                                           default=str)[:1200])
            lines.append("  ```")
        if res["approvals"]:
            lines.append("- first approval raw params:")
            lines.append("  ```json")
            lines.append("  " + json.dumps(res["approvals"][0]["params"],
                                           ensure_ascii=False, default=str)[:2000])
            lines.append("  ```")
        lines.append("")
    NOTES.write_text("\n".join(lines), encoding="utf-8")
    print(f"notes -> {NOTES}", flush=True)
    ok = all(r["ok"] for r in out.values()) if out else False
    print("PROBE", "OK" if ok else "PARTIAL/FAILED", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
