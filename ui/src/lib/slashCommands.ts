/** Composer slash commands: what "/" offers, how a typed line parses, and
 * the Codex CLI command each one mirrors (the workbench keeps the kernel's
 * vocabulary so a Codex user needs no second one). Execution lives in the
 * composer; this module is pure so it can be unit-tested. */
import { t } from "./i18n";

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
  { name: "model", desc: t.libs.slashModel, codex: "/model" },
  { name: "effort", desc: t.libs.slashEffort, codex: "/model" },
  { name: "permissions", aliases: ["approvals"], desc: t.libs.slashPermissions, codex: "/permissions" },
  { name: "subagents", args: "on|off|auto", desc: t.libs.slashSubagents, codex: "/agent" },
  { name: "compact", desc: t.libs.slashCompact, codex: "/compact" },
  { name: "context", desc: t.libs.slashContext, codex: "/status" },
  { name: "status", desc: t.libs.slashStatus, codex: "/status" },
  { name: "mcp", desc: t.libs.slashMcp, codex: "/mcp" },
  { name: "skills", desc: t.libs.slashSkills, codex: "/skills" },
  { name: "new", desc: t.newThread, codex: "/new" },
  { name: "rename", args: t.libs.slashRenameArgs, desc: t.libs.slashRename, codex: "/rename" },
  { name: "fork", desc: t.libs.slashFork, codex: "/fork" },
  { name: "stop", desc: t.libs.slashStop, codex: "Ctrl+C" },
  { name: "settings", desc: t.libs.slashSettings, codex: "config.toml" },
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
