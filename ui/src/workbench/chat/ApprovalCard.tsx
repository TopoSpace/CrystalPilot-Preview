/** Inline approval item in the stream. While PENDING it is a passive
 * placeholder only - the actionable controls live in ComposerApproval
 * above the composer (DeepSeek Harness lesson: rendering the same wait
 * twice, once as an in-stream card and once at the input, splits the
 * user's attention; the input area is where their hands already are).
 * Resolved items collapse to a status line. */
import { cx } from "../../lib/format";
import { humanizeCommand } from "../../lib/humanizeCommand";
import { OBSERVE_TOOLS } from "../../lib/toolCards";
import { t } from "../../lib/i18n";
import type { ApprovalItem } from "../../state/threadReducer";
import { IconShield } from "../icons";

export interface ParamRow {
  name: string;
  value: string;
}

/** Defensive extraction from the elicitation `detail` payload. */
export function describeApproval(
  item: ApprovalItem,
): { message: string; params: ParamRow[] } {
  let message = item.mcpMessage ?? "";
  // codex phrases every MCP elicitation as `Allow the <server> MCP server
  // to run tool "<name>"?` - the decision row read as raw English next to
  // Chinese cards (visual review, 2026-09-05); the tool name is the fact
  const mcp = /^Allow the (\S+) MCP server to run tool "([^"]+)"\??$/.exec(message.trim());
  if (mcp) message = `${t.approvalMcpTool}${mcp[2]}`;
  const params: ParamRow[] = [];
  const detail = item.detail;
  if (detail && typeof detail === "object") {
    const d = detail as Record<string, unknown>;
    if (!message && typeof d.message === "string") message = d.message;
    const meta = d._meta;
    if (meta && typeof meta === "object") {
      const display = (meta as Record<string, unknown>).tool_params_display;
      if (Array.isArray(display)) {
        for (const row of display) {
          if (row && typeof row === "object") {
            const r = row as Record<string, unknown>;
            const name = r.display_name ?? r.name;
            if (typeof name === "string") {
              params.push({ name, value: String(r.value ?? "") });
            }
          }
        }
      }
    }
  }
  if (params.length === 0 && item.mcpToolParams && typeof item.mcpToolParams === "object") {
    for (const [k, v] of Object.entries(item.mcpToolParams as Record<string, unknown>)) {
      params.push({ name: k, value: typeof v === "string" ? v : JSON.stringify(v) });
    }
  }
  // commandExecution approvals carry the raw (powershell-wrapped) command
  // line - decision-makers need "what it wants to do", not that string
  // (调研 P1-8); the raw command stays in the params rows below
  if (!message && detail && typeof detail === "object") {
    const cmd = (detail as Record<string, unknown>).command;
    if (typeof cmd === "string" && cmd !== "") {
      const h = humanizeCommand(cmd);
      // the unrecognized fallback label already reads 运行命令：… - do not
      // stack the 执行命令 prefix on top of it (seen live: 执行命令：运行命令：)
      message = h.recognized ? `${t.approvalRunCommand}${h.label}` : h.label;
      if (!params.some((p) => p.name === "command")) {
        params.push({ name: "command", value: cmd });
      }
    }
  }
  if (!message) message = `${item.mcpServer ?? ""} ${item.method}`.trim();
  return { message, params };
}

export interface ApprovalFacets {
  what: string;
  why: string | null;
  risk: string;
  files: string[];
  tool: string | null;
}

const DELIVER_TOOLS = new Set(["write_outputs", "finalize_delivery"]);
const UPLOAD_TOOLS = new Set(["submit_iucr_checkcif"]);
const WHY_KEYS = ["reason", "rationale", "why", "purpose", "note", "justification"];
const PATH_KEYS = ["path", "cif_path", "hkl_path", "out_dir", "output_dir", "file", "res_path", "directory", "cwd"];

