"""Credential/config resolution for the BYOK provider layer.

Resolution order (first hit wins):
  1. Environment: CRYSTALPILOT_LLM_BASE_URL / _API_KEY / _MODEL / _PROVIDER
  2. User config file: ~/.crystalpilot/config.json  {"llm": {...}}
  3. Project config:   <project>/.crystalpilot/config.json
  4. Dev fallback:     <project>/testAPI.txt  (local test endpoint; never committed)

API keys are never logged and never serialized back to disk by this module.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .openai_responses import OpenAIResponsesProvider
from .provider import LLMProvider


@dataclass
class ModelRouting:
    """Which model/effort to use per task class."""

    planner: str = "gpt-6-astra"        # complex reasoning: strategy, diagnosis
    planner_effort: str | None = "xhigh"
    analyst: str = "gpt-6-astra"        # result interpretation, validation review
    analyst_effort: str | None = "high"
    fast: str = "gpt-6-astra"           # summaries and formatting
    fast_effort: str | None = None


@dataclass
class LLMConfig:
    provider: str = "openai-responses"
    base_url: str = ""
    api_key: str = ""
    routing: ModelRouting = field(default_factory=ModelRouting)

    def redacted(self) -> dict:
        return {"provider": self.provider, "base_url": self.base_url,
                "api_key": "***", "routing": vars(self.routing)}


def _from_env() -> LLMConfig | None:
    url = os.environ.get("CRYSTALPILOT_LLM_BASE_URL")
    key = os.environ.get("CRYSTALPILOT_LLM_API_KEY")
    if not (url and key):
        return None
    cfg = LLMConfig(provider=os.environ.get("CRYSTALPILOT_LLM_PROVIDER", "openai-responses"),
                    base_url=url, api_key=key)
    model = os.environ.get("CRYSTALPILOT_LLM_MODEL")
    if model:
        cfg.routing = ModelRouting(planner=model, analyst=model, fast=model,
                                   planner_effort=None, analyst_effort=None)
    return cfg


def _from_config_file(path: Path) -> LLMConfig | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8")).get("llm") or {}
    except (json.JSONDecodeError, OSError):
        return None
    key = data.get("api_key") or ""
    if data.get("api_key_env"):
        key = os.environ.get(data["api_key_env"], "")
    if data.get("api_key_file"):
        try:
            key = Path(data["api_key_file"]).expanduser().read_text(encoding="utf-8").strip()
        except OSError:
            key = ""
    if not (data.get("base_url") and key):
        return None
    cfg = LLMConfig(provider=data.get("provider", "openai-responses"),
                    base_url=data["base_url"], api_key=key)
    routing = data.get("routing") or {}
    for k, v in routing.items():
        if hasattr(cfg.routing, k):
            setattr(cfg.routing, k, v)
    return cfg


def _from_dev_testapi(project_root: Path) -> LLMConfig | None:
    p = project_root / "testAPI.txt"
    if not p.exists():
        return None
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    url_m = re.search(r"URL[：:]\s*(\S+)", text)
    key_m = re.search(r"Key[：:]\s*(\S+)", text)
    if not (url_m and key_m):
        return None
    return LLMConfig(base_url=url_m.group(1).rstrip("/"), api_key=key_m.group(1))


def resolve_llm_config(project_root: Path | None = None) -> LLMConfig:
    root = Path(project_root) if project_root else Path.cwd()
    for cfg in (
        _from_env(),
        _from_config_file(Path.home() / ".crystalpilot" / "config.json"),
        _from_config_file(root / ".crystalpilot" / "config.json"),
        _from_dev_testapi(root),
    ):
        if cfg:
            return cfg
    raise RuntimeError(
        "No LLM credentials found. Set CRYSTALPILOT_LLM_BASE_URL/_API_KEY, or create "
        "~/.crystalpilot/config.json with an 'llm' section.")


def build_provider(cfg: LLMConfig, task: str = "planner") -> tuple[LLMProvider, str, str | None]:
    """Return (provider, model, reasoning_effort) for a task class."""
    model = getattr(cfg.routing, task, cfg.routing.planner)
    effort = getattr(cfg.routing, f"{task}_effort", None)
    if cfg.provider == "openai-responses":
        return OpenAIResponsesProvider(cfg.base_url, cfg.api_key, model), model, effort
    raise RuntimeError(f"Unknown LLM provider: {cfg.provider}")
