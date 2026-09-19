"""Build the ka1 knowledge-ablation manifests.

Where pa1 varies the OPENING MESSAGE (the prompt ladder L0..L3), ka1 holds
the message fixed at L0 and instead varies the KNOWLEDGE LAYER baked into
the project's own AGENTS.md:

  * arm "tools_only" - the project gets only the operational contract and
    the honesty-rules template: how to call the typed tools, the delivery
    format, the "unresolved, don't fabricate" rule. No skill-card library
    (data-ingest-space-group-protocol, flack-absolute-structure, mof-
    solvent-mask-discipline, mof-guest-evidence-rule, ...), no
    crystallographic judgment/heuristics text at all. The tool surface
    itself (MCP `crystalpilot` server) is identical to the other arm.
  * arm "full" - the current AGENTS v32 template plus the full skill-card
    set, unchanged from every other campaign.

Same L0 brief, same model/effort, same data, in both arms - the only
thing that varies is how much crystallographic knowledge is pre-loaded
into the agent's instructions versus left for it to reconstruct itself
from raw tool output. This module only stages the *manifests*; which
AGENTS.md text a "tools_only" project actually gets is a runner-side
concern for whatever consumes case["knowledge_mode"], not decided here.

hex and cage reuse pa1's crystal specs (same staging dirs, same
references) verbatim - only the arms and the brief change, so the specs
are imported, never copy-pasted. org is new: a small COD-deposited
organic (P2(1)2(1)2(1), Z=4) staged blind at
H:/CrystalPilotData/staging/ka1o/, with the deposited CIF as an *exact*
mentor-side reference (not a prior "literature" analogue).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from crystalpilot.benchmark.pa1_manifests import (
    CRYSTALS as _PA1_CRYSTALS, DATA_ROOT, L0, SERVER)

ARMS = ["tools", "full"]

#: case["knowledge_mode"] value per arm - the lever this experiment pulls
KNOWLEDGE_MODE = {"tools": "tools_only", "full": "full"}

# ------------------------------------------------------------------ crystals
#: hex and cage: same data, same references as pa1 - imported, not
#: retyped, so the two experiments can never drift apart on what a
#: crystal *is*. Their pa1-only "context" key (L3 synthesis priors) is
#: simply never read here: ka1 has no context.json in any arm.
CRYSTALS: dict[str, dict[str, Any]] = {
    "hex": _PA1_CRYSTALS["hex"],
    "cage": _PA1_CRYSTALS["cage"],
    "org": {
        "data_dir": "H:/CrystalPilotData/staging/ka1o",
        # mentor-side only - never written into any case/brief/context
        "reference": "H:/CrystalPilot/benchmark/data_ext2/"
                     "org_hsl_cod2241460/ref.cif",
        "reference_kind": "exact",   # deposited/published, not a prior run
        "case_timeout_s": 7200,
    },
}

#: one lane per crystal: three runner processes, three independent
#: state.json files. Each lane is the same crystal's two knowledge arms,
#: tools_only first so a partial run always has the "leaner" case done.
LANES: list[tuple[str, list[tuple[str, str, int]]]] = [
    # (campaign name, [(crystal, arm, replicate)])
    ("ka1-hex", [("hex", a, 1) for a in ARMS]),
    ("ka1-cage", [("cage", a, 1) for a in ARMS]),
    ("ka1-org", [("org", a, 1) for a in ARMS]),
]


def build_case(crystal: str, arm: str, rep: int) -> dict[str, Any]:
    spec = CRYSTALS[crystal]
    case: dict[str, Any] = {
        "name": f"{crystal}-{arm}-r{rep}",
        "crystal": crystal,
        "arm": arm,
        "replicate": rep,
        "reference": spec["reference"],
        "reference_kind": spec["reference_kind"],
        "case_timeout_s": spec["case_timeout_s"],
        # the prompt-level variable is held at L0 for BOTH arms - ka1
        # never writes a context.json, at any arm, for any crystal
        "brief": L0,
        "followups": [],
        "knowledge_mode": KNOWLEDGE_MODE[arm],
    }
    if "data_alias" in spec:
        case["data_alias"] = spec["data_alias"]
    else:
        case["data_dir"] = spec["data_dir"]
    return case


def _manifest(name: str, cells: list[tuple[str, str, int]]
             ) -> dict[str, Any]:
    max_timeout = max(CRYSTALS[c]["case_timeout_s"] for c, _, _ in cells)
    return {
        "campaign": name,
        "server": SERVER,
        # Deliberately OUTSIDE the repo (H:/CrystalPilot-campaigns/..., not
        # H:/CrystalPilot/workbench/...). A repo-root AGENTS.md
        # (H:/CrystalPilot/AGENTS.md - generic "drive the cli solve engine"
        # instructions, unrelated to this experiment) was being picked up
        # by the coding-agent harness on top of the project-level AGENTS.md
        # whenever the project dir was nested inside the repo tree. That
        # silently re-injected knowledge-flavoured text into the
        # "tools_only" arm, defeating the whole ablation. Running both
        # lanes under a projects_root with no CrystalPilot repo anywhere
        # above it means there is nothing for the harness to find but the
        # project's own AGENTS.md.
        "projects_root": f"H:/CrystalPilot-campaigns/{name}",
        "defaults": {"permission_mode": "auto",
                     "case_timeout_s": max_timeout,
                     "anonymize_projects": True,
                     "model_override": "gpt-5.6-sol",
                     "effort_override": "xhigh"},
        "_experiment": {
            "design": (
                "knowledge-layer ablation: arm tools_only gives the "
                "project only the operational contract and honesty-rules "
                "template (how to call the tools, delivery format, "
                "'unresolved, don't fabricate') with no skill-card "
                "library and no crystallographic judgment/heuristics "
                "text; arm full gets the current AGENTS v32 template plus "
                "the full skill-card set, unchanged from every other "
                "campaign. Same L0 brief, same model/effort, same data in "
                "both arms - the only thing varied is how much "
                "crystallographic knowledge is pre-loaded into the "
                "agent's own instructions versus left for it to "
                "reconstruct from raw tool output. Both lanes run under a "
                "projects_root outside the repo so no repo-root "
                "AGENTS.md is injected into either arm."),
            "arms": {
                "tools_only": "operational contract + honesty-rules "
                              "template only; no skill-card library; no "
                              "crystallographic judgment/heuristics text; "
                              "same typed MCP tool surface as full",
                "full": "current AGENTS v32 template + full skill-card "
                       "set (data-ingest-space-group-protocol, flack-"
                       "absolute-structure, mof-solvent-mask-discipline, "
                       "mof-guest-evidence-rule, ...), unchanged from "
                       "every other campaign",
            },
            "lane": name,
        },
        "cases": [build_case(c, a, r) for c, a, r in cells],
    }


def build_all() -> dict[str, dict[str, Any]]:
    return {name: _manifest(name, cells) for name, cells in LANES}


def write_all(dest: Path = DATA_ROOT / "campaigns") -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, man in build_all().items():
        p = dest / f"{name}.json"
        p.write_text(json.dumps(man, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        paths.append(p)
    return paths


def main() -> list[Path]:
    paths = write_all()
    for p in paths:
        print(p)
    return paths


if __name__ == "__main__":  # pragma: no cover
    main()
