"""MCP server startup must be instant when the spec cache is warm - the
round-5 shell-fallback root cause was cctbx imports pushing the codex
handshake past its startup timeout on a loaded machine."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


class TestSpecCache:
    def test_roundtrip_and_fingerprint(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CRYSTALPILOT_CACHE_DIR", str(tmp_path))
        from crystalpilot.mcp import spec_cache
        fp = spec_cache.code_fingerprint()
        assert len(fp) == 24
        assert spec_cache.load_specs(fp) is None
        specs = [{"name": "t1", "description": "d",
                  "parameters": {"type": "object"}}]
        spec_cache.store_specs(fp, specs)
        assert spec_cache.load_specs(fp) == specs
        # malformed cache entries are rejected, not served
        (tmp_path / f"tool_specs-{fp}.json").write_text("[{}]")
        assert spec_cache.load_specs(fp) is None

    def test_fingerprint_is_content_not_mtime(self, tmp_path):
        """D15: a touch / checkout / copy must not cost a cold tools/list;
        a one-byte edit must, and so must a rename."""
        import os
        import time
        from crystalpilot.mcp import spec_cache
        pkg = tmp_path / "pkg"
        (pkg / "sub").mkdir(parents=True)
        (pkg / "a.py").write_text("x = 1\n", encoding="utf-8")
        (pkg / "sub" / "b.py").write_text("y = 2\n", encoding="utf-8")
        fp0 = spec_cache.code_fingerprint(pkg)
        assert len(fp0) == 24
        later = time.time() + 100
        os.utime(pkg / "a.py", (later, later))          # mtime only
        assert spec_cache.code_fingerprint(pkg) == fp0
        (pkg / "a.py").write_text("x = 2\n", encoding="utf-8")   # same size
        assert spec_cache.code_fingerprint(pkg) != fp0
        (pkg / "a.py").write_text("x = 1\n", encoding="utf-8")
        assert spec_cache.code_fingerprint(pkg) == fp0
        (pkg / "a.py").rename(pkg / "c.py")
        assert spec_cache.code_fingerprint(pkg) != fp0

    def test_cache_key_follows_knowledge_mode(self, monkeypatch):
        """The tool list depends on the knowledge mode (tools_only has no
        skill tools), so the cache key must too - a tools_only MCP process
        served the full 69-tool list from the code-only key (2026-09-03)."""
        from crystalpilot.mcp import spec_cache
        monkeypatch.delenv("CRYSTALPILOT_KNOWLEDGE_MODE", raising=False)
        base = spec_cache.cache_key()
        assert base == spec_cache.code_fingerprint()
        monkeypatch.setenv("CRYSTALPILOT_KNOWLEDGE_MODE", "tools_only")
        assert spec_cache.cache_key() == base + "-tools_only"
        monkeypatch.setenv("CRYSTALPILOT_KNOWLEDGE_MODE", "garbage")
        assert spec_cache.cache_key() == base       # anything else = full


class TestHandshakeLatency:
    def test_initialize_and_list_tools_fast_with_warm_cache(self, tmp_path):
        """Full stdio handshake against a real subprocess. Warm the cache
        first (in this process, cheap: registry specs need the project
        open - use an existing tiny fixture project? No: warm via the
        subprocess itself once, then measure the second run)."""
        env = dict(os.environ)
        env["CRYSTALPILOT_CACHE_DIR"] = str(tmp_path / "cache")
        env["PYTHONUTF8"] = "1"
        proj = tmp_path / "proj"           # nonexistent project is fine:
        proj.mkdir()                       # cache-hit path never opens it

        # seed the cache directly (what a prior warm run would have left)
        from crystalpilot.mcp import spec_cache
        os.environ["CRYSTALPILOT_CACHE_DIR"] = str(tmp_path / "cache")
        try:
            fp = spec_cache.code_fingerprint()
            spec_cache.store_specs(fp, [{
                "name": "get_project_brief", "description": "d",
                "parameters": {"type": "object", "properties": {}}}])
        finally:
            os.environ.pop("CRYSTALPILOT_CACHE_DIR", None)

        t0 = time.time()
        p = subprocess.Popen(
            [sys.executable, "-m", "crystalpilot.mcp",
             "--project", str(proj)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, cwd=str(REPO), env=env)
        try:
            send, recv = _rpc(p)
            send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2024-11-05",
                             "capabilities": {},
                             "clientInfo": {"name": "t", "version": "0"}}})
            init = recv()
            assert init["id"] == 1 and "result" in init
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            tools = recv()
            dt = time.time() - t0
            assert tools["id"] == 2
            names = [t["name"] for t in tools["result"]["tools"]]
            assert "get_project_brief" in names
            # generous bound: must be far under any startup timeout even
            # on a slow CI box - the point is NO cctbx import happened
            assert dt < 20, f"handshake took {dt:.1f}s (cache not used?)"
        finally:
            p.kill()

    def test_cold_cache_list_tools_does_not_deadlock(self, tmp_path):
        """Regression: importing the cctbx chain inside the running loop
        deadlocked in the Windows loader lock (numpy/OpenBLAS DllMain vs
        the stdio worker threads) until numpy was pre-imported before
        anyio.run. Before the fix this hung FOREVER; the generous bound
        only guards the test session."""
        env = dict(os.environ)
        env["CRYSTALPILOT_CACHE_DIR"] = str(tmp_path / "cache")  # empty
        env["PYTHONUTF8"] = "1"
        proj = tmp_path / "proj"
        proj.mkdir()

        p = subprocess.Popen(
            [sys.executable, "-m", "crystalpilot.mcp",
             "--project", str(proj)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, cwd=str(REPO), env=env)
        try:
            send, recv = _rpc(p)
            send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2024-11-05",
                             "capabilities": {},
                             "clientInfo": {"name": "t", "version": "0"}}})
            recv()
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            import threading
            got: list = [None]
            th = threading.Thread(
                target=lambda: got.__setitem__(0, p.stdout.readline()),
                daemon=True)
            th.start()
            th.join(120)
            assert got[0], "cold tools/list deadlocked (loader-lock bug)"
            tools = json.loads(got[0])
            # empty project dir -> open fails -> single error pseudo-tool;
            # the point is a RESPONSE arrived (import completed in-loop)
            names = [t["name"] for t in tools["result"]["tools"]]
            assert names, tools
        finally:
            p.kill()


def _rpc(p):
    def send(obj):
        p.stdin.write((json.dumps(obj) + "\n").encode())
        p.stdin.flush()

    def recv():
        line = p.stdout.readline()
        assert line, "server closed stdout"
        return json.loads(line)

    return send, recv
