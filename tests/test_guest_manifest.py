"""pa3 guest re-run manifest: the brief names the modification reagent and
nothing structural; the reference stays mentor-side."""
from __future__ import annotations

import re

from crystalpilot.benchmark import pa1_manifests as pm

STRUCTURAL = re.compile(r"P ?6/m ?m ?m|P6/mmm|39\.19|16\.61|R1 ?[=<>]|Br6|"
                        r"0\.125|C95|NU-1000", re.I)


def test_guest_manifest_states_the_reagent_only():
    mans = pm.build_guest_rerun(projects_root="X:/wb/pa3")
    man = mans["pa3-hex-guest"]
    assert man["projects_root"] == "X:/wb/pa3"
    (case,) = man["cases"]
    assert case["name"] == "hex-l2g-r1" and case["arm"] == "L2G"
    brief = case["brief"]
    assert brief.startswith(pm.brief_for("L2"))          # L2 scaffold intact
    assert "4-bromophenylacetic acid" in brief and "对溴苯乙酸" in brief
    assert "mof-guest-evidence-rule" in brief
    assert not STRUCTURAL.search(brief), STRUCTURAL.search(brief)
    ctx = case["context"]
    assert "对溴苯乙酸" in ctx["chemistry"]["note"]
    assert not STRUCTURAL.search(ctx["chemistry"]["note"])
    assert set(ctx) == {"experiment", "chemistry"}
    # the reference is a mentor-side path, never in the brief/context
    assert "refs" not in brief and "refs" not in str(ctx)
    assert case["reference"].endswith("nu1000_034a1_manual.cif")


def test_pa2_manifests_unchanged_by_the_guest_builder():
    reg = pm.build_regression()
    assert set(reg) == {"pa2-hex", "pa2-cage1", "pa2-cage2"}
    for man in reg.values():
        for c in man["cases"]:
            assert "对溴苯乙酸" not in c["brief"]
