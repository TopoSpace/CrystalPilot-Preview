"""Item lifecycle events carry the codex item id, benign phases are not
recorded as gaps, and the SSE channel can be closed / heartbeats / waited
on without a thread (2026-09-16, review docs/REVIEW-2026-09-16-stability-logo-sync.md).

Evidence behind these: six real transcripts (usertest 09-08..09-10) show 0
items without a terminal event but 12 out-of-start-order command
completions; the UI paired completions with the newest running card, so the
first card spun forever. The id on the wire is the fix; the UI tests live in
ui/src/state/threadReducer.pairing.test.ts.
"""
import asyncio
import json
from types import SimpleNamespace

from crystalpilot.workbench.core import normalize_notification
from crystalpilot.workbench.service import Channel


def _item(item):
    return SimpleNamespace(item=item)


class TestItemIds:
    def test_mcp_tool_call_events_carry_the_item_id(self):
        for phase in ("started", "updated", "completed"):
            ev = normalize_notification(f"item/{phase}", _item({
                "type": "mcpToolCall", "id": "call_A1", "server": "crystalpilot",
                "tool": "inspect_model", "status": "in_progress", "arguments": {}}))
            assert ev["kind"] == f"tool_{phase}"
            assert ev["item_id"] == "call_A1"

    def test_a_tool_call_without_an_id_reports_null_not_a_crash(self):
        ev = normalize_notification("item/started", _item({
            "type": "mcpToolCall", "server": "crystalpilot", "tool": "refine"}))
        assert ev["item_id"] is None

    def test_command_output_delta_names_its_command(self):
        ev = normalize_notification("item/commandExecution/outputDelta",
                                    SimpleNamespace(item_id="call_B2", delta="TITL x\n"))
        assert ev == {"kind": "command_output", "delta": "TITL x\n", "item_id": "call_B2"}

    def test_tool_progress_names_its_call(self):
        ev = normalize_notification("item/mcpToolCall/progress",
                                    SimpleNamespace(item_id="call_C3", message="等待 SHELXL 作业 · 42 s"))
        assert ev["kind"] == "tool_progress"
        assert ev["item_id"] == "call_C3"
        assert ev["message"].startswith("等待")

    def test_generic_items_carry_the_id_and_image_view_is_a_family(self):
        for itype in ("webSearch", "todoList", "error", "imageView"):
            ev = normalize_notification("item/completed", _item({"type": itype, "id": f"{itype}-1"}))
            assert ev["kind"] == f"{itype}_completed"
            assert ev["item_id"] == f"{itype}-1"
        fc = normalize_notification("item/started", _item({"type": "fileChange", "id": "fc-9", "changes": []}))
        assert fc["kind"] == "file_change_started" and fc["item_id"] == "fc-9"


class TestBenignPhases:
    def test_message_and_reasoning_starts_are_dropped_not_marked_unhandled(self):
        for itype, phase in (("userMessage", "started"), ("userMessage", "completed"),
                             ("agentMessage", "started"), ("reasoning", "started")):
            assert normalize_notification(f"item/{phase}", _item({"type": itype, "id": "x"})) is None

    def test_their_meaningful_phases_still_surface(self):
        msg = normalize_notification("item/completed", _item({"type": "agentMessage", "text": "hi"}))
        assert msg == {"kind": "agent_message", "text": "hi"}
        rs = normalize_notification("item/completed", _item({
            "type": "reasoning", "summary": [{"text": "why"}]}))
        assert rs == {"kind": "reasoning_summary", "text": "why"}

    def test_truly_unknown_items_are_still_recorded_by_name(self):
        ev = normalize_notification("item/completed", _item({"type": "somethingNew", "name": "n"}))
        assert ev["kind"] == "item_unhandled" and ev["item_type"] == "somethingNew"


class TestChannel:
    def test_oldest_tracks_the_buffer_head(self):
        ch = Channel(maxlen=3)
        assert ch.oldest == 1
        for i in range(5):
            ch.push({"kind": "k", "i": i})
        assert ch.seq == 5
        assert ch.oldest == 3            # 1 and 2 fell out of the 3-deep buffer
        assert [s for s, _ in ch.peek_since(0)] == [3, 4, 5]

    def test_close_wakes_a_blocked_thread_reader(self):
        import threading
        import time
        ch = Channel()
        out = {}

        def reader():
            t0 = time.time()
            out["events"] = ch.read_since(0, timeout=10.0)
            out["dt"] = time.time() - t0

        t = threading.Thread(target=reader)
        t.start()
        time.sleep(0.1)
        ch.close()
        t.join(5)
        assert not t.is_alive()
        assert out["events"] == [] and out["dt"] < 5

    def test_wait_async_returns_on_push_and_on_close_without_a_thread(self):
        ch = Channel()

        async def scenario():
            loop = asyncio.get_running_loop()
            loop.call_later(0.05, ch.push, {"kind": "idle"})
            got = await ch.wait_async(0, timeout=5.0)
            assert [s for s, _ in got] == [1]
            loop.call_later(0.05, ch.close)
            got2 = await ch.wait_async(1, timeout=5.0)
            assert got2 == [] and ch.closed

        asyncio.run(scenario())

    def test_wait_async_times_out_quietly(self):
        ch = Channel()
        assert asyncio.run(ch.wait_async(0, timeout=0.05)) == []


class TestSse:
    def _chunks(self, resp, n):
        async def take():
            it = resp.body_iterator
            return [await it.__anext__() for _ in range(n)]
        return asyncio.run(take())

    def test_hello_reports_the_oldest_buffered_seq(self):
        from crystalpilot.workbench.routes import _sse
        ch = Channel(maxlen=2)
        for i in range(4):
            ch.push({"kind": "k", "i": i})
        chunks = self._chunks(_sse(ch, 0), 2)
        hello = json.loads(chunks[1][len("data: "):].strip())
        assert hello["kind"] == "channel_hello"
        assert hello["oldest"] == 3 and hello["seq"] == 4 and hello["after"] == 0

    def test_a_quiet_channel_sends_a_ping_data_event_not_a_comment(self, monkeypatch):
        from crystalpilot.workbench import routes
        monkeypatch.setattr(routes, "SSE_PING_S", 0.05)
        ch = Channel()
        chunks = self._chunks(routes._sse(ch, 0), 3)
        assert chunks[2].startswith("data: ")
        assert json.loads(chunks[2][len("data: "):].strip())["kind"] == "ping"

    def test_a_closed_channel_ends_the_stream_with_channel_closed(self, monkeypatch):
        from crystalpilot.workbench import routes
        monkeypatch.setattr(routes, "SSE_PING_S", 0.05)
        ch = Channel()
        ch.push({"kind": "idle"})
        ch.close()
        resp = routes._sse(ch, 0)

        async def drain():
            out = []
            async for chunk in resp.body_iterator:
                out.append(chunk)
            return out

        chunks = asyncio.run(drain())
        kinds = [json.loads(c.split("data: ", 1)[1].strip())["kind"]
                 for c in chunks if "data: " in c]
        assert kinds == ["channel_hello", "idle", "channel_closed"]
