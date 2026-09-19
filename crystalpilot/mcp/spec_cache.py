"""Tool-spec cache so the MCP server answers tools/list without importing
cctbx.

Why: the registry import chain pulls the full cctbx/smtbx stack (tens of
seconds cold, worse under load). Round-5 evidence: a busy machine pushed
server startup past codex's startup timeout and the whole run degraded to
shell fallback. The tool LIST is a pure function of the code (registration
is uniform across projects; stage gating happens at invoke time), so it can
be served from a cache fingerprinted by the package sources.

Cache location is per-user (~/.crystalpilot/), keyed by fingerprint in the
filename - a code change simply misses and the next warm run rewrites it.

Since 2026-09-03 the tool list is a function of the code AND the process's
knowledge mode (crystalpilot.knowledge_mode: the tools_only ablation arm
registers no skill tools), so cache_key() - not code_fingerprint() - is
what the server must use. Bitten live the same day: a tools_only project
was served the full arm's 69-tool list from the code-only key.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .. import knowledge_mode as _km

_PKG_DIR = Path(__file__).resolve().parents[1]          # crystalpilot/


def _cache_dir() -> Path:
    d = Path(os.environ.get("CRYSTALPILOT_CACHE_DIR")
             or Path.home() / ".crystalpilot")
    return d


def code_fingerprint(pkg_dir: Path | None = None) -> str:
    """Hash of (relpath, CONTENT) over the package's .py files.

    Content, not mtime (D15, round-2 R5): a checkout, a `git stash pop`,
    a touch or a copy of the tree changes every mtime and used to cost a
    cold tools/list (the full cctbx import, tens of seconds, and on a busy
    machine past codex's startup timeout) for code that had not changed;
    conversely two different trees with equal sizes and mtimes would have
    shared a key. Reading ~1 MB of sources hashes in ~10 ms."""
    root = Path(pkg_dir) if pkg_dir is not None else _PKG_DIR
    h = hashlib.sha256()
    for p in sorted(root.rglob("*.py")):
        try:
            data = p.read_bytes()
        except OSError:
            continue
        h.update(str(p.relative_to(root)).replace("\\", "/").encode())
        h.update(b"|")
        h.update(hashlib.sha256(data).digest())
        h.update(b"\n")
    return h.hexdigest()[:24]


def cache_key() -> str:
    """code_fingerprint() plus the knowledge mode when it narrows the tool
    list. The full mode keeps the bare fingerprint so existing caches and
    tests are unaffected."""
    fp = code_fingerprint()
    mode = _km.current()
    return fp if mode == "full" else f"{fp}-{mode}"


def load_specs(fp: str) -> list[dict[str, Any]] | None:
    path = _cache_dir() / f"tool_specs-{fp}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not (isinstance(data, list) and data
            and all(isinstance(s, dict) and s.get("name") for s in data)):
        return None
    return data


def store_specs(fp: str, specs: list[dict[str, Any]]) -> None:
    d = _cache_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f"tool_specs-{fp}.json.tmp{os.getpid()}"
        tmp.write_text(json.dumps(specs, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, d / f"tool_specs-{fp}.json")
    except OSError:
        pass                                    # cache is best-effort
