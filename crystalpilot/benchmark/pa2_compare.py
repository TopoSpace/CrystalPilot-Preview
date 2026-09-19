"""Side-by-side of two prompt-ladder analyses (baseline vs regression).

Reads the ``analysis.json`` written by :mod:`pa1_report` for two campaigns,
matches cells on ``(crystal, arm)`` and writes one markdown table per arm
plus a pooled summary.  It is a mentor-side reading aid: nothing here is
statistical beyond medians, and a difference smaller than the baseline
noise floor (``noise_floor.per_crystal``) is printed as *not significant*.

    python -X utf8 -m crystalpilot.benchmark.pa2_compare \
        workdir/campaigns/pa1-analysis.json workdir/campaigns/pa2-analysis.json \
        --out workdir/campaigns/PA2-VS-PA1.md
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

GRADE_RANK = {"acceptable": 3, "below_bar": 2, "unresolved": 1,
              "disqualified": 0, "failed": 0}


def _num(x: Any) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _median(xs: list[float | None]) -> float | None:
    v = [x for x in xs if x is not None]
    return statistics.median(v) if v else None


def cell_row(c: dict[str, Any]) -> dict[str, Any]:
    """Flatten one analysis cell into the handful of numbers we compare."""
    m = c.get("mined") or {}
    tools = m.get("tools") or {}
    n_calls = m.get("n_tool_calls")
    if n_calls is None and tools:
        n_calls = sum(int(t.get("calls") or 0) for t in tools.values())
    n_err = m.get("n_tool_errors")
    if n_err is None and tools:
        n_err = sum(int(t.get("errors") or 0) for t in tools.values())
    spin = sum(int(s.get("repeats") or 0) for s in (m.get("spin") or []))
    return {
        "case": c.get("case"), "crystal": c.get("crystal"), "arm": c.get("arm"),
        "grade": c.get("grade"), "r1": _num(c.get("r1")),
        "space_group": c.get("space_group"), "formula": c.get("formula"),
        "n_atoms": c.get("n_atoms"),
        "checkcif_A": ((c.get("checkcif") or {}).get("A")),
        "wall_s": _num(c.get("wall_s")), "lanes_busy": c.get("lanes_busy"),
        "tokens": _num(c.get("tokens")),
        "n_tool_calls": n_calls, "n_tool_errors": n_err,
        "tool_error_rate": (n_err / n_calls) if (n_calls and n_err is not None)
        else None,
        "spin_repeats": spin,
        "n_pivots": len(m.get("pivots") or []),
        "n_shell_hazards": len(m.get("shell_hazards") or []),
        "leak_clean": m.get("leak_clean"),
        "top_failing_tools": sorted(
            ((t, v.get("errors", 0), v.get("calls", 0)) for t, v in tools.items()
             if v.get("errors")), key=lambda r: -r[1])[:4],
    }


def arm_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    return {
        "n": n,
        # "达标" = publication or acceptable (the first pa2 rendering counted
        # only 'acceptable' and reported three publication cells as 0)
        "n_acceptable": sum(1 for r in rows
                            if r["grade"] in ("publication", "acceptable")),
        "n_publication": sum(1 for r in rows if r["grade"] == "publication"),
        "grades": [r["grade"] for r in rows],
        "r1_median": _median([r["r1"] for r in rows]),
        "r1_best": min((r["r1"] for r in rows if r["r1"] is not None),
                       default=None),
        "wall_median": _median([r["wall_s"] for r in rows]),
        "tools_median": _median([_num(r["n_tool_calls"]) for r in rows]),
        "tokens_median": _median([r["tokens"] for r in rows]),
        "tool_error_rate": (
            sum(r["n_tool_errors"] or 0 for r in rows)
            / max(1, sum(r["n_tool_calls"] or 0 for r in rows))),
        "spin_total": sum(r["spin_repeats"] for r in rows),
        "pivots_total": sum(r["n_pivots"] for r in rows),
        "hazards_total": sum(r["n_shell_hazards"] for r in rows),
    }


def _crystal_floor(analysis: dict[str, Any], crystal: str) -> float | None:
    """R1 replicate floor of one crystal from an analysis JSON. pa1_report
    writes noise_floor.per_crystal[<crystal>].floor.r1 (the largest same-arm
    replicate spread); a flat r1_sd / r1_range / r1 is accepted too."""
    per = ((analysis.get("noise_floor") or {}).get("per_crystal") or {})
    fl = per.get(crystal) or {}
    fl = fl.get("floor") or fl
    return _num(fl.get("r1_sd") or fl.get("r1_range") or fl.get("r1"))


def compare(base: dict[str, Any], new: dict[str, Any],
            base_name: str = "pa1", new_name: str = "pa2") -> dict[str, Any]:
    b_rows = [cell_row(c) for c in base.get("cells") or []]
    n_rows = [cell_row(c) for c in new.get("cells") or []]
    keys = sorted({(r["crystal"], r["arm"]) for r in n_rows},
                  key=lambda k: (k[0] or "", k[1] or ""))
    arms = []
    for crystal, arm in keys:
        b = [r for r in b_rows if (r["crystal"], r["arm"]) == (crystal, arm)]
        n = [r for r in n_rows if (r["crystal"], r["arm"]) == (crystal, arm)]
        sb, sn = arm_summary(b), arm_summary(n)
        # the more conservative of the two campaigns' replicate floors
        r1_floor = max((f for f in (_crystal_floor(base, crystal),
                                    _crystal_floor(new, crystal))
                        if f is not None), default=None)
        d_r1 = (None if sb["r1_median"] is None or sn["r1_median"] is None
                else sn["r1_median"] - sb["r1_median"])
        arms.append({
            "crystal": crystal, "arm": arm,
            base_name: sb, new_name: sn,
            "delta_r1_median": d_r1,
            "r1_noise_floor": r1_floor,
            "r1_significant": (None if d_r1 is None or r1_floor is None
                               else abs(d_r1) > r1_floor),
            "delta_acceptable": sn["n_acceptable"] - sb["n_acceptable"],
            "delta_tool_error_rate": sn["tool_error_rate"] - sb["tool_error_rate"],
            "delta_spin": sn["spin_total"] - sb["spin_total"],
            "cells": {base_name: b, new_name: n},
        })
    return {"base": base_name, "new": new_name, "arms": arms,
            "pooled": {base_name: arm_summary(
                [r for r in b_rows if (r["crystal"], r["arm"]) in keys]),
                new_name: arm_summary(n_rows)}}


def _f(x: Any, nd: int = 4) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f}%"


def _mins(x: float | None) -> str:
    return "—" if x is None else f"{x / 60:.0f} min"


def render(cmp: dict[str, Any]) -> str:
    b, n = cmp["base"], cmp["new"]
    L = [f"# {n} 对 {b} 的同臂对照", "",
         "同一晶体、同一提示词档位的格子放在一起看；R1 差小于该晶体重复格的"
         "噪声地板时写作“不显著”。墙钟带并发泳道数，不能跨格硬比。", ""]
    L += ["## 逐臂汇总", "",
          f"| 晶体 | 臂 | 格数 {b}/{n} | 达标 {b}→{n} | R1 中位 {b}→{n} | ΔR1 | 噪声地板 | 判定 | 工具错误率 {b}→{n} | 打转 {b}→{n} | 中位工具数 {b}→{n} | 中位墙钟 {b}→{n} |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for a in cmp["arms"]:
        sb, sn = a[b], a[n]
        sig = ("不显著" if a["r1_significant"] is False else
               "显著" if a["r1_significant"] else "无地板")
        L.append(
            f"| {a['crystal']} | {a['arm']} | {sb['n']}/{sn['n']} | "
            f"{sb['n_acceptable']}→{sn['n_acceptable']} | "
            f"{_f(sb['r1_median'])}→{_f(sn['r1_median'])} | "
            f"{_f(a['delta_r1_median'], 4)} | {_f(a['r1_noise_floor'], 4)} | {sig} | "
            f"{_pct(sb['tool_error_rate'])}→{_pct(sn['tool_error_rate'])} | "
            f"{sb['spin_total']}→{sn['spin_total']} | "
            f"{_f(sb['tools_median'], 0)}→{_f(sn['tools_median'], 0)} | "
            f"{_mins(sb['wall_median'])}→{_mins(sn['wall_median'])} |")
    L += ["", "## 逐格明细", ""]
    for a in cmp["arms"]:
        L += [f"### {a['crystal']} / {a['arm']}", "",
              "| 战役 | 格 | 评级 | R1 | 空间群 | 原子数 | A 级 | 工具数 | 错误率 | 打转 | 转向 | shell 隐患 | 墙钟(泳道) | tokens | 出错最多的工具 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for name in (b, n):
            for r in a["cells"][name]:
                fails = ", ".join(f"{t} {e}/{c}" for t, e, c in r["top_failing_tools"]) or "—"
                L.append(
                    f"| {name} | {r['case']} | {r['grade']} | {_f(r['r1'])} | "
                    f"{r['space_group'] or '—'} | {r['n_atoms'] or '—'} | "
                    f"{_f(r['checkcif_A'])} | {_f(r['n_tool_calls'])} | "
                    f"{_pct(r['tool_error_rate'])} | {r['spin_repeats']} | "
                    f"{r['n_pivots']} | {r['n_shell_hazards']} | "
                    f"{_mins(r['wall_s'])}({r['lanes_busy'] if r['lanes_busy'] is not None else '?'}) | "
                    f"{_f(r['tokens'], 0)} | {fails} |")
        L.append("")
    pb, pn = cmp["pooled"][b], cmp["pooled"][n]
    L += ["## 合并（只算两边都有的臂）", "",
          f"| 指标 | {b} | {n} |", "|---|---|---|",
          f"| 格数 | {pb['n']} | {pn['n']} |",
          f"| 达标格 | {pb['n_acceptable']} | {pn['n_acceptable']} |",
          f"| R1 中位 | {_f(pb['r1_median'])} | {_f(pn['r1_median'])} |",
          f"| 工具错误率 | {_pct(pb['tool_error_rate'])} | {_pct(pn['tool_error_rate'])} |",
          f"| 打转（重复调用累计） | {pb['spin_total']} | {pn['spin_total']} |",
          f"| 转向 | {pb['pivots_total']} | {pn['pivots_total']} |",
          f"| shell 隐患 | {pb['hazards_total']} | {pn['hazards_total']} |",
          f"| 中位工具数 | {_f(pb['tools_median'], 0)} | {_f(pn['tools_median'], 0)} |",
          f"| 中位墙钟 | {_mins(pb['wall_median'])} | {_mins(pn['wall_median'])} |",
          f"| 中位 tokens | {_f(pb['tokens_median'], 0)} | {_f(pn['tokens_median'], 0)} |", ""]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("base")
    ap.add_argument("new")
    ap.add_argument("--base-name", default="pa1")
    ap.add_argument("--new-name", default="pa2")
    ap.add_argument("--out", required=True)
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)
    base = json.loads(Path(a.base).read_text(encoding="utf-8"))
    new = json.loads(Path(a.new).read_text(encoding="utf-8"))
    cmp = compare(base, new, a.base_name, a.new_name)
    Path(a.out).write_text(render(cmp), encoding="utf-8")
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(cmp, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
