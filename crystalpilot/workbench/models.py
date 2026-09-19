"""The models a provider can run, with what the composer needs to offer them:
display name, the reasoning ladder (the model's OWN levels, shown as they
are), input modalities, context window, and whether codex already knows the
model (catalog) - the "自适应" model / effort menus read this.

Sources, by provider kind (workbench/providers.py):

* OpenRouter: GET /api/v1/models (public, cached a day by model_caps);
  a model that lists `reasoning` among its supported parameters takes
  OpenRouter's unified effort levels low / medium / high (documented as the
  three levels every reasoning model maps onto; OpenAI models add xhigh);
  context window = `context_length`, modalities = `architecture.
  input_modalities`.
* an OpenAI-compatible endpoint (the gateway): the codex catalog - bundled
  GPT models plus CrystalPilot's custom entries for this provider - and,
  when the endpoint answers GET /models with the stored key, which of
  those ids it actually serves (marked `remote_available`; ids the endpoint
  serves but the catalog lacks are listed too, ladder unknown).

Picking a model that codex does not know yet adds a custom catalog entry
(model_catalog.upsert_custom_model) so codex learns its context window and
ladder; that takes effect when the project's engine restarts.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from . import model_catalog, providers
from .model_caps import openrouter_models

OPENROUTER_LADDER = ("low", "medium", "high")
OPENROUTER_OPENAI_LADDER = ("low", "medium", "high", "xhigh")
REMOTE_TTL_S = 600
_remote_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_remote_lock = threading.Lock()


def _remote_ids(pid: str, refresh: bool = False) -> dict[str, Any]:
    """Ids the endpoint serves (GET /models with the stored key), cached."""
    with _remote_lock:
        hit = _remote_cache.get(pid)
    if hit and not refresh and time.time() - hit[0] < REMOTE_TTL_S:
        return hit[1]
    res = providers.test_connection(pid)
    out = {"ok": bool(res.get("ok")), "ids": list(res.get("ids") or res.get("sample") or []),
           "status": res.get("status"), "error": res.get("error"),
           "n_models": res.get("n_models")}
    with _remote_lock:
        _remote_cache[pid] = (time.time(), out)
    return out


def _openrouter_entry(rec: dict[str, Any], catalog_by_slug: dict[str, dict[str, Any]]) -> dict[str, Any]:
    mid = str(rec.get("id"))
    params = rec.get("supported_parameters") or []
    reasoning = "reasoning" in params or "reasoning_effort" in params
    if mid.startswith("openai/"):
        ladder: tuple[str, ...] = OPENROUTER_OPENAI_LADDER if reasoning else ()
    else:
        ladder = OPENROUTER_LADDER if reasoning else ()
    cat = catalog_by_slug.get(mid)
    if cat and cat.get("efforts"):
        ladder = tuple(cat["efforts"])
    mods = (rec.get("architecture") or {}).get("input_modalities")
    if not isinstance(mods, list) or not mods:
        mods = ["text"]
    ctx = rec.get("context_length") or (cat or {}).get("context_window")
    pricing = rec.get("pricing") or {}
    return {"id": mid,
            "display_name": rec.get("name") or mid,
            "description": (rec.get("description") or "")[:240],
            "efforts": list(ladder),
            "default_effort": (cat or {}).get("default_effort") or ("high" if ladder else None),
            "input_modalities": [m for m in mods if m in ("text", "image", "file", "audio", "video")],
            "context_window": int(ctx) if ctx else None,
            "in_catalog": cat is not None,
            "reasoning": reasoning,
            "pricing": {k: pricing.get(k) for k in ("prompt", "completion") if k in pricing},
            "source": "openrouter"}


def _catalog_entry(m: dict[str, Any], remote: dict[str, Any] | None) -> dict[str, Any]:
    slug = str(m["slug"])
    avail: bool | None = None
    if remote and remote.get("ok"):
        avail = slug in set(remote.get("ids") or [])
    return {"id": slug,
            "display_name": m.get("display_name") or slug,
            "description": (m.get("description") or "")[:240],
            "efforts": list(m.get("efforts") or []),
            "default_effort": m.get("default_effort"),
            "input_modalities": list(m.get("input_modalities") or ["text", "image"]),
            "context_window": m.get("context_window"),
            "in_catalog": True,
            "hidden": bool(m.get("hidden")),
            "remote_available": avail,
            "source": m.get("source") or "catalog"}


def list_models(pid: str, refresh: bool = False, include_hidden: bool = False,
                probe_remote: bool = True) -> dict[str, Any]:
    """`probe_remote=False` answers from the catalog and cached provider
    metadata only (no GET /models against the endpoint) - what a settings
    write may afford."""
    prov = providers.get_provider(pid)
    if prov is None:
        raise KeyError(pid)
    catalog = model_catalog.catalog_models()
    by_slug = {m["slug"]: m for m in catalog}
    out: dict[str, Any] = {"provider": pid, "kind": prov["kind"], "models": [],
                           "fetched_at": time.time(), "note": None}
    if prov["kind"] == providers.KIND_OPENROUTER:
        recs = openrouter_models(refresh=refresh)
        if not recs:
            out["note"] = "OpenRouter 模型列表暂不可得（离线且无缓存）；下面只列 codex 已知的模型"
            out["models"] = [_catalog_entry(m, None) for m in catalog
                             if m.get("source") == "custom" and m.get("provider") == pid]
            return out
        models = [_openrouter_entry(r, by_slug) for r in recs.values()]
        # the ones this workbench already declared to codex float to the top,
        # then by name
        models.sort(key=lambda m: (not m["in_catalog"], m["display_name"].lower()))
        out["models"] = models
        out["n_total"] = len(models)
        return out
    remote = None
    if prov.get("has_key") and probe_remote:
        try:
            remote = _remote_ids(pid, refresh=refresh)
        except Exception as e:  # noqa: BLE001 - the list must not depend on the network
            remote = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    models = []
    for m in catalog:
        if m.get("source") == "custom" and m.get("provider") not in (None, pid):
            continue
        if m.get("hidden") and not include_hidden:
            continue
        if not m.get("supported_in_api", True):
            continue
        models.append(_catalog_entry(m, remote))
    known = {m["id"] for m in models}
    if remote and remote.get("ok"):
        for rid in remote.get("ids") or []:
            if rid not in known:
                models.append({"id": rid, "display_name": rid, "description": "",
                               "efforts": [], "default_effort": None,
                               "input_modalities": ["text", "image"], "context_window": None,
                               "in_catalog": False, "remote_available": True, "source": "remote"})
    out["models"] = models
    out["remote"] = {k: remote.get(k) for k in ("ok", "status", "error", "n_models")} if remote else None
    return out


def ladder_from_metadata(pid: str | None, model_id: str | None) -> tuple[str, ...] | None:
    """The reasoning levels the PROVIDER's metadata gives a model (OpenRouter
    today), without the codex catalog. None when nothing is known. Never
    touches the network beyond model_caps' day-long cache."""
    if not pid or not model_id:
        return None
    try:
        prov = providers.get_provider(pid)
    except Exception:  # noqa: BLE001 - config unreadable
        return None
    if prov is None or prov.get("kind") != providers.KIND_OPENROUTER:
        return None
    recs = openrouter_models()
    if not recs:
        return None
    rec = recs.get(model_id)
    if rec is None:
        return None
    params = rec.get("supported_parameters") or []
    reasoning = "reasoning" in params or "reasoning_effort" in params
    if not reasoning:
        return ()
    return OPENROUTER_OPENAI_LADDER if model_id.startswith("openai/") else OPENROUTER_LADDER


