"""The model catalog codex runs with: bundled models + CrystalPilot's own.

`model_catalog_json` in codex-home/config.toml REPLACES codex's bundled
catalog (probed 2026-09-07 on 0.153.4: model/list returned exactly the
three entries of the hand-built file). So the file codex reads is
generated here from two sources:

* the catalog bundled inside the active codex binary (plain JSON inside the
  exe; extracted once per binary and cached under workdir/cache) - this is
  what makes the gateway's GPT ladder and its prompts/tool modes current
  after every kernel upgrade;
* codex-home/model_catalog.custom.json - the lean, committed list of the
  third-party models CrystalPilot added (OpenRouter's GLM models, anything
  the user picks in the model menu). Each is rendered from a bundled
  template entry (gpt-5.5: plain tool mode, no responses-lite) so the
  format always matches the binary; fields the spec names override.

A custom entry exists so that codex knows a model's context window
(thread/tokenUsage/updated carries it, the composer ring depends on it),
its reasoning ladder (spawn_agent validates a sub-agent's effort against
it) and its input modalities (whether pictures may be sent).
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from .core import CODEX_HOME, ENGINE_ROOT
from . import kernel

CATALOG_PATH = CODEX_HOME / "model_catalog.json"
CUSTOM_PATH = CODEX_HOME / "model_catalog.custom.json"
GENERIC_PROMPT_PATH = CODEX_HOME / "base_instructions.generic.txt"
CACHE_DIR = ENGINE_ROOT / "workdir" / "cache"
TEMPLATE_SLUG = "gpt-5.5"

#: descriptions codex shows next to each effort (the bundled wording)
LEVEL_DESCRIPTIONS = {
    "none": "No extra reasoning",
    "minimal": "Minimal reasoning for the fastest replies",
    "low": "Fast responses with lighter reasoning",
    "medium": "Balances speed and reasoning depth for everyday tasks",
    "high": "Greater reasoning depth for complex problems",
    "xhigh": "Extra high reasoning depth for the hardest problems",
    "max": "Maximum reasoning depth",
    "ultra": "Ultra reasoning depth",
}


# ------------------------------------------------------------ bundled part
def _scan_json_object(data: bytes, anchor: bytes) -> dict[str, Any] | None:
    k = data.find(anchor)
    if k < 0:
        return None
    start = data.rfind(b"{", 0, k)
    depth = 0
    i = start
    instr = False
    esc = False
    n = len(data)
    while i < n:
        c = data[i]
        if instr:
            if esc:
                esc = False
            elif c == 0x5C:      # backslash
                esc = True
            elif c == 0x22:      # quote
                instr = False
        else:
            if c == 0x22:
                instr = True
            elif c == 0x7B:      # {
                depth += 1
            elif c == 0x7D:      # }
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(data[start:i + 1].decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        return None
        i += 1
    return None


def bundled_catalog(binary: str | Path | None = None) -> dict[str, Any]:
    """The catalog compiled into the codex binary, cached per binary."""
    exe = Path(binary) if binary else kernel.codex_binary()
    st = exe.stat()
    tag = hashlib.sha1(f"{exe}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:12]
    cache = CACHE_DIR / f"codex-bundled-catalog-{tag}.json"
    if cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    cat = _scan_json_object(exe.read_bytes(), b'"models": [')
    if not cat or not isinstance(cat.get("models"), list):
        raise RuntimeError(f"no bundled model catalog found in {exe}")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")
    return cat


# ------------------------------------------------------------- custom part
def load_custom() -> list[dict[str, Any]]:
    if not CUSTOM_PATH.is_file():
        return []
    try:
        data = json.loads(CUSTOM_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [m for m in (data.get("models") or []) if isinstance(m, dict) and m.get("slug")]


def save_custom(models: list[dict[str, Any]]) -> None:
    CUSTOM_PATH.parent.mkdir(parents=True, exist_ok=True)
    CUSTOM_PATH.write_text(json.dumps({"models": models}, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")


def _levels(spec_levels: Any) -> list[dict[str, str]]:
    out = []
    for lv in spec_levels or []:
        if isinstance(lv, str):
            out.append({"effort": lv, "description": LEVEL_DESCRIPTIONS.get(lv, lv)})
        elif isinstance(lv, dict) and lv.get("effort"):
            out.append({"effort": str(lv["effort"]),
                        "description": str(lv.get("description") or LEVEL_DESCRIPTIONS.get(lv["effort"], lv["effort"]))})
    return out


def render_custom_entry(spec: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    """A full catalog entry for `spec` in the template's format."""
    e = copy.deepcopy(template)
    slug = str(spec["slug"])
    levels = _levels(spec.get("supported_reasoning_levels"))
    default = spec.get("default_reasoning_level")
    if levels and (not default or default not in [lv["effort"] for lv in levels]):
        default = levels[-1]["effort"]
    ctx = spec.get("context_window")
    e.update({
        "slug": slug,
        "display_name": str(spec.get("display_name") or slug),
        "description": str(spec.get("description") or f"{slug} (CrystalPilot custom model)"),
        "default_reasoning_level": default or e.get("default_reasoning_level") or "medium",
        "supported_reasoning_levels": levels or e.get("supported_reasoning_levels") or [],
        "input_modalities": clean_modalities(spec.get("input_modalities")),
        "visibility": spec.get("visibility") or "list",
        "supported_in_api": True,
        "upgrade": None,
        "priority": int(spec.get("priority") or 0),
    })
    if ctx:
        e["context_window"] = int(ctx)
        e["max_context_window"] = int(spec.get("max_context_window") or ctx)
    if "base_instructions" in template and GENERIC_PROMPT_PATH.is_file():
        # 0.147 carried the prompt in the catalog; keep the generic one the
        # third-party models already ran under
        e["base_instructions"] = GENERIC_PROMPT_PATH.read_text(encoding="utf-8")
    for k in ("availability_nux", "upgrade_info"):
        e.pop(k, None) if k not in template else None
    return e


