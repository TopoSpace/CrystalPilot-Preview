"""collabAgentToolCall normalization: subagent activity must surface in
transcripts instead of being silently dropped (recon 2026-09-01: codex
multi_agent v2 is ON in every session; the old whitelist returned None
for this item type)."""
from crystalpilot.workbench.core import normalize_notification


class _P:
    def __init__(self, item):
        self.item = item


def test_collab_spawn_surfaces():
    item = {
        "type": "collabAgentToolCall",
        "tool": "spawnAgent",
        "sender_thread_id": "th_root",
        "receiver_thread_ids": ["th_child1"],
        "prompt": "audit the first half of the skill cards",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "medium",
        "status": "completed",
        "agents_states": {"th_child1": {"status": "running",
                                        "message": "reading cards"}},
    }
    ev = normalize_notification("item/completed", _P(item))
    assert ev is not None
    assert ev["kind"] == "collab_completed"
    assert ev["tool"] == "spawnAgent"
    assert ev["receivers"] == ["th_child1"]
    assert "skill cards" in ev["prompt"]
    assert ev["agents_states"]["th_child1"]["status"] == "running"


def test_collab_prompt_truncated_and_optional_fields():
    item = {"type": "collabAgentToolCall", "tool": "wait",
            "status": "in_progress", "prompt": "x" * 5000}
    ev = normalize_notification("item/started", _P(item))
    assert ev["kind"] == "collab_started"
    assert len(ev["prompt"]) == 2000
    assert ev["receivers"] is None


def test_unknown_items_are_recorded_by_type_not_dropped():
    """reg11-cage: a real delegation left no trace in the transcript because
    its items were of a type the whitelist dropped. Unknown types now leave
    a named marker (transcript/SSE only; the UI ignores the kind)."""
    ev = normalize_notification(
        "item/completed", _P({"type": "somethingUnknown", "name": "x",
                              "payload": 1}))
    assert ev == {"kind": "item_unhandled", "phase": "completed",
                  "item_type": "somethingUnknown", "name": "x",
                  "keys": ["name", "payload", "type"]}


def test_custom_tool_call_with_a_collab_verb_is_a_collab_event():
    """The rollout of reg11-cage shows spawn_agent / wait as custom tool
    calls; whatever item type codex uses for them, the verb decides."""
    item = {"type": "customToolCall", "name": "spawn_agent",
            "status": "completed",
            "input": '{"agent_type": "density", "fork_turns": "none", '
                     '"message": "audit n0005 difference map"}',
            "output": "spawned agent th_child9"}
    ev = normalize_notification("item/completed", _P(item))
    assert ev["kind"] == "collab_completed" and ev["tool"] == "spawn_agent"
    assert ev["agent_type"] == "density"
    assert ev["prompt"] == "audit n0005 difference map"
    assert ev["output_tail"].endswith("th_child9")
    assert ev["item_type"] == "customToolCall"
    # the v2 cell-style wait, with dict arguments
    ev = normalize_notification("item/started", _P({
        "type": "customToolCall", "name": "wait",
        "arguments": {"cell_id": "2", "yield_time_ms": 10000}}))
    assert ev["kind"] == "collab_started" and ev["tool"] == "wait"
    assert ev["prompt"] is None and ev["agent_type"] is None
