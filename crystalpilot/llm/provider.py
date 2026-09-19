"""BYOK LLM provider layer.

The engine talks to this interface only; concrete providers adapt OpenAI-Responses,
Anthropic, Gemini, or any OpenAI-compatible endpoint. Credentials come exclusively
from user config / environment - never hardcoded, never logged.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolSpec:
    """Provider-agnostic function-tool description."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema


@dataclass
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMMessage:
    role: str                    # system | user | assistant | tool
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None   # for role == tool (result of that call)


@dataclass
class LLMRequest:
    messages: list[LLMMessage]
    tools: list[ToolSpec] = field(default_factory=list)
    model: str | None = None          # None -> provider default
    reasoning_effort: str | None = None   # low | medium | high | xhigh (provider-dependent)
    max_output_tokens: int | None = None
    temperature: float | None = None
    response_json_schema: dict[str, Any] | None = None  # force structured output


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: LLMUsage = field(default_factory=LLMUsage)
    raw_id: str | None = None
    model: str | None = None
    stop_reason: str | None = None

    @property
    def json(self) -> Any:
        """Parse text as JSON (for structured-output requests)."""
        return json.loads(self.text)


class LLMProvider(Protocol):
    name: str

    def complete(self, request: LLMRequest) -> LLMResponse: ...


class LLMError(RuntimeError):
    pass