def _template(bundled: dict[str, Any]) -> dict[str, Any]:
    models = bundled.get("models") or []
    for m in models:
        if m.get("slug") == TEMPLATE_SLUG:
            return m
    for m in models:
        if not m.get("tool_mode"):
            return m
    return models[0]


def build(binary: str | Path | None = None) -> dict[str, Any]:
    bundled = bundled_catalog(binary)
    template = _template(bundled)
    by_slug: dict[str, dict[str, Any]] = {}
    for m in bundled.get("models") or []:
        by_slug[str(m.get("slug"))] = copy.deepcopy(m)
    n_custom = 0
    for spec in load_custom():
        by_slug[str(spec["slug"])] = render_custom_entry(spec, template)
        n_custom += 1
    out = dict(bundled)
    out["models"] = list(by_slug.values())
    out["_crystalpilot"] = {"generated_from": str(binary or kernel.codex_binary()),
                            "n_bundled": len(bundled.get("models") or []),
                            "n_custom": n_custom}
    return out


def ensure_catalog(binary: str | Path | None = None) -> dict[str, Any]:
    """Write codex-home/model_catalog.json when it differs from the current
    build. Returns {"written": bool, "n_bundled", "n_custom", "path"}."""
    cat = build(binary)
    text = json.dumps(cat, indent=1, ensure_ascii=False)
    cur = None
    try:
        cur = CATALOG_PATH.read_text(encoding="utf-8")
    except OSError:
        pass
    written = False
    if cur != text:
        CATALOG_PATH.write_text(text, encoding="utf-8")
        written = True
    meta = cat.get("_crystalpilot") or {}
    return {"written": written, "path": str(CATALOG_PATH),
            "n_bundled": meta.get("n_bundled"), "n_custom": meta.get("n_custom")}


# ---------------------------------------------------------------- queries
# codex's own ModelInputModality enum. A provider that reports anything else
# (OpenRouter says "file" for Claude/GPT and "video" for GLM-Flash) would make
# the generated catalog unparsable, and codex then refuses to load its config
# at all - every project stops being able to start a thread. Filter, never
# pass through.
CODEX_INPUT_MODALITIES = ("text", "image", "audio")


def clean_modalities(values: Any) -> list[str]:
    """The subset codex understands; never empty."""
    if not isinstance(values, (list, tuple)):
        return ["text"]
    out = [str(v) for v in values if str(v) in CODEX_INPUT_MODALITIES]
    return out or ["text"]


def _summary(m: dict[str, Any], source: str) -> dict[str, Any]:
    levels = [lv.get("effort") for lv in (m.get("supported_reasoning_levels") or [])
              if isinstance(lv, dict) and lv.get("effort")]
    return {"slug": m.get("slug"), "display_name": m.get("display_name") or m.get("slug"),
            "description": m.get("description"),
            "efforts": levels,
            "default_effort": m.get("default_reasoning_level"),
            "input_modalities": list(m.get("input_modalities") or ["text", "image"]),
            "context_window": m.get("context_window"),
            "max_context_window": m.get("max_context_window"),
            "hidden": (m.get("visibility") or "list") != "list",
            "supported_in_api": bool(m.get("supported_in_api", True)),
            "multi_agent": m.get("multi_agent_version"),
            "source": source}


def catalog_models(binary: str | Path | None = None) -> list[dict[str, Any]]:
    """Every model codex knows (bundled + custom), summarised."""
    try:
        bundled = bundled_catalog(binary)
    except (OSError, RuntimeError, FileNotFoundError):
        bundled = {"models": []}
    custom = {str(s["slug"]): s for s in load_custom()}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in bundled.get("models") or []:
        slug = str(m.get("slug"))
        if slug in custom:
            continue
        seen.add(slug)
        out.append(_summary(m, "bundled"))
    for slug, spec in custom.items():
        seen.add(slug)
        s = _summary({**spec, "supported_reasoning_levels": _levels(spec.get("supported_reasoning_levels"))},
                     "custom")
        s["provider"] = spec.get("provider")
        out.append(s)
    return out


def catalog_entry(slug: str | None, binary: str | Path | None = None) -> dict[str, Any] | None:
    if not slug:
        return None
    for m in catalog_models(binary):
        if m["slug"] == slug:
            return m
    return None


def effort_ladder_of(slug: str | None) -> tuple[str, ...] | None:
    """The reasoning efforts the catalog declares for `slug`, None when the
    model is unknown to codex."""
    e = catalog_entry(slug)
    if e is None:
        return None
    return tuple(e["efforts"])


def upsert_custom_model(spec: dict[str, Any]) -> dict[str, Any]:
    """Add or replace one custom model (by slug) and regenerate the catalog.
    Returns ensure_catalog()'s record plus the stored spec."""
    slug = str(spec.get("slug") or "").strip()
    if not slug:
        raise ValueError("model slug required")
    models = [m for m in load_custom() if m.get("slug") != slug]
    clean = {k: v for k, v in spec.items() if v is not None}
    clean["slug"] = slug
    if "input_modalities" in clean:
        clean["input_modalities"] = clean_modalities(clean["input_modalities"])
    models.append(clean)
    save_custom(models)
    rec = ensure_catalog()
    rec["spec"] = clean
    return rec


def remove_custom_model(slug: str) -> dict[str, Any]:
    models = [m for m in load_custom() if m.get("slug") != slug]
    save_custom(models)
    return ensure_catalog()
