# CrystalPilot Architecture

CrystalPilot is a refinement workbench for single-crystal X-ray structures. A
language-model agent works on one project folder at a time through typed
crystallographic tools; the numerics are done by cctbx/smtbx, SHELXT, SHELXL,
PLATON and DIALS. The deterministic coarse-solve engine that preceded the
workbench is kept as the initial-model tool. This document describes the
layers and their contracts, then keeps a dated record of what changed and
why. Sections are ordered newest first in the record and oldest first in the
history at the end.

## Update (2026-09-16): stability, storage, brand

**Event pipeline.** `normalize_notification` stamps every item-scoped event
(`tool_*`, `command_*`, `command_output`, `tool_progress`, `file_change_*`,
generic families incl. the new `imageView`) with the kernel `item_id`; the
reducer pairs completions by id (id-less fallback kept for old transcripts).
Benign `userMessage`/`agentMessage`/`reasoning` phases are no longer emitted
as `item_unhandled`. At a turn boundary any row still streaming is closed as
`no_result` (turn ended normally / idle / new turn) or `interrupted` (stop,
failure); a transcript that ends mid-turn while the server says idle is a cut
transcript and closes the same way. Cards keep their last 8 raw events.
**Channels.** `Channel` gained a `closed` flag, asyncio waiters and
`wait_async`; `/api/wb/sse` is an async generator (no threadpool token per
connection), sends `{"kind":"ping"}` every 15 s (SSE comments are invisible
to JavaScript) and a final `channel_closed` when the project session is
reaped; the hello carries `oldest` so a client can detect a gap. The client
(`useThreadChannel`) recovers from `EventSource` CLOSED (non-2xx never
retries by itself), `channel_closed`, hello gaps, and a 45 s silence
watchdog; `visibilitychange`/`online` trigger a reconcile against the
transcript head. Connection state is visible in the chat pane.
**Pool.** `WorkbenchPool.open` serialises concurrent construction of the
same project (a second kernel spawn used to fail on the shared sqlite).
**Storage.** `crystalpilot/refine/storage.py`: reflection data lives once in
the immutable revision (`data/dNNNNNN/observations.hkl`); job directories
hard-link it (`_stage_job_hkl`); a successful job's `job.cif` drops its
embedded hkl block behind a marker and `write_outputs`/checkCIF restore it
byte-for-byte; `plan_cleanup`/`apply_cleanup` (dry run first, re-checked on
apply) reclaim unreferenced by-products; `/api/projects/usage` and
`/api/projects/cleanup` back the project-home card. Nodes, data revisions,
user files and `CrystalPilot Results` are never modified.
**Performance.** `/api/projects/status` caches each project's answer behind
the mtimes of what it reads (2.1 s → 25 ms warm for 30 projects). The codex
kernel's own log database (`codex-home/logs_2.sqlite`, 1.6 GB after three
weeks) is rotated by the restart scripts above 256 MB; it was the cause of
multi-minute project opens and "failed to initialize sqlite state runtime".
**Brand.** `design/CrystalPilot-logo-v1/` (merged from `origin/Logo`) is the
source; `ui/public/brand/` holds the four SVGs the UI uses (sidebar mark,
hero app icon light/dark, favicon per theme).

## Update (2026-09-08): transactions, data revisions, comparison

See `docs\UPGRADE-2026-09-08-workbench.md` for implementation and real evidence.
Project APIs use a stable cross-process/reentrant lock, project revisions and
explicit state preconditions. Controlled reflection imports/swaps now create
immutable app-managed data revisions; nodes bind their observation input separately
from model/engine interpretation. Staged data and node publication share one active
model/data state commit point, with a finite owned journal for compatibility inputs.
Legacy nodes retain unknown data binding: geometry is available, but reflection
reconstruction needs explicit supplied-data binding into a new node. Reads remain
serialized; global all-file ACID, power-loss durability, call idempotency and automatic
upstream approval binding are not supplied. The read-only comparison API reports
per-metric comparability independently of coordinate-frame compatibility; model/H/
fitted-scale changes are not blanket R1 gates, and weighted metrics disclose actual
weights. Optional nested consultants copy the selected node's matching bound data
into independent read-only snapshots; unknown history still refuses. Source/data/
configuration limitations remain explicit. checkCIF uses short execution staging and owned process-tree cleanup,
and publishes durable completed/partial/failed/cancelled provenance rather than
turning missing reports into zero alerts. The UI links analysis to exact instances,
preserves transcript source identity and respects reduced motion/visibility.
Full project instructions are v42; open factual questions ask for actual values.

