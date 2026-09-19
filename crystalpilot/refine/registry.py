"""Tool registry for the agentic refinement workbench.

Registers the benchmark-validated engine tools that make sense in a
refinement session. Ab-initio solving IS part of the workbench since
round 10 (ingest_vendor_data cold-starts atomless projects): the two
solver routes are solve_charge_flipping (+ interpret_peaks) built-in and
run_shelxt (vendor). Space-group determination stays out of this list -
scale_and_export's screen + check_symmetry/change_space_group cover it
with disclosure discipline. The refinement-specific tools
(inspect/check_ligand/fit_fragment/nodes/...) are added by their own
modules in this package.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

from .. import knowledge_mode as _km
from ..tools.base import ToolRegistry
from ..tools.hydrogen_tools import AddHydrogens, OptimizeWeights
from ..tools.mask_tools import SolventMask
from ..tools.model_tools import (AddAtomsFromDifferenceMap, EditAtoms,
                                 FourierComplete, InterpretPeaks)
from ..tools.refinement_tools import RefineLS
from ..tools.solution_tools import ChargeFlippingSolve, SolveSuperflip
from ..tools.validation_tools import ValidateStructure

#: tools whose success changes the model/flags state -> auto-commit a node
MUTATING_TOOLS = {
    "edit_atoms", "add_atoms_from_difference_map", "fourier_complete",
    "fit_fragment", "accept_fragment_pose", "add_hydrogens", "set_restraints",
    "solvent_mask",
    "optimize_weights", "refine", "run_shelxl", "rename_atoms",
    "model_disorder", "set_twin", "invert_structure", "change_space_group",
    "assemble_asu", "run_shelxt", "interpret_peaks",
    "swap_reflection_data", "set_weights", "set_z",
    "set_resolution_limit",
    "set_adp", "set_afix", "set_site_occupancy",
}

#: tools that work BEFORE reduced data exists (raw-frames stage + brief);
#: everything else is refused while the project is awaiting data
SESSIONLESS_TOOLS = {
    "get_project_brief", "list_nodes",
    "import_frames", "find_spots", "index_frames", "integrate_frames",
    "scale_and_export", "export_twin_hklf5", "create_start_model",
    "import_cif_model",
    "estimate_resolution", "ingest_vendor_data", "set_experiment",
    "reduce_with_crysalis",
    "list_skills", "read_skill", "save_skill", "delete_skill",
    # round-3 WP7: the goal can be written before any data is loaded
    "set_investigation",
}


REFERENCE_TOOLS = {"branch", "checkout"}
DATA_TOOLS = {"swap_reflection_data", "import_cif_model", "create_start_model",
              "ingest_vendor_data"}
COMPOUND_TOOLS = {"ghost_test", "element_scan", "probe_site"}
WORKFLOW_TOOLS = {"import_frames", "find_spots", "index_frames", "integrate_frames",
                  "scale_and_export", "export_twin_hklf5", "reduce_with_crysalis"}
METADATA_TOOLS = {"set_experiment", "set_investigation", "save_skill", "delete_skill"}
ARTIFACT_TOOLS = {"write_outputs", "finalize_delivery", "submit_iucr_checkcif",
                  "consult_specialist"}
DERIVED_TOOLS = {"solve_charge_flipping", "solve_superflip", "inspect_map",
                 "search_fragment_pose", "run_checkcif", "run_olex2", "view_structure"}
INSPECTION_TOOLS = {
    "get_project_brief", "inspect_model", "check_ligand", "validate_structure",
    "list_nodes", "compare_nodes", "get_geometry", "check_symmetry",
    "audit_reflection_data", "integrate_difference_density", "audit_element_assignment",
    "audit_guest_evidence", "audit_heavy_sites", "preflight_restraints", "list_skills",
    "read_skill", "situation_report", "ncs_audit", "screen_space_groups",
    "reflection_statistics", "estimate_resolution", "analyze_packing",
}


@dataclass(frozen=True)
class OperationPolicy:
    kind: str
    auto_commit: bool = False

    @property
    def writes_state(self) -> bool:
        return self.kind in {"model", "reference", "data", "compound", "metadata", "workflow"}


def operation_policy(name: str, params: dict | None = None) -> OperationPolicy:
    """Storage semantics are separate from MCP permission readonly hints."""
    if name == "run_shelxl" and (params or {}).get("mode", "check") == "check":
        return OperationPolicy("derived")
    if name == "set_afix" and (params or {}).get("action") == "list":
        return OperationPolicy("inspection")
    if name == "ingest_vendor_data" and (params or {}).get("list_candidates"):
        return OperationPolicy("inspection")
    for names, kind in ((DATA_TOOLS, "data"), (REFERENCE_TOOLS, "reference"),
                        (COMPOUND_TOOLS, "compound"), (WORKFLOW_TOOLS, "workflow"),
                        (METADATA_TOOLS, "metadata"), (ARTIFACT_TOOLS, "artifact"),
                        (DERIVED_TOOLS, "derived"), (INSPECTION_TOOLS, "inspection")):
        if name in names:
            return OperationPolicy(kind, name in MUTATING_TOOLS)
    if name in MUTATING_TOOLS:
        return OperationPolicy("model", True)
    raise ValueError(f"No project operation policy for tool {name!r}")


class RefinementRegistry(ToolRegistry):
    def specs(self, names=None):
        specs = copy.deepcopy(super().specs(names))
        for spec in specs:
            props = spec["parameters"].setdefault("properties", {})
            props.update({
                "expected_node": {"type": ["string", "null"],
                                  "description": "Optional active-node precondition; alone does not detect ABA."},
                "expected_project_revision": {
                    "type": "integer", "minimum": 0,
                    "description": "Optional project revision, NOT node revision. Use the last result's "
                                   "operation_state.final_project_revision before approval; "
                                   "mismatch refuses without running."},
            })
        return specs


def knowledge_mode() -> str:
    """'full' or 'tools_only' (crystalpilot.knowledge_mode.current). Set per
    MCP process by workbench.core._mcp_overrides from the project setting;
    the tools_only arm gets no skill tools and no skill pointers."""
    return _km.current()


def refinement_registry(project=None) -> ToolRegistry:
    reg = RefinementRegistry()
    for tool in (EditAtoms(), AddAtomsFromDifferenceMap(), FourierComplete(),
                 RefineLS(), AddHydrogens(), OptimizeWeights(),
                 SolventMask(), ValidateStructure(),
                 ChargeFlippingSolve(), SolveSuperflip(), InterpretPeaks()):
        reg.register(tool)
    if project is not None:
        try:
            from .tools_extra import register_refine_tools
        except ImportError:          # M4 tools not built yet
            return reg
        register_refine_tools(reg, project)
        try:
            from .tools_analysis import register_analysis_tools
        except ImportError:          # analysis tools optional
            pass
        else:
            register_analysis_tools(reg, project)
        try:
            from .tools_disorder import register_disorder_tools
        except ImportError:          # disorder/twin tools optional
            pass
        else:
            register_disorder_tools(reg, project)
        try:
            from .tools_frames import register_frames_tools
        except ImportError:          # frames toolchain optional
            return reg
        register_frames_tools(reg, project)
        try:
            from .tools_cap import register_cap_tools
        except ImportError:          # vendor reduction optional
            pass
        else:
            register_cap_tools(reg, project)
        try:
            from .tools_specialist import register_specialist_tools
        except ImportError:          # workbench extra not installed
            pass
        else:
            register_specialist_tools(reg, project)   # opt-in gated inside
        try:
            from .tools_skills import register_skills_tools
        except ImportError:          # skill layer optional
            pass
        else:
            if knowledge_mode() != "tools_only":
                register_skills_tools(reg, project)
        try:
            from .tools_batch import register_batch_tools
        except ImportError:          # batch hypothesis tests optional
            pass
        else:
            register_batch_tools(reg, project)   # ghost_test, element_scan
        try:
            from .tools_probe import register_probe_tools
        except ImportError:          # low-occupancy probe optional
            pass
        else:
            register_probe_tools(reg, project)   # probe_site
    return reg
