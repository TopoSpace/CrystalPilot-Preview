import { commandActor } from "./humanizeCommand";

export type ActivityGlyph =
  | "solve" | "refine" | "density" | "symmetry" | "molecule" | "geometry"
  | "validation" | "diffraction" | "indexing" | "integration" | "chart" | "branch" | "compare"
  | "book" | "search" | "globe" | "list" | "group" | "file" | "folder"
  | "edit" | "download" | "delivery" | "view" | "user" | "crystal" | "terminal" | "tool";

/** Explicit scientific meanings: outcome never changes a tool's identity.
 * Unknown tools keep a neutral fallback rather than guessing from arguments. */
const SCIENTIFIC: Record<string, ActivityGlyph> = {
  run_shelxt: "solve", solve_charge_flipping: "solve", solve_superflip: "solve", create_start_model: "solve",
  run_shelxl: "refine", refine: "refine", optimize_weights: "refine", set_weights: "refine",
  set_restraints: "refine", set_experiment: "refine", set_resolution_limit: "refine", set_z: "refine",
  inspect_map: "density", integrate_difference_density: "density", fourier_complete: "density",
  solvent_mask: "density", interpret_peaks: "density", add_atoms_from_difference_map: "density",
  check_symmetry: "symmetry", screen_space_groups: "symmetry", change_space_group: "symmetry",
  ncs_audit: "symmetry", set_twin: "symmetry", invert_structure: "symmetry",
  set_afix: "edit", set_adp: "refine", set_site_occupancy: "refine",
  edit_atoms: "edit", rename_atoms: "edit", add_hydrogens: "molecule", assemble_asu: "molecule",
  fit_fragment: "molecule", search_fragment_pose: "molecule", accept_fragment_pose: "molecule", model_disorder: "molecule",
  get_geometry: "geometry", analyze_packing: "geometry", check_ligand: "geometry",
  run_checkcif: "validation", submit_iucr_checkcif: "validation", validate_structure: "validation",
  preflight_restraints: "validation", audit_element_assignment: "validation", audit_guest_evidence: "validation",
  import_frames: "download", import_cif_model: "download", ingest_vendor_data: "download", swap_reflection_data: "download",
  find_spots: "diffraction", index_frames: "indexing", integrate_frames: "integration", reduce_with_crysalis: "diffraction",
  scale_and_export: "chart", audit_reflection_data: "chart", reflection_statistics: "chart", estimate_resolution: "chart",
  branch: "branch", checkout: "branch", list_nodes: "branch", compare_nodes: "compare",
  write_outputs: "delivery", finalize_delivery: "delivery", export_twin_hklf5: "delivery",
  list_skills: "book", read_skill: "book", save_skill: "book", delete_skill: "book", get_project_brief: "book",
  inspect_model: "search", ghost_test: "search", element_scan: "search", probe_site: "search", audit_heavy_sites: "search",
  view_structure: "view", situation_report: "list", set_investigation: "list", consult_specialist: "user", run_olex2: "crystal",
};

const AUXILIARY: Record<string, ActivityGlyph> = {
  read_file: "book", read_resource: "book", read_text_file: "book", read_multiple_files: "book",
  list_directory: "folder", list_files: "folder", directory_tree: "folder",
  search: "search", search_query: "search", search_files: "search", grep: "search",
  web_search: "globe", fetch: "globe", fetch_url: "globe", browse: "globe",
  write_file: "edit", edit_file: "edit", apply_patch: "edit",
  exec_command: "terminal", run_command: "terminal", execute: "terminal", write_stdin: "terminal",
};

export function toolGlyph(tool: string, scientific: boolean): ActivityGlyph {
  return scientific ? SCIENTIFIC[tool] ?? "crystal" : AUXILIARY[tool] ?? "tool";
}

const COMMANDS: Record<string, ActivityGlyph> = {
  shelxt: "solve", shelxs: "solve", shelxl: "refine", platon: "validation",
  sadabs: "chart", twinabs: "chart",
  "dials.import": "download", "dials.find_spots": "diffraction", "dials.index": "indexing",
  "dials.refine": "refine", "dials.integrate": "integration", "dials.scale": "chart", "dials.export": "delivery",
  cat: "book", head: "book", tail: "book", type: "book", "get-content": "book",
  ls: "folder", dir: "folder", gci: "folder", "get-childitem": "folder", "get-item": "folder", "resolve-path": "folder", "test-path": "folder",
  rg: "search", grep: "search", findstr: "search", "select-string": "search",
  cp: "file", copy: "file", xcopy: "file", robocopy: "folder", "copy-item": "file",
  mv: "file", move: "file", "move-item": "file", rm: "file", del: "file", "remove-item": "file",
  mkdir: "folder", md: "folder", "new-item": "file", "set-content": "edit", "out-file": "edit", "add-content": "edit",
  sed: "edit", awk: "edit", curl: "globe", wget: "download", "invoke-webrequest": "globe", git: "branch",
};

export function commandGlyph(raw: string): ActivityGlyph {
  return COMMANDS[commandActor(raw) ?? ""] ?? "terminal";
}

export function genericGlyph(family: string): ActivityGlyph {
  switch (family) {
    case "file_change": return "edit";
    case "webSearch": return "globe";
    case "todoList": return "list";
    case "imageView": return "view";
    case "collab": return "user";
    case "approval_auto": return "validation";
    default: return "tool";
  }
}