## Update (2026-09-07): inventory and UI batch

The current review and next execution plan are `docs\AUDIT-2026-09-07.md`
and `docs\PLAN-2026-09-07-upgrade.md`. A fresh structure-project inventory
registered 74 tools. The late round-3 additions (effective state, layered tool
results, trial/investigation records, complete growth, periodic rings, axial PLD
and question cards) are implemented, not future work. Current sub-agent settings
are `auto/on/off`; historical policy descriptions below are not the current UI.

The latest UI batch adds independent palette/mode preferences, explicit camera
fog/clipping, bounded-layer coverage, and node anchors for structure/frame quotes.
Stage navigation reports observed/current/pending activity, not scientific completion.
Provider configuration now exposes native Responses compatibility, explicit auth
modes and bounded advanced fields, with shared key parsing and tested HTTP saves.
After user-supplied credentials, gateway Sol/xhigh completed a real read-only
four-tool MOF diagnosis; this is not a claim of blind structure solution.
Cross-process model-write transactions and reflection-data revisioning remain
priorities; the numerical engines and existing MCP/NodeStore interfaces are retained.

## Update (2026-09-05): current defaults

The sections below preserve the implementation history. The current workbench
uses the v37 project instruction family, approximately 70 MCP tools, per-node
analysis products, and optional read-only specialist roles. Code defaults are
now **GPT-6-Astra / xhigh**; historical experiment pins are preserved.

See `docs\AUDIT-2026-09-05.md` for the verified current inventory and real-data
limits, and `docs\PLAN-2026-09-05-upgrade.md` for the next design. The proposed
change is an evidence/state-consistent application layer around the existing
scientific engines, not a replacement of cctbx/SHELXL with LLM calculations.
Unknown, failed, stale and partial analysis must remain distinct from a clean
result. Node identity alone is not a sufficient long-term provenance contract
for data, model, display and publication artifacts.

## Update (2026-09-05): first upgrade batch

- `refine/structure_document.py`: explicit reflection-free projects with canonical
  CIF nodes; original labels, symmetry, disorder and missing-value provenance are
  preserved. A declared canonical RES remains supported for legacy nodes.
- `refine/analysis.py` + `workbench/analysis_jobs.py`: shared staged computation,
  bounded single-worker jobs, independent partial results, observer-aware cancel
  and release, and conditional metadata-only polling.
- `refine/provenance.py`: readable node/export-version linkage for checkCIF and
  delivery. The file inventory is no longer a content-digest gate.
- The UI supports CIF import, structure-only capability boundaries, pinned
  structure/analysis views and source-aware validation. Project instructions are
  v38 (tools-only v4). See `docs\UPGRADE-2026-09-05-first.md` for evidence and limits.

## Design philosophy

The model computes no crystallography. The engines (cctbx/smtbx, SHELXL) do
the numerics; the agent contributes chemical judgment from synthesis priors,
diagnosis, refinement strategy, and a plain statement of what is uncertain. All
crystallographic capability is **internalized as typed tools** the agent calls
through MCP - no shell-string gluing, every call logged and approvable.

