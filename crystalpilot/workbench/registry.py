"""Global project registry: recent projects list + Codex trust management.

The recent list lives in workdir/projects.json (runtime data, gitignored).
Trust entries are appended to the isolated codex-home/config.toml so the
app-server treats each opened project folder as trusted; the user's personal
~/.codex is never touched.
"""
from __future__ import annotations

import json
import os
import time
import tomllib
from pathlib import Path

from .core import CODEX_HOME, ENGINE_ROOT

REGISTRY_FILE = ENGINE_ROOT / "workdir" / "projects.json"
MAX_RECENT = 30


def _load() -> list[dict]:
    if REGISTRY_FILE.exists():
        try:
            return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return []


def record_recent(path: str | Path) -> None:
    p = str(Path(path).resolve())
    entries = [e for e in _load() if os.path.normcase(e.get("path", "")) != os.path.normcase(p)]
    entries.insert(0, {"path": p, "opened": time.time()})
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(json.dumps(entries[:MAX_RECENT], indent=2,
                                        ensure_ascii=False), encoding="utf-8")


def project_display_name(path: str | Path) -> str | None:
    """The name a person gave the project, if any: the workbench state's
    settings.display_name (renamable from the sidebar), else a title in
    context.json. None means "show the directory name" - the sidebar used
    to show only directory names, and a board of ui-import-1788590415165 /
    pe8f898bd rows said nothing about what was in them."""
    p = Path(path)
    st = p / ".crystalpilot-workbench.json"
    try:
        if st.exists():
            data = json.loads(st.read_text(encoding="utf-8"))
            v = (data.get("settings") or {}).get("display_name")
            if isinstance(v, str) and v.strip():
                return v.strip()
    except (OSError, ValueError, AttributeError):
        pass
    ctx = p / "context.json"
    try:
        if ctx.exists():
            data = json.loads(ctx.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in ("title", "name"):
                    v = data.get(key)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
    except (OSError, ValueError):
        pass
    return None


def recent_projects() -> list[dict]:
    out = []
    for e in _load():
        if not Path(e.get("path", "")).is_dir():
            continue
        out.append({**e, "display_name": project_display_name(e["path"])})
    return out


def ensure_trusted(path: str | Path) -> None:
    """Append a trust entry for the project to the isolated config.toml."""
    key = os.path.normcase(str(Path(path).resolve()))
    cfg = CODEX_HOME / "config.toml"
    if not cfg.exists():
        raise RuntimeError(f"isolated Codex config missing: {cfg}")
    with cfg.open("rb") as fh:
        existing = tomllib.load(fh).get("projects", {})
    if any(os.path.normcase(k) == key for k in existing):
        return
    quoted = key.replace("'", "''")
    with cfg.open("a", encoding="utf-8") as fh:
        fh.write(f"\n[projects.'{quoted}']\ntrust_level = \"trusted\"\n")
