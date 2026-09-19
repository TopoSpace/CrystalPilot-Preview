"""Owned reflection snapshots and finite input publication, without digest gates."""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import uuid
from pathlib import Path

from .transactions import TransactionError

ALIASES = ("crystal.hkl", "start.res", "start.ins", "source.cif", "context.json")


class DataBindingRequired(TransactionError):
    code = "data_binding_required"


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, value):
    from .nodes import atomic_write_json
    atomic_write_json(Path(path), value, indent=2)


def _same(a, b):
    if not a.is_file() or not b.is_file() or a.stat().st_size != b.stat().st_size:
        return False
    with a.open("rb") as left, b.open("rb") as right:
        while True:
            chunk = left.read(1024 * 1024)
            if chunk != right.read(1024 * 1024):
                return False
            if not chunk:
                return True


def is_protected(project_dir, path):
    root = Path(project_dir).resolve() / ".crystalpilot" / "refine"
    resolved = Path(path).resolve()
    return any(resolved.is_relative_to(root / name) for name in ("data", "nodes"))


def input_directory(project):
    stage = getattr(project, "_input_stage", None)
    return stage.inputs if stage is not None else project.dir


def capture_source(project, path):
    stage = getattr(project, "_input_stage", None)
    return stage.add_source(path) if stage is not None else Path(path)


class DataVersions:
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir).resolve()
        self.root = self.project_dir / ".crystalpilot" / "refine"
        self.directory = self.root / "data"

    def path(self, revision):
        if not isinstance(revision, str) or not re.fullmatch(r"d\d{6,}", revision):
            raise DataBindingRequired("Reflection data binding is unknown; explicitly supply matching data")
        path = self.directory / revision
        if path.is_symlink() or not path.resolve().is_relative_to(self.directory.resolve()):
            raise DataBindingRequired("Reflection version must be an app-managed directory")
        return path

    def resolve(self, revision):
        path = self.path(revision)
        try:
            meta = _json(path / "data.json")
        except (OSError, ValueError) as exc:
            raise DataBindingRequired(f"Reflection version {revision} is missing or unreadable") from exc
        hkl = path / "observations.hkl"
        if (not isinstance(meta, dict) or meta.get("schema") != 1 or meta.get("id") != revision
                or not hkl.is_file() or hkl.is_symlink()):
            raise DataBindingRequired(f"Reflection version {revision} is incomplete")
        return hkl, meta

    def for_node(self, meta):
        if not meta.get("data_revision"):
            raise DataBindingRequired(
                f"Node {meta.get('id')} has unknown reflection data. Geometry and recorded "
                "evidence remain available. Supply matching HKL with "
                "swap_reflection_data(model_node=..., hkl=..., reason=...) to create a new bound node.")
        return self.resolve(meta["data_revision"])


