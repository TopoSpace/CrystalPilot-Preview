"""Auto-mode shell approval blocklist (internalized approval daemon, r9).

The verdict function must accept ordinary workspace/data-reading shell calls
(unattended E2Es raise one approval per command on Windows) while queuing
anything that touches protected areas for a human.
"""
from __future__ import annotations

from crystalpilot.workbench.service import (SHELL_APPROVAL_BLOCKLIST,
                                            shell_approval_verdict)

BS = chr(92)


def _cmd(command: str) -> dict:
    return {"method": "item/commandExecution/requestApproval",
            "detail": {"command": command}}


def _file(path: str) -> dict:
    return {"method": "item/fileChange/requestApproval",
            "detail": {"changes": [{"path": path}]}}


def test_ordinary_commands_accepted():
    assert shell_approval_verdict(
        _cmd(f"powershell Get-ChildItem H:{BS}CrystalPilotData{BS}mof")) == "accept"
    assert shell_approval_verdict(
        _cmd("& dials.scale.exe scaled.refl scaled.expt d_min=1.4")) == "accept"
    # r8 false-positive regression: PowerShell Format-Table is not `format c:`
    assert shell_approval_verdict(
        _cmd("powershell $x | Format-Table -AutoSize")) == "accept"


def test_protected_areas_queued():
    assert shell_approval_verdict(
        _cmd(f"powershell Get-Content E:{BS}data{BS}x.txt")) == "ask"
    assert shell_approval_verdict(_cmd("cmd /c type testAPI.txt")) == "ask"
    assert shell_approval_verdict(
        _file(f"H:{BS}CrystalPilot{BS}codex-home{BS}config.toml")) == "ask"


def test_process_kills_and_system_commands_queued():
    assert shell_approval_verdict(_cmd("taskkill /F /IM python.exe")) == "ask"
    assert shell_approval_verdict(_cmd("Stop-Process -Name codex")) == "ask"
    assert shell_approval_verdict(_cmd("format d: /q")) == "ask"
    assert shell_approval_verdict(_cmd("git push origin main")) == "ask"


def test_dataset_writes_queued_but_reads_ok():
    assert shell_approval_verdict(
        _cmd(f"Remove-Item H:{BS}CrystalPilotData{BS}mof{BS}a.cbf")) == "ask"
    assert shell_approval_verdict(
        _cmd(f"Get-Content H:{BS}CrystalPilotData{BS}mof{BS}MANIFEST.md")) == "accept"


def test_non_shell_methods_always_ask():
    assert shell_approval_verdict(
        {"method": "session/elicitation", "detail": {}}) == "ask"
    assert shell_approval_verdict({"method": None, "detail": {}}) == "ask"


def test_blocklist_regexes_compile():
    import re
    for pat in SHELL_APPROVAL_BLOCKLIST:
        re.compile(pat)


def test_auto_mode_rejects_protected_areas_at_once():
    """Unattended auto mode answers a blocklist hit with a rejection now
    (the model reroutes) instead of queueing it for a human: on the R7 A2
    continuation (2026-09-06 16:33) `New-Item .codex\\tmp` sat in the
    queue for 10 minutes."""
    import threading
    from types import SimpleNamespace
    from crystalpilot.workbench import service
    pushed: list = []
    stub = SimpleNamespace(
        permission_mode="auto", auto_approve=False,
        wb=SimpleNamespace(project=SimpleNamespace(settings={})),
        _push=lambda tid, ev: pushed.append(ev), _session_allow=set(),
        _allow_key=service.ProjectSession._allow_key, _lock=threading.Lock(),
        _pending={})
    req = _cmd('powershell -Command "New-Item -ItemType Directory .codex\\tmp"')
    req["approval_id"] = "x1"
    req["thread_id"] = "t"
    out = service.ProjectSession._on_approval(stub, req)
    assert out == {"decision": "reject"}
    assert pushed and pushed[-1]["policy"] == "shell_blocklist_reject"
    assert pushed[-1]["blocked_by"] and ".codex" in pushed[-1]["blocked_by"]
    # an ordinary command is still accepted by the blocklist policy
    ok = _cmd("python -c print(1)")
    ok["approval_id"] = "x2"
    assert service.ProjectSession._on_approval(stub, ok) == {"decision": "accept"}
    assert pushed[-1]["policy"] == "shell_blocklist"
    # copilot mode keeps queueing (not exercised here: it would block)


def test_secrets_directory_queued_even_for_reads():
    # 2026-09-16 review: only testAPI.txt was named; secrets/ holds the rest
    assert shell_approval_verdict(_cmd("type secrets/openrouter.txt")) == "ask"
    assert shell_approval_verdict(
        _cmd(f"Get-Content H:{BS}CrystalPilot{BS}secrets{BS}openrouter.txt")) == "ask"
    assert shell_approval_verdict(_file(f"H:{BS}CrystalPilot{BS}secrets{BS}new.txt")) == "ask"


def test_source_checkout_mutations_queued_but_reads_and_projects_ok():
    from crystalpilot.workbench import service
    root = str(service._REPO_ROOT)
    # mutating the checkout unattended: ask
    assert shell_approval_verdict(_cmd(f"Remove-Item {root}{BS}crystalpilot{BS}refine{BS}x.py")) == "ask"
    assert shell_approval_verdict(_cmd(f"git -C {root} checkout -- ui")) == "ask"
    assert shell_approval_verdict(_cmd(f"echo x > {root.lower()}/server/app.py")) == "ask"
    assert shell_approval_verdict(_cmd(f"cp a.py {root.replace(BS, '/')}/scripts/")) == "ask"
    # reading it is fine
    assert shell_approval_verdict(_cmd(f"Get-Content {root}{BS}README.md")) == "accept"
    # sibling directories (where projects live) are not the checkout
    assert shell_approval_verdict(_cmd(f"Remove-Item {root}-campaigns{BS}usertest{BS}p{BS}tmp.txt")) == "accept"
    assert shell_approval_verdict(_cmd(f"Move-Item {root}-campaigns{BS}p{BS}a.hkl b.hkl")) == "accept"
    # (writes under CrystalPilotData stay queued by the older dataset rule)
    assert shell_approval_verdict(_cmd(f"Move-Item {root}Data{BS}mof{BS}a.hkl b.hkl")) == "ask"
