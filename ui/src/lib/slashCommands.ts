/** Composer slash commands: what "/" offers, how a typed line parses, and
 * the Codex CLI command each one mirrors (the workbench keeps the kernel's
 * vocabulary so a Codex user needs no second one). Execution lives in the
 * composer; this module is pure so it can be unit-tested. */

export interface SlashCommand {
  name: string;
  aliases?: string[];
  /** argument hint shown after the name, e.g. "<名称>" */
  args?: string;
  desc: string;
  /** the Codex CLI counterpart, shown dimmed on the right */
  codex?: string;
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { name: "model", desc: "选择模型", codex: "/model" },
  { name: "effort", desc: "选择推理档位", codex: "/model" },
  { name: "permissions", aliases: ["approvals"], desc: "权限模式", codex: "/permissions" },
  { name: "subagents", args: "on|off|auto", desc: "子代理开关", codex: "/agent" },
  { name: "compact", desc: "立即压缩上下文", codex: "/compact" },
  { name: "context", desc: "上下文窗口用量", codex: "/status" },
  { name: "status", desc: "当前状态：模型、提供方、档位、权限、内核", codex: "/status" },
  { name: "mcp", desc: "晶体学工具（MCP）状态", codex: "/mcp" },
  { name: "skills", desc: "已安装的技能", codex: "/skills" },
  { name: "new", desc: "新对话", codex: "/new" },
  { name: "rename", args: "<名称>", desc: "重命名当前对话", codex: "/rename" },
  { name: "fork", desc: "分叉当前对话（在当前提供方/模型上继续）", codex: "/fork" },
  { name: "stop", desc: "中断当前回合", codex: "Ctrl+C" },
  { name: "settings", desc: "打开设置：提供方、密钥、内核", codex: "config.toml" },
];

export interface ParsedSlash {
  name: string;
  args: string;
}

/** "/rename  My title" -> { name: "rename", args: "My title" }; null when
 * the text is not a single-line slash command. */
export function parseSlash(text: string): ParsedSlash | null {
  if (!text.startsWith("/")) return null;
  if (text.includes("\n")) return null;
  const m = /^\/([a-z][a-z0-9_-]*)\s*(.*)$/i.exec(text);
  if (!m) return null;
  return { name: m[1].toLowerCase(), args: m[2].trim() };
}

/** Commands matching the typed prefix (name or alias), in list order. */
export function filterSlash(query: string): SlashCommand[] {
  const q = query.trim().toLowerCase().replace(/^\//, "");
  if (q === "") return SLASH_COMMANDS;
  return SLASH_COMMANDS.filter(
    (c) => c.name.startsWith(q) || (c.aliases ?? []).some((a) => a.startsWith(q)),
  );
}

/** The command a typed name resolves to (exact name or alias). */
export function resolveSlash(name: string): SlashCommand | null {
  const n = name.toLowerCase();
  return (
    SLASH_COMMANDS.find((c) => c.name === n || (c.aliases ?? []).includes(n)) ?? null
  );
}

/** Is the draft in "command mode" (the palette should show)? Only while the
 * first line is being typed as a command. */
export function slashActive(text: string): boolean {
  return /^\/[a-z0-9_-]*$/i.test(text);
}
