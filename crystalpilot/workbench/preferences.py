"""Workbench-wide preferences that outlive a request.

Today this holds one value: the language the person chose for the interface
(Settings > Appearance). The browser keeps its own copy for rendering; the
server keeps this one so that the agent template written into every project
(AGENTS.md) and the developer instructions of new threads can follow the same
choice. Runtime data: ``workdir/preferences.json`` is not tracked.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .core import ENGINE_ROOT
from .i18n import normalize

_lock = threading.Lock()


def prefs_file() -> Path:
    override = os.environ.get("CRYSTALPILOT_PREFERENCES_FILE")
    return Path(override) if override else ENGINE_ROOT / "workdir" / "preferences.json"


def _load() -> dict:
    p = prefs_file()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    p = prefs_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def language() -> str:
    """The interface language the workbench remembers ('zh' or 'en')."""
    return normalize(_load().get("language"))


def set_language(value: str | None) -> str:
    lang = normalize(value)
    with _lock:
        data = _load()
        data["language"] = lang
        _save(data)
    return lang