```
user browser ── React Workbench (ui/src/workbench, zh-CN, Codex-desktop-aligned)
   │  left: projects/threads   center: streaming chat + humanized tool cards +
   │  approval cards + composer (upload / mid-turn steer / permission modes)
   │  right: live crystal pane (asu|cell|grow|2³|3³ + polyhedra + Fo−Fc + diff)
   │      SSE /api/threads/events (+replay)         REST scene/map/nodes/steer/…
   ▼
FastAPI server ── workbench routes + refine scene service (cctbx in-process)
   │
   ▼  per-turn sandbox/approval (permission modes), TurnHandle.steer
Codex agent (app-server harness; AGENTS.md v4 = SOP + honesty + checkCIF 纪律)
        │   MCP stdio, injected per-project via CodexConfig.config_overrides
        ▼
crystalpilot/mcp ── ToolRegistry bridge ── tools/call → invoke() → JSONL audit
        ▼
crystalpilot/refine   RefineProject (wraps SolveSession) + NodeStore
   ├─ observe: get_project_brief / inspect_model / inspect_map / check_ligand / validate_structure
   │           get_geometry / check_symmetry / audit_reflection_data / compare_nodes
   │           integrate_difference_density (omit-map electron counting, guest-evidence test 1)
   ├─ solve:   solve_charge_flipping → interpret_peaks (built-in, auditable)
   │           ⇄ run_shelxt (vendor dual-space, large cells)     [cold-start projects]
   ├─ edit:    edit_atoms / add_atoms_from_difference_map / fit_fragment / set_restraints
   │           add_hydrogens / optimize_weights / solvent_mask / fourier_complete
   │           rename_atoms / assemble_asu / change_space_group / model_disorder / set_twin
   ├─ refine:  refine (smtbx LS + restraints_manager)  ⇄  run_shelxl (vendor, check|adopt)
   │           [SHELX PART semantics engine-wide: conformer_indices tables, pi-metal prune]
   ├─ frames:  import_frames / find_spots / index_frames / integrate_frames /
   │           scale_and_export / create_start_model   (DIALS conda env, staged+resumable)
   │           ingest_vendor_data (SAINT/TWINABS/XPREP products, ._ls provenance)
   ├─ skills:  list_skills / read_skill / save_skill / delete_skill
   │           [dynamic expert knowledge: knowledge/**/*.md units, live on save,
   │            tools compute facts - skills guide judgement; run_checkcif
   │            auto-attaches related_skills by alert code]
   └─ deliver: write_outputs (final.cif/fcf/res + the hand-over set ins/hkl/p4p/fab,
               each with its recorded source) / run_checkcif (PLATON, structured)
               / submit_iucr_checkcif (opt-in, per-call approval) / nodes: branch/checkout/…
        ▼
vendor SHELXL+SHELXT+PLATON / DIALS env / (opt-in, approved) checkcif.iucr.org
```

## Round-3 core: `crystalpilot/refine` + `crystalpilot/mcp`

**RefineProject** (`refine/project.py`) owns one crystal = one persistent
project folder. It resolves inputs (`context.json` or glob), imports the start
model (full `.res` parse incl. restraint cards + AFIX riding H), and resumes
from the NodeStore's active node on every open - a fresh MCP server process
reconstructs the live smtbx session from disk (mask recomputed from stored
params, H re-derived, restraints resolved label→i_seq at refine time).

**NodeStore** (`refine/nodes.py`, at `<project>/.crystalpilot/refine/`):
disk-is-truth snapshots. Every successful mutating tool auto-commits a node
(`model.res` canonical + `model.cif` viewer-only + `node.json` with metrics,
restraint specs, weights, mask params, H metadata, lineage). Branches are
named refs; `checkout` rebuilds the session and must reproduce the recorded R1
(< 1e-4, an acceptance gate). The old bug where a snapshot lost its flags
cannot recur with this design.

**Dual engines, cross-validated**: `refine` runs smtbx
`least_squares.crystallographic_ls` in-process (the olex2.refine core) with a
`restraints_manager` built from label-based RestraintSpecs
(DFIX/DANG→bond, SADI→similarity, FLAT→planarity, SIMU/DELU/RIGU/ISOR→smtbx
ADP generators, SHELX σ conventions). `run_shelxl` writes a complete `.ins`
(+ P1-expanded `.fab`/ABIN when a solvent mask is active) via
`io/shelx_writer.py`, runs the project-local `vendor/shelx/shelxl.exe`,
parses R1/wR2/GooF, and either reports agreement (`mode=check`) or adopts the
SHELXL result as a new node (`mode=adopt`). |ΔR1| < 0.005 counts as agreement;
divergence is reported, not hidden.

