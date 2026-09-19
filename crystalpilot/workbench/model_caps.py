"""What the model behind a provider can take - today: image input.

The engine's picture channel (view_structure, inspect_map renders) hands
PNGs to the model as MCP image blocks. A text-only model rejects the whole
request (OpenRouter, z-ai/glm-5.3, 2026-09-06: HTTP 404 "No endpoints found
that support image input"), the turn fails and every later turn on that
thread fails too because the image sits in the history. So the MCP server
must know BEFORE the first picture whether it may send one.

- the gateway provider (config default) serves multimodal GPT models: True;
- OpenRouter publishes `architecture.input_modalities` per model in
  GET /api/v1/models (no auth); cached on disk for a day;
- anything else / offline with no cache: None = unknown (images are sent,
  as before; the settings say the capability is unknown).
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

from .core import ENGINE_ROOT

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_FILE = ENGINE_ROOT / "workdir" / "cache" / "openrouter-models.json"
CACHE_TTL_S = 24 * 3600
#: providers whose models are known multimodal without a lookup
IMAGE_CAPABLE_PROVIDERS = ("crystalpilot",)


def _load_cache() -> dict[str, Any] | None:
    try:
        if time.time() - CACHE_FILE.stat().st_mtime > CACHE_TTL_S:
            return None
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - no cache / unreadable
        return None


_MEM: dict[str, Any] = {}


def openrouter_models(refresh: bool = False) -> dict[str, dict] | None:
    """{model id: model record} from OpenRouter, cached for CACHE_TTL_S.
    None when there is neither a fresh cache nor network. The parsed
    file is also kept in memory (keyed by the cache file's mtime): the
    settings assembly asks for a model's ladder on every request."""
    if not refresh:
        try:
            mt = CACHE_FILE.stat().st_mtime
        except OSError:
            mt = None
        if mt is not None and _MEM.get("mtime") == mt and time.time() - mt <= CACHE_TTL_S:
            return _MEM["models"]
    data = None if refresh else _load_cache()
    if data is None:
        try:
            with urllib.request.urlopen(OPENROUTER_MODELS_URL, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8"))
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(json.dumps(data), encoding="utf-8")
        except Exception:  # noqa: BLE001 - offline: fall back to a stale cache
            try:
                data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return None
    models = {m.get("id"): m for m in (data.get("data") or []) if m.get("id")}
    try:
        _MEM["mtime"] = CACHE_FILE.stat().st_mtime
        _MEM["models"] = models
    except OSError:
        pass
    return models


def image_input_supported(provider: str | None, model: str | None) -> bool | None:
    """True / False when known, None when it cannot be told."""
    if os.environ.get("CRYSTALPILOT_NO_IMAGES") == "1":
        return False
    prov = provider or "crystalpilot"
    if prov in IMAGE_CAPABLE_PROVIDERS:
        return True
    if prov == "openrouter":
        if not model:
            return None
        models = openrouter_models()
        if not models:
            return None
        rec = models.get(str(model))
        if rec is None:
            return None
        mods = (rec.get("architecture") or {}).get("input_modalities")
        if not isinstance(mods, list):
            return None
        return "image" in mods
    return None
