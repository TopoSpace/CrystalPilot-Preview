"""Turn the pa1 batch into a report you can act on.

Two questions, and they need different treatment.

**Did prompt informativeness matter?** Only answerable against a noise
floor. One crystal runs its whole ladder twice, so the same cell is
measured twice under the same conditions; the spread between those pairs
is what run-to-run variance looks like here. Any L0-to-L3 difference
smaller than that gets reported as not distinguishable, not as a finding.
This exists because r22's single informed/blind pair differed by R1
0.0006 and there was no way to say whether that was a real null result or
an underpowered one.

**Where does the system trip?** Aggregated across every run, because a
tool that fails once is an accident and a tool that fails in nine runs out
of sixteen is a defect. Ranked by cost in seconds where cost is known -
"run_shelxt burned 41 minutes across the batch" is a budget item; "some
tools errored" is not.

Wall-clock carries its concurrency count everywhere it appears. Three
lanes shared one CPU budget, and lanes drained at different times, so a
bare minute count would be comparing measurements taken under different
loads.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
LANES = ("pa1-hex", "pa1-hex3", "pa1-cu", "pa1-cu2", "pa1-cu3",
         "pa1-cage", "pa1-cage2")
ARMS = ("L0", "L1", "L2", "L3")

#: worst to best. Ordinal only for "did the ladder move it", never printed
#: as a score - the bands are qualitative and spacing between them is not
#: meaningful.
GRADE_RANK = {
    "no_delivery": 0, "below_bar": 1, "self_consistent_fail": 1,
    "self_consistent": 2, "self_consistent_pass": 2,
    "acceptable": 3, "publication": 4,
}


def _load(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def collect(work: Path = REPO / "workdir" / "campaigns",
            lanes: tuple[str, ...] = LANES) -> list[dict[str, Any]]:
    """One record per cell: state + grade + mined logs."""
    from .campaign_analysis import analyse_case
    from .pa1_manifests import CRYSTALS

    allow = {}
    for name, spec in CRYSTALS.items():
        d = (spec.get("data_alias") or {}).get("target") or spec.get("data_dir")
        allow[name] = [d, (spec.get("data_alias") or {}).get("link")]

    out: list[dict[str, Any]] = []
    for lane in lanes:
        state = _load(work / lane / "state.json") or {}
        for case, st in state.items():
            cdir = work / lane / case
            crystal, arm = case.split("-")[0], case.split("-")[1].upper()
            rec: dict[str, Any] = {
                "lane": lane, "case": case, "crystal": crystal, "arm": arm,
                "replicate": int(case.rsplit("r", 1)[-1] or 1),
                "status": st.get("status"), "grade": st.get("grade"),
                "wall_s": st.get("wall_s"),
                "lanes_busy": st.get("lanes_busy"),
                "turn_status": st.get("turn_status"),
                "tokens": (st.get("usage") or {}).get("total_tokens"),
                "n_tool_events": st.get("n_tool_events"),
                "log_errors": st.get("log_errors"),
            }
            g = _load(cdir / "grade.json") or {}
            sc = g.get("self_consistency") or {}
            cif = sc.get("cif") or {}
            rec.update({
                "space_group": cif.get("space_group"),
                "r1": cif.get("r1_gt"), "wr2": cif.get("wr2"),
                "goof": cif.get("goof"), "n_atoms": cif.get("n_atoms"),
                "formula": cif.get("formula"),
                "cif_matches_fcf": sc.get("s2_cif_matches_fcf"),
                "peek_clean": (sc.get("peek_report") or {}).get("clean"),
                "checkcif": _cc_counts(sc.get("checkcif") or {}),
                "ref": _ref_summary(g),
            })
            if (cdir / "logs" / "rollout.jsonl").exists():
                rec["mined"] = analyse_case(cdir / "logs",
                                            allow.get(crystal, []))
            out.append(rec)
    return out


def _cc_counts(cc: dict[str, Any]) -> dict[str, int] | None:
    counts = cc.get("counts") or cc.get("salvagedCounts") or cc.get("salvaged_counts")
    return counts if isinstance(counts, dict) else None


def _ref_summary(g: dict[str, Any]) -> dict[str, Any]:
    r = g.get("reference") or {}
    return {k: r.get(k) for k in
            ("space_group_match", "heavy_matched", "heavy_total",
             "heavy_rms_A", "note") if k in r}


# ------------------------------------------------------------- noise floor
def noise_floor(recs: list[dict[str, Any]], crystal: str = "hex"
                ) -> dict[str, Any]:
    """Spread between the two runs of each duplicated cell.

    This is the whole reason the duplicate ladder exists. Without it an
    R1 gap of 0.01 between L0 and L3 is uninterpretable: it could be the
    prompt, or it could be what you get running the same prompt twice."""
    pairs = defaultdict(list)
    for r in recs:
        if r["crystal"] == crystal:
            pairs[r["arm"]].append(r)

    def spread(vals: list[float]) -> float | None:
        # full range, not first-vs-second: with three replicates the pair
        # that happens to be listed first is not the informative one
        vals = [v for v in vals if v is not None]
        return round(max(vals) - min(vals), 4) if len(vals) >= 2 else None

    out: dict[str, Any] = {"crystal": crystal, "arms": {}}
    d_r1, d_rank, d_atoms, d_rank_del = [], [], [], []
    for arm, rs in sorted(pairs.items()):
        if len(rs) < 2:
            continue
        row: dict[str, Any] = {
            "n": len(rs),
            "grades": [r["grade"] for r in rs],
            "space_groups": [r["space_group"] for r in rs],
        }
        for key, src, sink in (("d_r1", "r1", d_r1),
                               ("d_n_atoms", "n_atoms", d_atoms)):
            v = spread([r.get(src) for r in rs])
            if v is not None:
                row[key] = v
                sink.append(v)
        ranks = [GRADE_RANK.get(r.get("grade") or "") for r in rs]
        v = spread([float(x) for x in ranks if x is not None])
        if v is not None:
            row["d_grade_rank"] = int(v)
            d_rank.append(int(v))
        # ...and again over only the runs that actually reached the tool
        # surface. The two numbers answer different questions: the first is
        # "how much does an outcome move run to run", the second is "how
        # much does it move once the plumbing worked". A four-band spread
        # driven entirely by a run that never called a crystallography tool
        # says nothing about crystallography.
        # a cell still running has grade None, and GRADE_RANK.get(None, 0)
        # would score it as no_delivery - inflating the spread with a run
        # that has not finished
        delivered = [r for r in rs
                     if r.get("grade") and r["grade"] != "no_delivery"]
        row["n_delivered"] = len(delivered)
        v = spread([float(GRADE_RANK.get(r.get("grade") or "", 0))
                    for r in delivered])
        if v is not None:
            row["d_grade_rank_delivered"] = int(v)
            d_rank_del.append(int(v))
        out["arms"][arm] = row
    out["floor"] = {
        "r1": max(d_r1) if d_r1 else None,
        "grade_rank": max(d_rank) if d_rank else None,
        "grade_rank_delivered": max(d_rank_del) if d_rank_del else None,
        "n_atoms": max(d_atoms) if d_atoms else None,
        "n_pairs": len(d_r1),
    }
    return out


def noise_floors(recs: list[dict[str, Any]]) -> dict[str, Any]:
    """A floor per crystal that has replicates, plus the pooled one.

    Two crystals rather than one because a floor measured on `hex` does
    not automatically apply to `cu`: a crystal whose ladder spans
    no_delivery to publication may simply be a higher-variance problem,
    and using the quieter crystal's floor to judge it would manufacture
    findings. The pooled floor is the conservative number to quote when a
    claim ranges over crystals."""
    out: dict[str, Any] = {"per_crystal": {}}
    pooled_r1: list[float] = []
    pooled_rank: list[int] = []
    pooled_rank_del: list[int] = []
    for crystal in sorted({r["crystal"] for r in recs}):
        reps = {r["replicate"] for r in recs if r["crystal"] == crystal}
        if len(reps) < 2:
            continue
        nf = noise_floor(recs, crystal)
        out["per_crystal"][crystal] = nf
        for row in nf["arms"].values():
            if "d_r1" in row:
                pooled_r1.append(row["d_r1"])
            if "d_grade_rank" in row:
                pooled_rank.append(row["d_grade_rank"])
            if "d_grade_rank_delivered" in row:
                pooled_rank_del.append(row["d_grade_rank_delivered"])
    out["pooled"] = {
        "r1": max(pooled_r1) if pooled_r1 else None,
        "grade_rank": max(pooled_rank) if pooled_rank else None,
        "grade_rank_delivered": (max(pooled_rank_del)
                                 if pooled_rank_del else None),
        "n_pairs": len(pooled_r1),
    }
    return out


# -------------------------------------------------------------- aggregation
def aggregate_failures(recs: list[dict[str, Any]]) -> dict[str, Any]:
    """Failure modes across the whole batch, ranked by what they cost."""
    tools: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "errors": 0, "secs": 0.0, "runs": 0,
                 "runs_with_error": 0, "messages": Counter()})
    spin: Counter[str] = Counter()
    churn: Counter[str] = Counter()
    hazards: dict[str, dict[str, Any]] = {}
    consequences: list[dict[str, Any]] = []
    leaks: list[dict[str, Any]] = []

    for r in recs:
        m = r.get("mined")
        if not m:
            continue
        for tool, row in (m.get("tools") or {}).items():
            t = tools[tool]
            t["calls"] += row["calls"]
            t["errors"] += row["errors"]
            t["secs"] += row["secs"]
            t["runs"] += 1
            if row["errors"]:
                t["runs_with_error"] += 1
        for f in m.get("failures") or []:
            tools[f["tool"]]["messages"][(f.get("error") or "")[:120]] += 1
        for s in m.get("spin") or []:
            spin[s["tool"]] += s["repeats"]
        for c in m.get("arg_churn") or []:
            churn[c["tool"]] += c["distinct_args"]
        for h in m.get("shell_hazards") or []:
            row = hazards.setdefault(h["hazard"],
                                     {"count": 0, "runs": 0, "why": h["why"],
                                      "example": h["example"]})
            row["count"] += h["count"]
            row["runs"] += 1
        for fc in m.get("failure_consequences") or []:
            consequences.append({**fc, "case": r["case"]})
        if not m.get("leak_clean", True):
            leaks.append({"case": r["case"], "hits": m.get("leakage")})

    ranked = sorted(tools.items(),
                    key=lambda kv: (-kv[1]["errors"], -kv[1]["secs"]))
    for _, t in ranked:
        t["secs"] = round(t["secs"], 1)
        t["error_rate"] = round(t["errors"] / t["calls"], 3) if t["calls"] else 0
        t["messages"] = t["messages"].most_common(4)
    return {
        "tools": dict(ranked),
        "spin": spin.most_common(15),
        "arg_churn": churn.most_common(15),
        "shell_hazards": hazards,
        "consequences": sorted(consequences,
                               key=lambda c: -(c.get("cost_s") or 0))[:40],
        "leaks": leaks,
    }


# ------------------------------------------------------------------ render
def _cell(r: dict[str, Any] | None) -> str:
    if r is None:
        return "—"
    g = r.get("grade") or r.get("status") or "?"
    bits = [g]
    if r.get("r1") is not None:
        bits.append(f"R1 {r['r1']:.4f}")
    if r.get("space_group"):
        bits.append(str(r["space_group"]))
    return "<br>".join(bits)


def render(recs: list[dict[str, Any]]) -> str:
    by: dict[tuple[str, str, int], dict[str, Any]] = {
        (r["crystal"], r["arm"], r["replicate"]): r for r in recs}
    crystals = sorted({r["crystal"] for r in recs})
    L: list[str] = ["# pa1，提示词信息量阶梯批测结果", ""]

    L += ["## 1. 结果矩阵", "",
          "每格：评级 / R1 / 空间群。`hex` 有两条独立阶梯（r1、r2），",
          "两者之差就是本批次的噪声地板。", "",
          "| 晶体 | " + " | ".join(ARMS) + " |",
          "|---|" + "---|" * len(ARMS)]
    for c in crystals:
        reps = sorted({r["replicate"] for r in recs if r["crystal"] == c})
        for rep in reps:
            label = f"{c}" + (f" (r{rep})" if len(reps) > 1 else "")
            L.append(f"| {label} | " + " | ".join(
                _cell(by.get((c, a, rep))) for a in ARMS) + " |")

    nfs = noise_floors(recs)
    L += ["", "## 2. 噪声地板（同一提示词跑两次的散布）", ""]
    if nfs["per_crystal"]:
        p = nfs["pooled"]
        L += ["**判读规则**：任何小于同晶体噪声地板的档位差，都不能称为",
              "提示词的效果，它落在同一提示词重复跑两次的散布之内。",
              "跨晶体的结论用合并地板（更保守）。", "",
              f"合并地板（{p['n_pairs']} 组重复）：ΔR1 ≤ **{p['r1']}**，"
              f"评级 ≤ **{p['grade_rank']}** 档；"
              f"**只看跑通了工具面的 run**，评级 ≤ "
              f"**{p.get('grade_rank_delivered')}** 档。",
              "",
              "两个数回答不同的问题：前者是「同一提示词重跑一次结果能差多少」，",
              "后者是「在管道没出问题的前提下能差多少」。四档的散布若全部来自",
              "一个从未调用过晶体学工具的 run，它说明的是管道，不是晶体学。",
              ""]
        L += ["| 晶体 | 档 | 两次评级 | 两次空间群 | ΔR1 |",
              "|---|---|---|---|---|"]
        for crystal, nf in nfs["per_crystal"].items():
            for arm, row in nf["arms"].items():
                sgs = [str(x) for x in row["space_groups"] if x]
                if len(sgs) < 2:
                    sg = (sgs[0] + "（仅 1 次交付）") if sgs else "—"
                elif len(set(sgs)) == 1:
                    sg = sgs[0] + "（一致）"
                else:
                    sg = " / ".join(sorted(set(sgs))) + "（不一致）"
                L.append(f"| {crystal} | {arm} (n={row['n']}) "
                         f"| {' / '.join(str(x) for x in row['grades'])} "
                         f"| {sg} | {row.get('d_r1', '—')} |")
        for crystal, nf in nfs["per_crystal"].items():
            f = nf["floor"]
            L.append(f"- `{crystal}` 地板：ΔR1 {f['r1']}，评级 "
                     f"{f['grade_rank']} 档，原子数 {f['n_atoms']}"
                     f"（{f['n_pairs']} 对）")
    else:
        L.append("_重复格尚未跑完，暂无噪声地板_")

    L += ["", "## 3. 成本（注意：三泳道并发下测得）", "",
          "| 格 | 墙钟 | 并发泳道 | tokens | 工具调用 |", "|---|---|---|---|---|"]
    for r in sorted(recs, key=lambda r: (r["crystal"], r["arm"], r["replicate"])):
        w = f"{r['wall_s']/60:.0f} min" if r.get("wall_s") else "—"
        tk = f"{r['tokens']/1e6:.1f}M" if r.get("tokens") else "—"
        L.append(f"| {r['case']} | {w} | {r.get('lanes_busy') or '—'} | {tk} "
                 f"| {r.get('n_tool_events') or '—'} |")

    agg = aggregate_failures(recs)
    L += ["", "## 4. 工具面失败模式（全批次汇总）", "",
          "### 4.1 出错的工具（按出错次数排）", "",
          "| 工具 | 调用 | 出错 | 错误率 | 出错的run数 | 耗时 |",
          "|---|---|---|---|---|---|"]
    for tool, t in list(agg["tools"].items())[:20]:
        if not t["errors"]:
            continue
        L.append(f"| `{tool}` | {t['calls']} | {t['errors']} "
                 f"| {t['error_rate']} | {t['runs_with_error']}/{t['runs']} "
                 f"| {t['secs']}s |")
        for msg, n in t["messages"]:
            L.append(f"| | | | | | ×{n} `{msg}` |")

    L += ["", "### 4.2 最贵的工具（按累计耗时）", "",
          "| 工具 | 调用 | 累计耗时 |", "|---|---|---|"]
    for tool, t in sorted(agg["tools"].items(),
                          key=lambda kv: -kv[1]["secs"])[:12]:
        L.append(f"| `{tool}` | {t['calls']} | {t['secs']}s |")

    L += ["", "### 4.3 原地打转（短窗口内重复同一调用）", ""]
    L += ([f"- `{t}` ×{n}" for t, n in agg["spin"]] or ["_无_"])
    L += ["", "### 4.4 参数试探（同工具连续调用、参数每次都变）", ""]
    L += ([f"- `{t}` {n} 种参数" for t, n in agg["arg_churn"]] or ["_无_"])

    L += ["", "### 4.5 shell 危险写法", ""]
    if agg["shell_hazards"]:
        for h, row in agg["shell_hazards"].items():
            L += [f"- **{h}**：{row['count']} 次，{row['runs']} 个 run",
                  f"  - 后果：{row['why']}",
                  f"  - 例：`{row['example'][:140]}`"]
    else:
        L.append("_无_")

    L += ["", "### 4.6 工具失败 → agent 下一步（最贵的在前）", "",
          "这是本轮最直接的可行动信息：一条错误消息把 agent 推去了哪里。", ""]
    for c in agg["consequences"][:15]:
        L += [f"- `{c['tool']}` 烧掉 {c['cost_s']}s，错误 `{c['error'][:110]}`"
              f"（{c['case']}，{c['gap_s']}s 后）"
              + ("　**转向**" if c.get("pivoted") else ""),
              f"  > {(c.get('next_reasoning') or '')[:300]}"]

    L += ["", "## 5. 泄露审计（硬门）", ""]
    if agg["leaks"]:
        L.append("**以下格子读到了自己 staging 之外的导师侧路径，"
                 "结果不计入上表：**")
        for lk in agg["leaks"]:
            L.append(f"- `{lk['case']}`")
            for h in (lk["hits"] or [])[:4]:
                L.append(f"  - {h['where']}: `{h['context'][:140]}`")
    else:
        n_audited = sum(1 for r in recs if r.get("mined"))
        L.append(f"全部 {n_audited} 格干净：没有任何一格读取自己 staging 目录"
                 "以外的导师侧路径（`H:/CrystalPilotData`、`benchmark/data`、"
                 "`refs/`、`e-survey`）。")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path,
                    default=REPO / "workdir" / "campaigns" / "PA1-ANALYSIS.md")
    ap.add_argument("--json", type=Path,
                    default=REPO / "workdir" / "campaigns" / "pa1-analysis.json")
    ap.add_argument("--lanes", default=",".join(LANES),
                    help="comma-separated campaign lane names (workdir/"
                         "campaigns/<lane>); pa2: pa2-hex,pa2-cage1,pa2-cage2")
    a = ap.parse_args(argv)
    recs = collect(lanes=tuple(s.strip() for s in a.lanes.split(",")
                               if s.strip()))
    a.json.write_text(json.dumps(
        {"cells": recs, "noise_floor": noise_floors(recs),
         "aggregate": aggregate_failures(recs)},
        ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    a.out.write_text(render(recs), encoding="utf-8")
    print(f"{len(recs)} cell(s) -> {a.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
