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
const VERBS: Record<string, string> = {
  // crystallography executables
  shelxl: "运行 SHELXL 精修",
  shelxt: "运行 SHELXT 求解",
  shelxs: "运行 SHELXS 求解",
  platon: "运行 PLATON 检查",
  sadabs: "运行 SADABS 吸收校正",
  twinabs: "运行 TWINABS 吸收校正",
  // file reading / listing
  "get-content": "读取文件",
  type: "读取文件",
  cat: "读取文件",
  "get-childitem": "查看文件列表",
  gci: "查看文件列表",
  dir: "查看文件列表",
  ls: "查看文件列表",
  "get-item": "查看文件信息",
  "test-path": "检查路径",
  "resolve-path": "解析路径",
  "measure-object": "统计",
  "select-object": "筛选字段",
  "get-filehash": "计算文件校验和",
  head: "查看文件开头",
  tail: "查看文件末尾",
  // file writes / moves
  "set-content": "写入文件",
  "out-file": "写入文件",
  "add-content": "追加写入文件",
  "copy-item": "复制文件",
  copy: "复制文件",
  cp: "复制文件",
  xcopy: "复制文件",
  robocopy: "复制目录",
  "move-item": "移动文件",
  move: "移动文件",
  mv: "移动文件",
  "remove-item": "删除文件",
  del: "删除文件",
  rm: "删除文件",
  "new-item": "新建文件/目录",
  mkdir: "新建目录",
  md: "新建目录",
  "expand-archive": "解压文件",
  "compress-archive": "打包文件",
  tar: "解压/打包",
  "7z": "解压/打包",
  // search
  "select-string": "检索文本",
  findstr: "检索文本",
  rg: "检索文本",
  grep: "检索文本",
  // misc tooling
  git: "Git 操作",
  curl: "网络请求",
  wget: "下载文件",
  "invoke-webrequest": "网络请求",
  taskkill: "结束进程",
  "stop-process": "结束进程",
  "get-process": "查看进程",
  "set-location": "切换目录",
  cd: "切换目录",
  "write-output": "输出文本",
  echo: "输出文本",
  sed: "文本处理",
  awk: "文本处理",
  sort: "排序",
  wc: "统计行数",
};

const PY_NAMES = new Set(["python", "python3", "py", "pythonw"]);

/** Tokenize enough of a PS/cmd one-liner to find the acting executable:
 * skips `$var = …` assignments and call operators, unquotes paths. */
function findActor(inner: string): { name: string; verb: string; rest: string[] } | null {
  // statements split on ; then scan each for the first recognizable actor
  for (const stmt of inner.split(/[;|]/)) {
    const t = stmt.trim();
    if (t === "") continue;
    // skip pure variable assignment prefix: `$p = <expr>` -> scan expr
    const body = t.replace(/^\$\w+\s*=\s*/, "").trim();
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
            ? "调用 CrystalPilot 组件"
            : `运行 Python 模块 ${mod}`,
          rest: [],
        };
      }
      if (rest.includes("-c")) return { name, verb: "运行 Python 片段", rest: [] };
      const script = rest.find((x) => /\.py['"]?$/i.test(x));
      return {
        name,
        verb: "运行 Python 脚本",
        rest: script !== undefined ? [script] : [],
      };
    }
    if (name.startsWith("dials.")) {
      return { name, verb: `运行 DIALS（${name.slice(6)}）`, rest: [] };
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
      label: `运行命令：${head}${inner.length > 60 ? "…" : ""}`,
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
