# Workbench prototype archive (round 2, Phase 0)

The Codex-harness prototype that used to live here was **merged into the main
package in Phase 1**. Current locations:

| was (prototype) | now (product) |
|---|---|
| `workbench/crystalpilot_workbench/` | `crystalpilot/workbench/` (core, service, routes, cli, agents_md, print_token) |
| `workbench/codex-home/` | `codex-home/` at the repo root (isolated CODEX_HOME) |
| `workbench/.venv` (own SDK install) | main `.venv` via the `workbench` extra (`pip install -e .[workbench]`, pinned `openai-codex==0.147.0`) |
| debug web UI on port 8100 | served by the main server: `http://localhost:8000/wb` |
| `workbench/smoke_test.py` | `scripts/workbench_smoke.py` |

Still here, still current:

- `ADR-001-codex-harness.md` — the harness decision record (accepted).
- `MIGRATION.md` — the phased plan (Phase 1 done; see per-phase status inside).
- `demo-project/`, `demo-mof/` — validation projects. The evidence from the
  round-2 natural-language MOF solve demo is in
  `demo-mof/CrystalPilot Results/task_20260827_234012/` (final.cif, report.html,
  agent-written Chinese SUMMARY.md, redacted transcript.jsonl).

## Reproduce (Phase 1 layout)

```bash
# harness smoke test (isolated CODEX_HOME + gateway + thread resume)
H:/CrystalPilot/.venv/Scripts/python.exe -X utf8 scripts/workbench_smoke.py

# CLI chat over a project folder
H:/CrystalPilot/.venv/Scripts/python.exe -X utf8 -m crystalpilot.workbench.cli chat workbench/demo-mof --yes

# full server (legacy /api/solve + workbench APIs + /wb debug UI)
H:/CrystalPilot/.venv/Scripts/python.exe -X utf8 -m uvicorn server.app:app --port 8000
```

Credentials: fetched on demand by `crystalpilot/workbench/print_token.py`
(provider `auth.command`); never stored in env vars, config or logs.
