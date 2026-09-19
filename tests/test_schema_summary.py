"""R5: every tool description ends with one readable parameter line built
from its JSON schema (names, types, enums, defaults, required), so the agent
does not have to probe parameter names call by call."""
from __future__ import annotations

from crystalpilot.tools.base import (SCHEMA_SUMMARY_MAX, Tool, ToolRegistry,
                                     describe_with_params, schema_summary)


def test_summary_covers_types_enums_defaults_required():
    schema = {
        "type": "object",
        "required": ["node"],
        "properties": {
            "node": {"type": "string", "description": "node id"},
            "scope": {"type": "string", "enum": ["bonds", "angles", "both"],
                      "default": "both"},
            "atoms": {"type": "array", "items": {"type": "string"}},
            "kinds": {"type": "array", "items": {"enum": ["hbond", "pipi"]}},
            "opts": {"type": "object", "properties": {"a": {}, "b": {}}},
            "n": {"type": "integer", "default": 4},
            "flag": {"type": "boolean", "default": False},
            "either": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
    }
    line = schema_summary(schema)
    assert line.startswith("Params: ") and line.endswith(".")
    assert "node*: string" in line
    assert "scope: bonds|angles|both = both" in line
    assert "atoms: [string]" in line and "kinds: [hbond|pipi]" in line
    assert "opts: {a,b}" in line and "n: integer = 4" in line
    assert "flag: boolean = false" in line and "either: string|null" in line


def test_empty_schema_and_truncation():
    assert schema_summary({"type": "object", "properties": {}}) == "Params: none."
    assert schema_summary(None) == "Params: none."
    big = {"type": "object", "properties": {
        f"parameter_{i}": {"type": "string"} for i in range(200)}}
    line = schema_summary(big)
    assert len(line) <= SCHEMA_SUMMARY_MAX and line.endswith("\u2026")


def test_description_gets_the_line_once():
    d = describe_with_params("Does a thing.", {"type": "object", "properties": {
        "x": {"type": "number"}}})
    assert d == "Does a thing.\nParams: x: number."
    # a description that already carries its own Params line is left alone
    assert describe_with_params("Own text. Params: custom.", {"type": "object",
                                "properties": {"x": {}}}) == "Own text. Params: custom."
    assert describe_with_params("", None) == "Params: none."


def test_registry_specs_carry_the_line():
    class T(Tool):
        name = "t"
        description = "Tool t."
        params_schema = {"type": "object", "properties": {
            "mode": {"type": "string", "enum": ["a", "b"], "default": "a"}}}

        def run(self, ctx, **params):  # pragma: no cover - never invoked
            raise NotImplementedError

    reg = ToolRegistry()
    reg.register(T())
    spec = reg.specs()[0]
    assert spec["description"] == "Tool t.\nParams: mode: a|b = a."
    assert spec["parameters"] is T.params_schema