class InputStage:
    """A single controlled input operation; working aliases change only after commit."""

    def __init__(self, project):
        self.project = project
        self.store = project.nodes
        self.token = uuid.uuid4().hex
        self.directory = self.store.root / ".staging" / self.token
        self.inputs = self.directory / "inputs"
        self.inputs.mkdir(parents=True)
        self.sources = []
        self.processing = ["verbatim input copy"]
        self.scale_applied = 1.0
        self.revision = None
        self.committed = False
        self.previous_state = self.store.state()
        self.previous_experiment = copy.deepcopy(project.experiment())
        context = copy.deepcopy(project.context)
        for name in ALIASES:
            source = project.dir / name
            if source.is_file():
                shutil.copyfile(source, self.inputs / name)
        hkl = project.hkl_path
        if hkl is not None and Path(hkl).is_file():
            shutil.copyfile(hkl, self.inputs / "crystal.hkl")
            context.setdefault("data", {})["hkl"] = "crystal.hkl"
            self.add_source(hkl)
        model = project.start_model_path
        if model is not None and Path(model).is_file():
            name = "start.ins" if Path(model).suffix.lower() == ".ins" else "start.res"
            shutil.copyfile(model, self.inputs / name)
            context.setdefault("data", {})["start_model"] = name
            self.add_source(model)
        _write(self.inputs / "context.json", context)

    def add_source(self, path):
        source = Path(path).resolve()
        if not source.is_file():
            return
        for row in self.sources:
            if row["source"] == str(source):
                return self.directory / "sources" / row["file"]
        name = f"source-{len(self.sources):04d}{source.suffix.lower()}"
        directory = self.directory / "sources"
        directory.mkdir(exist_ok=True)
        shutil.copyfile(source, directory / name)
        self.sources.append({"source": str(source), "file": name, "bytes": (directory / name).stat().st_size})
        return directory / name

    def prepare(self, session):
        if self.revision is not None:
            return self.revision
        state = self.store.state()
        self.revision = "d%06d" % (int(state.get("data_seq", 0)) + 1)
        final = DataVersions(self.project.dir).path(self.revision)
        if final.exists():
            raise FileExistsError(f"Refusing to overwrite reflection version {self.revision}")
        target = self.directory / "data"
        target.mkdir()
        shutil.copyfile(self.inputs / "crystal.hkl", target / "observations.hkl")
        if self.sources:
            shutil.copytree(self.directory / "sources", target / "sources")
        context = _json(self.inputs / "context.json")
        context["experiment"] = copy.deepcopy(self.project.experiment())
        _write(self.inputs / "context.json", context)
        self.project.context = context
        data = context.get("data") or {}
        # Scientific input facts only; no arbitrary project settings/history.
        known = {k: copy.deepcopy(data[k]) for k in (
            "ins_elements", "vendor_hkl", "vendor_ins", "vendor_p4p", "vendor_ls",
            "vendor_abs", "vendor_source", "note", "space_group_hint") if k in data}
        meta = {"schema": 1, "id": self.revision, "transaction": self.token,
                "sources": self.sources, "bytes": (target / "observations.hkl").stat().st_size,
                "input_context": {"data": known, "experiment": copy.deepcopy(self.project.experiment())},
                "format": "SHELX HKL", "processing": list(self.processing),
                "scale_applied": self.scale_applied}
        _write(target / "data.json", meta)
        self.prepare_aliases()
        session._crystalpilot_data_revision = self.revision
        session._crystalpilot_data_manifest = meta
        session._crystalpilot_input_transaction = self.token
        session._crystalpilot_previous_experiment = {
            "node": self.previous_state.get("active_node"),
            "data_revision": self.previous_state.get("active_data_revision"),
            "experiment": self.previous_experiment}
        return self.revision

    def prepare_aliases(self):
        aliases = []
        for name in ALIASES:
            after = self.inputs / name
            before = self.project.dir / name
            if not after.is_file() or _same(before, after):
                continue
            if before.is_symlink():
                raise ValueError(f"Refusing to replace symlink input {name}")
            backup = self.directory / "before" / name
            if before.exists():
                backup.parent.mkdir(exist_ok=True)
                shutil.copyfile(before, backup)
            aliases.append({"name": name, "existed": before.exists()})
        _write(self.directory / "aliases.json", aliases)


def _owned_directory(store, token):
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        raise ValueError("Invalid input transaction; manual recovery required")
    directory = store.root / ".staging" / token
    if directory.is_symlink() or not directory.resolve().is_relative_to((store.root / ".staging").resolve()):
        raise ValueError("Input transaction is not owned staging")
    return directory


def finish_aliases(store, token):
    directory = _owned_directory(store, token)
    for row in _json(directory / "aliases.json"):
        name = row["name"]
        if name not in ALIASES:
            raise ValueError("Unowned input alias in publication journal")
        target = store.project_dir / name
        after = directory / "inputs" / name
        before = directory / "before" / name
        if target.is_symlink() or after.is_symlink() or not after.is_file():
            raise ValueError("Unowned or missing staged input")
        if _same(target, after):
            continue
        if (row["existed"] and not _same(target, before)) or (not row["existed"] and target.exists()):
            raise ValueError(f"Input {name} changed outside publication; manual recovery required")
        copies = directory / "alias-copies"
        copies.mkdir(exist_ok=True)
        # A killed copy is incomplete, not a foreign target. Retry into a fresh
        # owned file and leave earlier partial files available for diagnosis.
        staged = copies / f"{uuid.uuid4().hex}-{name}"
        with after.open("rb") as incoming, staged.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing)
        os.replace(staged, target)
    _write(directory / "completed.json", {"transaction": token})


def publish_data(store, pending):
    token = pending.get("input_transaction")
    if not token:
        return
    directory = _owned_directory(store, token)
    revision = pending.get("data_revision")
    if revision:
        target = DataVersions(store.project_dir).path(revision)
        target.parent.mkdir(exist_ok=True)
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite {revision}")
        manifest = _json(directory / "data" / "data.json")
        if manifest.get("id") != revision or manifest.get("transaction") != token:
            raise ValueError("Refusing to publish an unowned data package")
        os.rename(directory / "data", target)


