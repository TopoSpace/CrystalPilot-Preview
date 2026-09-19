# Round 5 probed facts & conventions

Working notes for the autonomous iteration round (2026-08-29). Complements
ROUND4_NOTES.md; durable engineering knowledge only.

## Deterministic ADDSYM (check_symmetry)

- cctbx `lattice_symmetry.group(cell, max_delta)` returns the **acentric**
  lattice holohedry (P432 for cubic, P422 for tetragonal): every lattice is
  centrosymmetric by convention, the inversion is implicit. For any
  order/coset comparison `expand_inv(sgtbx.tr_vec((0,0,0)))` first — this
  also puts −x,−y,−z into the candidate set (the P1-vs-P‑1 trap needs it).
- Compare group orders **in the primitive Niggli setting only**
  (`change_of_basis_op_to_niggli_cell`, transform the structure AND the
  group): a centered group's order_z counts centering copies, the lattice
  group of the reduced cell doesn't.
- Direct element-aware site matching (min distance under pure lattice
  translations) — NOT emma: emma's Euclidean normalizer contains −1 and
  silently absorbs inversion (round-4 negative result, reconfirmed).
- Verified: I4₁/amd demo model → "complete", no candidates; toy P‑1
  expanded to P1 → inversion found, suggests P‑1.

## Twin laws

- Merohedral/pseudo-merohedral candidate laws = coset reps of the
  (centric) lattice point group modulo the current **Laue** group, rotation
  parts transformed back to the working basis. No candidates ⇒ metric
  forbids merohedral twinning ⇒ any twin must be non-merohedral (shows as
  un-indexed spots at the frames stage / split profiles), which HKLF5
  represents in the data rather than a TWIN card.
- SHELX conventions: TWIN r11..r33 [n]; BASF k per extra component.
  BASF WITHOUT TWIN is legal and means HKLF5 (law lives in the data).
  sof coding: +(10k+p) = p·fv(k); −(10k+p) = p·(1−fv(k)); 10<v<15 fixed.
- HKLF5: batch column (3I4,2F8.2,I4); negative batch = extra component
  rows of a composite observation. iotbx `hklf.reader.as_miller_arrays`
  returns the batch numbers as arrays[1]. For the in-process view keep
  batch>0 rows only (still twin-composite ⇒ approximate; refine must go
  through SHELXL — enforced by a typed refusal).

## Import fidelity (the campaign's five lessons)

Gate: SHELXL `L.S. 0` on the imported model must reproduce the published
R1 (|Δ| ≤ 0.005). What broke it, in order of discovery:

1. Stripping + re-deriving deposited H renames them → DFIX cards
   referencing deposit H labels hard-abort SHELXL, and idealized positions
   shift R. Deposits' H must be kept verbatim (`_import_h_policy="keep"`),
   AFIX groups round-tripped via h_riding_meta.
2. Parser AFIX grouping must close on ANY new AFIX card and on non-H
   atoms — `AFIX 43 / H29 / AFIX 6 / O30 / H30A H30B / AFIX 0` is two
   groups (aromatic CH + rigid water). Also capture the deposit's
   u_mult from the H card's negative U field (−1.5 vs −1.2).
3. HKLF5 data cannot be represented by a batch-less hkl derived from the
   fcf — when the embedded res says HKLF 5, use the CIF's embedded
   `_shelx_hkl_file` (deposits carry it precisely for this).
4. SHEL / OMIT / MERG / EXTI / SWAT change the reflection set / Fc and
   must round-trip verbatim (`data_cards` through parser → flags → nodes →
   every SHELX job). The in-process engine ignores them — disclosed in the
   refine summary, visible as an engine-vs-SHELXL offset.
5. `ABIN` in a deposit means the published R includes a solvent-mask
   contribution whose .fab is NOT deposited: R looks ~0.03-0.04 too high
   until `solvent_mask` recomputes it (our mask hit −0.001 vs published
   SQUEEZE on mof_cu3).

Final: 8/9 within gate; twin cases digit-exact (HKLF5 d=0.0000,
TWIN+BASF d=−0.0001, twin+82-disordered-sites d=+0.0005). The 9th
(twintrap_nm) deposits no twin metadata at all — an agent-discovery case
by construction.

## Specialist sub-agents (consult_specialist)

- Containment: nested Workbench inside the MCP process; the specialist's
  own MCP server runs with CRYSTALPILOT_MCP_READONLY=1 (server-side hard
  gate ⇒ can never write), ephemeral ProjectState (save() no-op) so the
  app-server-owned .crystalpilot-workbench.json is never raced;
  transcripts + verdict.json under .crystalpilot/specialists/.
