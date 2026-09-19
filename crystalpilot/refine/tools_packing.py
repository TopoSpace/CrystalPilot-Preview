"""`analyze_packing` (round-2 R5): the measurement tables of ONE node's
packing - interactions, pores, packing numbers, guest sites - read from the
same per-node analysis product the workbench 分析 tab shows
(`refine/analysis.py`), so the number the agent quotes is the number the
user sees.

Three parts per block, always (plan §2 "判断力 > 阈值"): the measurements,
the criteria they were measured under (with their sources), and a reading
that is labelled as interpretation. Nothing here is a verdict; the
structure is not called "right" or "wrong" by this tool.

The hydrogen-bond table also comes back as ready-made `EQIV` / `HTAB`
cards for `run_shelxl(extra_cards=...)`: SHELXL - not this tool - then
computes `_geom_hbond_*` WITH esds into the CIF (`refine/shelx_cards.py`).
"""
from __future__ import annotations

import json
from typing import Any

from ..tools.base import ToolContext, ToolResult, progress_heartbeat
from .toolbase import _ProjectTool

#: rows per kind returned by default; the product keeps up to 600 per kind
DEFAULT_MAX_ROWS = 40

_ROW_DROP_SUFFIXES = ("_seq", "_xyz", "_inst")
_ROW_DROP_KEYS = {"ring_key", "h_xyz", "c_xyz", "anion"}

_KIND_ZH = {"hbond": "氢键", "pipi": "π–π 堆积", "chpi": "C–H···π",
            "chx": "C–H···X", "halogen": "卤键", "anion_pi": "阴离子–π"}
_REL_ZH = {"translation": "晶格平移相关", "space_group_op": "空间群操作相关",
           "independent": "晶体学独立"}
_SITE_ZH = {"cage_cavity": "笼内", "channel": "通道", "cavity": "分子间空腔",
            "interstitial": "晶格间隙"}
_BLOCKS = ("interactions", "pores", "packing", "guests", "topology")
_BLOCK_ZH = {"interactions": "相互作用", "pores": "孔道", "packing": "堆积数字",
             "guests": "客体位置", "topology": "拓扑"}


def _block_state(product: dict, block: str, value: Any) -> dict[str, Any]:
    """Adapt staged and legacy products without turning missing blocks into zeros."""
    stage = "pores" if block == "packing" else block
    recorded = (product.get("stages") or {}).get(stage) or {}
    status = recorded.get("status")
    error = product.get(f"{block}_error") or recorded.get("error")
    note = product.get(f"{block}_note") or recorded.get("note")
    if block == "packing":
        pores = product.get("pores")
        note = (pores or {}).get("packing_note") or note
        if pores is None:
            error = error or product.get("pores_error")
            note = "堆积数字依赖 pores 块；" + str(
                note or product.get("pores_note") or "孔道分析结果不可用")
        if value is not None:
            status = "ready"
    if value is None:
        if status in (None, "ready"):
            status = "error" if error else "unavailable"
        note = note or "该分析块没有可用计算结果；不能视为零或未发现。"
    elif status is None:
        status = "ready"
    return {"status": status, "elapsed_s": recorded.get("elapsed_s"),
            "error": None if status == "ready" else error,
            "note": note}


def _slim_row(r: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in r.items()
            if not k.startswith("_") and k not in _ROW_DROP_KEYS
            and not k.endswith(_ROW_DROP_SUFFIXES)}


