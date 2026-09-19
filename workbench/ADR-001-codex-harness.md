# ADR-001: CrystalPilot Agent Harness — adopt Codex App Server via the official Python SDK

Date: 2026-08-27 · Status: **Accepted** 2026-08-28 (user-confirmed; Phase 1 merge
implemented — adapter now lives in `crystalpilot/workbench/`, isolated
CODEX_HOME at `<repo>/codex-home/`)

## Context

CrystalPilot is repositioning from "one-click solve pipeline with a chat box" to a
Codex-style scientific agent workbench for SCXRD/MOF work: project folders, ongoing
natural-language threads, autonomous file/command/tool use, approvals, streaming UI,
and deliverables in the project directory. Building and maintaining a full agent
harness (context management, shell, sandboxing, approvals, interrupts, resume,
compaction) is a large ongoing cost that is not CrystalPilot's differentiator; the
crystallography engine, domain knowledge, benchmark and scientific UI are.

We audited openai/codex (Apache-2.0, NOTICE present, ~10k commits, official OpenAI
maintenance) and prototyped against **codex-cli 0.147.0** on Windows 11.

## Options considered

### A. Full fork of openai/codex
- ✅ Unlimited customization (could rebrand the TUI, bake in crystallography).
- ❌ codex-rs is a large, fast-moving Rust codebase (~10k commits, frequent releases);
  a fork bifurcates within weeks and we inherit security-sensitive surface
  (sandboxing, shell spawning) without upstream fixes.
- ❌ We would maintain Rust expertise permanently for no scientific gain.
- Verdict: **rejected** — nothing we need is missing upstream (see evidence).

### B. Codex App Server (JSON-RPC over stdio) driven directly
- ✅ Full protocol access (threads, turns, streaming items, approvals, interrupts,
  steer, fork, compact); this is what the official IDE extensions use.
- ❌ We would hand-write the protocol client (schema tracking across versions).
- Verdict: viable, but strictly dominated by C given the official SDK exists.

### C. **Official Python SDK (`openai-codex`) wrapping the App Server** ← chosen
- The SDK (`openai-codex` 0.147.0, PyPI) spawns `codex app-server --listen stdio://`
  from the bundled, versioned binary (`openai-codex-cli-bin`) and exposes typed
  APIs: `thread_start/resume/fork/list/compact`, `turn/steer/interrupt`,
  streamed notifications, approval callbacks, per-thread `cwd`/sandbox/approval
  policy/`developer_instructions`, `config_overrides`, and env injection.
- ✅ Python — same language as the CrystalPilot engine and server.
- ✅ SDK + binary version-locked together; upgrades are `pip install -U`.
- ✅ `CodexConfig(env=...)` lets us point `CODEX_HOME` at a CrystalPilot-owned
  directory → **zero interference with the user's personal Codex install** (hard
  requirement).
- ⚠️ SDK is young (approval high-level modes are limited; we construct
  `ThreadStartParams` directly for on-request + no auto-reviewer). Low risk: the
  generated protocol models expose everything.

### D. Keep the self-built harness (round-1 `crystalpilot/agent`)
- ✅ No new dependency; full control.
- ❌ Would need: durable threads/resume, streaming protocol, shell tool with
  sandboxing/approvals, interrupts, context compaction, project trust — months of
  non-differentiating work, permanently behind Codex.
- Verdict: **retire as the harness**; keep the deterministic pipeline and the
  engine tools as callable workflows (they are the agent's power tools now).
  The round-1 inner agent remains available for benchmark comparison but is no
  longer the product control flow.

## Decision

Adopt **Codex App Server through the official Python SDK** as an upstream
dependency with a thin CrystalPilot adapter (`crystalpilot_workbench`):
project registry, task/results conventions (`CrystalPilot Results/<task-id>/`),
AGENTS.md domain layer, approval routing to the product UI, event normalization
for the scientific frontend, and credential isolation. No fork, no vendored
patches. MCP is the designated extension point if/when we want first-class
crystallography tools instead of CLI calls (Codex supports stdio MCP servers with
per-tool approval modes in config).

## Evidence (all verified by running, this machine, 2026-08-27)

1. Custom OpenAI-Responses gateway works unmodified: `model_providers` with
   `wire_api="responses"`, `base_url`, and **`auth.command`** (bearer fetched on
   demand — key never in env/config/logs). Gateway supports SSE streaming
   (verified event sequence) and prompt caching (9.7k cached tokens observed).
2. `gpt-5.6-sol` + `model_reasoning_effort = "xhigh"` accepted end-to-end.
3. Windows-native operation: bundled `codex.exe` 0.147.0 runs app-server; shell
   tool uses PowerShell; command reads execute sandboxed; writes escalate to
   `item/commandExecution/requestApproval` → our callback decides. (OS-level
   Windows sandbox `[windows] sandbox=...` exists upstream; not yet enabled in
   the prototype — everything is approval-gated instead.)
4. Threads persist and resume across client crashes (validated mid-demo);
   `thread_resume` continued a half-finished crystallography task.
5. Real NL demo: "解析这个铜MOF" → agent read AGENTS.md, ran the crystalpilot
   engine CLI, verified artifact hashes, cross-checked a validation alert
   (CN=8 → actually CN=5 square-pyramidal, Addison τ5=0.059), tried alternative
   space groups, wrote a publication-grade Chinese SUMMARY.md into
   `CrystalPilot Results/<task-id>/`.
6. Reasoning: only encrypted ids + optional summaries cross the wire; the UI
   shows summaries, never raw chain-of-thought (none is available).
7. Existing system regression: benchmark subset reruns identical
   (P2-4 SOLVED R1 0.1021; Ca_imidazolate SOLVED R1 0.0542).

## Risks & mitigations

- **SDK/app-server API churn** (0.x): pin exact versions in `workbench`
  requirements; the adapter touches a narrow surface (≈6 SDK calls + event
  names); add a protocol smoke test to CI.
- **Auto-review reviewer calls unavailable models** on the gateway: we disable
  `approvals_reviewer` and route approvals to the user (found + fixed in
  prototype).
- **Key exposure via TRACE logs**: fixed — `auth.command` + `RUST_LOG=warn`;
  logged rows purged; transcripts redact the key pattern.
- **Agent could read local credential files**: AGENTS.md forbids it and all
  writes/sensitive commands are approval-gated; for production, move credentials
  outside project scope and use OS ACLs.
- **License**: Apache-2.0 + NOTICE — attribution required in distribution;
  compatible with commercial use. We depend on official PyPI artifacts, not a
  copied source tree.
