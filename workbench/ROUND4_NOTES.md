# Round 4 probed facts (M0)

Verified 2026-08-29 on this machine. These are load-bearing implementation facts.

## Scene / viewer closed loop (workdir/spike_scene/)

- `fft_map.as_ccp4_map(file_name=...)` works (SJTU-9 Fo−Fc: 3.9 MB, grid
  64×64×240) → browser `new $3Dmol.VolumeData(arrayBuffer, 'ccp4')` +
  `addIsosurface(vol, {isoval:±0.35})` renders both signs. Verified visually
  (preview screenshot: packed cell + green/red surfaces + unit cell box).
- 3Dmol CIF path needs `_space_group_symop_operation_xyz` →
  `_symmetry_equiv_pos_as_xyz` rename (ui/src/components/StructureViewer.tsx
  already does this).
- `viewer.addCustom({vertexArr, normalArr, faceArr})` renders coordination
  polyhedra; brute-force convex hull on ≤12 vertices is fine (C(8,3)=56 tris);
  flat-shade by duplicating vertices per face. Orient normals away from
  centroid.
- grow expansion server-side: `pair_asu_table(asu_mappings(buffer)).
  add_all_pairs(cutoff)` → `extract_pair_sym_table()`, BFS materializing
  `rt_mx` products from the seed atom; remember the sym table stores i<j only —
  walk both directions. 2.6 Å cutoff is too tight for Zr–O(aqua) 2.27+; use
  element-aware radii (as refine/inspect.py does).
- Computables for the publication CIF (verified numbers for mvp-sjtu9):
  `xs.f_000()`=3758.9; density from `xs.unit_cell_content()` + tiny_pse masses
  (0.879 g/cm³); μ via `cctbx.eltbx.attenuation_coefficient.get_table(elem)
  .mu_at_angstrom(λ)/table.density()` mass-attenuation summed over cell content
  → 3.80 mm⁻¹ (Cu Kα, Zr-MOF, plausible).

## Codex SDK per-turn controls (openai-codex 0.147.0)

- `Thread.turn(input, *, approval_mode, cwd, effort, model, output_schema,
  personality, sandbox, service_tier, summary)`.
- `from openai_codex import Sandbox` → `read_only|workspace_write|full_access`
  (public enum; wire values read-only/workspace-write; full_access maps to
  danger level internally).
- Per-turn `approval_mode` maps ONLY to: `ApprovalMode.deny_all` →
  approval_policy=never + reviewer None; `auto_review` → on-request + model
  reviewer (**unusable on our gateway** — reviewer model not served, same as
  round-2 finding). `None` inherits the thread's on-request.
- **`TurnHandle.steer(text)` works mid-turn** (probe: agent creating f1..f5
  with sleeps was steered after f4 → stopped, honestly reported "f5 未创建").
  Steer is immediate-ish (agent saw it at the next step boundary).
- **Per-turn `sandbox=Sandbox.read_only` works on Windows**: file write
  attempt raised `item/fileChange/requestApproval` (escalation), reject →
  agent reported the restriction; even PowerShell `Test-Path` escalated
  (`item/commandExecution/requestApproval`). So read-only mode = sandbox
  read_only + reject-by-policy; MUTATING MCP tools must additionally be gated
  server-side (MCP process is NOT under the codex sandbox).

## Permission-mode mapping (decided)

| mode | turn sandbox | approval | MCP approval_mode | extra |
|---|---|---|---|---|
| 只读 | read_only | inherit on-request | prompt | server-side refuse MUTATING_TOOLS |
| Copilot | workspace_write | inherit on-request | writes | — |
| 自动 (default) | workspace_write | inherit on-request | auto | — |
| 完全访问 | full_access | deny_all (=never ask) | auto | UI warning banner |

MCP approval_mode change requires re-baking config_overrides → transparent
Workbench reopen for the project (threads resume by id).

## IUCr web checkCIF automation (probed with PUBLIC COD data only)

- Form: POST multipart `https://checkcif.iucr.org/cgi-bin/checkcif_hkl.pl`
  fields: `filecif` (file), `from_index=from_index`, `runtype=symmonly`,
  `referer=checkcif_server`, `outputtype=HTML|PDF|PDFEMAIL`,
  `validtype=checkcif_with_hkl|iucr_checkcif_with_hkl|checkcif_only`,
  `valout=vrfa|vrfab|vrfabc|vrfno`, `duplic=duplicno|duplicyes`,
  `UPLOAD=Send CIF for checking`.
- Probe: Cu_aspirinate COD ref_cif (17 KB, checkcif_only/HTML/vrfabc/duplicno)
  → 11 KB HTML report, ALERT lines grep-parseable (7×G), PLATON version noted.
- Policy: tool must be per-call approved + per-project opt-in (default off);
  never submit lab data without explicit user action. Structure-factor
  validation uses `validtype=checkcif_with_hkl` + embedded _refln loop in the
  CIF (single file upload).

## PLATON local quirks (carried from round 3)

- platon.exe writes model.chk then hangs ("REWIND PROBLEM FOR UNIT 68") —
  poll .chk size-stable then kill (implemented in RunCheckcif).
- PLATON guesses elements from LABELS (Zr labelled FE01 → BVS as Fe) — the
  relabel tool (round-4 backlog) or canonical labels avoid this.
- Alerts 023/029 (type 3) are minimal-CIF artifacts; they become REAL checks
  once the publication CIF embeds the _refln loop (SHELXL ACTA output).

## M5 acceptance-day findings (2026-08-29)

- **Readonly hard gate E2E verified** (scripts/verify_readonly_gate.py): MCP
  server spawned with `CRYSTALPILOT_MCP_READONLY=1`; `list_nodes` works,
  `edit_atoms` returns the typed refusal "blocked: this workbench is in
  READ-ONLY mode (inspection tools only)…". Server-side, independent of the
  codex sandbox (the MCP process is outside it).
- **transcript.jsonl concurrency corruption**: turn iterator + notification
  callbacks both append via separate TextIOWrapper handles; a long
  agent_message line got flushed in chunks and an approval_request line landed
  in the middle, splitting a UTF-8 char (raw 0xbc at line start → decode error
  → /api/threads/transcript 500). Fix: Workbench._log_lock + single binary
  append write, `errors="replace"`; reader uses errors="replace" + skips bad
  JSON lines.
- **import_frames 300 s timeout too tight**: cold first read of 1700 CBF
  headers from a loaded spinning disk exceeded it twice in demo 2 (concurrent
  demos). Also `subprocess.run(timeout=)` kills only the `dials.*.exe`
  wrapper — the child python keeps running (agent had to Stop-Process
  manually). Fix: import timeout 1200 s; `_Runner` now Popen + taskkill /T /F
  tree-kill on timeout (frames_dials._kill_tree).
- **Demo-2 agent rescue pattern**: after the tool timeouts it ran the DIALS
  chain via shell *into the tool's own* `.crystalpilot/frames/` layout
  (imported.expt, strong.refl, …) after reading tools_frames.py, so the staged
  tools could resume (scale_and_export onward through MCP). Capability
  boundary evidence, kept in the run log.
- **Evaluator ccgate temp dirs** (4 MB PLATON scratch per gate run) now
  rmtree'd after parsing; `.gitignore` covers `ccgate_*` and scene-cache /
  frames intermediates / uploads / round3-* user dirs.
