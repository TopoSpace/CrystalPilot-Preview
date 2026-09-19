"""Scientific UI evidence must survive a long MCP result and non-finite bins."""
import json
from types import SimpleNamespace

from crystalpilot.workbench.core import normalize_notification


def notification(server, text):
    return SimpleNamespace(item={"type": "mcpToolCall", "server": server,
        "tool": "run_shelxl", "status": "completed", "arguments": {},
        "result": {"content": [{"type": "text", "text": text}]}})


def test_scientific_metrics_survive_diagnostic_tail():
    text = json.dumps({"ok": True, "summary": {"shelxl": {
        "r1_strong": 0.0766, "wr2": 0.2663, "goof": 2.18,
        "bounds": [0.7, float("inf")], "warnings": ["diagnostic " * 1500]}}})
    event = normalize_notification("item/completed", notification("crystalpilot", text))
    parsed = json.loads(event["result_tail"])
    assert parsed["summary"]["shelxl"]["r1_strong"] == 0.0766
    assert parsed["summary"]["shelxl"]["bounds"] == [0.7, None]
    assert "Infinity" not in event["result_tail"]
    assert len(event["result_tail"]) > 2000


def test_external_tools_keep_bounded_terminal_preview():
    event = normalize_notification("item/completed", notification("unrelated", "x" * 4000))
    assert len(event["result_tail"]) == 2000


def test_nonfinite_word_inside_a_string_is_not_rewritten():
    text = json.dumps({"ok": True, "summary": {"note": "Infinity is a label"}})
    event = normalize_notification("item/completed", notification("crystalpilot", text))
    assert json.loads(event["result_tail"])["summary"]["note"] == "Infinity is a label"
