"""The one sub-agent contract (round-3 R7): the specialty table and the
verdict schema live in workbench/subagent_contract.py and both paths - the
native role files and the nested consult_specialist tool - agree with it."""
from __future__ import annotations

import tomllib
from pathlib import Path

from crystalpilot.workbench.subagent_contract import (SPECIALTIES,
                                                      VERDICT_FIELDS,
                                                      VERDICT_SCHEMA,
                                                      parse_verdict)

ROLES_DIR = Path(__file__).resolve().parents[1] / "crystalpilot" / "workbench" / "agent_roles"


def test_role_files_and_specialties_are_the_same_set():
    roles = {p.stem for p in ROLES_DIR.glob("*.toml")}
    assert roles == set(SPECIALTIES), (roles, set(SPECIALTIES))


def test_every_role_spells_out_the_verdict_fields():
    """A spawned role has no output_schema hook, so its instructions must
    name the same five fields the nested tool enforces by schema."""
    for p in ROLES_DIR.glob("*.toml"):
        text = tomllib.loads(p.read_text(encoding="utf-8"))["developer_instructions"]
        for field in VERDICT_FIELDS:
            assert field in text, (p.name, field)
        assert "high|medium|low" in text, p.name


def test_nested_tool_uses_the_shared_contract():
    from crystalpilot.refine import tools_specialist as ts
    assert ts.SPECIALTIES is SPECIALTIES
    assert ts.VERDICT_SCHEMA is VERDICT_SCHEMA
    assert set(VERDICT_SCHEMA["required"]) == set(VERDICT_FIELDS)
    assert VERDICT_SCHEMA["additionalProperties"] is False


def test_parse_verdict_never_raises_and_never_invents():
    good = parse_verdict('{"assessment": "P-1 成立", "recommendation": "保持", '
                         '"confidence": "high", "evidence": ["check_symmetry: 0 missing ops"], '
                         '"risks": [], "extra": 1}')
    assert good == {"assessment": "P-1 成立", "recommendation": "保持",
                    "confidence": "high",
                    "evidence": ["check_symmetry: 0 missing ops"], "risks": []}
    partial = parse_verdict('{"assessment": "only this"}')
    assert partial["confidence"] == "low" and "did not return valid JSON" in partial["recommendation"]
    assert partial["assessment"].startswith('{"assessment"')
    prose = parse_verdict("I think the space group is fine.")
    assert prose["assessment"] == "I think the space group is fine."
    assert prose["evidence"] == [] and prose["risks"] == []
    assert parse_verdict("")["assessment"] == ""