def recover_data(store, pending, committed):
    token = pending.get("input_transaction")
    if not token:
        return
    directory = _owned_directory(store, token)
    if committed:
        if pending.get("data_revision"):
            DataVersions(store.project_dir).resolve(pending["data_revision"])
        finish_aliases(store, token)
        return
    revision = pending.get("data_revision")
    if revision:
        final = DataVersions(store.project_dir).path(revision)
        if final.exists():
            if _json(final / "data.json").get("transaction") != token:
                raise ValueError("Refusing to recover a foreign data version")
            os.rename(final, directory / "data")
    _write(directory / "failure.json", {"reason": "input publication did not commit"})


def save_working_experiment(store, state, previous):
    revision = previous.get("data_revision")
    experiment = previous.get("experiment")
    if not revision or not isinstance(experiment, dict):
        return
    recorded = store.node_meta(previous["node"]).get("experiment") if previous.get("node") else None
    saved = state.setdefault("working_experiments", {})
    if revision not in saved or experiment != recorded:
        saved[revision] = copy.deepcopy(experiment)


def pointer_aliases(store, node_meta, state=None, *, restore_experiment=True):
    """Restore bound inputs, retaining working notes separately from history."""
    revision = node_meta.get("data_revision")
    if not revision:
        return None
    source, _ = DataVersions(store.project_dir).resolve(revision)
    target = store.project_dir / "crystal.hkl"
    context_path = store.project_dir / "context.json"
    context = _json(context_path) if context_path.exists() else {}
    experiment = node_meta.get("experiment")
    change_hkl = not _same(source, target)
    change_experiment = (restore_experiment and isinstance(experiment, dict)
                         and (context.get("experiment") or {}) != experiment)
    if not change_hkl and not change_experiment:
        return None
    token = uuid.uuid4().hex
    directory = _owned_directory(store, token)
    (directory / "inputs").mkdir(parents=True)
    (directory / "before").mkdir()
    aliases = []
    for name in ((["crystal.hkl"] if change_hkl else [])
                 + (["context.json"] if change_experiment else [])):
        destination = store.project_dir / name
        if destination.is_symlink():
            raise ValueError("Refusing to replace a symlink compatibility input")
        if destination.exists():
            shutil.copyfile(destination, directory / "before" / name)
        if name == "crystal.hkl":
            shutil.copyfile(source, directory / "inputs" / name)
        else:
            current = store._read_state()
            old_meta = store.node_meta(current["active_node"]) if current.get("active_node") else {}
            working = ((context.get("experiment") or {}) if "experiment" in context
                       else (old_meta.get("experiment") or {}))
            if state is not None:
                save_working_experiment(store, state, {"node": current.get("active_node"),
                    "data_revision": current.get("active_data_revision"), "experiment": working})
            _write(directory / "inputs" / name, {**context, "experiment": copy.deepcopy(experiment)})
        aliases.append({"name": name, "existed": destination.exists()})
    _write(directory / "aliases.json", aliases)
    return token


def measurement_context(session, tool, summary):
    """Capture completed computation facts, not a model's proposed next settings."""
    if tool == "run_shelxl":
        return copy.deepcopy(getattr(session, "_crystalpilot_shelxl_measurement", None))
    if tool != "refine":
        return None
    return {"engine": "smtbx", "definition": "smtbx-r-factors-v1", "job": None,
            "weights": copy.deepcopy(session.flags.get("weights") or {"a": .1, "b": 0}),
            "applied_cards": [], "cutoff_application": "ignored",
            "mask_used": summary.get("solvent_mask_used"),
            "limited": bool(summary.get("cancelled") or summary.get("budget_exhausted"))}


