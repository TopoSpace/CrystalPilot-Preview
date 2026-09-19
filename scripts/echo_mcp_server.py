"""Minimal echo MCP server (stdio) for M0 protocol probing.

Two tools: cp_echo (read-only flavor) and cp_echo_write (annotated as
destructive so approval_mode='writes'/'prompt' behavior can be observed).
"""
from __future__ import annotations

import json
import sys

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

server = Server("cp_echo")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="cp_echo",
            description="Echo back the given message (CrystalPilot MCP probe, read-only).",
            inputSchema={"type": "object",
                         "properties": {"message": {"type": "string"}},
                         "required": ["message"]},
            annotations=types.ToolAnnotations(readOnlyHint=True),
        ),
        types.Tool(
            name="cp_echo_write",
            description="Echo back the given message (probe tool marked as mutating).",
            inputSchema={"type": "object",
                         "properties": {"message": {"type": "string"}},
                         "required": ["message"]},
            annotations=types.ToolAnnotations(readOnlyHint=False,
                                              destructiveHint=True),
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    payload = {"ok": True, "tool": name, "echo": arguments.get("message", "")}
    return [types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


async def _run() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    print("cp_echo mcp server starting", file=sys.stderr, flush=True)
    anyio.run(_run)
