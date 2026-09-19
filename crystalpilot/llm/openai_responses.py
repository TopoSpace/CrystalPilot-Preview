"""OpenAI Responses API provider (also serves any Responses-compatible endpoint).

Never logs or prints credentials. Retries transient failures with backoff.
"""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .provider import (LLMError, LLMMessage, LLMRequest, LLMResponse, LLMUsage,
                       ToolCall)


class OpenAIResponsesProvider:
    name = "openai-responses"

    def __init__(self, base_url: str, api_key: str, default_model: str,
                 timeout: float = 600.0, max_retries: int = 3) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.default_model = default_model
        self._client = httpx.Client(timeout=timeout)
        self._max_retries = max_retries

    # ------------------------------------------------------------------
    def complete(self, request: LLMRequest) -> LLMResponse:
        payload = self._build_payload(request)
        last_err: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                r = self._client.post(
                    f"{self._base_url}/responses",
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}",
                             "Content-Type": "application/json"},
                )
                if r.status_code in (429, 500, 502, 503, 504):
                    raise LLMError(f"transient HTTP {r.status_code}: {r.text[:300]}")
                if r.status_code != 200:
                    raise LLMError(f"HTTP {r.status_code}: {r.text[:500]}")
                return self._parse_response(r.json())
            except (httpx.TransportError, LLMError) as e:
                last_err = e
                if isinstance(e, LLMError) and "transient" not in str(e):
                    raise
                if attempt < self._max_retries:
                    time.sleep(2.0 * (attempt + 1))
        raise LLMError(f"LLM request failed after retries: {last_err}")

    # ------------------------------------------------------------------
    def _build_payload(self, request: LLMRequest) -> dict[str, Any]:
        input_items: list[dict[str, Any]] = []
        instructions: str | None = None
        for m in request.messages:
            if m.role == "system":
                instructions = (instructions + "\n\n" + m.content) if instructions else m.content
            elif m.role == "tool":
                input_items.append({
                    "type": "function_call_output",
                    "call_id": m.tool_call_id,
                    "output": m.content,
                })
            elif m.role == "assistant" and m.tool_calls:
                if m.content:
                    input_items.append({"role": "assistant", "content": m.content})
                for tc in m.tool_calls:
                    input_items.append({
                        "type": "function_call",
                        "call_id": tc.call_id,
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    })
            else:
                input_items.append({"role": m.role, "content": m.content})

        payload: dict[str, Any] = {
            "model": request.model or self.default_model,
            "input": input_items,
        }
        if instructions:
            payload["instructions"] = instructions
        if request.tools:
            payload["tools"] = [
                {"type": "function", "name": t.name, "description": t.description,
                 "parameters": t.parameters}
                for t in request.tools
            ]
        if request.reasoning_effort:
            payload["reasoning"] = {"effort": request.reasoning_effort}
        if request.max_output_tokens:
            payload["max_output_tokens"] = request.max_output_tokens
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.response_json_schema:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": request.response_json_schema.get("title", "result"),
                    "schema": request.response_json_schema,
                    "strict": False,
                }
            }
        return payload

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_response(data: dict[str, Any]) -> LLMResponse:
        texts: list[str] = []
        tool_calls: list[ToolCall] = []
        for item in data.get("output") or []:
            t = item.get("type")
            if t == "message":
                for part in item.get("content") or []:
                    if part.get("type") == "output_text":
                        texts.append(part.get("text") or "")
            elif t == "function_call":
                try:
                    args = json.loads(item.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": item.get("arguments")}
                tool_calls.append(ToolCall(call_id=item.get("call_id") or item.get("id"),
                                           name=item.get("name"), arguments=args))
        usage_d = data.get("usage") or {}
        usage = LLMUsage(
            input_tokens=usage_d.get("input_tokens", 0),
            output_tokens=usage_d.get("output_tokens", 0),
            cached_tokens=(usage_d.get("input_tokens_details") or {}).get("cached_tokens", 0),
        )
        return LLMResponse(
            text="\n".join(tx for tx in texts if tx),
            tool_calls=tool_calls,
            usage=usage,
            raw_id=data.get("id"),
            model=data.get("model"),
            stop_reason=data.get("status"),
        )
