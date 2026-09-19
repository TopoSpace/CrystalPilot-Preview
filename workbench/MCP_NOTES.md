# MCP integration notes (M0 probe, 2026-08-28)

Probe: `scripts/probe_mcp_approval.py` + `scripts/echo_mcp_server.py`, driven
through the real codex app-server + gateway (gpt-5.6-sol). Both rounds PASS.

## Confirmed facts

1. **Registration** — `CodexConfig(config_overrides=(...))` → `codex --config k=v ... app-server`
   works; `codex-home/config.toml` needs no edits. Working override set:
   ```
   mcp_servers.<name>.command='H:\...\python.exe'      # TOML literal strings (single quotes)
   mcp_servers.<name>.args=['-X','utf8','<script>']
   mcp_servers.<name>.env={PYTHONUTF8='1'}
   mcp_servers.<name>.startup_timeout_sec=60
   mcp_servers.<name>.approval_mode='auto'|'prompt'    # ('writes' exists too)
   projects.'<lowercase path>'.trust_level='trusted'   # per-project trust w/o config.toml edits
   ```
2. **Server SDK** — python `mcp` package must be **1.x** (`mcp>=1.2,<2` pinned).
   mcp 2.x renamed/removed the low-level decorator API and cannot register
   tools with explicit JSON schemas (FastMCP derives schemas from type hints).
   With 2.1.1 installed the server crashed at import and codex showed the
   server as configured but `tools: {}` / `serverInfo: null`.
3. **Diagnostics** — `client._request_raw("mcpServerStatus/list", {"detail": "full"})`
   returns per-server `{serverInfo, tools{...}, authStatus}`; `tools: {}` means
   the server process failed/never initialized. `codex mcp list` (with
   CODEX_HOME set + same `--config` flags) shows static registration.
4. **Events** — MCP tool calls arrive as `item/started` / `item/completed`
   with item `type="mcpToolCall"` and fields:
   `{server, tool, arguments, status(McpToolCallStatus.*), duration_ms,
     read_only_hint, result{content[{type,text}], structured_content}, error{message}}`.
   `read_only_hint` mirrors the MCP ToolAnnotations of the tool.
5. **Approvals (approval_mode='prompt')** — arrive at the SDK approval_handler as
   server request **`mcpServer/elicitation/request`** with params
   `{threadId, turnId, serverName, mode:"form", message,
     requestedSchema:{type:object,properties:{}},
     _meta:{codex_approval_kind:"mcp_tool_call", persist:["session","always"],
            tool_description, tool_params, tool_params_display}}`.
   The response must be an MCP elicitation result:
   - accept: `{"action": "accept", "content": {}}`  ✅ verified (tool then runs)
   - reject: `{"action": "decline"}` (codex reports "user rejected MCP tool call")
   - plain `{"decision": "accept"}` is treated as a rejection — wrong shape.
   `_meta.persist` suggests session/always persistence variants (not yet probed).
6. **approval_mode='auto'** — no approval round-trips; calls run immediately.
   Given fact 4 (read_only_hint flows through), `'writes'` should gate only
   tools annotated readOnlyHint=false — use for the Copilot demo; verify then.

## Consequences for the workbench

- `Workbench._on_approval_request` needs an elicitation branch mapping our
  accept/reject decisions to `{"action": "accept", "content": {}}` / `{"action": "decline"}`,
  and should surface `_meta.tool_params_display` + `serverName` + tool name in
  the /wb approval card.
- `normalize_notification` should emit first-class `tool_started/tool_completed`
  kinds from mcpToolCall items (server, tool, arguments, ok, duration_ms,
  result text (JSON), error).
- MVP acceptance run: `approval_mode='auto'`; Copilot demo: `'writes'` (fallback `'prompt'`).
