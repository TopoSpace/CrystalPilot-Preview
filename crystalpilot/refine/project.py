"""RefineProject: one crystal, one persistent branchable refinement session.

Project directory layout (controlled working aliases; original sources are archived):

    crystal.hkl            reflection data (any single *.hkl)
    start.res / *.ins      coarse model to start from
    context.json           synthesis priors + optional file overrides:
                           {"chemistry": {...}, "data": {"hkl": "...",
                            "start_model": "..."}}
    .crystalpilot/refine/  NodeStore (nodes/state/data revisions) + event logs

Bound nodes load their own immutable observation package, never the current
working HKL by inference. Legacy unbound nodes remain geometry-readable but
require explicit supplied-data binding into a new node before calculation.
The live SolveSession is rebuilt from disk on open/checkout, so any process
(MCP server restarts included) resumes exactly: model from the node's
model.res; restraints/weights/H metadata from node.json; the solvent mask
from the node's f_mask.pkl snapshot (recomputed from its recorded
parameters only when the snapshot is missing); the difference-map and
charge-flipping peak tables from the node's peaks.json. The reflection
file parse and the merge are memoized on the project handle (same file,
same cell, same space group -> same arrays), so a checkout costs a few
file reads, not a 10 MB hkl re-parse.
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any

from ..core.events import RunStore
from ..tools.base import ToolContext, ToolResult, invoke
from .nodes import NodeStore
from .registry import operation_policy, refinement_registry
from .transactions import (UNSET, TransactionError, TransactionCancelled, locked,
                           project_transaction, validate_expected)
from . import trial_ledger
from .trial_ledger import TRIALED_TOOLS


class ProjectError(RuntimeError):
    pass


class RefineProject:
    def __init__(self, project_dir: str | Path) -> None:
        self.dir = Path(project_dir).resolve()
        if not self.dir.is_dir():
            raise ProjectError(f"project directory does not exist: {self.dir}")
        self.nodes = NodeStore(self.dir)
        self._input_stage = None
        self._context_cache: dict[str, Any] = {}
        self._context_mtime: float | None = None
        self._refresh_context()
        try:
            self.hkl_path, self.start_model_path = self._resolve_inputs()
        except ProjectError:
            # raw-frames project: no reduced data / start model yet. The
            # frames tools produce them, then reload_inputs() activates the
            # refinement session.
            self.hkl_path = self.start_model_path = None
        self.session = None            # SolveSession, built in open()
        self.ctx: ToolContext | None = None
        self.registry = refinement_registry(self)
        self._z: int | None = None
        #: memoized reflection-file parse + merge (see _build_session /
        #: _merge_cached); keyed by file mtime/size, cell and space group
        self._data_cache: dict[str, Any] = {}
        self._loaded_version = None
        self._invocation_depth = 0
        self._operation_started_at = None
        self._pinned_context = None

    def _begin_inputs(self):
        from .data_versions import InputStage
        if self._input_stage is None:
            self._input_stage = InputStage(self)
            self._context_mtime = None
            self._pinned_context = None
        return self._input_stage

    def _end_inputs(self):
        stage = self._input_stage
        if stage is not None and stage.revision:
            self._adopt_published_reflections(stage)
        self._input_stage = None
        self._context_mtime = None
        self._pinned_context = None
        self._refresh_inputs()

    def _adopt_published_reflections(self, stage) -> None:
        """A committed controlled import parsed the STAGED input and then
        published the same bytes as the node's immutable observation
        revision. Re-key the parse and merge caches to the published file
        so the first checkout reuses them instead of parsing and merging
        the whole reflection file again (2026-09-08: one extra parse +
        merge per import, 0.65 s on the 337k-row MOF data). A stage that
        did not commit has no published file and is left alone."""
        from ..io.shelx import rekey_hklf_cache
        from .data_versions import DataBindingRequired, DataVersions
        try:
            published, meta = DataVersions(self.dir).resolve(stage.revision)
        except DataBindingRequired:
            return
        if meta.get("transaction") != stage.token:
            return
        keys = rekey_hklf_cache(self._data_cache, stage.inputs / "crystal.hkl", published)
        merge = self._data_cache.get("merge")
        if keys is not None and merge is not None and merge[0][0] == keys[0]:
            self._data_cache["merge"] = ((keys[1],) + tuple(merge[0][1:]), merge[1])

    def _remember_source(self) -> None:
        from .data_versions import DataVersions
        self._loaded_version = self.nodes.version()
        if self.session is not None:
            self.session._crystalpilot_source = {
                "node": self._loaded_version["node"],
                "project_revision": self._loaded_version["project_revision"]}
            revision = getattr(self.session, "_crystalpilot_data_revision", None)
            if revision:
                self.hkl_path, _ = DataVersions(self.dir).resolve(revision)
                if self.session.dataset is not None:
                    self.session.dataset.source_files[0] = str(self.hkl_path)

    def _discard_session(self) -> None:
        self.session = self.ctx = None
        self._loaded_version = None
        self._input_stage = None
        self._data_cache.clear()
        self._context_mtime = None

    def _refresh_inputs(self) -> None:
        try:
            self.hkl_path, self.start_model_path = self._resolve_inputs()
        except ProjectError:
            self.hkl_path = self.start_model_path = None

    @classmethod
    def create_structure_only(cls, project_dir: str | Path,
                              cif_path: str | Path, *,
                              block_name: str | None = None) -> "RefineProject":
        """Create an explicitly read-only CIF project in an empty external folder.

        Copies the original CIF verbatim; parsing/conversion only affects
        derived model nodes. Published metrics remain reference metadata.
        The selected CIF block is canonical; labels, symmetry settings and
        ADPs are loaded directly, without a required SHELX conversion.
        """
        import shutil
        from .structure_document import load_structure_document

        target = Path(project_dir).resolve()
        repo = Path(__file__).resolve().parents[2]
        if target == repo or repo in target.parents:
            raise ProjectError("Structure projects must live outside the CrystalPilot repository")
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ProjectError("Choose a new or empty directory for the structure-only project")
        target.mkdir(parents=True, exist_ok=True)
        with project_transaction(target, operation="create_structure_only"):
            # The lock creates only .crystalpilot; another creator may have
            # populated the directory between the initial check and acquisition.
            if any(path.name != ".crystalpilot" for path in target.iterdir()):
                raise ProjectError("Choose a new or empty directory for the structure-only project")
            document = load_structure_document(cif_path, block_name=block_name)
            shutil.copyfile(document.source, target / "source.cif")
            context = {
                "mode": "structure_only",
                "data": {"source_cif": "source.cif", "data_block": document.block_name},
                "reported_reference": document.reported_reference,
            }
            (target / "context.json").write_text(
                json.dumps(context, indent=2, ensure_ascii=False), encoding="utf-8")
            project = cls(target)
            project.open()
            return project

    @locked
    def import_structure_only(self, cif_path: str | Path, *,
                              block_name: str | None = None) -> dict[str, Any]:
        """Explicit CIF-only import into an uninitialized external project."""
        import shutil
        from .structure_document import load_structure_document

        repo = Path(__file__).resolve().parents[2]
        if self.dir == repo or repo in self.dir.parents:
            raise ProjectError("Structure projects must live outside the CrystalPilot repository")
        if (self.nodes.state().get("active_node") or self.hkl_path is not None
                or any(self.dir.glob("*.res")) or any(self.dir.glob("*.ins"))
                or any(self.dir.glob("*.hkl"))
                or (self.context.get("data") or {}).get("start_model")):
            raise ProjectError("Use a new project for a read-only CIF import; existing models/nodes/data are not replaced")
        source = Path(cif_path)
        if not source.is_absolute():
            source = self.dir / source
        document = load_structure_document(source, block_name=block_name)
        destination = self.dir / "source.cif"
        if source.resolve() != destination.resolve():
            if destination.exists():
                raise ProjectError("source.cif already exists; choose an empty project")
            shutil.copyfile(source, destination)
        context = {**self.context, "mode": "structure_only",
                   "data": {"source_cif": "source.cif", "data_block": document.block_name},
                   "reported_reference": document.reported_reference}
        (self.dir / "context.json").write_text(
            json.dumps(context, indent=2, ensure_ascii=False), encoding="utf-8")
        self.context = context
        self.hkl_path = self.start_model_path = None
        return self._import_structure_only()

    @property
    def structure_only(self) -> bool:
        if self.session is not None:
            return bool(self.session.flags.get("structure_only"))
        from .structure_document import project_mode_info
        return project_mode_info(self.dir)["mode"] == "structure_only"

    @property
    def capabilities(self) -> dict[str, bool]:
        from .structure_document import project_mode_info, structure_capabilities
        if self.session is None:
            return project_mode_info(self.dir)["capabilities"]
        return structure_capabilities(self.structure_only or bool(self.session.flags.get("data_binding_required")))

    def _structure_summary(self, node_id: str, *, resumed: bool) -> dict[str, Any]:
        meta = self.nodes.node_meta(node_id)
        return {
            "state": "structure_only", "mode": "structure_only", "read_only": True,
            "resumed": resumed, "node": node_id,
            "branch": self.nodes.state().get("active_branch"),
            "revision": meta.get("revision"),
            "n_atoms": self.session.model.scatterers().size(),
            "capabilities": self.capabilities, "data": None,
            "metrics": None, "metrics_current": False, "merge": {},
            "label_renames": meta.get("label_renames") or {},
            "canonical_model": meta.get("canonical_model") or "model.res",
            "block_name": meta.get("block_name"),
            "unknown_adp_labels": list(self.session.flags.get("unknown_adp_labels") or []),
            "note": meta.get("note"),
            "reported_reference": (meta.get("reported_reference")
                                   or self.context.get("reported_reference")),
        }

    @locked
    def _import_structure_only(self) -> dict[str, Any]:
        from ..pipeline.session import SolveSession
        from .structure_document import load_structure_document

        data = self.context.get("data") or {}
        document = load_structure_document(
            self.dir / data["source_cif"], block_name=data.get("data_block"))
        self.session = SolveSession(dataset=None, model=document.structure,
                                    symmetry=document.structure.crystal_symmetry())
        self.session.flags.update({
            "structure_only": True,
            "reported_reference": self.context.get("reported_reference") or document.reported_reference,
            "parts_extra": document.parts,
            "unknown_adp_labels": list(document.unknown_adp_labels),
        })
        self._z = document.z
        self._cell_esd = None
        self.merge_stats = {}
        self.ctx = self._new_ctx()
        from .structure_document import commit_structure_document
        meta = commit_structure_document(self.nodes, self.session, document)
        self._remember_source()
        return self._structure_summary(meta["id"], resumed=False)

    # ------------------------------------------------------------------
    @property
    def context(self) -> dict[str, Any]:
        """context.json content, mtime-fresh.

        A long-lived session must see external edits (mentor backfilling
        experiment metadata, tools updating provenance) without a project
        reopen - round-10 p770 shipped '?' cell-measurement fields because
        the cached copy shadowed a backfilled file."""
        if getattr(self, "_pinned_context", None) is not None:
            return self._pinned_context
        self._refresh_context()
        return self._context_cache

    @property
    def _context_file(self):
        from .data_versions import input_directory
        return input_directory(self) / "context.json"

    @context.setter
    def context(self, value: dict[str, Any]) -> None:
        # direct assignment pins the value until context.json actually
        # changes on disk (tests/tools that patch it keep working; a later
        # file write still refreshes via the getter)
        self._context_cache = value
        if getattr(self, "_pinned_context", None) is not None:
            self._pinned_context = copy.deepcopy(value)
        p = self._context_file
        try:
            self._context_mtime = p.stat().st_mtime if p.exists() else -1.0
        except OSError:
            self._context_mtime = -1.0

    def _refresh_context(self) -> None:
        p = self._context_file
        try:
            mtime = p.stat().st_mtime if p.exists() else -1.0
        except OSError:
            mtime = -1.0
        if mtime == self._context_mtime:
            return
        self._context_cache = self._load_context()
        self._context_mtime = mtime

    def _load_context(self) -> dict[str, Any]:
        p = self._context_file
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                raise ProjectError(f"context.json is not valid JSON: {e}") from e
        return {}

    def _resolve_inputs(self) -> tuple[Path, Path]:
        from .data_versions import input_directory
        directory = input_directory(self)
        data = self.context.get("data") or {}
        hkl = data.get("hkl")
        model = data.get("start_model")
        if hkl:
            hkl_path = directory / hkl
        else:
            cands = sorted(directory.glob("*.hkl"))
            if len(cands) != 1:
                raise ProjectError(
                    f"expected exactly one *.hkl in {self.dir} (found "
                    f"{[c.name for c in cands]}); set data.hkl in context.json")
            hkl_path = cands[0]
        if model:
            model_path = directory / model
        else:
            res = sorted(directory.glob("*.res")) + sorted(directory.glob("*.ins"))
            if not res:
                raise ProjectError(f"no start model (*.res/*.ins) in {self.dir}")
            model_path = res[0]
        if not hkl_path.exists():
            raise ProjectError(f"hkl file missing: {hkl_path}")
        if not model_path.exists():
            raise ProjectError(f"start model missing: {model_path}")
        return hkl_path, model_path

    # ------------------------------------------------------------------
    @locked
    def open(self) -> dict[str, Any]:
        """Build the live session: resume the active node, else import start.
        Raw-frames projects (no reduced data yet) open in an awaiting-data
        state where only the frames/brief tools work."""
        self._refresh_inputs()
        if self.context.get("mode") == "structure_only":
            active = self.nodes.state().get("active_node")
            return (self.checkout(active, _log_tool="resume") if active
                    else self._import_structure_only())
        active = self.nodes.state().get("active_node")
        if active:
            return self.checkout(active, _log_tool="resume")
        if self.hkl_path is None:
            self.ctx = self._new_ctx()
            return {"state": "awaiting_data",
                    "note": "no crystal.hkl / start model yet - process raw "
                            "frames first (import_frames -> ... -> "
                            "create_start_model)"}
        st = self.nodes.state()
        if st["active_node"]:
            return self.checkout(st["active_node"], _log_tool="resume")
        return self._bootstrap_once()

    @locked
    def _bootstrap_once(self) -> dict[str, Any]:
        """Recheck under the permanent OS lock; legacy sentinels are not deleted."""
        st = self.nodes.state()
        if st.get("active_node"):
            return self.checkout(st["active_node"], _log_tool="resume")
        return self._import_start()

    @locked
    def reload_inputs(self) -> dict[str, Any]:
        """Re-resolve data files after the frames pipeline produced them and
        import the start model."""
        if self.context.get("mode") == "structure_only":
            from .structure_document import STRUCTURE_ONLY_PRECONDITION
            raise ProjectError(STRUCTURE_ONLY_PRECONDITION)
        n_before = (self.session.model.scatterers().size()
                    if self.session is not None
                    and self.session.model is not None else 0)
        self._begin_inputs()
        self.hkl_path, self.start_model_path = self._resolve_inputs()
        self._data_cache.clear()       # the data files may have changed
        self.context = self._load_context()
        out = self._import_start()
        n_after = int(out.get("n_atoms") or 0)
        if n_before and n_after < n_before:
            # p770/p780: solve/import produced a real model but the
            # start_model pointer still named the atomless bootstrap ins -
            # reload silently replaced the model with an empty one, twice
            out["warning"] = (
                f"reload REPLACED a {n_before}-atom session model with a "
                f"{n_after}-atom start model "
                f"({Path(self.start_model_path).name}). If you meant to "
                "keep your work, checkout the latest node instead; if the "
                "start_model pointer is stale, update context.json "
                "data.start_model to the solved/imported file.")
        return out

    def _new_ctx(self) -> ToolContext:
        store = RunStore(self.dir / ".crystalpilot" / "refine" / "runs",
                         run_id=time.strftime("session_%Y%m%d_%H%M%S"))
        previous = self.ctx
        with project_transaction(self.dir) as owner:
            return ToolContext(store=store, session=self.session,
                               progress=owner.progress, cancel_event=owner.cancel_event,
                               budget=getattr(previous, "budget", None))

    def _build_session(self, model_path: Path, *, allow_unbound: bool = False,
                       binding_hkl: Path | None = None) -> dict[str, Any]:
        """Rebuild a canonical CIF-only document or a model with real data."""
        from ..io.shelx import load_shelx_dataset
        from ..io.shelx_writer import apply_anomalous_terms
        from ..pipeline.session import SolveSession
        from .structure_document import load_model_document

        parsed = load_model_document(model_path)
        node_meta_path = model_path.with_name("node.json")
        node_meta = (json.loads(node_meta_path.read_text(encoding="utf-8"))
                     if node_meta_path.exists() else {})
        if (node_meta.get("structure_only")
                or node_meta.get("mode") == "structure_only"
                or (not node_meta and self.context.get("mode") == "structure_only")
                or (node_meta.get("tool") == "import_structure_only")):
            xs = parsed.structure
            xs.scattering_type_registry(table="it1992")
            apply_anomalous_terms(xs, getattr(parsed, "wavelength", None))
            self.session = SolveSession(dataset=None, model=xs,
                                        symmetry=xs.crystal_symmetry())
            self.session.flags.update({
                "structure_only": True,
                "parts_extra": node_meta.get("parts_extra") or parsed.parts,
                "unknown_adp_labels": list(getattr(parsed, "unknown_adp_labels",
                                                   node_meta.get("unknown_adp_labels") or [])),
                "reported_reference": node_meta.get("reported_reference")
                                      or self.context.get("reported_reference"),
            })
            self._z = (node_meta.get("model") or {}).get("reported_z")
            self._cell_esd = None
            self.merge_stats = {}
            return {"parsed": parsed, "merge": {}}
        data_meta = {}
        if binding_hkl is not None:
            self.hkl_path = binding_hkl
        elif node_meta:
            from .data_versions import DataVersions, DataBindingRequired
            try:
                self.hkl_path, data_meta = DataVersions(self.dir).for_node(node_meta)
            except DataBindingRequired:
                if not allow_unbound:
                    raise
                xs = parsed.structure
                self.session = SolveSession(dataset=None, model=xs, symmetry=xs.crystal_symmetry())
                self.session.flags["data_binding_required"] = True
                self.merge_stats = {}
                return {"parsed": parsed, "merge": {}}
        dataset = load_shelx_dataset(self.hkl_path, ins_path=model_path,
                                     cache=self._data_cache)
        if dataset.symmetry_hint is None:
            raise ProjectError(f"{model_path.name} carries no LATT/SYMM symmetry")
        ses = SolveSession(dataset=dataset)
        merge_stats = self._merge_cached(ses, dataset)
        xs = parsed.structure
        xs.scattering_type_registry(table="it1992")
        # the f'/f'' the refinement used come back with the model: a
        # rebuild without them is a different scatterer set (Zr K-edge
        # data 2026-09-06: the viewer recount read 2x the refinement
        # mask's electrons on the SAME model.res)
        apply_anomalous_terms(xs, dataset.wavelength
                              or getattr(parsed, "wavelength", None))
        ses.model = xs
        ses.flags["afix_groups"] = copy.deepcopy(getattr(parsed, "afix_groups", []))
        if parsed.hklf != 4:
            ses.flags["hklf"] = parsed.hklf
        if parsed.data_cards:
            ses.flags["data_cards"] = list(parsed.data_cards)
        # ins_elements is bootstrap-time provenance (the start.ins SFAC/UNIT
        # ingest_vendor_data saw), not per-node state - it does not live in
        # any node's model.res once real atoms exist, so it is re-read
        # fresh from context.json on every rebuild (import/checkout/branch)
        # instead of being set once and lost the next time SolveSession()
        # resets .flags to {} (ka1-org: run_shelxt/get_project_brief must
        # still see it after a checkout).
        bound_context = data_meta.get("input_context") if node_meta else self.context
        ins_elements = ((bound_context or {}).get("data") or {}).get("ins_elements")
        if ins_elements:
            ses.flags["ins_elements"] = ins_elements
        self.session = ses
        ses._crystalpilot_data_revision = node_meta.get("data_revision") if binding_hkl is None else None
        ses._crystalpilot_data_manifest = data_meta
        self._z = parsed.z
        self._cell_esd = parsed.cell_esd
        # experimental metadata riding in the model file (TEMP/SIZE cards)
        self._model_experiment = {
            k: v for k, v in (("temperature_K", parsed.temperature_K),
                              ("crystal_size", parsed.crystal_size)) if v}
        if isinstance(node_meta.get("experiment"), dict):
            self._model_experiment = copy.deepcopy(node_meta["experiment"])
        ses._crystalpilot_experiment = copy.deepcopy(self._model_experiment)
        self.merge_stats = merge_stats
        return {"parsed": parsed, "merge": merge_stats}

    def _merge_cached(self, ses, dataset) -> dict[str, Any]:
        """ses.set_symmetry(dataset.symmetry_hint), memoized per
        (reflection file, cell, space group).

        The merge is the second half of the work every checkout/branch
        repeated for nothing (pa1: 730 switches; 0.1 s each on the 337k-row
        MOF data, on top of the 0.55 s hkl re-parse now cached in
        read_hklf_arrays). Its result is a pure function of the key, so a
        hit restores symmetry/fo_sq/merge_info from deep copies - a tool
        that later filters or replaces ses.fo_sq never touches the cache."""
        from ..io.shelx import _hklf_file_key
        sym = dataset.symmetry_hint
        key = None
        try:
            fkey = _hklf_file_key(Path(self.hkl_path), dataset.intensities)
            if fkey is not None:
                key = (fkey, int(dataset.intensities.size()),
                       tuple(op.as_xyz() for op in sym.space_group().all_ops()))
        except Exception:  # noqa: BLE001 - the cache is an optimisation only
            key = None
        hit = self._data_cache.get("merge") if key is not None else None
        if hit is not None and hit[0] == key:
            cs, fo_sq, stats = hit[1]
            ses.symmetry = cs
            ses.fo_sq = fo_sq.deep_copy()
            ses.merge_info = dict(stats)
            return dict(stats)
        stats = ses.set_symmetry(sym)
        if key is not None:
            self._data_cache["merge"] = (
                key, (ses.symmetry, ses.fo_sq.deep_copy(), dict(stats)))
        return stats

    @staticmethod
    def _h_replay_is_lossless(model, parsed) -> bool:
        """True when strip+re-place via add_hydrogens cannot lose H: every H
        in the model is covered by a re-derivable riding group and none is
        split-occupancy (PART / FVAR-coded sof). Live CD-MOF failure mode:
        replay turned 400 atoms into 345."""
        if getattr(parsed, "afix_groups", None):
            return False  # retain the imported rigid-group/H ordering
        h_labels = {sc.label.upper() for sc in model.scatterers()
                    if sc.scattering_type.strip().upper() == "H"}
        if not h_labels:
            return True
        covered: set[str] = set()
        for g in (parsed.h_riding or []):
            if g.get("kind") is None:
                return False
            covered.update(h.upper() for h in g.get("h", []))
        if h_labels - covered:
            return False
        for coded in (parsed.sof_codes or {}), (parsed.parts or {}):
            if any(lbl.upper() in h_labels for lbl in coded):
                return False
        return True

    @locked
    def _import_start(self) -> dict[str, Any]:
        from .restraints import parse_shelx_cards

        self._begin_inputs()
        self.hkl_path, self.start_model_path = self._resolve_inputs()
        built = self._build_session(self.start_model_path)
        parsed = built["parsed"]
        ses = self.session
        ses.flags["weights"] = {"a": parsed.weights[0], "b": parsed.weights[1]}
        if parsed.scale:
            ses.flags["scale_k"] = float(parsed.scale) ** 2
        specs, warns = parse_shelx_cards(parsed.restraint_lines)
        if specs:
            ses.flags["restraints"] = specs
        # WP2: EADP/EXYZ/SAME/SUMP in the start model are constraints the
        # deposit was refined with - carried as effective cards instead of
        # "kept as text" (which meant dropped)
        from .shelx_cards import effective_cards_from_lines
        eff_cards, eff_warns = effective_cards_from_lines(
            parsed.restraint_lines, ses.model)
        if eff_cards:
            ses.flags["effective_cards"] = eff_cards
            ses.flags["effective_cards_job"] = "import"
        warns = list(warns) + eff_warns
        from .nodes import disorder_from_parsed, loose_parts_from_parsed
        dg, twin = disorder_from_parsed(parsed)
        if dg:
            ses.flags["disorder_groups"] = dg
        loose = loose_parts_from_parsed(parsed, dg)
        if loose:
            ses.flags["parts_extra"] = loose
        if twin:
            ses.flags["twin"] = twin
        self.ctx = self._new_ctx()
        h_note = None
        if parsed.h_riding and getattr(self, "_import_h_policy",
                                       "rederive") == "keep":
            # Deposited-model import (import_cif_model): keep H verbatim -
            # restraint cards reference the deposit's H labels and the
            # positions are part of the refinement being validated. AFIX
            # groups round-trip through h_riding_meta so SHELX jobs stay
            # riding; the in-process engine treats them as free atoms.
            ses.flags["h_riding_meta"] = {
                "per_carrier": parsed.h_riding,
                "elements": sorted({g["carrier"][:1].upper()
                                    for g in parsed.h_riding})}
            h_note = (f"kept the deposit's H verbatim "
                      f"({len(parsed.h_riding)} AFIX groups preserved for "
                      f"SHELX round-trip; in-process refine treats H as "
                      f"free - add_hydrogens re-derives riding constraints "
                      f"if needed)")
        elif parsed.h_riding and self._h_replay_is_lossless(ses.model, parsed):
            # H in the start model: re-place so riding constraints exist -
            # per carrier, keeping the file's H labels (replay_riding_h)
            from .tools_shelxl import replay_riding_h
            elements = sorted({g["carrier"][:1].upper() for g in parsed.h_riding
                               if g["carrier"][:1].upper() in ("C", "N", "O")}) or ["C"]
            rep = replay_riding_h(self.registry, self.ctx, ses,
                                  parsed.h_riding, {"elements": elements})
            h_note = (f"riding H from the start model's "
                      f"{len(parsed.h_riding)} AFIX groups: "
                      f"{rep.get('h_replay_note', 'replayed')}")
        elif parsed.h_riding:
            # split-occupancy / special-AFIX H present: re-placement would
            # silently drop them - keep the model's H verbatim instead
            ses.flags["h_riding_meta"] = {
                "per_carrier": parsed.h_riding,
                "elements": sorted({g["carrier"][:1].upper()
                                    for g in parsed.h_riding})}
            h_note = ("kept the start model's H verbatim (split/special H "
                      "present; in-process refine treats them as free atoms)")
        ses._crystalpilot_experiment = copy.deepcopy(self.experiment())
        self._input_stage.prepare(ses)
        meta = self.nodes.commit(
            ses, tool="import",
            params={"start_model": self.start_model_path.name},
            note="; ".join(x for x in [
                f"imported {self.start_model_path.name}",
                h_note,
                (f"{len(getattr(parsed, 'afix_groups', []))} non-H AFIX groups preserved; "
                 "use SHELXL to refine their geometry") if getattr(parsed, "afix_groups", None) else None,
                f"{len(specs)} restraint card(s)" if specs else None,
                ("restraint warnings: " + "; ".join(warns)) if warns else None,
            ] if x),
            wavelength=parsed.wavelength, z=parsed.z,
            cell_esd=parsed.cell_esd)
        self._end_inputs()
        self._remember_source()
        return {"resumed": False, "node": meta["id"], "merge": built["merge"],
                "n_atoms": ses.model.scatterers().size()}

    # ------------------------------------------------------------------
    @locked
    def checkout(self, ref: str, _log_tool: str = "checkout", *,
                 expected_node=UNSET, expected_project_revision=UNSET) -> dict[str, Any]:
        validate_expected(self.nodes.state(), expected_node=expected_node,
                          expected_project_revision=expected_project_revision)
        self._refresh_inputs()
        out = self._load_node(ref)
        if _log_tool != "resume":
            self.nodes.set_active(out["node"])
        self._remember_source()
        out["branch"] = self.nodes.state().get("active_branch")
        out["project_revision"] = self._loaded_version["project_revision"]
        return out

    def _load_node(self, ref: str, *, binding_hkl: Path | None = None) -> dict[str, Any]:
        node_id = self.nodes.resolve(ref)
        meta = self.nodes.node_meta(node_id)
        built = self._build_session(self.nodes.node_dir(node_id) / "model.res",
                                    allow_unbound=True, binding_hkl=binding_hkl)
        ses = self.session
        if ses.flags.get("data_binding_required"):
            parsed = built["parsed"]
            ses.flags.update(parts_extra=meta.get("parts_extra") or getattr(parsed, "parts", {}) or {},
                             disorder_groups=meta.get("disorder_groups") or [],
                             weights=meta.get("weights"), twin=meta.get("twin"))
            self._z = getattr(parsed, "z", None)
            self.ctx = self._new_ctx()
            return {"state": "binding_required", "data_binding": "legacy_unknown",
                    "node": node_id, "resumed": True, "metrics": meta.get("metrics"),
                    "metrics_current": False, "n_atoms": ses.model.scatterers().size(),
                    "note": "Geometry and recorded evidence are available; explicitly bind matching HKL before reflection calculations"}
        if self.structure_only:
            self.ctx = self._new_ctx()
            return self._structure_summary(node_id, resumed=True)
        ses._crystalpilot_metrics_source = copy.deepcopy(meta.get("metrics_source"))
        ses._crystalpilot_mask_revision = meta.get("mask_revision")
        ses.flags["weights"] = meta.get("weights") or {"a": 0.1, "b": 0.0}
        if meta.get("scale_k"):
            ses.flags["scale_k"] = meta["scale_k"]
        if meta.get("restraints"):
            ses.flags["restraints"] = meta["restraints"]
        if meta.get("disorder_groups"):
            ses.flags["disorder_groups"] = meta["disorder_groups"]
        if meta.get("disorder_origins"):
            # model_disorder(undo=...) needs the pre-split state; without
            # this line a checkout silently makes every split permanent
            ses.flags["disorder_origins"] = meta["disorder_origins"]
        if meta.get("parts_extra"):
            ses.flags["parts_extra"] = meta["parts_extra"]
        if meta.get("twin"):
            ses.flags["twin"] = meta["twin"]
        eff = (meta.get("effective_state") or {})
        if eff.get("cards"):
            # WP2: the cards the node was refined with come back with it,
            # so the next SHELXL job refines the same model
            ses.flags["effective_cards"] = list(eff["cards"])
            if (eff.get("source") or {}).get("job"):
                ses.flags["effective_cards_job"] = eff["source"]["job"]
        self.ctx = self._new_ctx()
        notes = []
        hyd = meta.get("hydrogens") or {}
        # add_hydrogens replay STRIPS every H then re-places only re-derivable
        # riding geometries - split-occupancy / special-AFIX H are silently
        # lost (live CD-MOF failure: 400 -> 345 atoms on every checkout).
        # The node's model.res serializes all H verbatim, so replay only when
        # provably lossless; otherwise keep the loaded H and restore the
        # riding metadata for SHELX round-trip (in-process refine treats
        # them as free atoms - same as the import 'keep' policy).
        parsed = built["parsed"]
        n_h = sum(1 for sc in ses.model.scatterers()
                  if sc.scattering_type.strip().upper() == "H")
        if n_h and not self._h_replay_is_lossless(ses.model, parsed):
            if parsed.h_riding:
                ses.flags["h_riding_meta"] = {
                    "per_carrier": parsed.h_riding,
                    "elements": sorted({g["carrier"][:1].upper()
                                        for g in parsed.h_riding})}
            notes.append(
                f"kept {n_h} H verbatim (split-occupancy/special "
                f"H present - re-placement would lose them); in-process "
                f"refine treats H as free atoms")
        elif hyd.get("present"):
            # same per-carrier replay as run_shelxl adopt: replaces the
            # node's riding H in place (no duplicates, no H on carriers the
            # node left bare, labels kept) - see replay_riding_h
            from .tools_shelxl import replay_riding_h
            rep = replay_riding_h(self.registry, self.ctx, ses,
                                  parsed.h_riding,
                                  {"elements": hyd.get("elements") or ["C"]})
            notes.append(rep.get("h_replay_note") or "riding H replayed")
            if rep.get("h_replay_warning"):
                notes.append(rep["h_replay_warning"])
        mask = meta.get("mask") if binding_hkl is None else None
        if mask and mask.get("params") is not None:
            if self._restore_mask_snapshot(node_id):
                notes.append("solvent mask restored from the node snapshot")
            else:
                res = invoke(self.registry, self.ctx, "solvent_mask",
                             mask["params"])
                if res.ok:
                    notes.append("solvent mask recomputed")
                else:
                    notes.append(f"solvent mask recompute FAILED: {res.error}")
        peaks_note = self._restore_peaks(node_id) if binding_hkl is None else None
        if binding_hkl is not None:
            ses._crystalpilot_parent_node = node_id
        if peaks_note:
            notes.append(peaks_note)
        return {"resumed": True, "node": node_id,
                "branch": self.nodes.state().get("active_branch"),
                "n_atoms": ses.model.scatterers().size(),
                "metrics": meta.get("metrics"),
                "metrics_current": meta.get("metrics_current", False),
                "peaks": meta.get("peaks"),
                "notes": notes, "merge": built["merge"]}

    def _restore_peaks(self, node_id: str) -> str | None:
        """Put the node's saved peak tables (peaks.json) back into the
        fresh session; returns the checkout note or None.

        pa1: every branch/checkout rebuilt the session without them, so
        add_atoms_from_difference_map(peak_indices) failed 7x and
        interpret_peaks(metal_override=...) 4x right after a branch -
        each paid with a re-refine or a 12-50 s charge-flipping re-run."""
        doc = self.nodes.load_peaks(node_id)
        if not doc:
            return None
        ses = self.session
        parts = []
        dm = doc.get("diff_map") or {}
        from ..tools.twin_maps import MAP_ALGORITHM_VERSION
        if ((ses.flags.get("twin") or int(ses.flags.get("hklf") or 4) == 5)
                and dm.get("source") != "run_shelxl"
                and (dm.get("map_provenance") or {}).get("algorithm_version") != MAP_ALGORITHM_VERSION):
            dm = {}
            parts.append("legacy map did not record twin handling; run inspect_map for current density")
        if dm.get("peaks"):
            ses.flags["diff_map_peaks"] = list(dm["peaks"])
            ses.flags["diff_map_peaks_meta"] = {
                "source": dm.get("source"),
                "map_provenance": dm.get("map_provenance"),
                "node": dm.get("computed_on") or node_id,
                "max": dm.get("max"), "min": dm.get("min")}
            parts.append(f"{len(dm['peaks'])} difference-map peaks "
                         f"({dm.get('source')} on "
                         f"{dm.get('computed_on') or node_id})")
        cf = doc.get("charge_flipping") or {}
        if cf.get("peak_sites"):
            ses.cf_info = {
                **{k: v for k, v in cf.items()
                   if k not in ("peak_sites", "peak_heights")},
                "peak_sites": [tuple(float(x) for x in s)
                               for s in cf["peak_sites"]],
                "peak_heights": [float(h) for h in
                                 (cf.get("peak_heights") or [])]}
            parts.append(f"{len(cf['peak_sites'])} "
                         f"{cf.get('engine') or 'charge-flipping'} peaks "
                         f"for interpret_peaks")
        if not parts:
            return None
        return "peak table restored from the node: " + ", ".join(parts)

    def _restore_mask_snapshot(self, node_id: str) -> bool:
        """Load the node's cached f_mask instead of recomputing it.

        The snapshot is only trusted when every reflection of the live
        fo_sq has a mask value (same data, same merge); otherwise the
        caller falls back to the parameter-driven recompute."""
        path = self.nodes.node_dir(node_id) / "f_mask.pkl"
        if not path.exists() or self.session is None \
                or self.session.fo_sq is None:
            return False
        try:
            from libtbx import easy_pickle
            snap = easy_pickle.load(str(path))
            f_mask = snap["f_mask"]
            fo_sq = self.session.fo_sq
            if fo_sq.lone_set(f_mask).size() != 0:
                return False
            self.session.flags["f_mask"] = f_mask.matching_set(
                other=fo_sq, data_substitute=0j)
        except Exception:  # noqa: BLE001 - any doubt: recompute
            return False
        if snap.get("info") is not None:
            self.session.flags["solvent_mask_info"] = snap["info"]
        if snap.get("params") is not None:
            self.session.flags["solvent_mask_params"] = snap["params"]
        self.session._crystalpilot_mask_object = self.session.flags.get("f_mask")
        return True

    # ------------------------------------------------------------------
    def invoke_tool(self, name: str, params: dict[str, Any] | None = None,
                    progress: Any = None, cancel_event: Any = None, *,
                    lock_timeout_s: float = 1800.0) -> ToolResult:
        """Own read/preflight/compute/publication, including readonly invocations.

        Explicit expected_project_revision binds a request to observed project
        state. Omitted tokens reload stale memory, not upstream stale approvals.
        Independent diagnostic child commits survive a later outer failure.
        """
        from ..tools.base import attach_status, status_of
        from .input_undo import InputUndo

        params = dict(params or {})
        expected_node = params.pop("expected_node", UNSET)
        expected_revision = params.pop("expected_project_revision", UNSET)
        try:
            with project_transaction(self.dir, operation=name, timeout_s=lock_timeout_s,
                                     progress=progress, cancel_event=cancel_event) as owner:
                validate_expected(self.nodes.state(), expected_node=expected_node,
                                  expected_project_revision=expected_revision)
                policy = operation_policy(name, params)
                top_level = self._invocation_depth == 0
                if top_level and self._loaded_version != self.nodes.version():
                    self._discard_session()
                if self.session is None:
                    self.open()
                if not top_level and self.session is not None:
                    # Branch-name changes can keep a deliberately edited live
                    # model, but moving to a different node requires loading it.
                    loaded = getattr(self.session, "_crystalpilot_source", None)
                    active = self.nodes.state()["active_node"]
                    if loaded and loaded["node"] != active:
                        self.checkout(active, _log_tool="resume")
                    else:
                        self._remember_source()
                before = self.nodes.state()
                source = self.nodes.version()
                undo = InputUndo(self, data=policy.kind == "data") if policy.writes_state else None
                previous_context = self._pinned_context
                if policy.kind == "data" and not params.get("structure_only"):
                    self._begin_inputs()
                self._pinned_context = copy.deepcopy(self.context)
                self._invocation_depth += 1
                checkpoint = undo.checkpoint if undo is not None else None
                if checkpoint is not None:
                    owner.commit_hooks.append(checkpoint)
                keep_undo = False
                try:
                    if top_level:
                        self._operation_started_at = time.time()
                    try:
                        result = self._invoke_locked(name, params, progress,
                                                     owner.cancel_event)
                    except Exception as exc:
                        result = self._transaction_failure(exc)
                    if (owner.cancel_event is not None and owner.cancel_event.is_set()
                            and not self.nodes.state()["seq"] > before["seq"]):
                        result.ok = False
                        result.error = "Operation cancelled before publication"
                        attach_status(result, "cancelled")
                    if not status_of(result):
                        attach_status(result, "ran" if result.ok else "failed")
                    execution = status_of(result).get("execution")
                    failed = not result.ok or execution == "cancelled"
                    after = self.nodes.state()
                    committed = ["n%04d" % i for i in range(before["seq"], after["seq"])]
                    if failed:
                        result.ok = False
                        if committed:
                            result.summary.update(partial=True, committed_nodes=committed)
                        if undo is not None:
                            undo.restore()
                        if not committed:
                            self.nodes.restore_refs(before)
                        self._pinned_context = None
                        # Supervised charge flipping never mutates the live
                        # session on failure. Reconstructing a large mask here
                        # would itself exceed the solver's advertised budget.
                        keep_session = name == "solve_charge_flipping" and not committed
                        if not keep_session:
                            self._discard_session()
                            cancelled = (execution == "cancelled" or
                                         owner.cancel_event is not None and owner.cancel_event.is_set())
                            # A stopped advisor must release ownership promptly,
                            # not rebuild mask/H state during cleanup.
                            defer_rebuild = cancelled or name == "consult_specialist"
                            if self.nodes.state().get("active_node") and not defer_rebuild:
                                self.checkout(self.nodes.state()["active_node"], _log_tool="resume")
                    elif undo is not None and undo.changed() and after == before:
                        self.nodes.touch()
                    if self._input_stage is not None:
                        self._end_inputs()
                    self._remember_source()
                    result.summary["operation_state"] = {
                        "source_node": source["node"], "model_revision": source["revision"],
                        "project_revision": source["project_revision"],
                        "data_revision": source.get("data_revision"),
                        "final_node": self._loaded_version["node"],
                        "final_data_revision": self._loaded_version.get("data_revision"),
                        "final_project_revision": self._loaded_version["project_revision"],
                        "isolation": "serialized_project_lock",
                    }
                    self._note_state_change(result, before["active_node"], None)
                    env = status_of(result)
                    if committed:
                        env["state_changed"].update(changed=True,
                            revision_after=self._loaded_version["revision"])
                    elif self.nodes.state() != before:
                        env["state_changed"]["changed"] = True
                    return result
                except Exception as exc:
                    self._discard_session()
                    failure = self._transaction_failure(exc)
                    try:
                        after = self.nodes.state()
                    except Exception as recovery_error:
                        # We still own the project lock. The atomic state file is
                        # authoritative even while compatibility aliases are blocked.
                        after = self.nodes._read_state()
                        failure.summary["recovery_error"] = str(recovery_error)
                    retained = ["n%04d" % i for i in range(before["seq"], after["seq"])]
                    failure.summary.update(recovery_required=True, committed_nodes=retained)
                    status_of(failure)["state_changed"].update(
                        changed=after != before, node_before=before["active_node"],
                        node_after=after["active_node"])
                    if undo is not None:
                        keep_undo = True
                        failure.artifacts["input_undo"] = str(undo.directory)
                    return failure
                finally:
                    if checkpoint is not None:
                        owner.commit_hooks.remove(checkpoint)
                    self._invocation_depth -= 1
                    if self._invocation_depth == 0:
                        self._operation_started_at = None
                    self._pinned_context = (copy.deepcopy(self._context_cache)
                                            if previous_context is not None else None)
                    if self._invocation_depth == 0 and self.ctx is not None:
                        self.ctx.progress = self.ctx.cancel_event = self.ctx.budget = None
                    if undo is not None and not keep_undo:
                        try:
                            undo.close()
                        except OSError:
                            # A cleanup error after the commit point must not
                            # turn a committed result into a retryable failure.
                            result.artifacts["input_undo_cleanup"] = str(undo.directory)
        except Exception as exc:
            return self._transaction_failure(exc)

    @staticmethod
    def _transaction_failure(exc: Exception) -> ToolResult:
        from ..tools.base import attach_status
        result = ToolResult.failure(f"{type(exc).__name__}: {exc}")
        if isinstance(exc, TransactionError):
            result.summary["transaction_error"] = {"code": exc.code, **exc.details}
        env = attach_status(result, "cancelled" if isinstance(exc, TransactionCancelled) else "failed")
        env["state_changed"] = {"changed": False, "node_before": None,
                                "node_after": None, "revision_after": None}
        return result

    def _invoke_locked(self, name: str, params: dict[str, Any] | None = None,
                       progress: Any = None,
                       cancel_event: Any = None) -> ToolResult:
        """Run a registry tool; auto-commit a node after successful mutations.

        progress: optional callable(str) heartbeat sink, forwarded to the
        tool via ToolContext (long DIALS stages report liveness there).
        cancel_event: optional threading.Event the MCP server sets when the
        client gave up on the call; budgeted loops poll it and stop at a
        consistent point (crystalpilot/mcp/CANCELLATION_NOTES.md)."""
        from .registry import SESSIONLESS_TOOLS
        if self.session is None:
            self.open()
        if self.session is None and name not in SESSIONLESS_TOOLS:
            return ToolResult.failure(
                f"'{name}' needs reduced data, but this project has no "
                "crystal.hkl / start model yet. Process the raw frames first "
                "(import_frames -> find_spots -> index_frames -> "
                "integrate_frames -> scale_and_export -> create_start_model).")
        params = params or {}
        if self.session is not None and self.session.flags.get("data_binding_required"):
            if name == "get_project_brief":
                return ToolResult(ok=True, summary={
                    "state": "binding_required", "data_binding": "legacy_unknown",
                    "node": self.nodes.state()["active_node"],
                    "model": self.session.model_summary(),
                    "metrics_current": False,
                    "note": "Geometry is available. Supply matching HKL via swap_reflection_data(model_node=..., hkl=..., reason=...) before reflection calculations."})
            allowed = {"inspect_model", "get_geometry", "analyze_packing", "view_structure",
                       "list_nodes", "checkout", "compare_nodes", "list_skills", "read_skill",
                       "swap_reflection_data", "import_cif_model", "ingest_vendor_data", "set_experiment"}
            if name not in allowed:
                from .data_versions import DataBindingRequired
                return self._transaction_failure(DataBindingRequired("Historical reflection data is unknown; bind matching HKL explicitly"))
        if self.structure_only:
            from .structure_document import STRUCTURE_ONLY_PRECONDITION
            if name == "get_project_brief":
                active = self.nodes.state()["active_node"]
                return ToolResult(ok=True, summary={
                    **self._structure_summary(active, resumed=True),
                    "active_node": active,
                    "model": self.session.model_summary(),
                    "space_group": str(self.session.model.space_group_info()),
                    "synthesis_priors": self.context.get("chemistry") or {},
                    "note": STRUCTURE_ONLY_PRECONDITION,
                })
            geometry_tools = {
                "inspect_model", "get_geometry", "check_symmetry", "ncs_audit",
                "check_ligand", "analyze_packing", "view_structure", "list_nodes",
                "checkout", "compare_nodes", "list_skills", "read_skill", "consult_specialist",
            }
            explicit_data_import = name == "import_cif_model" and params.get("hkl_path")
            if name not in geometry_tools and not explicit_data_import:
                return ToolResult.failure(STRUCTURE_ONLY_PRECONDITION)
        call_ctx = self.ctx
        previous_channels = (call_ctx.progress, call_ctx.cancel_event, call_ctx.budget)
        call_ctx.progress = progress
        call_ctx.cancel_event = cancel_event
        ses = self.session
        measured_before = ses.last_refinement() if ses is not None else None
        peaks_before = ((ses, ses.flags.get("diff_map_peaks"), ses.cf_info)
                        if ses is not None else (None, None, None))
        active_before = self._active_node_or_none()
        # round-3 WP7: "this exact call already ran on this node" - looked up
        # before the call, attached after it; the memo informs, never refuses
        trial_prior = None
        if name in TRIALED_TOOLS:
            try:
                trial_prior = trial_ledger.lookup(
                    self.dir, name, params, active_before,
                    trial_ledger.ancestor_chain(self.nodes, active_before))
            except Exception:  # noqa: BLE001 - a memo never blocks a tool
                trial_prior = None
        try:
            result = invoke(self.registry, call_ctx, name, params)
        finally:
            call_ctx.progress, call_ctx.cancel_event, call_ctx.budget = previous_channels
        if result.ok and name == "set_experiment":
            state = self.nodes.state()
            revision = state.get("active_data_revision")
            if revision and (state.get("working_experiments") or {}).get(revision) != self.experiment():
                self.nodes.touch(experiment=self.experiment())
        if result.ok and name == "get_project_brief":
            state = self.nodes.state()
            saved = (state.get("working_experiments") or {}).get(state.get("active_data_revision"))
            if saved is not None:
                result.summary["saved_experiment_notes"] = {"data_revision": state.get("active_data_revision"),
                    "values": saved, "note": "Working metadata retained separately; not applied retroactively to recorded node metrics"}
        if (result.ok and self.session is not None
                and self.session.last_refinement() is not None
                and self.session.last_refinement() is not measured_before):
            from .data_versions import measurement_context
            self.session._crystalpilot_new_measurement = measurement_context(self.session, name, result.summary)
        peaks_refreshed = self._note_peak_refresh(name, result, peaks_before)
        committed_meta: dict[str, Any] | None = None
        from ..tools.base import status_of
        if (result.ok and operation_policy(name, params).auto_commit
                and status_of(result).get("execution") != "cancelled"
                and not result.summary.get("no_state_change")):
            if self._input_stage is not None:
                self._input_stage.prepare(self.session)
            # expert-review guard: after any step that changes model quality,
            # surface ASU red flags (detached fragments / ghost atoms) right
            # in the tool result so the agent cannot miss them
            if name in ("refine", "run_shelxl", "add_atoms_from_difference_map",
                        "fourier_complete", "fit_fragment",
                        "accept_fragment_pose"):
                try:
                    from ..chem.asu_sanity import asu_coherence
                    asu = asu_coherence(self.session.model)
                    if asu["ghost_suspects"] or asu["n_detached_atoms"]:
                        result.summary["asu_sanity"] = {
                            "n_detached_atoms": asu["n_detached_atoms"],
                            "ghost_suspects": asu["ghost_suspects"],
                            "advice": ("run assemble_asu before delivery; "
                                       "ghost suspects need a delete-and-"
                                       "refine test - do not keep chemistry-"
                                       "free atoms to lower R1"),
                        }
                except Exception:  # noqa: BLE001 - advisory only
                    pass
            self.session._crystalpilot_experiment = copy.deepcopy(self.experiment())
            meta = self.nodes.commit(
                self.session, tool=name, params=params,
                summary=result.summary,
                wavelength=self.session.dataset.wavelength, z=self._z,
                cell_esd=getattr(self, "_cell_esd", None))
            result.summary["node"] = meta["id"]
            result.summary["branch"] = meta["branch"]
            committed_meta = meta
        elif result.ok and peaks_refreshed and status_of(result).get("execution") != "cancelled":
            self._sync_peaks_to_active(result)
        self._note_state_change(result, active_before, committed_meta)
        if name in TRIALED_TOOLS:
            try:
                trial_ledger.annotate(result, trial_prior)
                if result.ok:
                    trial_ledger.record(self.dir, name, params, active_before,
                                        self.nodes, result)
            except Exception:  # noqa: BLE001 - a memo never blocks a tool
                pass
        return result

    def _active_node_or_none(self) -> str | None:
        try:
            return self.nodes.state().get("active_node")
        except Exception:  # noqa: BLE001 - a status field never blocks a tool
            return None

    def _note_state_change(self, result: ToolResult, before: str | None,
                           meta: dict[str, Any] | None) -> None:
        """Round-3 WP1: the envelope's state_changed, from the one place
        that knows - the node store. A commit is a change; so is a moved
        active pointer without a commit (checkout / branch); a tool that
        ran and left both alone is `changed: False` even when ok."""
        from ..tools.base import STATUS_KEY
        env = (result.summary.get(STATUS_KEY)
               if isinstance(result.summary, dict) else None)
        if not isinstance(env, dict):
            return
        after = self._active_node_or_none()
        env["state_changed"] = {
            "changed": meta is not None or after != before,
            "node_before": before,
            "node_after": after,
            "revision_after": meta.get("revision") if meta else None,
        }

    def _note_peak_refresh(self, name: str, result: ToolResult,
                           before: tuple) -> bool:
        """Did the tool replace a peak table? Records the provenance of a
        new difference-map table (tool + map extremes; the node is pinned
        by the first save) so every consumer can tell which model the
        indices belong to."""
        ses = self.session
        if ses is None or ses is not before[0]:
            # a rebuilt session (checkout / branch / reload) carries tables
            # RESTORED from a node, not new ones - relabelling them with
            # this tool's name would lose their provenance
            return False
        diff_now = ses.flags.get("diff_map_peaks")
        refreshed = False
        if diff_now is not before[1]:
            refreshed = True
            if diff_now:
                ses.flags["diff_map_peaks_meta"] = {
                    "source": name, "node": None,
                    "map_provenance": result.summary.get("map_provenance"),
                    "max": result.summary.get("diff_map_max"),
                    "min": result.summary.get("diff_map_min")}
            else:
                ses.flags.pop("diff_map_peaks_meta", None)
        if ses.cf_info is not before[2]:
            refreshed = True
        return refreshed

    def _sync_peaks_to_active(self, result: ToolResult) -> None:
        """A tool that commits no node (inspect_map, solve_charge_flipping,
        solve_superflip) refreshed a peak table: save it with the active
        node so branch/checkout bring it back. Best-effort; the summary
        names the file only when the save succeeded."""
        active = self.nodes.state().get("active_node")
        if not active or self.session is None:
            return
        try:
            block = self.nodes.save_peaks(active, self.session,
                                          update_meta=True)
        except Exception:  # noqa: BLE001 - persistence must not fail the tool
            return
        if block is not None:
            result.summary["peak_table_saved"] = {
                "node": active,
                "file": f".crystalpilot/refine/nodes/{active}/"
                        f"{self.nodes.PEAKS_FILE}",
                "restored_by": "checkout / branch", **block}

    # ------------------------------------------------------------------
    def experiment(self) -> dict[str, Any]:
        """Experimental metadata: context.json `experiment` block wins over
        TEMP/SIZE cards found in the start model."""
        if (self.session is not None and getattr(self.session, "_crystalpilot_data_revision", None)
                and "experiment" in self.context):
            return copy.deepcopy(self.context.get("experiment") or {})
        exp = dict(getattr(self, "_model_experiment", {}) or {})
        for k, v in (self.context.get("experiment") or {}).items():
            exp[k] = v
        return exp

    # ------------------------------------------------------------------
    @locked
    def compare_nodes(self, ref_a: str, ref_b: str) -> dict[str, Any]:
        a_id, b_id = self.nodes.resolve(ref_a), self.nodes.resolve(ref_b)
        a, b = self.nodes.node_meta(a_id), self.nodes.node_meta(b_id)
        from .structure_document import load_model_document
        xa = load_model_document(self.nodes.node_dir(a_id) / "model.res").structure
        xb = load_model_document(self.nodes.node_dir(b_id) / "model.res").structure

        def sites(xs):
            uc = xs.unit_cell()
            return {sc.label.upper(): (sc.scattering_type.strip().capitalize(),
                                       uc.orthogonalize(sc.site))
                    for sc in xs.scatterers()}

        sa, sb = sites(xa), sites(xb)
        added = sorted(set(sb) - set(sa))
        removed = sorted(set(sa) - set(sb))
        element_changed, moved = [], []
        for lbl in set(sa) & set(sb):
            ea, pa = sa[lbl]
            eb, pb = sb[lbl]
            if ea != eb:
                element_changed.append({"atom": lbl, "from": ea, "to": eb})
            d = sum((x - y) ** 2 for x, y in zip(pa, pb)) ** 0.5
            if d > 0.3:
                moved.append({"atom": lbl, "d_A": round(d, 2)})

        def metrics_of(m):
            mm = m.get("metrics") or {}
            return {k: mm.get(k) for k in ("r1_strong", "r1_all", "wr2", "goof",
                                           "n_params", "n_restraints")}

        ma, mb = metrics_of(a), metrics_of(b)
        delta = {k: (round(mb[k] - ma[k], 4)
                     if isinstance(ma.get(k), (int, float))
                     and isinstance(mb.get(k), (int, float)) else None)
                 for k in ma}
        return {
            "a": {"node": a_id, "tool": a.get("tool"), "branch": a.get("branch"),
                  "metrics": ma, "metrics_current": a.get("metrics_current"),
                  "n_atoms": (a.get("model") or {}).get("n_atoms")},
            "b": {"node": b_id, "tool": b.get("tool"), "branch": b.get("branch"),
                  "metrics": mb, "metrics_current": b.get("metrics_current"),
                  "n_atoms": (b.get("model") or {}).get("n_atoms")},
            "delta_b_minus_a": delta,
            "comparison": self.nodes.comparison(b_id, a_id),
            "comparison_note": "Deltas are arithmetic only, not scientific-quality rankings; inspect per-metric comparison conditions",
            "structure_diff": {"atoms_added_in_b": added,
                               "atoms_removed_in_b": removed,
                               "element_changed": element_changed,
                               "moved_gt_0.3A": moved},
            "restraints_a": [f"{s['kind']}" for s in a.get("restraints") or []],
            "restraints_b": [f"{s['kind']}" for s in b.get("restraints") or []],
        }
