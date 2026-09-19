"""Probe a codex binary the way CrystalPilot drives it (the pinned pip SDK
openai-codex + the workbench's own env and config overrides) against an
ISOLATED copy of codex-home, so the live server and its databases are never
touched. Run this before switching vendor/codex to a new release.

    set CRYSTALPILOT_CODEX_HOME=<copy of codex-home outside the repo>
    set CRYSTALPILOT_CODEX_BIN=<new codex.exe>
    .venv/Scripts/python -X utf8 scripts/probe_codex_kernel.py <new codex.exe> [--turn] [--project DIR]

Checks: initialize, model/list (custom catalog included), provider
capabilities, config/read, skills/list, mcpServerStatus/list (the
CrystalPilot MCP server starts), thread/list; with --turn one cheap real turn
on OpenRouter (glm-5.3-flash), a second turn on the same thread and
thread/compact/start. Afterwards compare the copy's state_5.sqlite
`_sqlx_migrations` count with the live one and check that the OLD binary
still opens the migrated copy (rollback safety); see
scripts/diff_codex_schema.py for the protocol diff.

Never prints secrets: the provider's auth command hands the token to codex.
Refuses to run when CRYSTALPILOT_CODEX_HOME is the repo's own codex-home.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONUTF8", "1")

_home = os.environ.get("CRYSTALPILOT_CODEX_HOME")
if not _home or Path(_home).resolve() == (ROOT / "codex-home").resolve():
    sys.exit("refusing: CRYSTALPILOT_CODEX_HOME must point at a COPY of codex-home, not the live one")

from openai_codex import CodexConfig  # noqa: E402
from openai_codex.client import CodexClient  # noqa: E402
from openai_codex.generated.v2_all import (AskForApproval,  # noqa: E402
                                           AskForApprovalValue, SandboxMode,
                                           ThreadStartParams)
from crystalpilot.workbench.core import CODEX_HOME, _gateway_env, _mcp_overrides  # noqa: E402

exe = Path(sys.argv[1])
args = sys.argv[2:]
project = Path(args[args.index("--project") + 1]) if "--project" in args else Path(_home) / "probe-project"
project.mkdir(parents=True, exist_ok=True)
print("CODEX_HOME:", CODEX_HOME, "| exe:", exe, "| project:", project)

env = _gateway_env()
print("env keys:", sorted(env))
client = CodexClient(config=CodexConfig(codex_bin=str(exe), env=env, cwd=str(project),
                                        config_overrides=_mcp_overrides(project, approval="auto")),
                     approval_handler=lambda m, p: {"decision": "accept"})
t0 = time.time()
client.start()
init = client.initialize().model_dump()
print("initialize ok in %.1fs: userAgent=%s" % (time.time() - t0, init.get("user_agent") or init.get("userAgent")))

res = client._request_raw("model/list", {"includeHidden": True})
models = res.get("data") or []
print("model/list:", len(models), "models")
for m in models:
    effs = [e.get("reasoningEffort") for e in m.get("supportedReasoningEfforts") or []]
    print("  ", m.get("id"), "| default", m.get("defaultReasoningEffort"), "| efforts", effs,
          "| modalities", m.get("inputModalities"), "| hidden", m.get("hidden"), "| isDefault", m.get("isDefault"))

for method, params in (("modelProvider/capabilities/read", {}), ("config/read", {"cwd": str(project)}),
                       ("skills/list", {"cwds": [str(project)]}), ("mcpServerStatus/list", {}),
                       ("thread/list", {"limit": 3})):
    try:
        r = client._request_raw(method, params)
        if method == "config/read":
            c = r.get("config") or {}
            print(method, {k: c.get(k) for k in ("model", "model_provider", "model_reasoning_effort",
                                                 "approval_policy", "sandbox_mode", "model_context_window")},
                  "| keys:", len(c))
        elif method == "mcpServerStatus/list":
            servers = r.get("data") or []
            print(method, [(s.get("name"), len(s.get("tools") or {})) for s in servers])
        elif method == "thread/list":
            print(method, "n=", len(r.get("data") or []))
        else:
            print(method, json.dumps(r, default=str)[:300])
    except Exception as e:  # noqa: BLE001
        print(method, "FAILED:", e)

if "--turn" in args:
    started = client.thread_start(ThreadStartParams(
        approval_policy=AskForApproval(root=AskForApprovalValue.on_request),
        cwd=str(project), sandbox=SandboxMode.workspace_write,
        developer_instructions="Probe. Answer in one word.", model_provider="openrouter"))
    tid = started.thread.id
    print(f"thread {tid} started provider={started.thread.model_provider}")
    from openai_codex.api import Thread
    from openai_codex.types import ReasoningEffort
    th = Thread(client, tid)
    t1 = time.time()
    kinds: list[str] = []
    for note in th.turn("Reply with exactly the word OK and nothing else. Do not call any tool.",
                        model="z-ai/glm-5.3-flash", effort=ReasoningEffort("low")).stream():
        kinds.append(note.method)
        if note.method == "item/completed":
            item = note.payload.item
            d = item.model_dump() if hasattr(item, "model_dump") else item
            if isinstance(d, dict):
                print("   item:", d.get("type"), "id=", d.get("id"), str(d.get("text", ""))[:80])
        if note.method == "turn/completed":
            print("   turn status:", note.payload.turn.status, "error:", note.payload.turn.error,
                  "in %.1fs" % (time.time() - t1))
    print("   methods:", sorted(set(kinds)))
    for note in th.turn("Reply with exactly the word DONE.", model="z-ai/glm-5.3-flash",
                        effort=ReasoningEffort("low")).stream():
        if note.method == "turn/completed":
            print("   turn 2 status:", note.payload.turn.status)
    try:
        client._request_raw("thread/compact/start", {"threadId": tid})
        print("   thread/compact/start accepted")
    except Exception as e:  # noqa: BLE001
        print("   thread/compact/start FAILED:", e)
    time.sleep(3)
client.close()
print("done")
