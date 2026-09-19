"""NodeStore: disk-first snapshots of refinement states = candidate branches.

Every successful mutating tool call commits a node under
<project>/.crystalpilot/refine/nodes/nXXXX/:

    model.res   canonical serialization (atoms + AFIX H + restraint cards +
                WGHT + FVAR) - re-parseable, SHELXL-runnable, Olex2-openable
    model.cif   viewer copy (never re-read in-process: iotbx.cif segfaults on
                own files; readers must use gemmi)
    node.json   provenance + metrics + session flags metadata

state.json includes active_node, active_data_revision, branches, sequences and
project_revision, written atomically under a reentrant cross-process project lock.
A publication marker covers owned data/node staging and finite compatibility-input
updates; recovery follows the committed state pointer. Unrelated external files
and power-loss durability are outside this protocol. Disk is the source of truth:
a fresh process rebuilds
the live session from any node (checkout in project.py), which by construction
fixes the legacy snapshot_state bug of losing flags (mask/H/weights).
"""
from __future__ import annotations

import contextlib
import copy
import itertools
import json
import math
import os
import re
import time
import uuid

from .transactions import UNSET, locked, project_transaction, validate_expected
from pathlib import Path
from typing import Any

REFINE_DIRNAME = ".crystalpilot/refine"


def dedupe_scatterer_labels(xs) -> list[tuple[str, str]]:
    """Relabel the later twins of a duplicated label IN PLACE (case-
    insensitive, SHELX 4-character limit) and return [(old, new)].

    The first occurrence keeps its name so label-keyed metadata (riding
    H per carrier, restraints) stays attached to the atom it meant."""
    seen: set[str] = set()
    used: set[str] = {sc.label.strip().upper() for sc in xs.scatterers()}
    out: list[tuple[str, str]] = []
    for sc in xs.scatterers():
        key = sc.label.strip().upper()
        if key not in seen:
            seen.add(key)
            continue
        el = "".join(ch for ch in sc.scattering_type.strip()
                     if ch.isalpha()).capitalize() or "X"
        base = el[:2]
        n = 1
        while True:
            cand = f"{base}{n}"
            if len(cand) > 4:
                cand = f"{base[:1]}{n}"
            if cand.upper() not in used:
                break
            n += 1
        used.add(cand.upper())
        out.append((sc.label, cand))
        sc.label = cand
    return out


def better_nodes(rows: list[dict[str, Any]], delivered_id: str | None,
                 delivered_r1: float | None, margin: float = 0.02,
                 limit: int = 3) -> list[dict[str, Any]]:
    """Nodes of the tree whose CURRENT refinement R1 beats the delivered
    node by more than `margin` - the list write_outputs hands back so a
    worse delivery is a stated decision, never an oversight (pa2 cage:
    masked nodes at R1 0.12 sat in the tree while 0.22-0.23 was delivered
    with no mention of them)."""
    if delivered_r1 is None:
        return []
    from .data_versions import compare_sources
    delivered = next((row.get("comparison_source") for row in rows if row.get("id") == delivered_id), None)
    if not delivered:
        return []
    out = []
    for n in rows:
        source = n.get("comparison_source")
        if not source or compare_sources(source, delivered)["metrics"]["r1"]["status"] != "comparable":
            continue
        r1 = n.get("r1")
        if r1 is None or n.get("id") == delivered_id:
            continue
        if not n.get("metrics_current", False):
            continue
        if float(r1) <= float(delivered_r1) - margin:
            out.append({"id": n.get("id"), "branch": n.get("branch"),
                        "tool": n.get("tool"), "r1": r1, "wr2": n.get("wr2"),
                        "n_atoms": n.get("n_atoms"),
                        "masked": bool(n.get("masked")),
                        "delta_r1": round(float(r1) - float(delivered_r1), 4)})
    out.sort(key=lambda r: r["r1"])
    return out[:limit]


_WRITE_RETRIES = 40          # x 50 ms = 2 s of Windows sharing violations
_tmp_counter = itertools.count()