def describe_model(pid: str, model_id: str) -> dict[str, Any] | None:
    """One model's record from the catalog / cached provider metadata (None
    when unknown to every source). Never probes the endpoint."""
    try:
        for m in list_models(pid, probe_remote=False).get("models") or []:
            if m["id"] == model_id:
                return m
    except KeyError:
        return None
    return None


def _is_rich(m: dict[str, Any] | None) -> bool:
    """A record that actually knows the model (a ladder or a context
    window), as opposed to a placeholder."""
    return bool(m) and bool(m.get("efforts") or m.get("context_window"))


def learn_model(pid: str, model_id: str) -> dict[str, Any]:
    """Make codex know `model_id` (custom catalog entry from the provider's
    metadata). Returns model_catalog.ensure_catalog()'s record with
    "changed" = whether the catalog file was rewritten.

    A model the provider's own list does not describe is looked up in every
    other provider's cached metadata first (OpenRouter's list knows most
    public ids), so an id typed under the wrong provider - or before the
    provider switch - does not freeze a ladder-less entry. Existing weak
    entries are upgraded the same way instead of being kept forever."""
    m = describe_model(pid, model_id)
    source_pid = pid
    if not _is_rich(m):
        for other in providers.list_providers():
            if other["id"] == pid:
                continue
            alt = describe_model(other["id"], model_id)
            if _is_rich(alt):
                m, source_pid = alt, other["id"]
                break
    # the provider tag decides which tab lists the entry, so an entry that
    # already exists keeps its own: learning a model from another tab
    # upgrades its facts, it never steals it out of the tab it lives in
    prior = next((x for x in model_catalog.load_custom()
                  if x.get("slug") == model_id), None)
    tag = (prior or {}).get("provider") or source_pid
    if m is None:
        # unknown everywhere: declare a text-only entry; the ladder is left
        # UNKNOWN (not empty) so effort_ladder can still consult the
        # provider's metadata or fallback ladder
        spec = {"slug": model_id, "display_name": model_id, "provider": tag,
                "input_modalities": ["text"]}
    elif m.get("in_catalog") and m.get("source") in ("bundled", "catalog"):
        return {"changed": False, "written": False, "already": True}
    elif m.get("in_catalog") and m.get("source") == "custom" and _is_rich(m):
        return {"changed": False, "written": False, "already": True}
    else:
        efforts = list(m.get("efforts") or [])
        default = m.get("default_effort") or (efforts[-1] if efforts else None)
        spec = {"slug": model_id, "display_name": m.get("display_name") or model_id,
                "provider": tag, "description": m.get("description") or None,
                "input_modalities": model_catalog.clean_modalities(
                    m.get("input_modalities")),
                "context_window": m.get("context_window"),
                "default_reasoning_level": default,
                "supported_reasoning_levels": efforts or None}
    rec = model_catalog.upsert_custom_model(spec)
    rec["changed"] = bool(rec.get("written"))
    return rec
