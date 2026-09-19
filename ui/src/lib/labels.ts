/** Friendly labels for pipeline stages and engine tools. */

const TOOL_LABELS: Record<string, string> = {
  determine_space_group: "Determining space group",
  set_space_group: "Adopting space group",
  solve_charge_flipping: "Solving structure - charge flipping",
  interpret_peaks: "Building atomic model",
  refine: "Refining model",
  validate_structure: "Validating structure + MOF chemistry",
  edit_atoms: "Editing model",
  add_atoms_from_difference_map: "Recovering atoms from residual density",
  solvent_mask: "Modeling pore solvent",
  snapshot_state: "Branching trajectory",
  restore_state: "Branching trajectory",
};

const STAGE_LABELS: Record<string, string> = {
  load: "Loading diffraction data",
  symmetry: "Symmetry determination",
  solve: "Structure solution",
  interpret: "Model building",
  refine: "Refinement",
  validate: "Validation",
  finalize: "Finalizing",
  agent: "AI agent session",
};

export function toolLabel(tool: string): string {
  return TOOL_LABELS[tool] ?? tool.replace(/_/g, " ");
}

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage.replace(/_/g, " ");
}