def _topology_reading(nets: dict, net: dict, hel: list, ff: list) -> str:
    """One Chinese sentence over the topology block - a description with
    its basis, labelled as such; the shape words are left to the reader."""
    if nets.get("n_nets") is None:
        rd = "周期性网计数未提供，不能据此判定为分子晶体"
    elif nets["n_nets"] == 0:
        rd = "没有周期性网（分子晶体）"
    else:
        dims = "/".join(str(n.get("dimensionality")) for n in nets.get("nets") or [])
        rd = f"独立网 {nets['n_nets']} 个（维度 {dims}）"
        rel = [r for r in nets.get("relations") or []
               if r.get("relation") in ("translation", "space_group_op")]
        rel_txt = "；".join(
            f"网{r['a']}↔网{r['b']} {_REL_ZH.get(r['relation'], r['relation'])}"
            + (f"（{r['shift']}）" if r.get("shift") else "")
            + (f" {r['op']}" if r.get("op") else "") for r in rel)
        verdict = nets.get("interpenetrated")
        status = nets.get("interpenetration_status")
        # round-3 R5: the verdict is the ring-threading test's; the symmetry
        # relation is reported beside it, never in its place
        if verdict is True:
            ex = next((p.get("example") for p in
                       (nets.get("threading") or {}).get("pairs") or []
                       if p.get("status") == "threaded"), None)
            rd += "，**互穿**（环穿越判定：另一网的键穿过本网窗口"
            if ex:
                rd += f"，例 {ex['window_size']} 节点窗口 / 键 {'–'.join(ex['bond'])}"
            rd += "）"
            if rel_txt:
                rd += "，网间对称关系：" + rel_txt
        elif verdict is False and nets["n_nets"] > 1:
            rd += "，不互穿（环穿越判定：所有窗口都没有被另一网的键穿过）"
            if rel_txt:
                rd += "，但对称相关：" + rel_txt + "（平行层一类）"
        elif nets.get("symmetry_related", False):
            rd += (f"，对称相关多网（互穿未判定：{status}）：" + rel_txt)
        elif nets["n_nets"] > 1:
            rd += f"，未找到网间对称映射；互穿未判定（{status}）"
        if nets.get("interlocked_1d") is True:
            rd += "，一维链机械互锁（环穿越判定）"
        elif nets.get("symmetry_related_1d", False):
            rd += "，一维链对称相关（机械互锁未判定：无环可穿或未完成）"
    if net.get("n_nodes_per_cell"):
        hist = "、".join(f"{c}-连接 ×{n}" for c, n in
                        (net.get("node_connectivity_histogram") or {}).items())
        symbols = net.get("rcsr_symbols") or ([net["rcsr_symbol"]]
                                               if net.get("rcsr_symbol") else [])
        rd += (f"；简化网每胞 {net['n_nodes_per_cell']} 节点 / "
               f"{net.get('n_edges_per_cell', '未提供')} 边（{hist}）；"
               + ("RCSR " + "/".join(str(symbol) for symbol in symbols) if symbols
                  else str(net.get("rcsr_status") or "RCSR 状态未提供")))
    if hel:
        def _hand(h):
            if h.get("racemic"):
                return " 外消旋"
            return {"right": " 右手", "left": " 左手"}.get(h.get("handedness") or "", "")
        rd += "；螺旋链 " + "；".join(
            f"{h['screw']}{_hand(h)} 螺距 {h['pitch_A']:.2f} Å" for h in hel)
    if ff:
        bits = []
        for f in ff[:6]:
            b = f"{f['fragment']} {f['n_atoms']} 原子 {'宿主' if f.get('role') == 'host' else '客体'}"
            lc = f.get("largest_cycle") or {}
            if lc.get("size"):
                b += f" 最大无弦环 {lc['size']}"
            sh = f.get("shape") or {}
            if sh.get("sphericity") is not None:
                b += f" 球形度 {sh['sphericity']:.2f}"
            bits.append(b)
        rd += "；有限片段 " + "；".join(bits)
    return "拓扑（描述，不是判定）：" + rd + "。"


#: round-3 R5: electrons per cell come from TWO masks - the refinement's own
#: (the snapshot in node meta, the one that entered Fc) and a fresh recount on
#: this node with the recorded parameters; above this relative gap the reading
#: says they disagree and which one to quote
ELECTRON_BASIS_DISAGREE = 0.20