- Gating: default OFF. Project setting `enable_specialists` (toggle
  triggers the same transparent app-server rebuild as a permission-mode
  change — MCP tool list is baked at spawn) or CRYSTALPILOT_SPECIALISTS=1
  for headless. Hidden when the server itself is readonly (no recursion).
- Measured: density specialist on the round-4 demo — 108 s, 10 read-only
  calls, 181k input tokens; independently confirmed the split-site
  rejection from branch metrics and proposed a new falsifiable hypothesis
  (partially ordered DMF O–C at the 1.34 Å peak). Nested app-server spawn
  overhead ~10 s.

## DeepSeek Harness study (frontend)

Cloned at workdir/ref/deepseek-harness (MIT). Real web UI lives in
`packages/client/ui-*` plugin packages (`apps/web` is a shell). Patterns
adopted: tool-row `data-state` machine + pure-CSS running sweep
(2.6 s ease-out, ::after gradient), sr-only status text beside color
dots. Noted for later: approval-panel-in-composer (their comment: an
in-stream placeholder card renders the same wait twice), DisclosureRow
for system events, scroll "observed-position ledger" for human-vs-program
scroll discrimination, disabled-with-reason fork buttons.

## Two-lattice HKLF5 experiment (deterministic, v1)

Pipeline proven on the o-nitroaniline CBF set (scratch
workdir/onitwin_2latt): index max_lattices=2 joint_indexing=True →
dials.refine (14 expts, RMSD 0.10–0.15 px) → dials.integrate (61,940
refl) → dials.scale (KB; see crash workarounds below) → make_hklf5.py →
SHELXL BASF.

- HKLF5 semantics validated: negative batch rows FIRST, last (positive)
  row carries Fo²; Fc² = Σ k_|b|·F²(h_row); BASF = component-2 fraction
  (sources: SHELX manual HKLF/BASF; 2twin worked example). Our writer's
  convention matches SHELXL behaviour (BASF refined 0.35→0.179).
- **Basis mapping must be exact**: C = A_chain⁻¹·A_scratch (integer,
  dev 0.000). Cell-parameter matching alone is NOT safe.
- **BASF converged to the physics**: at overlap tol 0.10 (|h|≤2),
  BASF=0.221; independent check: median I(pure dom2)/I(pure dom1
  equivalent) = 0.295 = k/(1−k) → k=0.228. Widening tol "improves" R1
  (0.077 @0.35) but drives BASF→0.065 — that is the minor domain being
  discarded, not treated; do NOT chase R1 there.
- v1 accuracy: R1 0.107 (HKLF5, 10.8k obs) vs naive single-domain 0.081
  (7.2k obs) vs RDL ladder naive 0.0678 / PLATON-HKLF5 0.0465. Limit =
  single-domain integration boxes for (near-)overlapped spots (each
  domain's profile fit sees the other's counts) — the RDL's own
  conclusion that EVAL15-style JOINT integration is superior, reproduced
  from our own evidence. Productization (staged export_hklf5 tool) should
  ship with this disclosure; true rung-3 needs joint profile
  deconvolution.
- Model side note: the agent's P2₁ Z′=4 model absorbs twin error into
  doubled parameters; the pseudo-inversion near-miss (check_symmetry
  95%, unmatched C9/C22) is the model-side fingerprint of that.
- SHELXL gotchas: cleaned deliverable .res has NO L.S. card — insert one
  or nothing refines (R stays at L.S.0 value, BASF frozen); FVAR osf
  from a different data scale can be 100× off → estimate osf =
  Σ√(Fo²·Fc²mix)/ΣFc²mix before refining, or LS diverges (R1 1.44).
- PLATON TwinRotMat batch: `platon -o -T job.cif` (fcf alone refuses:
  "Weight Parameter A Negative"); it needs a live stdin — feed newlines
  every few seconds UNTIL DONE (EOF mid-analysis = quits, .lis truncated
  at a 40960-byte buffer boundary, empty .hkp); Z′=4 rotation search ran
  >20 min CPU. Poll .hkp size + process CPU, then kill.

## DIALS-on-Windows native crash workarounds (this conda build)

`dials.scale` / `dials.symmetry` die with "Windows fatal exception
0xc06d007f" inside scipy compiled code on this two-lattice input:
1. scaler factory calls calc_crystal_frame_vectors (scipy.spatial
   Rotation) when reflection_selection.method is auto →
   `reflection_selection.method=intensity_ranges` bypasses;
2. the post-scaling summary calls resolution_cc_half → scipy curve_fit
   (MINPACK) → same crash class; `cut_data.d_min=<value>` skips the fit
   (observers.py only calls it when d_min is None). Output files are
   written AFTER the summary, so the crash loses them.
3. dials.symmetry crashes in the same tanh resolution fit — no
   equivalent skip flag tried; avoid it for two-lattice scratch work
   (we know the SG) or reindex manually.