def atomic_write_json(path: Path, obj: Any, *, indent: int | None = None) -> None:
    """Write JSON through a temp file unique to this process and swap it in.

    The temp name used to be shared (<name>.json.tmp): two processes opening
    the same fresh project at the same moment (Codex starts more than one
    crystalpilot MCP server per thread on a cold spec cache, live cell
    2026-09-05) collided on it with WinError 32 and one of them came up as
    the 'project failed to open' error tool. os.replace is also retried,
    because on Windows it fails while another process momentarily has the
    target open for reading."""
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}-{next(_tmp_counter)}")
    tmp.write_text(json.dumps(obj, indent=indent, ensure_ascii=False,
                              default=str), encoding="utf-8")
    for attempt in range(_WRITE_RETRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == _WRITE_RETRIES - 1:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                raise
            time.sleep(0.05)


def read_json_retry(path: Path) -> Any:
    """json.loads(path) that tolerates another process mid-replace."""
    for attempt in range(_WRITE_RETRIES):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (PermissionError, json.JSONDecodeError):
            if attempt == _WRITE_RETRIES - 1:
                raise
            time.sleep(0.05)
    raise RuntimeError("unreachable")


class NodeStore:
    def __init__(self, project_dir: str | Path) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.root = self.project_dir / REFINE_DIRNAME
        self.nodes_dir = self.root / "nodes"
        self.nodes_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "state.json"
        self.publication_path = self.root / "publishing.json"

    # -- state -------------------------------------------------------------
    @locked
    def state(self) -> dict[str, Any]:
        self._recover_publication()
        return self._read_state()

    def _read_state(self) -> dict[str, Any]:
        if self.state_path.exists():
            st = read_json_retry(self.state_path)
            st.setdefault("project_revision", 0)
            st.setdefault("active_data_revision", None)
            st.setdefault("data_seq", 0)
            return st
        return {"active_node": None, "active_branch": "main",
                "active_data_revision": None, "data_seq": 0,
                "branches": {}, "seq": 0, "project_revision": 0}

    @locked
    def _save_state(self, st: dict[str, Any]) -> None:
        atomic_write_json(self.state_path, st, indent=2)

    def _recover_publication(self) -> None:
        if not self.publication_path.exists():
            return
        pending = read_json_retry(self.publication_path)
        node, token = pending["node"], pending["transaction"]
        if (node is not None and not re.fullmatch(r"n\d+", node)) or uuid.UUID(token).hex != token:
            raise ValueError("Invalid node publication marker; manual recovery required")
        st = self._read_state()
        committed = st.get("last_transaction") == token
        if not committed and node is not None:
            final = self.node_dir(node)
            if final.exists():
                failed = self.root / ".staging" / token
                failed.parent.mkdir(exist_ok=True)
                os.rename(final, failed)
                atomic_write_json(failed / "failure.json", {
                    "reason": "node publication did not commit", "node": node})
        from .data_versions import recover_data
        recover_data(self, pending, committed)
        if committed:
            with project_transaction(self.project_dir) as owner:
                owner.committed()
        self.publication_path.unlink()

    @contextlib.contextmanager
    def staged_node(self):
        """A single node, not an outer diagnostic batch, is the publication unit."""
        with project_transaction(self.project_dir, operation="commit") as owner:
            st = self.state()
            node = "n%04d" % st["seq"]
            if self.node_dir(node).exists():
                raise FileExistsError(f"Refusing to overwrite existing node {node}")
            token = uuid.uuid4().hex
            directory = self.root / ".staging" / token
            directory.mkdir(parents=True)
            try:
                yield st, node, directory, token
            except BaseException as exc:
                self._recover_publication()
                if directory.exists():
                    atomic_write_json(directory / "failure.json", {
                        "node": node, "error": f"{type(exc).__name__}: {exc}"})
                raise

    def publish_node(self, stage, meta: dict[str, Any], session=None) -> None:
        st, node, directory, token = stage
        with project_transaction(self.project_dir, operation="publish") as owner:
            from .data_versions import (DataVersions, pointer_aliases, publish_data,
                                        recover_data, save_working_experiment)
            owner.check_cancelled()
            data_revision = meta.get("data_revision")
            input_token = getattr(session, "_crystalpilot_input_transaction", None)
            pending = {"node": node, "transaction": token}
            if input_token:
                save_working_experiment(self, st, getattr(session, "_crystalpilot_previous_experiment", {}) or {})
                pending.update(input_transaction=input_token, data_revision=data_revision)
                st["data_seq"] = max(st.get("data_seq", 0), int(data_revision[1:]))
            elif data_revision:
                DataVersions(self.project_dir).resolve(data_revision)
                alias_token = pointer_aliases(self, meta, st)
                if alias_token:
                    pending["input_transaction"] = alias_token
            atomic_write_json(self.publication_path, pending)
            publish_data(self, pending)
            os.rename(directory, self.node_dir(node))
            owner.check_cancelled()
            st["active_data_revision"] = data_revision
            st["project_revision"] = st.get("project_revision", 0) + 1
            st["last_transaction"] = token
            self._save_state(st)
            # State replacement is the commit point. A lost response is not a retry licence.
            if session is not None:
                session._crystalpilot_source = {
                    "node": node, "project_revision": st["project_revision"]}
                session._crystalpilot_input_transaction = None
                session._crystalpilot_parent_node = None
                session._crystalpilot_previous_experiment = None
            recover_data(self, pending, committed=True)
            owner.committed()
            self.publication_path.unlink()

    def _publish_refs(self, st, *, restore_experiment=True):
        from .data_versions import pointer_aliases, recover_data
        before = self._read_state()
        node = st.get("active_node")
        meta = self.node_meta(node) if node else {}
        st["active_data_revision"] = meta.get("data_revision")
        token = uuid.uuid4().hex
        pending = {"node": None, "transaction": token}
        alias_token = pointer_aliases(self, meta, st, restore_experiment=restore_experiment)
        if not alias_token and st == before:
            return
        if st["project_revision"] == before["project_revision"]:
            st["project_revision"] += 1
        if alias_token:
            pending["input_transaction"] = alias_token
        with project_transaction(self.project_dir) as owner:
            owner.check_cancelled()
        atomic_write_json(self.publication_path, pending)
        st["last_transaction"] = token
        self._save_state(st)
        recover_data(self, pending, committed=True)
        self.publication_path.unlink()

    @locked
    def restore_refs(self, before: dict) -> None:
        """Undo a failed pointer-only operation without rewinding model commits."""
        st = self.state()
        if st["seq"] != before["seq"]:
            return
        keys = ("active_node", "active_branch", "branches")
        if any(st.get(key) != before.get(key) for key in keys):
            for key in keys:
                st[key] = before[key]
            st["project_revision"] += 1
            self._publish_refs(st, restore_experiment=False)

    @locked
    def touch(self, *, inputs_changed: bool = True, experiment=UNSET) -> int:
        """Version input/context or consumed peak-table state without a new model node."""
        st = self.state()
        if experiment is not UNSET and st.get("active_data_revision"):
            st.setdefault("working_experiments", {})[st["active_data_revision"]] = copy.deepcopy(experiment)
        st["project_revision"] += 1
        self._save_state(st)
        if inputs_changed:
            with project_transaction(self.project_dir) as owner:
                owner.committed()
        return st["project_revision"]

    def _published_peaks(self, node_id, session) -> None:
        revision = self.touch(inputs_changed=False)
        source = getattr(session, "_crystalpilot_source", None)
        if source and source["node"] == node_id == self.state()["active_node"]:
            source["project_revision"] = revision

    def node_dir(self, node_id: str) -> Path:
        return self.nodes_dir / node_id

    @locked
    def node_meta(self, node_id: str) -> dict[str, Any]:
        self.state()
        return json.loads((self.node_dir(node_id) / "node.json")
                          .read_text(encoding="utf-8"))

    @locked
    def version(self) -> dict[str, Any]:
        st = self.state()
        node = st.get("active_node")
        return {"node": node, "revision": self.node_meta(node).get("revision") if node else None,
                "data_revision": st.get("active_data_revision"),
                "project_revision": st["project_revision"]}

    @locked
    def source_state(self, ref: str | None = None) -> dict[str, Any]:
        """Readable model provenance; legacy nodes may not have a revision."""
        node = self.resolve(ref) if ref is not None else self.state()["active_node"]
        if node is None:
            return {"node": None, "revision": None, "data_revision": None}
        meta = self.node_meta(node)
        return {"node": node, "revision": meta.get("revision"),
                "data_revision": meta.get("data_revision")}

    @locked
    def comparison(self, node: str, baseline: str) -> dict[str, Any]:
        from .data_versions import comparison_source, compare_sources
        a, b = self.node_meta(self.resolve(node)), self.node_meta(self.resolve(baseline))
        sources = {"node": comparison_source(a, self), "baseline": comparison_source(b, self)}
        for name, meta in (("node", a), ("baseline", b)):
            if sources[name]["frame"].get("cell") is None:
                try:
                    from .structure_document import load_model_document
                    model = load_model_document(self.node_dir(meta["id"]) / (meta.get("canonical_model") or "model.res")).structure
                    sources[name]["frame"].update(cell=list(model.unit_cell().parameters()),
                        space_group_operations=[op.as_xyz() for op in model.space_group().all_ops()])
                except (OSError, ValueError, RuntimeError):
                    pass
        result = compare_sources(sources["node"], sources["baseline"])
        for metric, key in (("r1", "r1_strong"), ("wr2", "wr2"), ("goof", "goof")):
            if any(not isinstance((m.get("metrics") or {}).get(key), (int, float))
                   or not math.isfinite((m.get("metrics") or {}).get(key)) for m in (a, b)):
                result["metrics"][metric] = {"status": "unknown", "reasons": ["metric_missing"]}
        return {"schema": 1, "node": a["id"], "baseline": b["id"],
                "project_revision": self.state()["project_revision"], "sources": sources, **result}

    @locked
    def resolve(self, ref: str) -> str:
        """Branch name or node id -> node id."""
        st = self.state()
        if ref in st["branches"]:
            return st["branches"][ref]
        if (self.nodes_dir / ref / "node.json").exists():
            return ref
        raise KeyError(f"unknown node or branch {ref!r}. "
                       f"branches={st['branches']}")

    # -- peak tables -------------------------------------------------------
    PEAKS_FILE = "peaks.json"

    def peaks_path(self, node_id: str) -> Path:
        return self.node_dir(node_id) / self.PEAKS_FILE

    @locked
    def save_peaks(self, node_id: str, session,
                   update_meta: bool = False, *,
                   _directory: Path | None = None) -> dict[str, Any] | None:
        """Write the session's peak tables beside the node's model.res.

        Two tables used to live only in the live session and were lost on
        every branch/checkout (pa1: add_atoms_from_difference_map
        'no stored peaks' x7, interpret_peaks 'no peaks available' x4,
        each paid with a re-refine or a 12-50 s charge-flipping re-run):
        the difference-map table that refine / run_shelxl(adopt) /
        inspect_map produce and add_atoms_from_difference_map indexes
        into, and the charge-flipping/superflip peak list that
        interpret_peaks consumes. Returns the compact block recorded in
        node.json (None when the session holds neither table - a stale
        file is removed then). update_meta=True also patches node.json,
        for refreshes that happen without a commit (inspect_map)."""
        flags = getattr(session, "flags", None) or {}
        diff = flags.get("diff_map_peaks") or []
        meta = flags.get("diff_map_peaks_meta") or {}
        cf = getattr(session, "cf_info", None) or {}
        cf_sites = cf.get("peak_sites") or []
        self.state()
        path = (_directory / self.PEAKS_FILE if _directory is not None
                else self.peaks_path(node_id))
        if not diff and not cf_sites:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            else:
                if _directory is None:
                    self._published_peaks(node_id, session)
            return None
        if diff and meta.get("node") is None:
            # the first save pins the provenance: later commits (edit_atoms,
            # set_u_iso ...) carry the table forward, but the peaks were
            # computed on THIS node's model
            meta = {**meta, "node": node_id}
            flags["diff_map_peaks_meta"] = meta
        doc: dict[str, Any] = {"node": node_id, "ts": time.time()}
        block: dict[str, Any] = {}
        if diff:
            doc["diff_map"] = {
                "source": meta.get("source"),
                "map_provenance": meta.get("map_provenance"),
                "computed_on": meta.get("node"),
                "max": meta.get("max"), "min": meta.get("min"),
                "peaks": [dict(p) for p in diff],
            }
            block["diff_map"] = {"n": len(diff), "source": meta.get("source"),
                                 "computed_on": meta.get("node")}
        if cf_sites:
            doc["charge_flipping"] = {
                **{k: v for k, v in cf.items()
                   if k not in ("peak_sites", "peak_heights")},
                "peak_sites": [[float(x) for x in s] for s in cf_sites],
                "peak_heights": [float(h) for h in
                                 (cf.get("peak_heights") or [])],
            }
            block["charge_flipping"] = {
                "n": len(cf_sites),
                "engine": cf.get("engine") or "charge_flipping"}
        atomic_write_json(path, doc)
        if update_meta:
            meta_path = self.node_dir(node_id) / "node.json"
            try:
                m = read_json_retry(meta_path)
                m["peaks"] = block
                atomic_write_json(meta_path, m, indent=2)
            except (OSError, ValueError):
                pass
        if _directory is None:
            self._published_peaks(node_id, session)
        return block

    @locked
    def load_peaks(self, node_id: str) -> dict[str, Any] | None:
        """The node's saved peak tables (see save_peaks), or None."""
        path = self.peaks_path(node_id)
        if not path.exists():
            return None
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return doc if isinstance(doc, dict) else None

    # -- commit ------------------------------------------------------------
    @locked
    def commit(self, session, *, tool: str, params: dict[str, Any],
               summary: dict[str, Any] | None = None, note: str = "",
               wavelength: float | None = None, z: int | None = None,
               cell_esd: tuple | None = None, expected_node=UNSET,
               expected_project_revision=UNSET) -> dict[str, Any]:
        """Serialize under project ownership, then publish one complete node.

        A tracked stale session cannot be attached to the current head. Bare
        low-level sessions have no inferable source; callers can supply tokens.
        """
        st = self.state()
        validate_expected(st, expected_node=expected_node,
                          expected_project_revision=expected_project_revision)
        source = getattr(session, "_crystalpilot_source", None)
        if source:
            validate_expected(st, expected_node=source["node"],
                              expected_project_revision=source["project_revision"])
        with self.staged_node() as stage:
            return self._serialize_commit(session, stage, tool=tool, params=params,
                                          summary=summary, note=note, wavelength=wavelength,
                                          z=z, cell_esd=cell_esd)

    def _serialize_commit(self, session, stage, *, tool, params, summary,
                          note, wavelength, z, cell_esd):
        from ..io.shelx_writer import ShelxModel, write_res
        from ..report.cif import structure_to_cif
        from .restraints import emit_shelx_cards

        st, node_id, ndir, _ = stage

        ses = session
        flags = ses.flags
        weights = flags.get("weights") or {}
        w = (float(weights.get("a", 0.1)), float(weights.get("b", 0.0)))
        restraints = list(flags.get("restraints") or [])
        h_meta = flags.get("h_riding_meta") or {}
        scale_k = flags.get("scale_k")
        fvar = math.sqrt(scale_k) if scale_k and scale_k > 0 else None

        snap = ses.last_refinement()
        metrics: dict[str, Any] | None = None
        if snap is not None:
            metrics = snap.as_dict()
            metrics["scale_k"] = scale_k
            if summary:
                for k in ("n_restraints", "goof_restrained"):
                    if k in summary:
                        metrics[k] = summary[k]
        rem = [f"CrystalPilot node {node_id} tool={tool}"]
        if metrics:
            rem.append(f"R1 = {metrics.get('r1_strong')} wR2 = {metrics.get('wr2')} "
                       f"GooF = {metrics.get('goof')}")

        extras = serialization_extras(flags)
        # a label collision in the live model would be written as-is and
        # every later checkout of the node would die inside iotbx's parser
        # (pa2 cage-l0-r2 n0102/n0107: run_shelxl adopt after add_hydrogens
        # produced eleven doubled H labels) - relabel the later twins now
        dedup = dedupe_scatterer_labels(ses.model)
        if dedup:
            note = (note + " " if note else "") + (
                "label collision repaired at commit: "
                + ", ".join(f"{o}->{n}" for o, n in dedup))
        extras = serialization_extras(flags)
        rename = write_res(ShelxModel(
            xray_structure=ses.model,
            # None when unknown: the writer's REM then says so instead of
            # a silent Mo K-alpha CELL (final.res is this model.res)
            wavelength=wavelength or ses.dataset.wavelength or None,
            z=z, title=f"CrystalPilot {node_id}", rem_lines=rem,
            restraint_cards=emit_shelx_cards(restraints),
            weights=w, scale=fvar, cell_esd=cell_esd,
            h_riding=h_meta.get("per_carrier"), **extras), ndir / "model.res")
        if rename:
            # keep label-based metadata consistent with what we serialized
            restraints = _apply_rename_to_specs(restraints, rename)
            h_meta = _apply_rename_to_h_meta(h_meta, rename)
            flags["restraints"] = restraints
            flags["h_riding_meta"] = h_meta
            # ...and the LIVE session with both: renaming only the flags
            # leaves the in-memory model on the old labels, so every
            # label-keyed lookup (PART membership -> phantom-bond filter,
            # restraint resolution) silently misses from the next tool call
            # on (round-10 #13: 5-char disordered H labels desynced PART 2)
            for sc in ses.model.scatterers():
                nb = rename.get(sc.label)
                if nb:
                    sc.label = nb
            for c in flags.get("h_constraints") or []:
                checks = getattr(c, "checks", None)
                if checks:
                    c.checks = [(i, rename.get(l, l)) for i, l in checks]
            if flags.get("disorder_groups"):
                flags["disorder_groups"] = _apply_rename_to_disorder(
                    flags["disorder_groups"], rename)
            if flags.get("afix_groups"):
                flags["afix_groups"] = _apply_rename_to_afix_groups(flags["afix_groups"], rename)
            if flags.get("disorder_origins"):
                flags["disorder_origins"] = _apply_rename_to_origins(
                    flags["disorder_origins"], rename)
            if flags.get("parts_extra"):
                ren_up = {k.upper(): v for k, v in rename.items()}
                flags["parts_extra"] = {
                    str(ren_up.get(lbl, lbl)).upper(): p
                    for lbl, p in flags["parts_extra"].items()}
            if flags.get("effective_cards"):
                from .shelx_cards import rename_cards
                flags["effective_cards"] = rename_cards(
                    flags["effective_cards"], rename)

        mask_info = flags.get("solvent_mask_info") or None
        try:
            structure_to_cif(ses.model, ndir / "model.cif",
                             wavelength=ses.dataset.wavelength,
                             stats=metrics, mask_info=mask_info,
                             data_name=node_id, z=z)
        except Exception:  # noqa: BLE001 - viewer copy is best-effort
            pass

        try:
            peaks_block = self.save_peaks(node_id, ses, _directory=ndir)
        except Exception:  # noqa: BLE001 - a derived table must not fail a commit
            peaks_block = None

        parent = getattr(ses, "_crystalpilot_parent_node", None) or st["active_node"]
        branch = st.get("active_branch") or "main"
        head = st["branches"].get(branch)
        advances_branch = head in (parent, None)
        meta = {
            "schema": 3,
            "data_revision": getattr(ses, "_crystalpilot_data_revision", None),
            "experiment": copy.deepcopy(getattr(ses, "_crystalpilot_experiment", None)),
            "id": node_id, "parent": parent,
            "revision": int(st["seq"]) + 1,
            "branch": branch if advances_branch else f"(detached from {parent})",
            "ts": time.time(), "tool": tool, "params": _shrink(params),
            "note": note,
            "metrics": metrics,
            "metrics_current": tool in ("refine", "run_shelxl"),
            "model": {
                "n_atoms": int(ses.model.scatterers().size()),
                "element_counts": _element_counts(ses.model),
            },
            "restraints": restraints,
            # the DATA the model was fitted against. Not a refinement
            # metric - it only moves when the data move (swap_reflection_data,
            # a re-export, a SHEL cutoff) - but it belongs next to R1: Rint
            # bounds what R1 can be, and until now it was visible only as a
            # chip in a chat message that scrolled away.
            "data": _data_block(ses),
            "weights": {"a": w[0], "b": w[1]},
            "scale_k": scale_k,
            "mask": ({"params": flags.get("solvent_mask_params"),
                      "info": _shrink(mask_info)} if flags.get("f_mask") is not None
                     else None),
            "hydrogens": ({"present": True,
                           "elements": h_meta.get("elements"),
                           "n_groups": len(h_meta.get("per_carrier") or [])}
                          if h_meta.get("per_carrier") else {"present": False}),
            "disorder_groups": flags.get("disorder_groups") or [],
            # what model_disorder changed when it made each split, so
            # model_disorder(undo=...) can reverse it exactly after a
            # checkout or a fresh process - a split whose "before" state
            # is lost can only be rolled back by discarding everything
            # else done since
            "disorder_origins": flags.get("disorder_origins") or [],
            "parts_extra": flags.get("parts_extra") or {},
            "twin": flags.get("twin"),
            # round-3 WP2: everything a SHELXL job would refine with, in
            # one place - the instruction cards used to live only in the
            # job directory and were gone from the node, its model.res and
            # the delivery (forensic T-d: EADP/SUMP lost before final.res)
            "effective_state": effective_state(flags, w, tool),
            "label_renames": rename or {},
            # expert-review red flags (present only when the post-commit
            # asu_coherence check found detached fragments / ghost suspects)
            "asu": ((summary or {}).get("asu_sanity") or None),
            # what peaks.json beside this node holds (see save_peaks)
            "peaks": peaks_block,
        }
        from .data_versions import record_node_conditions
        record_node_conditions(self, meta, ses, tool)
        (ndir / "node.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
        if flags.get("f_mask") is not None:
            # snapshot the mask itself: checkout/branch used to RECOMPUTE
            # it from params (70-138 s per switch on a MOF channel in pa1,
            # 11 min in one run), and a recompute on a drifting BYPASS
            # series does not even return the same numbers
            try:
                from libtbx import easy_pickle
                easy_pickle.dump(str(ndir / "f_mask.pkl"), {
                    "f_mask": flags["f_mask"],
                    "info": mask_info,
                    "params": flags.get("solvent_mask_params")})
            except Exception:  # noqa: BLE001 - cache only; recompute stays
                pass

        if advances_branch:
            st["branches"][branch] = node_id
        st["active_node"] = node_id
        st["seq"] += 1
        self.publish_node(stage, meta, session)
        return meta

    # -- branches ----------------------------------------------------------
    @locked
    def branch(self, name: str, from_ref: str | None = None, *,
               expected_node=UNSET, expected_project_revision=UNSET) -> dict[str, Any]:
        st = self.state()
        validate_expected(st, expected_node=expected_node,
                          expected_project_revision=expected_project_revision)
        base = self.resolve(from_ref) if from_ref else st["active_node"]
        if base is None:
            raise ValueError("no node to branch from yet")
        before = json.dumps(st, sort_keys=True)
        st["branches"][name] = base
        st["active_branch"] = name
        st["active_node"] = base
        if json.dumps(st, sort_keys=True) != before:
            st["project_revision"] += 1
        self._publish_refs(st)
        return {"branch": name, "at": base}

    @locked
    def set_active(self, node_id: str, branch: str | None = None, *,
                   expected_node=UNSET, expected_project_revision=UNSET) -> None:
        st = self.state()
        validate_expected(st, expected_node=expected_node,
                          expected_project_revision=expected_project_revision)
        self.resolve(node_id)
        before = json.dumps(st, sort_keys=True)
        st["active_node"] = node_id
        if branch is not None:
            st["active_branch"] = branch
        elif st["branches"].get(st.get("active_branch")) != node_id:
            # keep the current branch when it still points here; else infer
            for b, head in st["branches"].items():
                if head == node_id:
                    st["active_branch"] = b
                    break
        if json.dumps(st, sort_keys=True) != before:
            st["project_revision"] += 1
        self._publish_refs(st)

    @locked
    def list_nodes(self, limit: int = 50) -> list[dict[str, Any]]:
        self.state()
        out = []
        for ndir in sorted(self.nodes_dir.iterdir()):
            meta_path = ndir / "node.json"
            if not meta_path.exists():
                continue
            m = json.loads(meta_path.read_text(encoding="utf-8"))
            metrics = m.get("metrics") or {}
            from .data_versions import comparison_source
            row = {
                "comparison_source": comparison_source(m, self),
                "id": m["id"], "parent": m.get("parent"),
                "revision": m.get("revision"),
                "structure_only": bool(m.get("structure_only") or m.get("mode") == "structure_only"),
                "capabilities": m.get("capabilities"),
                "reported_reference": m.get("reported_reference"),
                "branch": m.get("branch"), "tool": m.get("tool"),
                "note": m.get("note") or "",
                "n_atoms": (m.get("model") or {}).get("n_atoms"),
                "r1": metrics.get("r1_strong"),
                "wr2": metrics.get("wr2"),
                "goof": metrics.get("goof"),
                "diff_map_max": metrics.get("diff_map_max"),
                "diff_map_min": metrics.get("diff_map_min"),
                "n_params": metrics.get("n_params"),
                "metrics_current": m.get("metrics_current", False),
                "masked": bool(m.get("mask")),
                "n_restraints": len(m.get("restraints") or []),
                "data": m.get("data"),
                # stored difference-map peaks (inspect_map(node=...) reads
                # them without recomputing)
                "n_peaks": (((m.get("peaks") or {}).get("diff_map") or {})
                            .get("n")),
                "asu": (({"detached": (m["asu"] or {}).get(
                              "n_detached_atoms") or 0,
                          "ghosts": len((m["asu"] or {}).get(
                              "ghost_suspects") or [])})
                        if m.get("asu") else None),
            }
            if metrics.get("flack") is not None:
                row["flack"] = metrics["flack"]
                row["flack_su"] = metrics.get("flack_su")
            out.append(row)
        # A node committed by a geometry-only tool (add/delete atoms,
        # hydrogens, mask, checkout edits) has no measurement of its own;
        # the workbench showed "—" for R1/wR2/GooF and the user read that
        # as "the refinement was lost" (usertest test3-2, 2026-09-08). Name
        # the nearest measured ancestor instead - marked as inherited, never
        # merged into the node's own metrics.
        by_id = {row["id"]: row for row in out}
        for row in out:
            if row.get("r1") is not None:
                continue
            anc, hops = by_id.get(row.get("parent")), 1
            while anc is not None and anc.get("r1") is None:
                anc, hops = by_id.get(anc.get("parent")), hops + 1
            if anc is not None:
                row["metrics_inherited"] = {
                    "from": anc["id"], "distance": hops,
                    "r1": anc.get("r1"), "wr2": anc.get("wr2"), "goof": anc.get("goof")}
        st = self.state()
        return {"nodes": out[-limit:], "active_node": st["active_node"],
                "active_branch": st.get("active_branch"),
                "branches": st["branches"]}   # type: ignore[return-value]


def effective_state(flags: dict, weights, tool: str) -> dict[str, Any]:
    """The refinement-defining state of a node beyond its coordinates:
    the instruction cards an adopted SHELXL job refined with (EADP/EXYZ/
    SAME/SUMP and the measurement cards), data cards, weights, free
    variables, PART blocks, H treatment, twin and mask. `cards` is the
    only field the other node metadata did not already carry; the rest
    are gathered here so a reader (checkout, delivery coherence, the
    grader) has one place to look."""
    ex = serialization_extras(flags)
    h_meta = flags.get("h_riding_meta") or {}
    return {
        "cards": list(flags.get("effective_cards") or []),
        "data_cards": list(flags.get("data_cards") or []),
        "weights": {"a": float(weights[0]), "b": float(weights[1])},
        "fvars": list(ex.get("fvars") or []),
        "parts": dict(ex.get("parts") or {}),
        "h_treatment": ("riding" if h_meta.get("per_carrier")
                        else "free_or_none"),
        "twin": bool(flags.get("twin")),
        "afix_groups": flags.get("afix_groups") or [],
        "mask": flags.get("f_mask") is not None,
        "source": {"tool": tool,
                   "job": flags.get("effective_cards_job")},
    }


def serialization_extras(flags: dict) -> dict[str, Any]:
    """SHELX serialization kwargs for disorder groups + twin flags +
    effective instruction cards (WP2: model.res carries what the model
    was refined with; callers that pass their own instruction_cards pop
    the key).

    disorder_groups: [{"fvar_index": k>=2, "value": v, "members":
        [{"label", "part", "sign", "mult"}]}]  ->  FVAR list + coded sofs
    twin: {"matrix": [9], "n": int, "basf": [floats]}
    """
    out: dict[str, Any] = {}
    groups = flags.get("disorder_groups") or []
    if flags.get("afix_groups"):
        out["afix_groups"] = flags["afix_groups"]
    if groups:
        fvars: dict[int, float] = {}
        sof_codes: dict[str, float] = {}
        parts: dict[str, int] = {}
        for g in groups:
            k = int(g["fvar_index"])
            fvars[k] = float(g["value"])
            for mem in g.get("members", []):
                mult = float(mem.get("mult", 1.0))
                code = 10.0 * k + mult
                if int(mem.get("sign", 1)) < 0:
                    code = -code
                sof_codes[mem["label"]] = code
                if mem.get("part") is not None:
                    parts[mem["label"]] = int(mem["part"])
        out["fvars"] = [fvars[k] for k in sorted(fvars)]
        out["sof_codes"] = sof_codes
        out["parts"] = parts
    if flags.get("parts_extra"):
        # PART-block atoms with plain (non-FVAR) sofs keep their block
        parts = out.setdefault("parts", {})
        for lbl, p in flags["parts_extra"].items():
            parts.setdefault(lbl, int(p))
    twin = flags.get("twin")
    if twin and (twin.get("matrix") or twin.get("basf")):
        out["twin"] = {"matrix": list(twin.get("matrix") or []) or None,
                       "n": int(twin.get("n", 2)),
                       "basf": list(twin.get("basf") or [])}
    if int(flags.get("hklf") or 4) != 4:
        out["hklf"] = int(flags["hklf"])
    if flags.get("data_cards"):
        out["data_cards"] = list(flags["data_cards"])
    if flags.get("effective_cards"):
        out["instruction_cards"] = list(flags["effective_cards"])
    return out


def disorder_from_parsed(parsed) -> tuple[list[dict], dict | None]:
    """Rebuild (disorder_groups, twin) flags from a ParsedShelxModel."""
    by_k: dict[int, dict] = {}
    fvar_all = [parsed.scale or 1.0] + list(parsed.fvar_extra or [])
    for label, code in (parsed.sof_codes or {}).items():
        a = abs(float(code))
        if a < 15.0:
            continue                      # free occupancy, not fvar-linked
        k = int(a // 10.0)
        if k < 2 or k > len(fvar_all):
            continue
        g = by_k.setdefault(k, {"fvar_index": k,
                                "value": float(fvar_all[k - 1]),
                                "members": []})
        g["members"].append({
            "label": label,
            "part": int((parsed.parts or {}).get(label, 0)) or None,
            "sign": 1 if float(code) > 0 else -1,
            "mult": round(a - 10.0 * k, 4),
        })
    twin = None
    if (parsed.twin and parsed.twin.get("matrix")) or parsed.basf:
        twin = {"matrix": (list(parsed.twin["matrix"])
                           if parsed.twin else None),
                "n": int((parsed.twin or {}).get("n", 2)),
                "basf": list(parsed.basf or [])}
    return [by_k[k] for k in sorted(by_k)], twin


def loose_parts_from_parsed(parsed, groups: list[dict]) -> dict[str, int]:
    """PART-block atoms NOT captured in an FVAR-linked disorder group.

    SHELXL writes some sofs back as plain numbers (e.g. renormalized H);
    disorder_from_parsed only rebuilds members from FVAR-coded sofs, so on
    adopt these atoms would silently lose their PART - phantom-bond
    filtering misses them and the next serialization drops them out of
    their PART block. Store as flags['parts_extra']: {LABEL: signed part}.
    """
    in_groups = {str(m.get("label", "")).upper() for g in groups
                 for m in g.get("members", ())}
    out: dict[str, int] = {}
    for lbl, p in (getattr(parsed, "parts", None) or {}).items():
        if int(p) and str(lbl).upper() not in in_groups:
            out[str(lbl).upper()] = int(p)
    return out


def part_kwargs_from_parts(parts: list[int]) -> dict[str, Any]:
    """Signed per-atom PART numbers -> smtbx.utils.connectivity_table kwargs.

    cctbx conformer_indices implement SHELX PART semantics natively (0 bonds
    everything, different non-zero conformers never bond); negative PART n
    additionally suppresses bonds to symmetry equivalents, which maps to
    sym_excl_indices. Returns {} when nothing is disordered.
    """
    if not any(parts):
        return {}
    from cctbx.array_family import flex
    out: dict[str, Any] = {
        "conformer_indices": flex.size_t([abs(int(p)) for p in parts])}
    sym_excl = [abs(int(p)) if p < 0 else 0 for p in parts]
    if any(sym_excl):
        out["sym_excl_indices"] = flex.size_t(sym_excl)
    return out


def part_connectivity_kwargs(flags: dict, scatterers) -> dict[str, Any]:
    """connectivity_table kwargs applying SHELX PART semantics from the
    session's disorder_groups flags (see part_kwargs_from_parts). Pass to
    smtbx.utils.connectivity_table so overlapping PART 1/PART 2 alternatives
    are not treated as mutually bonded (connectivity is otherwise purely
    geometric and disordered pivots grow phantom neighbours -> riding-H
    constraints reject them at reparametrisation time)."""
    from .parts import part_of_labels
    part_of = part_of_labels(flags)
    if not part_of:
        return {}
    return part_kwargs_from_parts(
        [part_of.get(sc.label.upper(), 0) for sc in scatterers])


def prune_long_metal_contacts(ct, xs, part_kwargs: dict | None = None) -> int:
    """Remove from a connectivity table (in place) every metal pair that the
    bonding truth (`chem.bonding.bond_table`) does not classify as a bond.
    Returns the number of pairs removed.

    The table's distance cutoff (r_i + r_j + 0.5) legitimately captures
    pi/electrostatic metal contacts (La...C(arene) 3.2 A), which is right
    for a neighbour search but wrong for VALENCE consumers: riding-H
    constraint classes count the pivot's neighbours and reject the
    constraint when a contact inflates the count (secondary_xh2_sites on a
    P-CH2-N next to La = round-5 'bad connectivity').

    Until bonding migration 1b this pruned every metal pair beyond the plain
    covalent-radii sum, which also deleted real dative bonds - a chelating
    Cu-O at 2.41 A (sum 1.98), every Na-Cl of rock salt (2.85 vs 2.68), the
    long Zr-O of an acetate (D18). Now the pairs that survive are exactly
    the classified edges: covalent, coordination (MetalProfile window or
    the documented unlisted-metal fallback), eta and metal_metal; the
    chelate-bite carbon, a riding X-H hydrogen leaning at the metal and
    anything beyond the window are removed.

    part_kwargs: the smtbx PART keywords the table was built with, so the
    classification sees the same conformers (pass what you passed to
    `connectivity_table`).
    """
    from ..chem.bonding import bond_table, element_of, is_metal_element

    table = bond_table(xs, part_kwargs=part_kwargs)
    keep = {(e.i, e.j, e.op.replace(" ", "")) for e in table.edges}
    scs = xs.scatterers()
    elems = [element_of(sc) for sc in scs]
    pst = ct.pair_asu_table.extract_pair_sym_table(
        skip_j_seq_less_than_i_seq=False,
        all_interactions_from_inside_asu=True)
    to_remove = []
    for i, pd in enumerate(pst):
        for j, ops in pd.items():
            if not (is_metal_element(elems[i]) or is_metal_element(elems[int(j)])):
                continue
            for op in ops:
                if (i, int(j), str(op).replace(" ", "")) not in keep:
                    to_remove.append((i, int(j), op))
    for i, j, op in to_remove:
        try:
            ct.remove_bond(i, j, op)
        except Exception:  # noqa: BLE001 - already gone via the i<->j twin
            pass
    return len(to_remove)


def _apply_rename_to_afix_groups(groups: list[dict], rename: dict[str, str]) -> list[dict]:
    upper = {k.upper(): v for k, v in rename.items()}
    return [{**g, "atoms": [upper.get(a.upper(), a) for a in g["atoms"]]} for g in groups]


def _apply_rename_to_disorder(groups: list[dict],
                              rename: dict[str, str]) -> list[dict]:
    out = []
    for g in groups:
        g = dict(g)
        g["members"] = [{**m, "label": rename.get(m["label"], m["label"])}
                        for m in g.get("members", [])]
        out.append(g)
    return out


def _apply_rename_to_origins(origins: list[dict],
                             rename: dict[str, str]) -> list[dict]:
    """Same label bookkeeping for the undo records: an origin naming a
    label that de-duplication renamed would delete the wrong atom (or
    nothing) when the split is undone."""
    def _r(lbl: str) -> str:
        return rename.get(lbl, lbl)
    out = []
    for o in origins:
        o = dict(o)
        for key in ("created", "linked_existing", "image_labels"):
            if o.get(key):
                o[key] = [_r(str(x)) for x in o[key]]
        if o.get("restore"):
            o["restore"] = [{**r, "label": _r(str(r.get("label", "")))}
                            for r in o["restore"]]
        out.append(o)
    return out


def _shrink(obj: Any, limit: int = 4000) -> Any:
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except TypeError:
        return {"_truncated": str(obj)[:limit]}
    if len(s) > limit:
        return {"_truncated": s[:limit]}
    return obj


def _data_block(ses) -> dict[str, Any] | None:
    """Reflection-data state at commit time (cheap: no re-merge).

    Everything here is already in the session; merge stats were computed
    when the data were loaded. Never raises - a viewer field must not be
    able to fail a commit."""
    try:
        out: dict[str, Any] = {}
        merge = getattr(ses, "merge_info", None)
        if isinstance(merge, dict):
            out.update({k: merge.get(k) for k in
                        ("r_int", "n_unique", "d_min", "completeness",
                         "space_group") if merge.get(k) is not None})
        fo = getattr(ses, "fo_sq", None)
        if fo is not None and not out.get("n_unique"):
            out["n_unique"] = int(fo.size())
        ds = getattr(ses, "dataset", None)
        if ds is not None:
            if getattr(ds, "wavelength", None):
                out["wavelength"] = round(float(ds.wavelength), 5)
            raw = getattr(ds, "intensities", None)
            if raw is not None:
                out["n_obs"] = int(raw.size())
        flags = getattr(ses, "flags", {}) or {}
        if flags.get("hklf"):
            out["hklf"] = int(flags["hklf"])
        cards = flags.get("data_cards") or []
        shel = next((c for c in cards
                     if str(c).upper().startswith("SHEL")), None)
        if shel:
            out["shel"] = str(shel)
        return out or None
    except Exception:  # noqa: BLE001 - never break a commit for a metric
        return None


def _element_counts(xs) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sc in xs.scatterers():
        el = sc.scattering_type.strip().capitalize()
        counts[el] = counts.get(el, 0) + 1
    return counts


def _apply_rename_to_specs(specs: list[dict], rename: dict[str, str]) -> list[dict]:
    def r(x: str) -> str:
        return rename.get(x, x)
    out = []
    for s in specs:
        s = dict(s)
        atoms = s.get("atoms")
        if atoms and isinstance(atoms[0], (list, tuple)):
            s["atoms"] = [[r(a), r(b)] for a, b in atoms]
        elif atoms:
            s["atoms"] = [r(a) for a in atoms]
        out.append(s)
    return out


def _apply_rename_to_h_meta(h_meta: dict, rename: dict[str, str]) -> dict:
    def r(x: str) -> str:
        return rename.get(x, x)
    out = dict(h_meta)
    out["per_carrier"] = [
        {**e, "carrier": r(e["carrier"]), "h": [r(h) for h in e.get("h", [])]}
        for e in (h_meta.get("per_carrier") or [])]
    return out
