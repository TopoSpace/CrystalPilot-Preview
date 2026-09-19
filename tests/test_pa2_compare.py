"""Baseline-vs-regression comparison of two prompt-ladder analyses."""
from __future__ import annotations

import json

from crystalpilot.benchmark import pa2_compare as pc


def _cell(case, crystal, arm, grade, r1, calls, errors, spin=0, wall=1000.0):
    return {"case": case, "crystal": crystal, "arm": arm, "grade": grade,
            "r1": r1, "space_group": "P 1", "formula": "C", "n_atoms": 10,
            "checkcif": {"A": 2}, "wall_s": wall, "lanes_busy": 3,
            "tokens": 5e6,
            "mined": {"tools": {"refine": {"calls": calls, "errors": errors},
                                "exec": {"calls": 5, "errors": 0}},
                      "n_tool_calls": calls + 5, "n_tool_errors": errors,
                      "spin": [{"tool": "refine", "repeats": spin}] if spin else [],
                      "pivots": [], "shell_hazards": [], "leak_clean": True}}


BASE = {"cells": [_cell("hex-l0-r1", "hex", "L0", "acceptable", 0.080, 100, 10, 4),
                  _cell("hex-l0-r2", "hex", "L0", "acceptable", 0.090, 120, 12, 6),
                  _cell("cu-l0-r1", "cu", "L0", "acceptable", 0.05, 50, 1)],
        "noise_floor": {"per_crystal": {"hex": {"r1_sd": 0.02}}}}
NEW = {"cells": [_cell("hex-l0-r1", "hex", "L0", "acceptable", 0.085, 80, 2, 1),
                 _cell("hex-l0-r2", "hex", "L0", "below_bar", 0.140, 90, 3, 0)]}


def test_arms_are_matched_and_the_noise_floor_is_applied():
    cmp = pc.compare(BASE, NEW)
    assert [(a["crystal"], a["arm"]) for a in cmp["arms"]] == [("hex", "L0")]
    a = cmp["arms"][0]
    assert a["pa1"]["n"] == 2 and a["pa2"]["n"] == 2
    assert a["delta_acceptable"] == -1
    assert abs(a["delta_r1_median"] - (0.1125 - 0.085)) < 1e-9
    assert a["r1_significant"] is True                 # 0.0275 > 0.02
    assert a["pa1"]["tool_error_rate"] > a["pa2"]["tool_error_rate"]
    assert a["delta_spin"] == -9
    # the cu arm exists only in the baseline and is left out of the pooled row
    assert cmp["pooled"]["pa1"]["n"] == 2


def test_publication_counts_as_met_and_nested_floor_is_read():
    base = {"cells": [_cell("hex-l0-r1", "hex", "L0", "acceptable", 0.080, 10, 1)],
            "noise_floor": {"per_crystal": {"hex": {"floor": {"r1": 0.01}}}}}
    new = {"cells": [_cell("hex-l0-r1", "hex", "L0", "publication", 0.070, 10, 1),
                     _cell("hex-l0-r2", "hex", "L0", "publication", 0.075, 10, 1)],
           "noise_floor": {"per_crystal": {"hex": {"floor": {"r1": 0.03}}}}}
    a = pc.compare(base, new)["arms"][0]
    assert a["pa2"]["n_acceptable"] == 2 and a["pa2"]["n_publication"] == 2
    assert a["delta_acceptable"] == 1
    assert a["r1_noise_floor"] == 0.03          # the larger of the two floors
    assert a["r1_significant"] is False         # |0.0725 - 0.080| < 0.03


def test_render_and_cli(tmp_path):
    (tmp_path / "b.json").write_text(json.dumps(BASE), encoding="utf-8")
    (tmp_path / "n.json").write_text(json.dumps(NEW), encoding="utf-8")
    out = tmp_path / "o.md"
    assert pc.main([str(tmp_path / "b.json"), str(tmp_path / "n.json"),
                    "--out", str(out), "--json", str(tmp_path / "o.json")]) == 0
    md = out.read_text(encoding="utf-8")
    assert "显著" in md and "hex-l0-r2" in md and "refine 12/120" in md
    assert json.loads((tmp_path / "o.json").read_text(encoding="utf-8"))["arms"]
