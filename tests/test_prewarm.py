"""Main-thread prewarm of heavy extension modules (reg9-dbu P0, 2026-09-05):
the list imports, and every lazy scipy / cctbx / smtbx / iotbx / mmtbx /
gemmi import inside a function body anywhere in crystalpilot/ is on it."""
from __future__ import annotations

import ast
import json
import os
import time
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "crystalpilot"
HEAVY_ROOTS = ("scipy", "cctbx", "smtbx", "iotbx", "mmtbx", "gemmi")


def _lazy_imports() -> dict[str, list[str]]:
    """{module: [file:line, ...]} for imports nested inside def/async def."""
    found: dict[str, list[str]] = {}
    for path in sorted(PKG.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        stack: list[ast.AST] = []

        def visit(node: ast.AST, depth: int) -> None:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                depth += 1
            if depth > 0 and isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in HEAVY_ROOTS:
                    mods = [node.module]
                    for a in node.names:
                        mods.append(f"{node.module}.{a.name}")
                    for m in mods:
                        found.setdefault(m, []).append(f"{path.relative_to(REPO)}:{node.lineno}")
            if depth > 0 and isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split(".")[0] in HEAVY_ROOTS:
                        found.setdefault(a.name, []).append(f"{path.relative_to(REPO)}:{node.lineno}")
            for child in ast.iter_child_nodes(node):
                visit(child, depth)

        visit(tree, 0)
    return found


def test_prewarm_imports_the_list_on_this_thread():
    from crystalpilot.mcp.prewarm import (HEAVY_MODULES, PRELOOP_MODULES,
                                          prewarm_heavy_imports)
    rep = prewarm_heavy_imports()
    assert rep["thread"]
    # scipy is installed in the engine venv: the module that hung reg9 is
    # in the PRE-LOOP list (before anyio.run), cctbx/smtbx in the in-loop one
    for must in ("scipy.spatial", "scipy.linalg", "scipy.ndimage"):
        assert must in PRELOOP_MODULES
        assert must in sys.modules, rep["failed"].get(must)
    for must in ("cctbx.masks", "smtbx.masks"):
        assert must in HEAVY_MODULES
        assert must in sys.modules, rep["failed"].get(must)
    assert set(rep["imported"]) | set(rep["failed"]) == set(PRELOOP_MODULES) | set(HEAVY_MODULES)


def test_every_lazy_heavy_import_is_prewarmed():
    """A `from scipy.x import y` inside a function body must be reachable
    from HEAVY_MODULES (the module itself or a parent that imports it):
    otherwise a worker thread can be the first to load its extension."""
    from crystalpilot.mcp.prewarm import HEAVY_MODULES, PRELOOP_MODULES
    listed = set(HEAVY_MODULES) | set(PRELOOP_MODULES)
    lazy = _lazy_imports()
    missing: dict[str, list[str]] = {}
    for mod, where in lazy.items():
        # `from cctbx import sgtbx` yields "cctbx" and "cctbx.sgtbx"; the
        # attribute form may be a function, so accept when the module
        # part or any listed name starts with it
        ok = mod in listed or any(l == mod or l.startswith(mod + ".") for l in listed)
        if not ok:
            # attribute imports (from pkg import name) are fine when pkg is
            # listed and `name` is not itself a submodule on disk
            parent, _, leaf = mod.rpartition(".")
            if parent in listed:
                try:
                    import importlib
                    m = importlib.import_module(parent)
                    attr = getattr(m, leaf, None)
                    ok = attr is not None and not hasattr(attr, "__path__") and not (
                        hasattr(attr, "__file__") and getattr(attr, "__file__", "").endswith((".pyd", ".so")))
                except Exception:  # noqa: BLE001
                    ok = False
        if not ok:
            missing[mod] = where
    assert not missing, f"lazy heavy imports not in mcp.prewarm.HEAVY_MODULES: {missing}"


def test_cold_mcp_process_runs_analyze_packing(tmp_path):
    """Regression for the reg9-dbu hang (2026-09-05): the cell's FIRST
    analyze_packing call ran in an AnyIO worker thread of a cold MCP
    process, whose `import scipy.spatial` (chem/interactions.py) sat in
    the Windows loader lock for 65 min (py-spy: worker thread inside the
    import, main thread idle in the selector). Cold process -> initialize
    -> tools/list -> tools/call analyze_packing must come back."""
    import subprocess
    import sys
    import threading
    src = REPO / "benchmark" / "public" / "Ca_imidazolate"
    if not (src / "ref_cif.cif").exists():
        pytest.skip("Ca_imidazolate benchmark not present")
    d = tmp_path / "proj"
    d.mkdir()
    (d / "context.json").write_text(json.dumps({
        "chemistry": {"note": "prewarm regression"}}), encoding="utf-8")
    from crystalpilot.refine.project import RefineProject
    p = RefineProject(d)
    p.open()
    r = p.invoke_tool("import_cif_model", {
        "cif_path": str(src / "ref_cif.cif"),
        "hkl_path": str(src / "sf.cif")})
    assert r.ok, r.error

    env = dict(os.environ)
    env["CRYSTALPILOT_CACHE_DIR"] = str(tmp_path / "cache")   # cold specs
    env["PYTHONUTF8"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "-m", "crystalpilot.mcp", "--project", str(d)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, cwd=str(REPO), env=env)
    lines: list = []
    got = threading.Condition()

    def reader():
        for raw in proc.stdout:
            with got:
                lines.append(json.loads(raw))
                got.notify_all()

    def send(obj):
        proc.stdin.write((json.dumps(obj) + "\n").encode())
        proc.stdin.flush()

    def wait_id(i, timeout):
        deadline = time.time() + timeout
        with got:
            while True:
                for m in lines:
                    if m.get("id") == i:
                        return m
                left = deadline - time.time()
                assert left > 0, (f"no response to id={i} within {timeout}s "
                                  f"(loader-lock deadlock?)")
                got.wait(left)

    threading.Thread(target=reader, daemon=True).start()
    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                         "clientInfo": {"name": "t", "version": "0"}}})
        wait_id(1, 60)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = [t["name"] for t in wait_id(2, 120)["result"]["tools"]]
        assert "analyze_packing" in names, names
        t0 = time.time()
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "analyze_packing",
                         "arguments": {"blocks": ["interactions"],
                                       "max_rows": 5}}})
        resp = wait_id(3, 240)
        dt = time.time() - t0
        assert "result" in resp, resp
        assert not resp["result"].get("isError"), resp
        text = "".join(c.get("text", "")
                       for c in resp["result"].get("content", []))
        out = json.loads(text)
        assert out["ok"], out
        assert out["summary"]["interactions"]["counts"]["hbond"]["unique"] >= 0
        assert dt < 240, dt
    finally:
        proc.kill()
