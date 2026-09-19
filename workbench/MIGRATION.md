# CrystalPilot → Codex-style Workbench: phased migration plan

Target architecture (per ADR-001):

```
React scientific UI  (chat · activity timeline · 3D viewer · metrics · artifacts)
        │  SSE/WebSocket + REST
CrystalPilot Server (FastAPI)
        │  openai-codex SDK (typed JSON-RPC)
codex app-server  (bundled binary, isolated CODEX_HOME, custom provider+auth cmd)
        │  shell / approvals / sandbox                │ MCP (later)
project folder  ←→  AGENTS.md + CrystalPilot Results/  crystallography MCP tools
        │
crystalpilot engine (cctbx/smtbx pipeline · DIALS · benchmark)  ← unchanged
```

## Phase 0 — done in this round (prototype, `workbench/`)
Harness validation: isolated CODEX_HOME, custom gateway + xhigh, threads/resume,
approvals, streaming, results convention, real NL crystallography demo, debug web
UI, credential hardening, regression green.

## Phase 1 — product server merge (DONE 2026-08-28)
- Move `crystalpilot_workbench` into the main package (`crystalpilot/workbench/`),
  pin `openai-codex` in `pyproject.toml` (separate optional extra to keep the
  engine installable without it).
- Extend the main FastAPI server: `/api/projects` (open/create/recent),
  `/api/threads` (list/new/resume/fork/archive per project), `/api/threads/{id}/send`,
  `/api/threads/{id}/interrupt`, SSE per thread, `/api/approvals`.
  One app-server process per open project; process pool with idle shutdown.
- Persist the project registry + thread metadata in the project folder (as now).
- Keep `/api/solve` (legacy one-shot) working during transition.

## Phase 2 — React UI rebuild into a workbench (1-2 rounds)
- Left: project/thread sidebar (recent tasks, resume). Center: conversation with
  streamed replies + reasoning summaries + inline approval cards. Right: tabbed
  activity timeline / artifacts (auto-refresh from `CrystalPilot Results/`) /
  3D viewer (reuse the existing 3Dmol component, auto-load newest CIF) /
  metrics panel (parse newest report.json: R1/wR2/GooF/confidence/alerts).
- Modes map to approval policy: Auto = auto-approve allowlisted commands
  (engine CLI, read-only) + gate the rest; Copilot = gate all writes/commands;
  Expert = raw event log + config access.
- Drop-data flow: dropping files into the chat copies them into the project and
  pre-fills a task prompt (the round-1 dropzone UX survives as a shortcut).

## Phase 3 — crystallography MCP server (DONE 2026-08-28, round 3)
- Done, and it became the product center: `crystalpilot/mcp` bridges the
  ToolRegistry to Codex over stdio MCP (injected per-project via
  `CodexConfig.config_overrides`, no config.toml edits). ~20 typed
  **refinement** tools (`crystalpilot/refine`): inspect/map/ligand tools,
  model edits with density honesty gates, restraints, smtbx⇄SHELXL dual
  engines, NodeStore branches, PLATON checkCIF, write_outputs.
- Per-tool `readOnlyHint` annotations drive `approval_mode="writes"` =
  Copilot mode (approval cards in /wb). Protocol facts probed in MCP_NOTES.md
  (mcp SDK pinned `>=1.2,<2`; elicitation accept shape
  `{"action":"accept","content":{}}`).
- MVP acceptance passed at publication grade (corrupted SJTU-9 repaired blind:
  agent R1 0.0615 vs human 0.0617, 3/3 defects, honest unresolved list) — see
  ARCHITECTURE.md and `benchmark/`. CLI kept as fallback.

## Phase 4 — hardening & polish
- Enable the native Windows sandbox (`[windows] sandbox = "unelevated"`) and
  writable-roots config; re-test approval load.
- BYOK settings UI writing the isolated config.toml (never `~/.codex`).
- Thread compaction defaults for long crystallography sessions; artifact-aware
  context (feed report.json summaries, not raw files).
- Retire the round-1 inner agent from the product path (keep for benchmark A/B).
- Benchmark the workbench itself: agent-driven solve rate on the 33-case set vs
  round-1 numbers (same honesty rules).

## Rollback story
Each phase is additive; the deterministic pipeline, benchmark, legacy server and
UI remain runnable throughout. If upstream breaks us, pin the previous
`openai-codex` version — the adapter surface is ~6 calls + event names.