def record_node_conditions(store, meta, session, tool):
    node, revision = meta["id"], meta.get("data_revision")
    flags = session.flags
    previous = store.node_meta(meta["parent"]) if meta.get("parent") else {}
    measurement = getattr(session, "_crystalpilot_new_measurement", None)
    source = copy.deepcopy(getattr(session, "_crystalpilot_metrics_source", None))
    token = f"{revision}:{node}:conditions-v1" if revision else None
    if measurement:
        source = {"node": node, "model_revision": meta["revision"], "data_revision": revision,
                  "engine": measurement["engine"], "job": measurement.get("job"),
                  "conditions_token": token}
    current = bool(measurement and revision and not measurement.get("limited"))
    cell = list(session.model.unit_cell().parameters())
    operations = [op.as_xyz() for op in session.model.space_group().all_ops()]
    prior_frame = previous.get("frame") or {}
    unchanged = (tool in {"edit_atoms", "add_atoms_from_difference_map", "fourier_complete",
                         "fit_fragment", "accept_fragment_pose", "add_hydrogens", "set_restraints",
                         "solvent_mask", "optimize_weights", "refine", "run_shelxl", "rename_atoms",
                         "model_disorder", "set_twin", "swap_reflection_data", "set_weights", "set_z",
                         "set_resolution_limit"}
                 and prior_frame.get("cell") == cell
                 and prior_frame.get("space_group_operations") == operations)
    frame = {"revision": prior_frame.get("revision") if unchanged else f"frame:{node}",
             "cell": cell, "space_group_operations": operations}
    mask = flags.get("f_mask")
    mask_revision = None
    if mask is not None:
        if mask is getattr(session, "_crystalpilot_mask_object", None):
            mask_revision = getattr(session, "_crystalpilot_mask_revision", None)
        mask_revision = mask_revision or f"mask:{node}"
    stored_mask = {"state": "bound" if mask_revision else "none", "revision": mask_revision,
                   "params": copy.deepcopy(flags.get("solvent_mask_params")) if mask is not None else None}
    applied_mask = copy.deepcopy(stored_mask)
    if measurement:
        if measurement.get("mask_used") is False:
            applied_mask = {"state": "none", "revision": None, "params": None}
        elif measurement.get("mask_used") is not True or mask_revision is None:
            applied_mask = {"state": "unknown", "revision": None, "params": None}
    data = meta.get("data") or {}
    weights = measurement.get("weights") if measurement else meta.get("weights")
    engine = (measurement or {}).get("engine")
    data_manifest = getattr(session, "_crystalpilot_data_manifest", {})
    conditions = {
        "observations": ({"revision": revision, "format": "SHELX HKL",
                          "processing": data_manifest.get("processing", []),
                          "scale_applied": data_manifest.get("scale_applied")} if revision else None),
        "basis": {"cell": cell, "space_group_operations": operations,
                  "indexing": "bound_input_indices"},
        "wavelength": session.dataset.wavelength if session.dataset is not None else None,
        "hklf": int(flags.get("hklf") or 4),
        "merge": {"policy": "cctbx-input-merge-v1",
                  "n_obs": data.get("n_obs"), "n_unique": data.get("n_unique")},
        "cutoff": {"requested": list(flags.get("data_cards") or []),
                   "selected_reflections": (meta.get("metrics") or {}).get("n_reflections") if current else None,
                   "applied": (measurement or {}).get("applied_cards"),
                   "application": (measurement or {}).get("cutoff_application", "unknown")},
        "weights": ({**weights, "source": "measurement" if measurement else "next_model"}
                    if weights else None),
        "scale": {"treatment": "fitted_overall_scale", "fitted_value": flags.get("scale_k")},
        "mask": applied_mask, "stored_mask": stored_mask,
        "hydrogens": {"treatment": (meta.get("effective_state") or {}).get("h_treatment", "unknown"),
                      "groups": copy.deepcopy((flags.get("h_riding_meta") or {}).get("per_carrier") or [])},
        "twin": copy.deepcopy(flags.get("twin")), "engine": engine,
        "unknown_fields": (["data_revision"] if not revision else []) + ([] if measurement else ["metric_definition"]),
        "metric_definition": (measurement or {}).get("definition"),
        "experiment": copy.deepcopy((measurement or {}).get("experiment")),
        "declared_experiment": copy.deepcopy(meta.get("experiment")),
    }
    meta.update(conditions_token=token, comparison_conditions=conditions,
                metrics_source=source, metrics_current=current, frame=frame,
                mask_revision=mask_revision)
    session._crystalpilot_metrics_source = source
    session._crystalpilot_new_measurement = None
    session._crystalpilot_mask_object = mask
    session._crystalpilot_mask_revision = mask_revision


