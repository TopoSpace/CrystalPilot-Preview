"""Per-node analysis product: symmetry-unique interactions, topology, guest
sites and pore/packing geometry of ONE node. The common pipeline exposes
independent stage transitions for polling and also supports complete synchronous
callers. Successful products are cached on disk next to `voids.json`.

One computation, three consumers. The right-pane 分析 tab, the R5
`analyze_packing` tool and the HTAB card builder (`refine/shelx_cards.py`)
all read THIS product, so the number an agent quotes is the number the user
sees, and neither moves when the picture is grown: the canonical
interaction table is a property of the crystal, not of the view
(`chem/interactions.py`, "CANONICAL vs DISPLAY"). The viewer's dashed lines
are the display rows of the same engine, instantiated per view by
`refine/scene.py::_interactions_block`; the two cannot disagree because
they come out of the same geometry code.

Every block carries its rule set (`criteria`), its hydrogen provenance
(`h_source`) and its truncation state; a block that is not computed yet is
`None` WITH a note, never silently absent. Not here: display rows, esds
(only SHELXL has them), anything that needs reflection data beyond what
`voids.json` already carries.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterator

#: bump when the product's shape changes; a cached file with another `v`
#: is rebuilt (the voids block additionally re-validates against
#: `scene.VOIDS_CACHE_V`)
#: v5 (2026-09): the topology block carries `rcsr_symbols` - one RCSR symbol
#: per connected component of the simplified net, so an interpenetrated
#: structure no longer reports only the first component's answer
#: v6: symmetry relations are no longer asserted to prove interpenetration.
#: v7: independent stages, explicit missing/error states and source revision.
ANALYSIS_CACHE_V = 7

ANALYSIS_STAGES = ("interactions", "topology", "guests", "pores")
STAGE_TERMINAL = frozenset({"ready", "error", "unsupported", "cancelled"})

#: per-kind ceiling on canonical rows kept in the product (the tab and the
#: tool page through them; the engine's own display cap is separate)
MAX_UNIQUE_ROWS = 600

PENDING_PACKING_NOTE = ("该节点的 voids.json 早于 v4，没有堆积数字；"
                        "重建后即有")
PENDING_GUESTS_NOTE = "客体/抗衡离子的位置归属计算失败（见 guests_error）"
PENDING_TOPOLOGY_NOTE = "拓扑块计算失败（见 topology_error）"

#: finite (0-D) fragments described per product: the largest ones first
MAX_FINITE_FRAGMENTS = 24
#: DFS budget for the macrocycle census of one finite fragment (a fused
#: cage exhausts it and says so; the product must stay cheap to build)
MACROCYCLE_BUDGET = 200_000


def _load_analysis_model(model_path: str | Path):
    """Keep canonical CIF labels/settings instead of round-tripping via SHELX."""
    path = Path(model_path)
    if path.suffix.lower() == ".cif":
        from .structure_document import load_structure_document

        try:
            return load_structure_document(path)
        except ValueError as exc:
            if not str(exc).startswith("Choose one CIF structure"):
                raise
            meta_path = path.with_name("node.json")
            meta = (json.loads(meta_path.read_text(encoding="utf-8"))
                    if meta_path.exists() else {})
            block_name = (meta.get("params") or {}).get("data_block")
            if block_name is None:
                raise
            return load_structure_document(path, block_name=block_name)
    from ..io.shelx_model import load_res_model

    return load_res_model(path)


def guests_from_res(res_path, *, d_min=None):
    """Guest / counter-ion sites of a RES or canonical CIF model.

    The host void map is built from host atoms alone (no reflection data), so
    a guest cannot hide its own pore. `d_min` reproduces the viewer's
    resolution-based gridding when the node has data.
    """
    from ..chem.guests import locate_guests

    parsed = _load_analysis_model(res_path)
    return locate_guests(parsed.structure, parts=parsed.parts, d_min=d_min)


def interactions_from_res(res_path: str | Path, *,
                          criteria: str = "olex2") -> dict[str, Any]:
    """Canonical interaction tables of a RES or canonical CIF model.

    No reflections are required. CIF coordinates alone do not establish
    whether hydrogens were riding/refined; that provenance stays unknown.
    The engine's criteria, hydrogen provenance and counts are echoed verbatim.
    """
    from ..chem.interactions import KINDS, find_interactions
    from .scene import _h_source_of

    parsed = _load_analysis_model(res_path)
    xs = parsed.structure
    h_source = None if Path(res_path).suffix.lower() == ".cif" else _h_source_of(parsed)
    res = find_interactions(xs, parts=parsed.parts, h_source=h_source,
                            criteria=criteria)

    unique: dict[str, list[dict[str, Any]]] = {}
    truncated: dict[str, dict[str, int]] = {}
    passing: dict[str, int] = {}
    for k in KINDS:
        rows = list(res["unique"].get(k) or [])
        found = len(rows)
        if found > MAX_UNIQUE_ROWS:
            rows = rows[:MAX_UNIQUE_ROWS]      # engine order: distance
            truncated[k] = {"cap": MAX_UNIQUE_ROWS, "found": found}
        unique[k] = rows
        passing[k] = sum(1 for r in rows if r.get("passes"))

    rings = [{"atoms": r["atoms"], "aromatic": r["aromatic"],
              "centroid": r["centroid"], "radius": r["radius"]}
             for r in res["rings"] if r.get("in_range")]

    return {
        "scope": "canonical",
        "scope_note": ("对称唯一表：以不对称单元为基、在其光环内搜索，"
                       "去除对称等价行；不随查看器显示范围变化"),
        "h_source": res["h_source"],
        "h_source_note": res["h_source_note"],
        "criteria": res["criteria"],
        "unique": unique,
        "counts": {"unique": {k: len(unique[k]) for k in KINDS},
                   "passing": passing,
                   "intra": {k: sum(1 for r in unique[k] if r.get("intra"))
                             for k in KINDS},
                   "n_unique": sum(len(v) for v in unique.values())},
        "truncated": truncated,
        "rings": rings,
        "range": {"halo_A": res["range"]["halo_A"],
                  "halo_advised_A": res["range"]["halo_advised_A"],
                  "halo_sufficient": res["range"]["halo_sufficient"]},
    }


def _finite_fragments(xs, parts) -> list[dict[str, Any]]:
    """Macrocycle census and shape evidence of every finite (0-D) fragment -
    a molecule, a cage, a counter-ion - one record per symmetry-distinct
    fragment (P1 copies with the same ASU label set are one entry with
    `copies`), largest first, capped at MAX_FINITE_FRAGMENTS.

    The molecular graph handed to `largest_cycle` is SHIFT-FREE by
    construction: the BFS offsets of a 0-D component place every atom in one
    instance, and only edges consistent with those offsets are kept (an edge
    closing through another lattice translation would make a chain look
    like a macrocycle - `chem.shape.largest_cycle` docstring)."""
    import numpy as np

    from ..chem.shape import largest_cycle, shape_evidence
    from ..chem.topology import _components, _p1_graph, host_fragments

    g = _p1_graph(xs, parts)
    labels, elements, frac, adj, uc = (g["labels"], g["elements"], g["frac"],
                                       g["adj"], g["unit_cell"])
    host, _guests, _pd = host_fragments(xs, parts=parts)
    host_sets = {tuple(sorted(lb.upper() for lb in f["asu_labels"])) for f in host}
    seen: dict[tuple, dict[str, Any]] = {}
    for comp in _components(range(g["n"]), adj):
        if comp["dim"] != 0:
            continue
        key = tuple(sorted({labels[u].upper() for u in comp["atoms"]}))
        if key in seen:
            seen[key]["copies"] += 1
            continue
        atoms = comp["atoms"]
        off = comp["offset"]
        aset = set(atoms)
        adj0 = {u: {v for v, sh in adj[u]
                    if v in aset and np.array_equal(off[u] + np.array(sh, dtype=int), off[v])}
                for u in atoms}
        cart = [uc.orthogonalize(tuple(float(x) for x in (np.asarray(frac[u]) + off[u])))
                for u in atoms]
        rec: dict[str, Any] = {
            "fragment": None, "asu_labels": list(key), "n_atoms": len(atoms),
            "copies": 1, "role": "host" if key in host_sets else "guest",
        }
        cyc = largest_cycle(adj0, atoms, budget=MACROCYCLE_BUDGET)
        rec["largest_cycle"] = {k: cyc[k] for k in ("size", "truncated",
                                                     "n_cycles_basis", "note")}
        rec["largest_cycle"]["atoms"] = [labels[u] for u in cyc["atoms"]]
        if len(atoms) >= 4:
            sh = shape_evidence(cart, [elements[u] for u in atoms])
            rec["shape"] = {k: sh.get(k) for k in (
                "inertia_ratios", "sphericity", "hull_volume_A3", "hull_area_A2",
                "longest_axis_A", "aspect", "mass_weighted", "method", "note")}
        else:
            rec["shape"] = None
        seen[key] = rec
    out = sorted(seen.values(), key=lambda r: (-r["n_atoms"], r["asu_labels"]))
    for k, rec in enumerate(out, start=1):
        rec["fragment"] = f"F{k}"
    return out[:MAX_FINITE_FRAGMENTS]


def topology_from_res(res_path: str | Path, *, systre: bool = True) -> dict[str, Any]:
    """The topology block of a RES or canonical CIF model (`chem.topology` +
    `chem.shape`): independent nets and their symmetry relation
    (interpenetration only when symmetry-related), the node-linker
    simplified net with its Systre answer when `vendor/gavrog/*.jar` is
    present (otherwise `rcsr_status` says 未算), helical chains, and the
    finite fragments' macrocycle census + shape evidence. Descriptions with
    their definitions, never verdicts."""
    from ..chem.topology import (helices, independent_nets, run_systre,
                                 simplified_net, write_cgd)

    parsed = _load_analysis_model(res_path)
    xs, parts = parsed.structure, parsed.parts
    nets = independent_nets(xs, parts=parts)
    net = simplified_net(xs, parts=parts)
    if net.get("edges"):
        if systre:
            sy = run_systre(write_cgd(net, "crystalpilot_net"))
        else:
            sy = {"rcsr_symbol": None, "rcsr_status": "未算（本次未请求 Systre）"}
    else:
        sy = {"rcsr_symbol": None, "rcsr_symbols": [],
              "rcsr_status": "未算（简化网没有边：无金属节点或全为端基）"}
    net["rcsr_symbol"] = sy.get("rcsr_symbol")
    # one symbol per connected component: an interpenetrated / multi-net
    # structure has more than one, and Systre names each separately
    net["rcsr_symbols"] = sy.get("rcsr_symbols") or []
    net["rcsr_status"] = sy.get("rcsr_status")
    if sy.get("systre_error"):
        net["systre_error"] = sy["systre_error"]
    if sy.get("systre_output"):
        net["systre_output"] = str(sy["systre_output"])[:4000]
    return {
        "nets": nets,
        "simplified_net": net,
        "helices": helices(xs, parts=parts),
        "finite_fragments": _finite_fragments(xs, parts),
        "note": ("网/互穿/简化网/螺旋读自同一份成键真值（chem.bonding）在 P1 "
                 "展开上的连通分量；大环普查与形状证据只对 0 维片段（分子/笼/"
                 "抗衡离子）做，且一律是描述，命名留给晶体学家。"),
    }


class UnsupportedAnalysisStage(NotImplementedError):
    """A scientific block is unavailable for this input, not a zero result."""


class AnalysisStages:
    """One node's immutable inputs and independently callable analysis blocks.

    Construction only reads metadata; no session, reflections or expensive
    pore calculation is needed to expose the first three blocks.
    """

    def __init__(self, project_dir: str | Path, node_id: str) -> None:
        from .nodes import NodeStore
        from .scene import VOIDS_CACHE_V, _resolve_ref, cache_dir

        self.project_dir = Path(project_dir).resolve()
        store = NodeStore(self.project_dir)
        self.node = _resolve_ref(store, node_id)
        self.meta = store.node_meta(self.node)
        self.model_path = store.node_dir(self.node) / "model.res"
        cif_path = self.model_path.with_suffix(".cif")
        if (self.meta.get("canonical_model") == "model.cif"
                or (not self.model_path.exists() and cif_path.exists())):
            self.model_path = cif_path
        self.cache_path = cache_dir(self.project_dir, self.node) / "analysis.json"
        self.voids_v = VOIDS_CACHE_V

    def empty_result(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "v": ANALYSIS_CACHE_V, "voids_v": self.voids_v,
            "node": self.node, "source_revision": self.meta.get("revision"),
            "timings_s": {}, "stages": {},
        }
        for stage in ANALYSIS_STAGES:
            out[stage] = None
            out[f"{stage}_note"] = "等待计算"
            out["stages"][stage] = {
                "status": "waiting", "elapsed_s": 0.0,
                "error": None, "note": "等待计算",
            }
        return out

    def cached_result(self) -> dict[str, Any] | None:
        product = _read_current(self.cache_path)
        if product is not None and product.get("node") == self.node:
            return product
        return None

    def guest_d_min(self) -> float | None:
        """Recorded mask settings win over the node's data resolution.

        Legacy nodes with neither use the geometry engine's documented grid
        default; reconstructing a refinement session here would defeat early
        results and can reread different reflection data.
        """
        from .scene import _void_mask_params

        params, _source = _void_mask_params(
            self.meta, (self.meta.get("data") or {}).get("d_min"))
        return params.get("d_min")

    def compute(self, stage: str) -> dict[str, Any]:
        if stage == "interactions":
            return interactions_from_res(self.model_path)
        if stage == "topology":
            return topology_from_res(self.model_path)
        if stage == "guests":
            return guests_from_res(self.model_path, d_min=self.guest_d_min())
        if stage == "pores":
            from .scene import cached_voids

            _ccp4, meta = cached_voids(self.project_dir, self.node)
            pores = json.loads(meta.read_text(encoding="utf-8"))
            if pores.get("packing") is None:
                pores["packing"] = None
                pores["packing_note"] = PENDING_PACKING_NOTE
            return pores
        raise ValueError(f"unknown analysis stage: {stage}")

    def save(self, product: dict[str, Any]) -> Path:
        return _write_product(self.cache_path, product)


def iter_analysis_stages(
    analysis: AnalysisStages, *, cancelled: Callable[[], bool] | None = None,
) -> Iterator[dict[str, Any]]:
    """The common synchronous/background pipeline, fastest useful blocks first.

    Yielding ``running`` commits a stage start. Cancellation is checked again
    before calling its engine, but an engine already executing is not forcibly
    interrupted. Its honest result is retained; later stages are cancelled.
    """
    for stage in ANALYSIS_STAGES:
        if cancelled is not None and cancelled():
            yield {"stage": stage, "status": "cancelled", "elapsed_s": 0.0,
                   "error": None, "note": "已取消，未开始计算", "value": None}
            continue
        yield {"stage": stage, "status": "running", "elapsed_s": 0.0,
               "error": None, "note": "计算中", "value": None}
        if cancelled is not None and cancelled():
            yield {"stage": stage, "status": "cancelled", "elapsed_s": 0.0,
                   "error": None, "note": "已取消，未开始计算", "value": None}
            continue
        t0 = time.monotonic()
        value, error, note = None, None, None
        try:
            value = analysis.compute(stage)
            if value is None:
                raise ValueError("analysis stage returned no result")
            status = "ready"
        except (UnsupportedAnalysisStage, ModuleNotFoundError) as exc:
            status = "unsupported"
            note = str(exc)
            error = f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001 - isolate scientific blocks
            status = "error"
            error = f"{type(exc).__name__}: {exc}"
            note = {"guests": PENDING_GUESTS_NOTE,
                    "topology": PENDING_TOPOLOGY_NOTE}.get(
                        stage, f"{stage} 计算失败（见 {stage}_error）")
        yield {"stage": stage, "status": status,
               "elapsed_s": round(time.monotonic() - t0, 3),
               "error": error, "note": note, "value": value}


def apply_analysis_update(product: dict[str, Any], update: dict[str, Any]) -> None:
    """Apply one stage transition; the job manager calls this under its lock."""
    stage = update["stage"]
    product["stages"][stage] = {
        key: update[key] for key in ("status", "elapsed_s", "error", "note")
    }
    product[stage] = update["value"]
    for field in ("error", "note"):
        key = f"{stage}_{field}"
        if update[field] is None:
            product.pop(key, None)
        else:
            product[key] = update[field]
    if update["status"] in STAGE_TERMINAL:
        product["timings_s"][stage] = update["elapsed_s"]


def build_analysis(project_dir: str | Path, node_id: str,
                   progress=None) -> dict[str, Any]:
    """Compute all blocks synchronously, retaining other blocks on failure."""
    analysis = AnalysisStages(project_dir, node_id)
    product = analysis.empty_result()
    for update in iter_analysis_stages(analysis):
        apply_analysis_update(product, update)
        if progress is not None and update["status"] in STAGE_TERMINAL:
            try:
                progress(f"analysis product {analysis.node}: {update['stage']} "
                         f"{update['status']} in {update['elapsed_s']} s")
            except Exception:  # noqa: BLE001 - liveness is best-effort
                pass
    return product


def cacheable_analysis(product: dict[str, Any]) -> bool:
    """Do not make transient failures or cancelled work sticky cache hits."""
    stages = product.get("stages") or {}
    return all(isinstance(stages.get(stage), dict)
               and stages[stage].get("status") in {"ready", "unsupported"}
               and (stages[stage]["status"] != "ready"
                    or product.get(stage) is not None)
               for stage in ANALYSIS_STAGES)


def _read_current(path: Path) -> dict[str, Any] | None:
    from .scene import VOIDS_CACHE_V

    try:
        product = json.loads(path.read_text(encoding="utf-8"))
        if (product.get("v") == ANALYSIS_CACHE_V
                and product.get("voids_v") == VOIDS_CACHE_V
                and cacheable_analysis(product)):
            return product
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return None


def _current(path: Path) -> bool:
    return _read_current(path) is not None


def _write_product(path: Path, product: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Same-directory atomic replace: readers never see a partial JSON file.
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(product, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def cached_analysis(project_dir: str | Path, node_id: str,
                    progress=None) -> Path:
    """Complete synchronous product; validity uses integer cache versions only.

    Failed blocks are written for old path-based consumers, but are not reused
    as cache hits. Progressive callers never persist cancelled or failed work.
    """
    analysis = AnalysisStages(project_dir, node_id)
    if analysis.cached_result() is not None:
        return analysis.cache_path
    return analysis.save(build_analysis(project_dir, analysis.node, progress=progress))
