/** Stage track (round-2 R6): where a thread is in the crystallographer's
 * pipeline - 数据 → 定群 → 求解 → 建模 → 精修 → 验证 → 交付.
 *
 * Two signals, the later one wins: (1) a running or successful tool call
 * maps to a current stage by name; (2) `situation_report` returns `stage`
 * from node history and can correct that reading. Every stage-bearing call
 * is recorded as observed, including failures, but observation never proves
 * scientific completion. Per-stage turn lists keep the track navigable. */
import type { ChatItem, TurnAggregate } from "../state/threadReducer";

export const STAGES = ["data", "symmetry", "solve", "model", "refine", "validate", "deliver"] as const;
export type StageId = (typeof STAGES)[number];

/** Chinese stage names as situation_report emits them (数据/定群/求解/建模/精修/验证/交付). */
export const STAGE_ZH: Record<StageId, string> = {
  data: "数据",
  symmetry: "定群",
  solve: "求解",
  model: "建模",
  refine: "精修",
  validate: "验证",
  deliver: "交付",
};

const ZH_TO_STAGE: Record<string, StageId> = Object.fromEntries(
  (Object.entries(STAGE_ZH) as [StageId, string][]).map(([k, v]) => [v, k]),
) as Record<string, StageId>;

/** Tool → stage. Observe-only tools that belong to no stage (get_project_brief,
 * list_nodes, view_structure, situation_report itself…) are absent: they
 * neither advance nor count. */
export const STAGE_OF_TOOL: Readonly<Record<string, StageId>> = {
  import_frames: "data",
  find_spots: "data",
  index_frames: "data",
  integrate_frames: "data",
  scale_and_export: "data",
  export_twin_hklf5: "data",
  ingest_vendor_data: "data",
  reduce_with_crysalis: "data",
  estimate_resolution: "data",
  audit_reflection_data: "data",
  swap_reflection_data: "data",
  import_cif_model: "model",
  check_symmetry: "symmetry",
  change_space_group: "symmetry",
  screen_space_groups: "symmetry",
  reflection_statistics: "symmetry",
  ncs_audit: "symmetry",
  solve_charge_flipping: "solve",
  solve_superflip: "solve",
  run_shelxt: "solve",
  interpret_peaks: "solve",
  create_start_model: "solve",
  edit_atoms: "model",
  add_atoms_from_difference_map: "model",
  fourier_complete: "model",
  fit_fragment: "model",
  search_fragment_pose: "model",
  accept_fragment_pose: "model",
  rename_atoms: "model",
  assemble_asu: "model",
  model_disorder: "model",
  set_twin: "model",
  invert_structure: "model",
  add_hydrogens: "model",
  element_scan: "model",
  ghost_test: "model",
  probe_site: "model",
  set_restraints: "model",
  preflight_restraints: "model",
  set_z: "model",
  audit_element_assignment: "model",
  audit_heavy_sites: "model",
  audit_guest_evidence: "model",
  refine: "refine",
  run_shelxl: "refine",
  run_olex2: "refine",
  optimize_weights: "refine",
  set_weights: "refine",
  set_resolution_limit: "refine",
  solvent_mask: "refine",
  integrate_difference_density: "refine",
  validate_structure: "validate",
  run_checkcif: "validate",
  submit_iucr_checkcif: "validate",
  analyze_packing: "validate",
  get_geometry: "validate",
  write_outputs: "deliver",
  finalize_delivery: "deliver",
};

export interface StageTurn {
  /** id of the turn-status item (the divider) */
  id: string;
  ts: number;
  agg: TurnAggregate;
}

export interface StageInfo {
  id: StageId;
  /** at least one stage-bearing call was observed, regardless of outcome */
  observed: boolean;
  /** successful stage-bearing tool calls */
  nTools: number;
  turns: StageTurn[];
}

export interface StageTrackInfo {
  current: StageId | null;
  /** what set `current`: a situation_report reading or the last tool */
  basis: "situation_report" | "tool" | null;
  stages: StageInfo[];
}

function stageOfSituation(summary: unknown): StageId | null {
  if (!summary || typeof summary !== "object") return null;
  const parsed = (summary as { parsed?: unknown }).parsed;
  if (!parsed || typeof parsed !== "object") return null;
  const st = (parsed as { stage?: unknown }).stage;
  const name =
    typeof st === "string"
      ? st
      : st && typeof st === "object"
        ? (st as { stage?: unknown }).stage
        : undefined;
  return typeof name === "string" ? (ZH_TO_STAGE[name] ?? null) : null;
}

/** Walk the transcript once. A turn's digest is filed under the stage of
 * its most-called stage-bearing tool (ties → the later stage). */
export function stageTrack(
  items: readonly ChatItem[],
  runningToolIds: readonly string[] = [],
): StageTrackInfo {
  const running = new Set(runningToolIds);
  const stages: StageInfo[] = STAGES.map((id) => ({ id, observed: false, nTools: 0, turns: [] }));
  const byId = Object.fromEntries(stages.map((s) => [s.id, s])) as Record<StageId, StageInfo>;
  let current: StageId | null = null;
  let basis: StageTrackInfo["basis"] = null;
  for (const it of items) {
    if (it.type === "tool") {
      if (it.tool === "situation_report") {
        if (it.status !== "ok") continue;
        const s = stageOfSituation(it.summary);
        if (s !== null) {
          current = s;
          basis = "situation_report";
        }
        continue;
      }
      const s = STAGE_OF_TOOL[it.tool];
      if (s === undefined) continue;
      byId[s].observed = true;
      // Only a completed success or a card known to be live can identify the
      // current stage. Interrupted/failed/stale rows remain observed only.
      const live = it.status === "running" && running.has(it.id);
      if (it.status !== "ok" && !live) continue;
      if (it.status === "ok") byId[s].nTools += 1;
      current = s;
      basis = "tool";
    } else if (it.type === "turn" && it.phase !== "started" && it.summary) {
      let best: StageId | null = null;
      let bestN = 0;
      for (const [tool, n] of it.summary.tools) {
        const s = STAGE_OF_TOOL[tool];
        if (s === undefined || n <= 0) continue;
        byId[s].observed = true;
        if (n > bestN || (n === bestN && best !== null && STAGES.indexOf(s) > STAGES.indexOf(best))) {
          best = s;
          bestN = n;
        }
      }
      if (best !== null) byId[best].turns.push({ id: it.id, ts: it.ts, agg: it.summary });
    }
  }
  return { current, basis, stages };
}

export type StageState = "visited" | "current" | "pending";

/** State rests only on direct observation, never pipeline position. */
export function stageState(
  id: StageId,
  current: StageId | null,
  observed: boolean,
): StageState {
  if (id === current) return "current";
  return observed ? "visited" : "pending";
}