def reflection_cache_source(store, node):
    from .structure_document import is_structure_only_node
    meta = store.node_meta(node)
    if not is_structure_only_node(meta):
        DataVersions(store.project_dir).for_node(meta)
    return {"schema": 1, "builder": "bound-data-v3", "node": node,
            "model_revision": meta.get("revision"), "data_revision": meta.get("data_revision"),
            "conditions_token": meta.get("conditions_token"),
            "interpretation": {"engine": "cctbx",
                "data_view": "geometry_only" if is_structure_only_node(meta) else
                             "positive_batch_composite_approximation" if (meta.get("data") or {}).get("hklf") == 5 else "merged_input",
                "ignored_data_cards": (meta.get("effective_state") or {}).get("data_cards") or [],
                "recorded_mask": (meta.get("comparison_conditions") or {}).get("mask")}}


def comparison_source(meta, store=None):
    from .structure_document import is_structure_only_node
    structure_only = is_structure_only_node(meta)
    revision = meta.get("data_revision")
    source = copy.deepcopy(meta.get("metrics_source"))
    available = bool(revision and not structure_only)
    reason = None if available else ("structure_only" if structure_only else "data_revision_unknown")
    if available and store is not None:
        try:
            DataVersions(store.project_dir).resolve(revision)
        except DataBindingRequired:
            available, reason = False, "data_version_missing"
    current = bool(meta.get("metrics_current") and available and source
                   and source.get("node") == meta.get("id")
                   and source.get("data_revision") == revision
                   and source.get("model_revision") == meta.get("revision"))
    return {"node": meta["id"], "model_revision": meta.get("revision"),
            "data_revision": revision,
            "data_binding": "structure_only" if structure_only else "bound" if revision else "legacy_unknown",
            "metrics_current": current, "metrics_source": source,
            "conditions_token": meta.get("conditions_token"),
            "conditions": copy.deepcopy(meta.get("comparison_conditions")),
            "frame": copy.deepcopy(meta.get("frame") or {
                "revision": None, "cell": None, "space_group_operations": None}),
            "evidence": {"reflection_recompute": available, "reason": reason}}


def compare_sources(a, b):
    unknown, differences = [], []
    for key, source in (("node", a), ("baseline", b)):
        if not source.get("data_revision"):
            unknown.append(f"{key}.data_revision")
        if not source.get("metrics_source"):
            unknown.append(f"{key}.metrics_source")
        if not source.get("metrics_current"):
            unknown.append(f"{key}.metrics_current")
        if not source.get("evidence", {}).get("reflection_recompute"):
            unknown.append(f"{key}.data_available")
    ca, cb = a.get("conditions") or {}, b.get("conditions") or {}
    # Model variables are intentionally not comparability gates for R1.
    gating = ("observations", "basis", "wavelength", "hklf", "metric_definition")
    reasons = []
    for key in gating:
        va, vb = ca.get(key), cb.get(key)
        if va is None or vb is None:
            unknown.append(key)
        elif va != vb:
            reasons.append(f"{key}_different")
    aa, ab = (ca.get("cutoff") or {}).get("applied"), (cb.get("cutoff") or {}).get("applied")
    if aa is None or ab is None:
        unknown.append("applied_selection")
    elif aa != ab:
        reasons.append("selection_different")
    for key in sorted(set(ca) | set(cb)):
        if ca.get(key) != cb.get(key):
            differences.append({"field": key, "node": ca.get(key), "baseline": cb.get(key)})
    metrics = {}
    for metric in ("r1", "wr2", "goof"):
        mr, mu = list(reasons), list(unknown)
        if metric != "r1":
            wa, wb = ca.get("weights"), cb.get("weights")
            if not wa or not wb:
                mu.append("weights")
            elif any(wa.get(k) != wb.get(k) for k in ("a", "b")):
                mr.append("weights_different")
        metrics[metric] = {"status": "unknown" if mu else "different" if mr else "comparable",
                           "reasons": sorted(set(mr + [f"unknown:{k}" for k in mu]))}
    fa, fb = a.get("frame") or {}, b.get("frame") or {}
    frame = {"status": "unknown", "reasons": ["frame_unknown"]}
    if fa.get("cell") and fb.get("cell"):
        if any(fa.get(k) != fb.get(k) for k in ("cell", "space_group_operations")):
            frame = {"status": "different", "reasons": ["coordinate_frame_different"]}
        elif fa.get("revision") and fa.get("revision") == fb.get("revision"):
            frame = {"status": "compatible", "reasons": []}
    return {"metrics": metrics, "frame": frame, "differences": differences,
            "unknown_fields": sorted(set(unknown))}
