/** Shell-command translation layer (调研 P0-1).
 *
 * On Windows the engine wraps EVERY agent shell in
 * `"…\powershell.exe" -Command '…'` with layered quote escaping - raw
 * command lines are unreadable to crystallographers. This module unwraps
 * the host shell and maps the first recognizable executable / cmdlet to a
 * short Chinese action phrase; the raw command stays available in the
 * expandable details. Unknown commands degrade to a trimmed one-liner,
 * never to nothing.
 */
import { t } from "./i18n";

export interface HumanCommand {
  /** One-line zh action phrase, e.g. "运行 SHELXL 精修 · job.ins". */
  label: string;
  /** Command with the host shell wrapper stripped. */
  inner: string;
  /** True when the verb dictionary matched (vs. generic fallback). */
  recognized: boolean;
}

/** Strip PowerShell, cmd and POSIX shell command wrappers for presentation. */
export function unwrapCommand(raw: string): string {
  let s = raw.trim();
  const ps = s.match(
    /^"?[^"]*powershell(?:\.exe)?"?\s+(?:-NoProfile\s+|-NoLogo\s+|-ExecutionPolicy\s+\S+\s+)*-(?:Command|c)\s+([\s\S]+)$/i,
  );
  if (ps) {
    s = ps[1].trim();
  } else {
    const cmd = s.match(/^"?cmd(?:\.exe)?"?\s+(?:\/[a-z]+(?::\w+)?\s+)*\/c\s+([\s\S]+)$/i);
    if (cmd) s = cmd[1].trim();
    else {
      const sh = s.match(/^(?:["']?(?:\/[^\s"']*\/)?(?:bash|sh|zsh)["']?)\s+(?:--(?:noprofile|norc)\s+)*-[a-z]*c\s+([\s\S]+)$/i);
      if (sh) s = sh[1].trim();
    }
  }
  // one layer of symmetric outer quotes around the whole payload
  if (
    s.length >= 2 &&
    ((s.startsWith("'") && s.endsWith("'")) ||
      (s.startsWith('"') && s.endsWith('"')))
  ) {
    s = s.slice(1, -1).trim();
  }
  return s;
}

/** basename without quotes/extension noise, capped for display. */
function basename(p: string): string {
  const clean = p.replace(/^['"]+|['"]+$/g, "");
  const seg = clean.split(/[\\/]/).filter((x) => x !== "");
  const last = seg.at(-1) ?? clean;
  return last.length > 40 ? `${last.slice(0, 40)}…` : last;
}

/** exe/cmdlet (lowercased, no .exe) -> action phrase. */
const VERBS: Record<string, string> = t.libs.cmdVerbs;

const PY_NAMES = new Set(["python", "python3", "py", "pythonw"]);

/** Tokenize enough of a PS/cmd one-liner to find the acting executable:
 * skips `$var = …` assignments and call operators, unquotes paths. */
function findActor(inner: string): { name: string; verb: string; rest: string[] } | null {
  // statements split on ; then scan each for the first recognizable actor
  for (const stmt of inner.split(/[;|]/)) {
    const text = stmt.trim();
    if (text === "") continue;
    // skip pure variable assignment prefix: `$p = <expr>` -> scan expr
    const body = text.replace(/^\$\w+\s*=\s*/, "").trim();
    const tokens = body.match(/(?:"[^"]*"|'[^']*'|\S)+/g) ?? [];
    let i = 0;
    if (tokens[i] === "&" || tokens[i] === ".") i += 1; // call operator
    const first = tokens[i];
    if (first === undefined) continue;
    const name = basename(first).toLowerCase().replace(/\.(exe|bat|cmd|ps1)$/, "");
    if (name.startsWith("$")) continue; // variable-invoked: unknowable
    if (PY_NAMES.has(name)) {
      const rest = tokens.slice(i + 1).filter((x) => !x.startsWith("-X"));
      const mi = rest.indexOf("-m");
      if (mi >= 0 && rest[mi + 1] !== undefined) {
        const mod = rest[mi + 1];
        return {
          name,
          verb: mod.startsWith("crystalpilot")
            ? t.libs.cmdPyCrystalpilot
            : t.libs.cmdPyModule(mod),
          rest: [],
        };
      }
      if (rest.includes("-c")) return { name, verb: t.libs.cmdPySnippet, rest: [] };
      const script = rest.find((x) => /\.py['"]?$/i.test(x));
      return {
        name,
        verb: t.libs.cmdPyScript,
        rest: script !== undefined ? [script] : [],
      };
    }
    if (name.startsWith("dials.")) {
      return { name, verb: t.libs.cmdDials(name.slice(6)), rest: [] };
    }
    const verb = VERBS[name];
    if (verb !== undefined) return { name, verb, rest: tokens.slice(i + 1) };
    // unrecognized first actor in this statement: try next statement
  }
  return null;
}

/** Same actor as the caption, never a keyword found in command arguments. */
export function commandActor(raw: string): string | null {
  return findActor(unwrapCommand(raw))?.name ?? null;
}

/** First path-looking argument -> display object (basename). */
function firstObject(rest: string[]): string | null {
  for (const tok of rest) {
    if (tok.startsWith("-")) continue;
    const clean = tok.replace(/^['"]+|['"]+$/g, "");
    if (clean === "" || clean.startsWith("$") || clean.startsWith("@")) continue;
    if (/[\\/.]/.test(clean)) return basename(clean);
  }
  return null;
}

export function humanizeCommand(raw: string): HumanCommand {
  const inner = unwrapCommand(raw);
  const actor = findActor(inner);
  if (actor === null) {
    const head = inner.replace(/\s+/g, " ").slice(0, 60);
    return {
      label: t.libs.cmdRun(head, inner.length > 60),
      inner,
      recognized: false,
    };
  }
  const obj = firstObject(actor.rest);
  const multi = /[;|]/.test(inner);
  return {
    label: `${actor.verb}${obj !== null ? ` · ${obj}` : ""}${multi ? " …" : ""}`,
    inner,
    recognized: true,
  };
}