**Chemistry-aware tools**: `check_ligand` matches model fragments into the
RDKit graph of the prior ligand SMILES (subgraph monomorphism) → mapped atoms +
missing-neighbor repair hypotheses; `fit_fragment` places missing atoms by
per-atom local rigid fit (anchors within 3 template bonds, Kabsch) and **refuses
any atom without difference-density support** (honesty gate); `inspect_model`
reports coordination geometry (CN, distances, τ4/τ5), ring census, dangling
atoms, ADP/occupancy suspects.

**Honesty mechanisms (hard gates in the evaluator)**: (a) every added atom must
be density-supported; (b) the agent's final structured verdict must match the
final node's metrics (≤ 0.002); (c) failed checks must appear in `unresolved`
with non-high confidence. A dishonest full fix ranks *below* an honest partial
fix.

**MCP server** (`crystalpilot/mcp`): low-level `mcp` 1.x stdio server, one
process per project, tools/list from `ToolRegistry.specs()` with
`readOnlyHint` annotations (drives Codex `approval_mode="writes"` = Copilot
mode). cctbx is imported in the main thread before the async loop (Windows
boost deadlock). The protocol details were probed against the kernel before the bridge was written.

## Supporting layers

- **`crystalpilot/workbench`**: Codex app-server harness: isolated
  `CODEX_HOME` (never `~/.codex`), gateway auth via `print_token.py` (keys never
  in env/config/logs), threads/resume, approval translation (incl. MCP
  elicitation shapes), event normalization (`tool_started/completed/progress`),
  AGENTS.md v3 writer, `/wb` routes + static UI.
- **`crystalpilot/io`**: SHELX read (`load_res_model` tolerant of Olex2
  instruction soup) and **write** (`shelx_writer.py`: full .ins/.res, LATT sign
  rule, special-position sof, aniso, AFIX riding-H groups, ABIN .fab).
- **`crystalpilot/tools` + `pipeline`**: the deterministic coarse-solve engine
  (SG determination → charge flipping → interpretation → LS → Fourier →
  mask → validation). Kept as the initial-model tool and benchmark subject
  (v5: 33-case 75.8 % solved).
- **`crystalpilot/chem`**: MOF knowledge (Zr₆, paddlewheels, sane M–O/M–N
  ranges) + connectivity analysis, used by interpretation and validation.
- **`crystalpilot/benchmark`**: coarse-solve benchmark (runner/evaluate) plus
  round-3 additions: `corrupt.py` (deterministic corruption presets; originals
  are never modified in place) and `evaluate_refinement.py` (per-defect
  recovery, emma match, ADP/H/residual checks, honesty gates, cost accounting).
- **`crystalpilot/agent`**: round-1 inner LLM agent. **Deprecated as the main
  path** (superseded by the Codex-harness workbench); kept for benchmark A/B.
- **`server/`, `ui/`**: FastAPI local server serving the built React
  Workbench (SPA fallback; legacy pages at `/legacy`, old `/wb` debug page
  retained).

## Round-4 additions

- **React Workbench** (`ui/src/{workbench,state,lib}`, legacy pages at
  `/legacy`): Codex-desktop-aligned chat (streaming deltas, reasoning
  summaries, humanized tool cards with technical fold-outs, inline approval
  cards, markdown), composer with file upload + **mid-turn steer**
  (`TurnHandle.steer`), and a live crystal pane (3Dmol) driven by the scene
  service. State = useReducer + split contexts folding the SSE event stream;
  transcript replay and live SSE share one code path.
- **Scene service** (`refine/scene.py` + `/api/wb/refine/scene|map`):
  symmetry-aware instancing (i_seq, rt_mx), closure bonds from the smtbx pair
  table, modes asu|cell|grow (bounded BFS - MOFs are infinite polymers)
  |supercell 2³/3³, metal coordination polyhedra (convex hull), node-vs-parent
  diff flags, Fo−Fc as CCP4 for isosurfaces; per-node disk cache.