def _electron_count_basis(pores: dict[str, Any]) -> dict[str, Any]:
    """Which mask the electron numbers in `pores` come from, both per cell:
    {per, recomputed_on_node, params_source, recomputed_total_e,
    refinement_mask_snapshot{...} | None, relative_difference?, note}."""
    recorded = pores.get("recorded") or {}
    recomputed = pores.get("total_solvent_electrons_per_cell")
    snapshot = recorded.get("total_solvent_electrons_per_cell")
    snap_block = {k: recorded.get(k) for k in
                  ("n_voids", "solvent_volume_A3", "solvent_volume_pct_of_cell",
                   "total_solvent_electrons_per_cell")
                  if recorded.get(k) is not None}
    basis: dict[str, Any] = {
        "per": "cell",
        "recomputed_on_node": pores.get("node"),
        "params_source": pores.get("params_source"),
        "recomputed_total_e": recomputed,
        "refinement_mask_snapshot": snap_block or None,
    }
    bypass = pores.get("bypass") or {}
    if "converged" in bypass:
        # the recount's own series: an unconverged recount is not a number
        # to compare the snapshot against, whatever the gap
        basis["recomputed_converged"] = bool(bypass["converged"])
        basis["recomputed_cycles"] = bypass.get("n_cycles")
    if pores.get("anomalous_terms"):
        basis["anomalous_terms"] = pores["anomalous_terms"]
    if recomputed is not None and snapshot is not None:
        diff = abs(float(recomputed) - float(snapshot))
        ref = max(abs(float(snapshot)), 1e-9)
        rel = diff / ref
        basis["relative_difference"] = round(rel, 3)
        basis["agree"] = rel <= ELECTRON_BASIS_DISAGREE
        basis["note"] = (
            "same unit (electrons per cell), two computations: the refinement "
            "mask snapshot is the one that entered Fc; the recomputed number is "
            "a fresh mask on this node's model with the recorded parameters. "
            "Quote the snapshot for stoichiometry; the recount is a cross-check"
            + (f" - they disagree by more than {ELECTRON_BASIS_DISAGREE:.0%}, "
               "so the model or the mask cycles differ between the two"
               if rel > ELECTRON_BASIS_DISAGREE else "")
            + (f" - and the recount did NOT converge ({bypass.get('n_cycles')} "
               f"cycles, f_000_s {bypass.get('f000s_first')} -> "
               f"{bypass.get('f000s_last')} e), so it is not a settled number"
               if basis.get("recomputed_converged") is False else ""))
    elif recomputed is not None:
        basis["note"] = ("electrons per cell from a mask recomputed on this "
                         "node; no refinement mask snapshot to compare with")
    elif snapshot is not None:
        basis["note"] = ("no recount on this node (geometric / structure-only "
                         "product); the refinement mask snapshot is the only "
                         "electron count")
    return basis


def _electron_basis_sentence(basis: dict[str, Any]) -> str | None:
    """The reading sentence for `_electron_count_basis`: both numbers, both
    labelled per cell, and which one to quote when they differ."""
    rec = basis.get("recomputed_total_e")
    snap = (basis.get("refinement_mask_snapshot") or {}).get(
        "total_solvent_electrons_per_cell")
    if rec is None and snap is None:
        return None
    if rec is None:
        return (f"残余电子合计（每胞）只有精修所用掩膜快照 {snap} e/胞；"
                "本节点没有重算（几何/仅结构产物）。")
    line = (f"残余电子合计 {rec} e/胞（本节点重算的掩膜，"
            f"参数来源 {basis.get('params_source')}）")
    unconverged = basis.get("recomputed_converged") is False
    if unconverged:
        line += (f"，但重算的 BYPASS 序列未收敛（{basis.get('recomputed_cycles')} 轮），"
                 "该值不是定值")
    if snap is not None:
        line += f"；精修所用掩膜快照 {snap} e/胞"
        if unconverged:
            line += "，计量以精修掩膜快照为准"
        elif basis.get("agree") is False:
            line += (f"，两者口径相同（整胞）但相差超过 "
                     f"{ELECTRON_BASIS_DISAGREE:.0%}：模型或掩膜循环不同，"
                     "计量以精修掩膜快照为准，重算值只作对照")
        else:
            line += "（两者一致）"
    return line + "。"


