"""Copilot-mode demo: MCP approval_mode='writes' puts every mutating tool
behind an approval gate; this script records the approval cards (what a human
would see in /wb) and approves them, on a throwaway copy of the MVP project.

Evidence lands in workdir/copilot_demo/ (transcript + approval cards).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

os.environ["CRYSTALPILOT_MCP_APPROVAL"] = "writes"     # the Copilot switch

from crystalpilot.workbench.core import Workbench      # noqa: E402

SRC = REPO / "workbench" / "mvp-sjtu9"
PROJ = REPO / "workbench" / "copilot-demo"
OUT = REPO / "workdir" / "copilot_demo"

PROMPT = (
    "Copilot 演示：请用 crystalpilot 工具做两件小事，"
    "1) inspect_model 看一眼当前模型；"
    "2) 用 edit_atoms 把 O007 的 U_iso 设为 0.08，然后 refine 一轮"
    "（mode=anisotropic, n_cycles=2）。做完简单汇报即可。")


def main() -> int:
    shutil.rmtree(PROJ, ignore_errors=True)
    shutil.copytree(SRC, PROJ,
                    ignore=shutil.ignore_patterns("CrystalPilot Results",
                                                  ".crystalpilot-workbench.json",
                                                  "AGENTS.md"))
    OUT.mkdir(parents=True, exist_ok=True)
    cards = []

    def on_approval(req):
        card = {"approval_id": req["approval_id"], "method": req["method"],
                "mcp_server": req.get("mcp_server"),
                "message": req.get("mcp_message"),
                "tool_params": req.get("mcp_tool_params"),
                "decision": "accept"}
        cards.append(card)
        print(f"  [APPROVAL CARD] {card['message']} | params="
              f"{json.dumps(card['tool_params'], ensure_ascii=False)}", flush=True)
        return {"decision": "accept"}

    events = []
    with Workbench(PROJ, approval_cb=on_approval) as wb:
        task = wb.new_task(title="Copilot 审批演示")
        final = ""
        for ev in task.send(PROMPT):
            events.append(ev)
            if ev["kind"] == "tool_completed":
                print(f"  [tool] {ev.get('tool')} ok={ev.get('ok')}", flush=True)
            if ev["kind"] == "agent_message":
                final = ev["text"]
        transcript = task.results_dir / "transcript.jsonl"
    (OUT / "approval_cards.json").write_text(
        json.dumps(cards, indent=2, ensure_ascii=False), encoding="utf-8")
    if transcript.exists():
        shutil.copy(transcript, OUT / "transcript.jsonl")
    (OUT / "final_message.md").write_text(final, encoding="utf-8")
    n_gated = len(cards)
    tools = [e.get("tool") for e in events if e.get("kind") == "tool_completed"]
    print(f"\n=== approval cards: {n_gated}; tools: {tools}")
    print(f"=== evidence -> {OUT}")
    ok = n_gated >= 1 and any(c.get("mcp_server") == "crystalpilot" for c in cards)
    print("COPILOT DEMO", "OK" if ok else "CHECK", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