- **Permission modes** (per-project, persisted): 只读 (read-only sandbox +
  server-side MCP hard gate - the MCP process is *outside* the codex sandbox,
  so non-read tools are refused in-process), Copilot (`writes` elicitation per
  mutating tool), 自动 (default; auto-accepts own-MCP elicitations), 完全访问
  (full-access sandbox + never-ask). Sandbox/approval are per-turn kwargs;
  changing the MCP column transparently rebuilds the app-server.
- **Publication CIF** (`report/publication.py`): the SHELXL ACTA `job.cif`
  (esds, weighting, H-treatment, geometry loops, embedded reflections) is the
  backbone; the assembler fills only honest data (merge stats, computables
  like μ/F000/θ ranges, `experiment` block from context.json, TEMP/SIZE/ZERR
  esd parsed from SHELX and re-emitted, `_platon_squeeze_details` from real
  mask voids) and never invents metadata - unknown stays `?` with caveats.
  `final.fcf` = SHELXL LIST 4. The CIF is paired with the node's *linked*
  SHELXL job first (`metrics_source.job`, riding-H drift tolerated); an
  unpaired node gets a graded **model CIF** (coordinates + the statistics
  measured for this exact model: a zero-cycle SHELXL job at write time or
  the node's current metrics) with `# CrystalPilot delivery cif: model` in
  the header, never a silent minimal CIF. `deliver_files.py` adds the
  hand-over set the group continues from by hand: `final.hkl` (the bound
  observation revision, byte-preserved, SHELX terminator appended when the
  data end at EOF), `final.ins` (the paired job's job.ins, else the node
  model + `L.S.`/ACTA so a restart refines), `final.p4p` (captured at ingest
  - reported as a *missing input* when absent, never fabricated); sources
  in `REPORT.json files` / `MANIFEST.json provenance`, readiness in
  `manual_continuation`. A `bond_table_audit` compares SHELXL's `_geom_bond`
  loop with `chem.bonding` (radius-table metal-C rows → `FREE` card advice).
  A *diagnostic* delivery seals without `final.fcf`/`checkcif.json`/
  `VALIDATION.md` (open items), so a not-publication-grade result is still
  delivered, traceable and continuable.
- **checkCIF loop**: `run_checkcif(cif=…)` returns structured alerts
  `{code,type,level,text,kb}` (KB ≈60 codes, Chinese); AGENTS.md v4 mandates
  run_shelxl → write_outputs → run_checkcif → `VALIDATION.md` explaining every
  A/B/C alert (含义/原因/已做检查/影响评估). The evaluator's gate (d)
  independently reruns PLATON and fails honesty if any A/B/C code is missing
  from VALIDATION.md; structural A alerts (type≠1) block publication grade.
  `submit_iucr_checkcif` posts to checkcif.iucr.org only when the project
  setting `allow_iucr_upload` is on *and* the per-call approval is granted.
- **Raw frames** (`refine/tools_frames.py`): six staged, resumable DIALS tools
  with per-stage stats (spots, indexing cell/SG, RMSD, CC½/Rmerge/
  completeness) into `.crystalpilot/frames/state.json`; `create_start_model`
  hands over to the coarse-solve pipeline → `start.res` in the same project.

## Round-5 additions

- **Analysis tools** (`refine/tools_analysis.py`): `get_geometry`
  (symmetry-aware bonds/angles from the smtbx pair table; esds parsed from the
  newest SHELXL `job.cif` when present, honest note when absent),
  `check_symmetry` (deterministic ADDSYM: primitive-Niggli coset search with
  `expand_inv`, direct element-aware site matching - *not* emma, whose
  Euclidean normalizer absorbs inversion; also emits merohedral twin-law
  candidates = coset reps of the centric lattice group modulo the Laue group),
  `rename_atoms` (canonical element+ordinal labels, H follows carrier),
  `import_cif_model` (published-CIF entry: embedded `_shelx_res_file`/hkl
  verbatim preferred over gemmi reconstruction; experiment block harvested
  into context; ABIN → solvent-mask warning).
- **Import fidelity gate**: campaign discipline - SHELXL `L.S. 0` on any
  imported model must reproduce the published R1 within 0.005. This gate
  converted 5 hidden import bugs into fixes (deposit-H kept verbatim with
  AFIX groups, per-card AFIX closing, HKLF5 via embedded hkl, data cards
  SHEL/OMIT/MERG/EXTI/SWAT round-trip, ABIN mask recompute); 8/9 final,
  twin cases digit-exact.
- **Disorder & twin engine path** (`refine/tools_disorder.py`, `io/shelx_*`,
  `refine/nodes.py`): SHELX sof codes (±(10k+p)), PART, FVAR, TWIN/BASF and
  HKLF5 (negative-batch composite rows disclosed, batch>0 kept for the
  in-process view) are first-class through parser → flags → node metadata →
  every SHELX job. `model_disorder` splits a site along its ADP major axis
  into PART 1/PART 2 with one free variable; `set_twin` applies/suggests twin
  laws (inversion refused in centric groups, |det|=1 checked). In-process
  `refine_ls` refuses twin/HKLF5 jobs with a typed error pointing to
  `run_shelxl(mode='adopt')`, which refreshes refined BASF/occupancies back
  into project flags.
- **Specialist sub-agents** (`refine/tools_specialist.py`): `consult_specialist`
  spawns a nested Workbench *inside the MCP process* whose own MCP server runs
  with `CRYSTALPILOT_MCP_READONLY=1` (server-side hard gate - a specialist can
  never write), on an ephemeral ProjectState (save() no-op → no state races).
  5 roles (space group / chemistry / refinement strategy / residual density /
  validation) return a structured verdict {assessment, recommendation,
  confidence, evidence, risks} + transcript under `.crystalpilot/specialists/`.
  **Default off**; per-project `enable_specialists` toggle (transparent
  app-server rebuild) or `CRYSTALPILOT_SPECIALISTS=1`; hidden inside read-only
  servers (no recursion).
- **Frames multi-lattice** (`refine/tools_frames.py`): `index_frames` gains
  `max_lattices`/`method`/`keep_lattice` (twin rescue: index both domains,
  split experiments, continue with one); `find_spots` gains `min_spot_size` +
  a filter warning when the size filter eats >50 % of extracted spots (CCD
  trap). Known upstream gap: dxtbx
  FormatBruker drops 2θ swing and the χ-tilted φ axis on sfrm sweeps - the
  o-nitroaniline RDL set reduces via the authors' CBF conversion instead.

## Run modes

- Four UI permission modes (above) replace the old two env-var modes;
  `CRYSTALPILOT_MCP_APPROVAL` remains for headless runs.
- Deterministic CLI (`crystalpilot solve`) remains for coarse solving without
  any LLM.

## Milestones

- **M0–M2 (rounds 1–2)**: engine, benchmark and the Codex harness (ADR-001).
- **Round 3**: refinement workbench: MCP bridge, NodeStore, dual engines,
  restraints, ligand tools, corruption benchmark, MVP acceptance passed at
  publication grade (SJTU-9: agent R1 0.0615 vs human 0.0617, 3/3 defects
  fixed blind, open reporting of what remained).
- **Round 4**: Workbench v1: live React UI (steer/approvals/crystal pane),
  scene service, 4 permission modes, publication CIF + checkCIF discipline
  (demo: A16→0 on the assembled CIF; live demo graded publication with
  A6/B4/C8 all explained), raw-frames chain (l-cysteine 1700 frames → CC½
  0.998 → R1 ≈0.05 publication CIF).
- **Round 5**: disorder/twin as first-class engine state (PART/FVAR,
  TWIN/BASF, HKLF5), analysis tools (ADDSYM/geometry/rename/CIF-import),
  import-fidelity campaign 8/9 (5 real bugs fixed), twin-trap agent E2E
  (R1 recomputed from the deposit, no metric-chasing), opt-in specialist
  sub-agents (contained, read-only), frames multi-lattice indexing.
- **Next**: frames-stage twin E2E (o-nitroaniline CBF), real MOF raw frames
  (user-supplied), audit_reflection_data tool, EXTI in-process, 3+-site
  disorder, multi-user.