## Ops

- Piping a background command through `tail` buffers ALL output until
  process exit — watch disk side-effects (state.json, transcript growth)
  instead, or redirect to a file.
- After an OS reboot: staged frames tools resume from
  `.crystalpilot/frames/state.json`; an interrupted agent thread resumes
  via `Workbench.resume_task(thread_id)` (codex-home rollout persists) —
  hand it a short "system note" recap of its own last conclusions.

## dxtbx FormatBruker geometry gaps (o-nitroaniline sfrm, precisely characterized)

Probe evidence in workdir/onitwin_probe + workdir/fix_bruker_tth.py:

1. **Swung detector**: header ANGLES[0]=2θ=21.52°, but the imported panel is
   face-on (fast={1,0,0}, slow={0,−1,0}, origin z=−41) with the swing folded
   into a beam-center shift (offset 16.2 mm = 41·tan 21.5° exactly). At
   41 mm distance the flat approximation mis-places edge spots by tens of
   pixels.
2. **φ scan on a fixed-χ Kappa**: header AXIS=3 (φ scan), χ=35°, yet the
   goniometer imports as a bare rotation about {−1,0,0} with identity
   fixed/setting rotations — the 35° tilt of the physical φ axis is lost.
   With a wrong rotation axis nothing can index (confirmed: 18k clean
   centroids after min_spot_size=3 re-spotfind, max_cell=20 sane, both ±2θ
   panel corrections tried, dials.search_beam_position insoluble in every
   geometry).
3. Practical route for this dataset: the authors' own CBF conversion
   (Zenodo same record) carries correct geometry; sfrm support for
   swung-2θ + φ-scan Brukers is a dxtbx upstream gap worth reporting.
4. sfrm header parsing: fixed 80-byte records (7-char key + ':' + 72-char
   value, NO newlines) — regex captures must be bounded to 72 chars or
   they swallow the next card. CELL card may be all zeros; ANGLES =
   2θ ω φ χ; DISTANC in cm; CENTER = zero-swing beam center in px.

Spot-finding lesson: auto min_spot_size=6 kept only 33.7k of 114k
extracted spots on this APEXII CCD set; min_spot_size=3 on sweep 1 alone
recovered 18.7k clean spots. find_spots should expose min_spot_size and
warn when the filter eats >50% of extracted spots.

## o-nitroaniline CBF outcome (the authors' conversion works)

The cbf/ set (same Zenodo record) imports with the full geometry
(rotation axis {−0.819,−0.574,0} = the 35°-tilted φ axis; genuinely
swung panel) and the staged chain goes straight through: 18,839 strong
spots (min_spot_size=3) → single-lattice index 86.9 % (cell 8.34 10.08
15.07 β 74.6° P1) → integrate 14,667 refl → scale (conventional
β 105.33°, hall P 2yb, i/σ 10.9, **R_int 0.0727 — twin-inflated**) →
coarse solve R1 0.160, 40 atoms, **SG picked P2₁ not the published
P2₁/a** (twin overlap corrupts the a-glide absences — the documented
trap; 40 atoms = 4 independent molecules in P2₁ = the doubled ASU).

Discovery-E2E hygiene: the project context.json originally carried
"非切变孪晶已知案例 + RDL DOI" in the chemistry note — get_project_brief
served it to the agent on call 1 (spoiler). Killed that run at 1 tool
call, sanitized context to plain chemistry + instrument (compound name,
SMILES, Bruker APEXII, 150 K), wiped the spoiled task dir, killed the
orphaned app-server (TaskStop skips Workbench.__exit__ — check
`tasklist codex.exe` after killing a driver), relaunched. Residual leak
disclosed in the round report: the data directory NAME contains
"…_twin" (visible only if the agent reads frames logs/state.json paths);
renaming the benchmark dir would break manifests, accepted as-is.

Two-lattice probe (scratch, max_lattices=2 **joint_indexing=True** —
required explicitly for multi-sweep + max_lattices): both domains same
cell, combined **99.0–99.4 % indexed** per sweep (vs 86.9 single), DIALS
reports the domain relation directly: rotation 179.992° about lab
(0.919,0.254,0.301). hkl-space law T = A1⁻¹·R·A1 =
[[1,0,0],[0,−1,0],[0.957,0,−1]]: the 0.043 deviation from integer in
T[3][1] IS the non-merohedral signature (partial overlaps ⇒ TWIN card
cannot represent it; needs HKLF5 / two-lattice integration). Evidence:
workdir/onitwin_2latt/{index2.log,twin_law.json} (kept OUT of the
project so the discovery E2E isn't spoiled).

Ops (recurring): bash cwd persists across tool calls —一切后台命令用绝对路径
（本轮 curl -o 相对路径与 heredoc 相对路径各中招一次）。
