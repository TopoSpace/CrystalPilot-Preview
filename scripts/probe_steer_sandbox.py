"""M0 probe: (1) TurnHandle.steer mid-turn, (2) per-turn sandbox=read_only.

Throwaway project, MCP disabled for fast startup. Evidence printed to stdout.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["CRYSTALPILOT_DISABLE_MCP"] = "1"

from crystalpilot.workbench.core import Workbench  # noqa: E402

PROJ = REPO / "workbench" / "probe-steer"


def main() -> int:
    PROJ.mkdir(parents=True, exist_ok=True)
    with Workbench(PROJ) as wb:
        # ---- probe 1: steer mid-turn ------------------------------------
        task = wb.new_task(title="steer probe")
        events = []
        steer_result = {}

        def run():
            for ev in task.send(
                    "请用 PowerShell 依次创建 5 个文件 f1.txt..f5.txt，"
                    "每创建一个之间 Start-Sleep 3 秒。全部做完后汇报。"):
                events.append(ev)
                print(f"  [{ev['kind']}] {str(ev.get('command') or ev.get('text') or '')[:90]}",
                      flush=True)

        t = threading.Thread(target=run)
        t.start()
        # wait until first command starts, then steer
        deadline = time.time() + 120
        while time.time() < deadline:
            if any(e["kind"] == "command_started" for e in events):
                break
            time.sleep(0.5)
        time.sleep(2)
        try:
            h = task._active_turn
            if h is None:
                steer_result["error"] = "no active turn to steer"
            else:
                resp = h.steer("插话：请立刻停止创建更多文件，改为汇报目前已创建了哪些文件，然后结束。")
                steer_result["response"] = repr(resp)[:200]
                print(f"  [STEER SENT] {steer_result['response']}", flush=True)
        except Exception as e:  # noqa: BLE001
            steer_result["error"] = f"{type(e).__name__}: {e}"
            print(f"  [STEER FAILED] {steer_result['error']}", flush=True)
        t.join(timeout=240)
        finals = [e for e in events if e["kind"] == "agent_message"]
        made = sorted(p.name for p in PROJ.glob("f*.txt"))
        print(f"== steer probe: files created={made}; final={((finals or [{}])[-1].get('text') or '')[:300]}")

        # ---- probe 2: per-turn sandbox=read_only ------------------------
        from openai_codex import Sandbox  # public enum
        task2 = wb.new_task(title="readonly probe")
        ev2 = []
        approvals = []

        def on_approval(req):
            approvals.append(req)
            print(f"  [APPROVAL in RO turn] {str(req)[:160]}", flush=True)
            return {"decision": "reject"}

        wb.approval_cb = on_approval
        handle = task2._thread.turn(
            "请创建文件 readonly_test.txt 内容为 hello。如果系统不允许写入，"
            "请如实说明你遇到的限制。", sandbox=Sandbox.read_only)
        task2._active_turn = handle
        stream = handle.stream()
        from crystalpilot.workbench.core import normalize_notification
        for note in stream:
            ev = normalize_notification(note.method, note.payload)
            if ev is None:
                continue
            ev2.append(ev)
            if ev["kind"] in ("command_started", "command_completed", "turn_failed"):
                print(f"  [{ev['kind']}] exit={ev.get('exit_code')} {str(ev.get('command'))[:90]}",
                      flush=True)
            if ev["kind"] == "agent_message":
                print(f"  [agent] {ev['text'][:300]}", flush=True)
            if ev["kind"] in ("turn_completed", "turn_failed"):
                break
        stream.close()
        wrote = (PROJ / "readonly_test.txt").exists()
        print(f"== readonly probe: file_written={wrote}; approvals={len(approvals)}")
        print("PROBE DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
