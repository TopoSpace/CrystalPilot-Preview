"""Bounded evidence copies for nested advisors; never borrow the parent's lock.

Reflection-backed nodes require their recorded immutable observation version;
unknown historical data is refused. A snapshot copies only the selected scientific
state and its bound observations, not credentials, workbench history or map caches.
"""
from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .nodes import NodeStore, atomic_write_json
from .structure_document import is_structure_only_node
from .transactions import check_cancelled, project_transaction

SAFE_SETTINGS = ("model_override", "model_provider_override", "effort_override", "knowledge_mode")
NODE_FILES = ("model.res", "model.cif", "f_mask.pkl", "peaks.json")


class SnapshotUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class SpecialistSnapshot:
    directory: Path
    source: dict[str, Any]
    settings: dict[str, str]


def safe_settings(project_dir: Path) -> dict[str, str]:
    path = project_dir / ".crystalpilot-workbench.json"
    if not path.exists():
        return {}
    settings = json.loads(path.read_text(encoding="utf-8")).get("settings") or {}
    return {key: settings[key] for key in SAFE_SETTINGS
            if isinstance(settings.get(key), str) and settings[key].strip()}


def _check(cancel_event, deadline) -> None:
    check_cancelled(cancel_event)
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("specialist snapshot exceeded the consultation budget")


def _copy(source: Path, target: Path, project_dir: Path, cancel_event, deadline) -> dict:
    if not source.resolve().is_relative_to(project_dir.resolve()):
        raise SnapshotUnavailable("Snapshot inputs must be inside the source project; import external inputs first")
    if not source.is_file():
        raise SnapshotUnavailable(f"Required snapshot input is missing: {source.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with source.open("rb") as incoming, target.open("xb") as outgoing:
        while True:
            _check(cancel_event, deadline)
            chunk = incoming.read(1024 * 1024)
            if not chunk:
                break
            outgoing.write(chunk)
            size += len(chunk)
    return {"bytes": size, "source": str(source.resolve())}


def create_snapshot(project, out_dir: Path, ref: str | None = None, *,
                    cancel_event=None, deadline: float | None = None) -> SpecialistSnapshot:
    """Copy one eligible scientific state while the parent still owns its OS lock."""
    with project_transaction(project.dir, operation="specialist_snapshot",
                             cancel_event=cancel_event):
        _check(cancel_event, deadline)
        state = project.nodes.state()
        node = project.nodes.resolve(ref) if ref else state.get("active_node")
        if node is None:
            raise SnapshotUnavailable("A specialist snapshot needs a committed model node")
        meta = copy.deepcopy(project.nodes.node_meta(node))
        structure_only = is_structure_only_node(meta)
        data_meta = {}
        if not structure_only:
            from .data_versions import DataVersions, DataBindingRequired
            try:
                bound_hkl, data_meta = DataVersions(project.dir).for_node(meta)
            except DataBindingRequired as exc:
                raise SnapshotUnavailable(str(exc)) from exc

        settings = safe_settings(project.dir)
        directory = out_dir / "snapshot"
        directory.mkdir(parents=True, exist_ok=False)
        store = NodeStore(directory)
        target_node = store.node_dir(node)
        target_node.mkdir()
        canonical = meta.get("canonical_model") or "model.res"
        if canonical not in ("model.res", "model.cif"):
            raise SnapshotUnavailable("Unsupported canonical model in specialist snapshot")
        files = {}
        source_node = project.nodes.node_dir(node)
        for name in NODE_FILES:
            source = source_node / name
            if name == canonical or source.exists():
                files[f"nodes/{node}/{name}"] = _copy(
                    source, target_node / name, project.dir, cancel_event, deadline)

        context = {key: copy.deepcopy(project.context[key])
                   for key in ("chemistry", "reported_reference")
                   if key in project.context}
        context["experiment"] = copy.deepcopy(meta.get("experiment") or {})
        measured_experiment = (meta.get("comparison_conditions") or {}).get("experiment")
        if isinstance(measured_experiment, dict):
            context["experiment"].update(copy.deepcopy(measured_experiment))
        if structure_only:
            context.update(mode="structure_only", data={
                "source_cif": f".crystalpilot/refine/nodes/{node}/{canonical}",
                "data_block": meta.get("block_name")})
        else:
            files["crystal.hkl"] = _copy(bound_hkl, directory / "crystal.hkl",
                                         project.dir, cancel_event, deadline)
            version_dir = store.root / "data" / meta["data_revision"]
            for name in ("observations.hkl", "data.json"):
                files[f"data/{meta['data_revision']}/{name}"] = _copy(
                    bound_hkl.parent / name, version_dir / name, project.dir, cancel_event, deadline)
            context.update(mode="refinement", data={
                "hkl": "crystal.hkl",
                "start_model": f".crystalpilot/refine/nodes/{node}/{canonical}"})
            ins_elements = ((data_meta.get("input_context") or {}).get("data") or {}).get("ins_elements")
            if ins_elements is not None:
                context["data"]["ins_elements"] = copy.deepcopy(ins_elements)

        source = {
            "project": str(project.dir.resolve()), "node": node,
            "model_revision": meta.get("revision"),
            "project_revision": state["project_revision"],
            "snapshot_id": out_dir.name,
            "data_binding": "structure_only" if structure_only else "bound_revision",
            "data_revision": meta.get("data_revision"),
            "historical_data_revision": meta.get("data_revision"),
            "experiment_binding": "node" if isinstance(meta.get("experiment"), dict) else "unknown",
            "recorded_metrics_current": bool(meta.get("metrics_current")),
            "limitations": [
                "Only the selected node is present; other history/branches are not copied.",
                "Copied metrics are recorded evidence, not a new replay/validation result.",
                "Bound data identity is preserved; it does not establish scientific equivalence to a different data revision.",
            ],
            "files": files,
        }
        meta["metrics_current"] = False
        meta["specialist_source"] = source
        context["specialist_source"] = source
        atomic_write_json(target_node / "node.json", meta, indent=2)
        atomic_write_json(directory / "context.json", context, indent=2)
        store._save_state({"active_node": node, "active_branch": "snapshot",
                           "branches": {"snapshot": node}, "seq": state["seq"],
                           "active_data_revision": meta.get("data_revision"),
                           "data_seq": state.get("data_seq", 0),
                           "project_revision": state["project_revision"]})
        atomic_write_json(out_dir / "origin.json", source, indent=2)
        from ..workbench.agents_md import ensure_agents_md
        ensure_agents_md(directory, settings.get("knowledge_mode"), delegate=False)
        _check(cancel_event, deadline)
        return SpecialistSnapshot(directory, source, settings)
