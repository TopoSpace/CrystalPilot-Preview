"""Which codex binary drives the workbench - the "kernel".

The Python SDK (openai-codex) pins a codex build (openai-codex-cli-bin,
0.147.0 at the time of writing) that lags the official CLI releases on npm
(@openai/codex, 0.155.0 on 2026-09-17). The app-server protocol the SDK
speaks is a superset-compatible JSON-RPC surface, so a newer binary can be
driven by the older SDK: probed 2026-09-07 (workdir/scratch/kernel_probe.py)
- initialize, model/list, config/read, skills/list, thread/start and full
turns on 0.153.4 with SDK 0.147.0; re-probed 2026-09-18 on 0.155.0
(scripts/probe_codex_kernel.py + scripts/diff_codex_schema.py: schema diff
additive only, strict config clean, real turn + compact, state DB migration
54 -> 55 still openable by 0.154.0).

Candidates, first wins:

1. CRYSTALPILOT_CODEX_BIN - an explicit path (tests, experiments);
2. the npm package under vendor/codex (scripts/update_codex_kernel.ps1 runs
   `npm install @openai/codex@latest` there; the platform package carries
   the exe under vendor/<triple>/bin/) - the newest installed version wins;
3. the pip package pinned by the SDK (codex_cli_bin).

`codex --version` is asked once per (path, size, mtime) and cached in
memory; the settings dialog shows the result (kernel version + source).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ENGINE_ROOT = Path(__file__).resolve().parents[2]
VENDOR_DIR = ENGINE_ROOT / "vendor" / "codex"
_EXE = "codex.exe" if os.name == "nt" else "codex"

_version_cache: dict[tuple[str, int, int], str | None] = {}


def _version_key(path: Path) -> tuple[str, int, int]:
    try:
        st = path.stat()
        return (str(path), int(st.st_size), int(st.st_mtime))
    except OSError:
        return (str(path), -1, -1)


def _parse_version(text: str) -> tuple[int, ...]:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else ()


def codex_version(path: str | Path | None = None) -> str | None:
    """`codex --version` -> "0.153.4" (None when the binary cannot answer)."""
    p = Path(path) if path else codex_binary()
    key = _version_key(p)
    if key in _version_cache:
        return _version_cache[key]
    ver: str | None = None
    try:
        out = subprocess.run([str(p), "--version"], capture_output=True,
                             text=True, timeout=20,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        m = re.search(r"(\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.]+)?)", out.stdout or "")
        ver = m.group(1) if m else None
    except (OSError, subprocess.SubprocessError):
        ver = None
    _version_cache[key] = ver
    return ver


def npm_candidates() -> list[Path]:
    """Every codex exe under vendor/codex/node_modules/@openai/*/vendor/*/bin."""
    base = VENDOR_DIR / "node_modules" / "@openai"
    if not base.is_dir():
        return []
    out: list[Path] = []
    for pkg in sorted(base.glob("codex*")):
        for exe in sorted(pkg.glob(f"vendor/*/bin/{_EXE}")):
            if exe.is_file():
                out.append(exe)
    return out


def pip_candidate() -> Path | None:
    try:
        from codex_cli_bin import bundled_codex_path
        return bundled_codex_path()
    except Exception:  # noqa: BLE001 - package absent / metadata missing
        return None


def candidates() -> list[dict[str, Any]]:
    """Every usable kernel with its version and where it came from."""
    out: list[dict[str, Any]] = []
    env = os.environ.get("CRYSTALPILOT_CODEX_BIN")
    if env and Path(env).is_file():
        out.append({"path": str(Path(env)), "source": "env",
                    "version": codex_version(env)})
    for p in npm_candidates():
        out.append({"path": str(p), "source": "npm", "version": codex_version(p)})
    pip = pip_candidate()
    if pip is not None and pip.is_file():
        out.append({"path": str(pip), "source": "pip", "version": codex_version(pip)})
    return out


def codex_binary() -> Path:
    """The kernel to run: the env override, else the newest npm build, else
    the pip build the SDK pins."""
    env = os.environ.get("CRYSTALPILOT_CODEX_BIN")
    if env and Path(env).is_file():
        return Path(env)
    best: tuple[tuple[int, ...], Path] | None = None
    for p in npm_candidates():
        v = _parse_version(codex_version(p) or "")
        if v and (best is None or v > best[0]):
            best = (v, p)
    if best is not None:
        return best[1]
    pip = pip_candidate()
    if pip is not None:
        return pip
    raise FileNotFoundError(
        "no codex binary: install the SDK's openai-codex-cli-bin or run "
        "scripts/update_codex_kernel.ps1 (npm install @openai/codex into vendor/codex)")


def codex_path_dir(binary: str | Path | None = None) -> Path | None:
    """The `codex-path` directory beside the binary (rg.exe and friends); the
    SDK prepends it to PATH only for the pip build, so the workbench does it
    for every build."""
    p = Path(binary) if binary else codex_binary()
    d = p.parent.parent / "codex-path"
    return d if d.is_dir() else None


def kernel_env(binary: str | Path | None = None) -> dict[str, str]:
    """PATH with the kernel's own tool directory in front (a dict to merge
    into the app-server environment)."""
    d = codex_path_dir(binary)
    if d is None:
        return {}
    key = "Path" if os.name == "nt" and "Path" in os.environ else "PATH"
    cur = os.environ.get(key, "")
    parts = [str(d)] + [x for x in cur.split(os.pathsep) if x and x != str(d)]
    return {key: os.pathsep.join(parts)}


def sdk_version() -> str | None:
    try:
        from importlib.metadata import version
        return version("openai-codex")
    except Exception:  # noqa: BLE001
        return None


def kernel_info() -> dict[str, Any]:
    """What the settings dialog shows: the active kernel, the SDK, and every
    candidate found on disk."""
    try:
        active = codex_binary()
        path: str | None = str(active)
        ver = codex_version(active)
    except FileNotFoundError:
        path, ver = None, None
    cands = candidates()
    source = next((c["source"] for c in cands if c["path"] == path), None)
    newest = max((_parse_version(c["version"] or "") for c in cands), default=())
    return {"path": path, "version": ver, "source": source,
            "sdk_version": sdk_version(),
            "candidates": cands,
            "python": sys.version.split()[0],
            "vendor_dir": str(VENDOR_DIR),
            "update_hint": "scripts/update_codex_kernel.ps1",
            "newest_installed": ".".join(str(x) for x in newest) if newest else None}