class AnalyzePacking(_ProjectTool):
    name = "analyze_packing"
    description = (
        "Measurement tables of one node's PACKING, from the cached per-node "
        "analysis product the workbench 分析 tab shows (first build of a "
        "large cell can take 1-2 min: the solvent mask). Blocks: "
        "interactions (symmetry-unique hydrogen bonds, pi-pi, C-H...pi, "
        "C-H...X, halogen, anion-pi; intermolecular and passing by default, "
        "every row with its operator), pores (volume, dimensionality, "
        "channel directions, LCD, PLD +- grid step, electrons), packing "
        "(vdW-envelope packing index +-, A^3 per non-H atom), guests "
        "(cage_cavity / channel / cavity / interstitial, definitions "
        "attached), topology (independent nets and their symmetry relation - "
        "symmetry relations by translation/space-group mapping, NOT a proof "
        "of interpenetration or interlocking -, the node-linker simplified net "
        "with its connectivity histogram and the RCSR symbol when Systre is "
        "installed, helices with handedness and pitch, finite fragments' largest "
        "chordless ring + shape evidence: sphericity, aspect, longest axis - "
        "descriptions, never a shape name). Every block = measurements + the "
        "criteria with sources "
        "+ a reading marked as interpretation; no verdicts. Also returns "
        "EQIV/HTAB cards for run_shelxl(extra_cards=) so SHELXL computes "
        "the hydrogen-bond esds into the CIF. Missing/failed requested blocks "
        "are null with explicit block_status; successful blocks remain available. "
        "criteria='platon' recomputes "
        "the interactions with the wider Steiner/PLATON thresholds.")
    params_schema = {
        "type": "object",
        "properties": {
            "node": {"type": "string", "default": "active",
                     "description": "node id (n0012) or 'active'"},
            "blocks": {"type": "array",
                       "items": {"type": "string",
                                 "enum": ["interactions", "pores", "packing",
                                          "guests", "topology"]},
                       "description": "subset of blocks (default: all)"},
            "kinds": {"type": "array",
                      "items": {"type": "string",
                                "enum": ["hbond", "pipi", "chpi", "chx",
                                         "halogen", "anion_pi"]},
                      "description": "interaction kinds (default: all)"},
            "criteria": {"type": "string", "enum": ["olex2", "platon"],
                         "default": "olex2",
                         "description": "olex2 = htab/pipi defaults (the "
                                        "cached product); platon = Steiner "
                                        "H...A <= sum vdW, angle >= 110"},
            "only_passing": {"type": "boolean", "default": True,
                             "description": "drop rows that fail the angle "
                                            "criterion (counts stay)"},
            "include_intra": {"type": "boolean", "default": False,
                              "description": "keep intramolecular rows "
                                             "(same fragment, identity op)"},
            "max_rows": {"type": "integer", "default": DEFAULT_MAX_ROWS,
                         "description": "rows per interaction kind"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from .analysis import (AnalysisStages, UnsupportedAnalysisStage,
                               cached_analysis, interactions_from_res)
        from .nodes import NodeStore
        from .scene import _resolve_ref
        from .shelx_cards import htab_cards

        p = self.project
        node_ref = str(params.get("node") or "active")
        try:
            store = NodeStore(p.dir)
            node = _resolve_ref(store, node_ref)
        except Exception as e:  # noqa: BLE001
            return ToolResult.failure(f"unknown node {node_ref!r}: {e}")
        blocks = set(params.get("blocks") or _BLOCKS)
        kinds = list(params.get("kinds") or
                     ("hbond", "pipi", "chpi", "chx", "halogen", "anion_pi"))
        criteria = str(params.get("criteria") or "olex2")
        only_passing = bool(params.get("only_passing", True))
        include_intra = bool(params.get("include_intra", False))
        max_rows = max(1, int(params.get("max_rows") or DEFAULT_MAX_ROWS))

        try:
            # liveness while the mask / distance field / topology build:
            # the reg9-dbu agent read a silent 8-minute build as a hang
            with progress_heartbeat(ctx, f"analyze_packing: building the "
                                         f"analysis product of {node}"):
                path = cached_analysis(p.dir, node, progress=getattr(ctx, "progress", None))
                product = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            return ToolResult.failure(f"analysis product failed: {e}")

        payloads = {block: product.get(block) for block in _BLOCKS}
        pores = payloads["pores"]
        payloads["packing"] = (pores or {}).get("packing")
        states = {block: _block_state(product, block, payloads[block])
                  for block in _BLOCKS if block in blocks}
        if "interactions" in blocks and criteria != "olex2":
            try:
                model_path = AnalysisStages(p.dir, node).model_path
                payloads["interactions"] = interactions_from_res(model_path, criteria=criteria)
                if payloads["interactions"] is None:
                    raise ValueError("interaction calculation returned no result")
                states["interactions"] = {
                    "status": "ready", "elapsed_s": None, "error": None, "note": None}
            except Exception as e:  # noqa: BLE001 - retain independent blocks
                payloads["interactions"] = None
                states["interactions"] = {
                    "status": ("unsupported" if isinstance(
                        e, (UnsupportedAnalysisStage, ModuleNotFoundError)) else "error"),
                    "elapsed_s": None, "error": f"{type(e).__name__}: {e}",
                    "note": f"{criteria} 相互作用计算未能提供结果；未回退到其他判据。",
                }

        summary: dict[str, Any] = {
            "node": node,
            "product": str(path),
            "product_version": product.get("v"),
            "scope": "canonical",
            "scope_note": ("对称唯一表：整个晶体的性质，不随查看器显示范围变；"
                           "查看器画的是同一引擎在当前范围上的实例化"),
            "filters": {"criteria": criteria, "only_passing": only_passing,
                        "include_intra": include_intra, "max_rows": max_rows,
                        "kinds": kinds, "blocks": list(states)},
            "block_status": states,
            "reading_note": "reading 是解读，不是判词；判据与来源随每块给出",
        }
        reading: list[str] = []
        for block, state in states.items():
            if state["status"] != "ready":
                summary[block] = None
                summary[f"{block}_note"] = state["note"]
                summary[f"{block}_error"] = state["error"]
                reading.append(f"{_BLOCK_ZH[block]}不可用（{state['status']}）："
                               f"{state['note'] or state['error'] or '没有可用结果'}")
        if ("interactions" in states and states["interactions"]["status"] != "ready"
                and "hbond" in kinds):
            summary["suggested_cards"] = None
            summary["suggested_cards_note"] = "相互作用块不可用，未生成 EQIV/HTAB 卡。"

        # ---- interactions ---------------------------------------------------
        if "interactions" in blocks and states["interactions"]["status"] == "ready":
            inter = payloads["interactions"]
            rows_by_kind: dict[str, list[dict[str, Any]]] = {}
            counts: dict[str, dict[str, int]] = {}
            shown_total = 0
            for k in kinds:
                rows = list(inter["unique"].get(k) or [])
                n_all = len(rows)
                n_pass = sum(1 for r in rows if r.get("passes"))
                n_intra = sum(1 for r in rows if r.get("intra"))
                kept = [r for r in rows
                        if (r.get("passes") or not only_passing)
                        and (not r.get("intra") or include_intra)]
                counts[k] = {"unique": n_all, "passing": n_pass,
                             "intra": n_intra, "kept": len(kept),
                             "shown": min(len(kept), max_rows)}
                rows_by_kind[k] = [_slim_row(r) for r in kept[:max_rows]]
                shown_total += counts[k]["shown"]
            crit_block = {k: inter["criteria"].get(k) for k in kinds}
            summary["interactions"] = {
                "criteria_set": (inter["criteria"].get(kinds[0]) or {}).get("set")
                if kinds else None,
                "h_source": inter["h_source"],
                "h_source_note": inter["h_source_note"],
                "counts": {**counts, "shown_total": shown_total},
                "rows": rows_by_kind,
                "criteria": crit_block,
                "truncated_in_product": inter.get("truncated") or {},
                "halo": inter.get("range"),
            }
            inter_pass = {k: counts[k]["passing"] - counts[k]["intra"]
                          for k in kinds}
            parts = [f"{_KIND_ZH[k]} {counts[k]['passing']} 条满足判据"
                     f"（其中分子内 {counts[k]['intra']}）"
                     for k in kinds if counts[k]["unique"]]
            if parts:
                reading.append("相互作用（对称唯一、" + inter["criteria"]
                               .get(kinds[0], {}).get("set", criteria)
                               + " 判据）：" + "；".join(parts) + "。")
            else:
                reading.append("按所选判据未找到任何相互作用行。")
            if inter["h_source"] in ("riding", "mixed"):
                reading.append("氢为骑乘模型：H···A 系统性偏长 0.1–0.15 Å，"
                               "角度由约束决定，不是测量值。")
            # ---- HTAB cards: SHELXL computes the esds, not this tool ------
            if "hbond" in kinds:
                cards = htab_cards(inter["unique"].get("hbond") or [],
                                   inter["h_source"])
                summary["suggested_cards"] = {
                    **cards, "n_cards": len(cards.get("cards") or []),
                    "how": ("run_shelxl(extra_cards=cards, reason=...) -> "
                            "_geom_hbond_* with esds in final.cif"),
                }
            del inter_pass

        # ---- pores ------------------------------------------------------------
        if "pores" in blocks and states["pores"]["status"] == "ready":
            voids = (None if pores.get("voids") is None else [
                {k: v.get(k) for k in (
                    "void", "volume_A3", "masked", "dimensionality",
                    "directions", "lcd_A", "pld_A", "pld_error_A",
                    "pld_directions", "pld_note", "pld_along",
                    "pld_along_error_A", "pld_along_note",
                    "inscribed_centre_frac",
                    "centre_frac", "grid_step_A", "electrons") if k in v}
                for v in pores["voids"]])
            summary_basis = _electron_count_basis(pores)
            summary["pores"] = {
                "n_voids": pores.get("n_voids"),
                "voids": voids,
                "solvent_volume_A3": pores.get("solvent_volume_A3"),
                "solvent_volume_pct_of_cell":
                    pores.get("solvent_volume_pct_of_cell"),
                "total_solvent_electrons_per_cell":
                    pores.get("total_solvent_electrons_per_cell"),
                "electron_count_note": pores.get("electron_count_note"),
                "electron_count_status": pores.get("electron_count_status"),
                "electron_count_basis": summary_basis,
                "bypass": pores.get("bypass"),
                "anomalous_terms": pores.get("anomalous_terms"),
                "mode": pores.get("mode"),
                "params_source": pores.get("params_source"),
                "mask_params": pores.get("mask_params"),
                "criteria": pores.get("pore_note"),
            }
            if voids:
                for v in voids:
                    dim = v.get("dimensionality")
                    dim_zh = {0: "孤立空腔", 1: "1-D 通道", 2: "2-D 层",
                              3: "3-D 网络"}.get(dim, str(dim))
                    s = (f"孔 V{v['void']}：{v['volume_A3']} Å³，{dim_zh}"
                         + (f"，方向 {v['directions']}" if v.get("directions") else "")
                         + (f"，LCD {v['lcd_A']} Å" if v.get("lcd_A") is not None else ""))
                    if v.get("pld_A") is not None:
                        s += f"，PLD {v['pld_A']} ± {v.get('pld_error_A')} Å"
                    elif v.get("pld_note"):
                        s += f"，PLD：{v['pld_note']}"
                    along = v.get("pld_along")
                    if isinstance(along, dict):
                        s += "，沿 a/b/c 的 PLD " + "/".join(
                            "—" if along.get(ax) is None else f"{along[ax]}"
                            for ax in ("a", "b", "c")) + " Å（— = 该方向不贯通）"
                    elif v.get("pld_along_note"):
                        s += f"，沿轴 PLD：{v['pld_along_note']}"
                    if v.get("electrons") is not None:
                        s += f"，残余电子约 {v['electrons']} e（每胞）"
                    reading.append(s + "。")
                basis_line = _electron_basis_sentence(summary_basis)
                if basis_line:
                    reading.append(basis_line)
                pct = pores.get("solvent_volume_pct_of_cell")
                if pct is not None:
                    reading.append(
                        f"溶剂可及体积占胞 {pct} %（探针 "
                        f"{pores.get('solvent_radius')} Å；探针滚不进的尖角"
                        "空间不在其中）。")
            elif pores.get("n_voids") == 0:
                reading.append("该模型未检出溶剂可及孔道（按本次记录的探针参数）。")
            else:
                reading.append("孔道逐项明细未提供；不能据此判定没有孔道。")

        # ---- packing numbers ---------------------------------------------------
        if "packing" in blocks and states["packing"]["status"] == "ready":
            pk = payloads["packing"]
            summary["packing"] = pk
            reading.append(
                f"堆积指数（vdW 球并集）{pk.get('packing_index_pct')} ± "
                f"{pk.get('packing_index_error_pct')} %，"
                f"{pk.get('volume_per_non_h_atom_A3')} Å³/非氢原子"
                "（致密分子晶体典型 65–77 % 与 ≈18 Å³；"
                "多孔骨架两者都会偏离，这不是缺陷）。")

        # ---- guests --------------------------------------------------------------
        if "guests" in blocks and states["guests"]["status"] == "ready":
            g = payloads["guests"]
            rows = []
            for x in g.get("guests") or []:
                c = (x.get("nearest_host_contacts") or [None])[0]
                rows.append({k: x.get(k) for k in (
                    "fragment", "formula", "copies", "role", "site",
                    "void_id", "host_fragment", "clearance_A",
                    "d_to_inscribed_centre_A", "straddles_regions",
                    "parts")} | {"nearest_host_contact": c})
            summary["guests"] = {
                "host": g.get("host"),
                "summary": g.get("summary"),
                "guests": rows,
                "criteria": g.get("criteria"),
                "grid_step_A": g.get("grid_step_A"),
                "probe_A": g.get("probe_A"),
            }
            sm = g.get("summary") or {}
            if rows:
                reading.append("客体位置：" + "；".join(
                    f"{_SITE_ZH.get(k, k)} {n}" for k, n in sm.items() if n)
                    + f"（宿主规则：{(g.get('host') or {}).get('selection_rule')}）。")
            else:
                # T-j (round 3): "no guest fragment" read as "no guest" in the
                # forensic thread while the guest was COORDINATED to the
                # framework and therefore part of the host fragment
                rule = (g.get("host") or {}).get("selection_rule")
                reading.append(
                    f"按宿主规则（{rule}）没有单列出客体 / 抗衡离子片段。注意："
                    "与骨架配位或共价相连的客体已并入宿主片段，不会出现在这"
                    "一栏，请到配位环境或原子表按标签核对；独立的溶剂 / "
                    "抗衡离子片段也确实没有。")

        # ---- topology (R4) -------------------------------------------------------
        if "topology" in blocks and states["topology"]["status"] == "ready":
            tp = payloads["topology"]
            nets = tp.get("nets") or {}
            net = tp.get("simplified_net") or {}
            hel = tp.get("helices") or []
            ff = tp.get("finite_fragments") or []
            summary["topology"] = {
                "nets": {k: nets.get(k) for k in (
                    "n_nets", "nets", "relations", "interpenetrated",
                    "interlocked_1d", "symmetry_related", "symmetry_related_1d",
                    "interpenetration_status", "threading", "host", "notes",
                    "definition")},
                "simplified_net": {k: net.get(k) for k in (
                    "nodes", "edges", "n_nodes_per_cell", "n_edges_per_cell",
                    "node_connectivity_histogram", "linkers", "rcsr_symbol",
                    "rcsr_symbols", "rcsr_status", "confidence", "note", "definition")},
                "helices": [{k: h.get(k) for k in (
                    "fragment", "asu_labels", "screw", "handedness",
                    "pitch_A", "axis_repeat_A", "chain_direction",
                    "racemic", "definition")} for h in hel],
                "finite_fragments": ff,
                "note": tp.get("note"),
            }
            reading.append(_topology_reading(nets, net, hel, ff))

        ready = [block for block, state in states.items() if state["status"] == "ready"]
        unavailable = [block for block in states if block not in ready]
        failed = [block for block in unavailable if states[block]["status"] == "error"]
        status = ("ready" if not unavailable else "partial" if ready else
                  "error" if failed else "unsupported" if all(
                      state["status"] == "unsupported" for state in states.values())
                  else "unavailable")
        summary.update({"status": status, "failed_blocks": failed,
                        "unavailable_blocks": unavailable, "reading": reading})
        error = None if ready else (
            "No requested analysis block is available: " + "; ".join(
                f"{block}: {states[block]['error'] or states[block]['note']}"
                for block in unavailable))
        return ToolResult(ok=bool(ready), summary=summary, error=error)