/** 做什么 / 为什么 / 风险 / 涉及文件 for the composer approval card (R6):
 * the tool name is read off the elicitation message, the reason off the
 * tool's own reason-like parameter, the risk off the tool class, the files
 * off path-like parameters, a file-change payload or a command's cwd. */
export function approvalFacets(item: ApprovalItem): ApprovalFacets {
  const { message, params } = describeApproval(item);
  const detail = (item.detail && typeof item.detail === "object" ? item.detail : {}) as Record<string, unknown>;
  const tool = /run tool "([^"]+)"/.exec(message)?.[1] ?? null;
  const paramMap = new Map(params.map((r) => [r.name, r.value] as const));
  let why: string | null = null;
  for (const k of WHY_KEYS) {
    const v = paramMap.get(k);
    if (typeof v === "string" && v.trim() !== "") {
      why = v.trim();
      break;
    }
  }
  const files: string[] = [];
  for (const k of PATH_KEYS) {
    const v = paramMap.get(k);
    if (typeof v === "string" && v.trim() !== "") files.push(v.trim());
  }
  const changes = detail.changes;
  if (changes && typeof changes === "object" && !Array.isArray(changes)) {
    files.push(...Object.keys(changes as Record<string, unknown>));
  } else if (Array.isArray(changes)) {
    for (const c of changes) {
      if (c && typeof c === "object" && typeof (c as { path?: unknown }).path === "string") {
        files.push((c as { path: string }).path);
      }
    }
  }
  if (typeof detail.cwd === "string" && detail.cwd !== "" && !files.includes(detail.cwd)) files.push(detail.cwd);
  const isCommand = typeof detail.command === "string" && detail.command !== "";
  const isFileChange = changes !== undefined || /patch|file/i.test(item.method);
  let risk: string;
  if (tool !== null) {
    if (UPLOAD_TOOLS.has(tool)) risk = t.riskUpload;
    else if (DELIVER_TOOLS.has(tool)) risk = t.riskDeliver;
    else if (OBSERVE_TOOLS.has(tool)) risk = t.riskObserve;
    else risk = t.riskMutate;
  } else if (isCommand) {
    risk = t.riskShell;
  } else if (isFileChange) {
    risk = t.riskFile;
  } else {
    risk = t.riskUnknown;
  }
  return { what: message, why, risk, files: Array.from(new Set(files)).slice(0, 8), tool };
}

function statusLabel(status: ApprovalItem["status"]): string {
  switch (status) {
    case "accepted":
      return t.approvalAccepted;
    case "rejected":
      return t.approvalRejected;
    case "auto":
      return t.approvalAuto;
    case "timeout":
      return t.approvalTimeout;
    case "resolved":
      return t.approvalResolved;
    default:
      return t.approvalPending;
  }
}

export function ApprovalCard({ item }: { item: ApprovalItem }) {
  const { message } = describeApproval(item);
  const pending = item.status === "pending";

  if (!pending) {
    return (
      <div className="flex items-center gap-2 text-xs text-ink-3">
        <IconShield size={13} className="shrink-0" />
        <span
          className={cx(
            "shrink-0 whitespace-nowrap",
            (item.status === "rejected" || item.status === "timeout") &&
              "text-warn",
          )}
        >
          {statusLabel(item.status)}
        </span>
        <span className="min-w-0 truncate">{message}</span>
      </div>
    );
  }

  // pending: passive placeholder - the controls live above the composer
  return (
    <div
      id={`approval-${item.approvalId}`}
      className="flex items-center gap-2.5 rounded-card border border-warn/30 bg-warn/5 px-4 py-2.5"
    >
      <IconShield size={14} className="shrink-0 text-warn" />
      <span className="min-w-0 flex-1 truncate text-xs text-ink-2">
        {message}
      </span>
      <span className="shrink-0 rounded-pill bg-warn/10 px-2 py-0.5 text-2xs text-warn">
        {t.approvalInComposer}
      </span>
    </div>
  );
}
