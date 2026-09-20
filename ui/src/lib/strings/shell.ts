/** Strings for the chat, composer, sidebar, project home and state modules.
 *  `en` is typed against `zh`: both must carry the same keys. */

export const zh = {
  // shared punctuation: full-width in Chinese, ASCII (with a leading space
  // before the bracket) in English
  colon: "：",
  paren: (s: string | number) => `（${s}）`,
  pair: (label: string, value: string) => `${label}：${value}`,

  // Composer: attachments, frames-directory insert, /status, /context, /skills, /rename
  composerFramesPrompt: (path: string, exts: string, totalMB: number) =>
    `原始衍射帧目录：${path}（${exts}，共 ${totalMB} MB）。请从 import_frames 开始分阶段还原，逐段汇报统计再前进。`,
  composerPastedImage: (stamp: string) => `粘贴图片-${stamp}.png`,
  statusModel: (model: string, provider: string) => `模型：${model}（${provider}）`,
  statusEffort: (effort: string, choices: string | null) =>
    `推理档位：${effort}${choices ? `，可选 ${choices}` : ""}`,
  statusPermission: (mode: string) => `权限：${mode}`,
  statusSubagents: (state: string) => `子代理：${state}`,
  statusKernel: (version: string, note: string | null) =>
    `内核：codex ${version}${note ? `（${note}）` : ""}`,
  statusThread: (id: string) => `对话：${id}`,
  statusProject: (path: string) => `项目：${path}`,
  ctxUsageLine: (used: string, total: string, pct: number, remaining: string) =>
    `${used} / ${total}（${pct}%）· ${remaining}`,
  skillLine: (name: string, disabled: boolean, description: string | null | undefined) =>
    `${name}${disabled ? "（已停用）" : ""}${description ? `：${description}` : ""}`,
  renameUsage: "/rename <名称>",

  // PermissionMenu: sub-agent switch state
  subagentsAutoOffAt: (effort: string) => `（${effort}档时开）`,

  // SlashPalette: keyboard hint
  paletteSelect: "选择",
  paletteComplete: "补全",

  // ShellCurve: resolution-shell plot
  shellCurveLabel: (dLo: string, dHi: string) => `分辨率壳层曲线，${dLo} 到 ${dHi} Å`,
  shellCurveFullScale: (max: string) => `（满刻度 ${max}）`,

  // GenericRow: detail summaries
  countItems: (n: number) => `${n} 项`,

  // StatusRail: stage tooltip
  railStageVisited: (label: string) => `${label} · 已进行`,

  // CommandCard: heading verb state around the humanised command label
  commandRunning: (label: string) => `正在${label}`,
  commandDone: (label: string) => `已${label}`,

  // FolderBrowser
  folderReadFailed: "无法读取文件夹",
  folderUp: "上一级文件夹",
  folderDefault: "默认项目目录",
  folderFilter: "筛选文件夹",
  folderFilterPlaceholder: "筛选文件夹…",
  folderLoading: "正在读取文件夹…",
  folderNoMatch: "没有匹配的文件夹",
  folderEmpty: "这里没有子文件夹，可以选择当前位置。",
  folderTruncated: "仅显示前 1000 个文件夹；也可以返回并直接输入完整路径。",
  folderBackToPath: "返回路径输入",
  folderChoose: "选择此文件夹",

  // OpenProjectDialog
  openFailed: "打开失败",
  closeProjectPicker: "关闭项目选择",

  // RightPane (the tab group label is also the selector CrystalProvider focuses)
  rightPaneTabs: "结构工作区页面",
  rightPaneAlertsTitle: (n: number) => `checkCIF A 级警报 ${n}`,

  // ProjectStatusBoard: relative time
  relJustNow: "刚刚",
  relMinutesAgo: (n: number) => `${n} 分钟前`,
  relHoursAgo: (n: number) => `${n} 小时前`,
  relDaysAgo: (n: number) => `${n} 天前`,
};

export const en: typeof zh = {
  // shared punctuation
  colon: ": ",
  paren: (s: string | number) => ` (${s})`,
  pair: (label: string, value: string) => `${label}: ${value}`,

  // Composer
  composerFramesPrompt: (path: string, exts: string, totalMB: number) =>
    `Raw diffraction frame directory: ${path} (${exts}, ${totalMB} MB in total). Start with import_frames and reduce the data stage by stage, reporting the statistics of each stage before moving on.`,
  composerPastedImage: (stamp: string) => `pasted-image-${stamp}.png`,
  statusModel: (model: string, provider: string) => `Model: ${model} (${provider})`,
  statusEffort: (effort: string, choices: string | null) =>
    `Reasoning effort: ${effort}${choices ? `, options ${choices}` : ""}`,
  statusPermission: (mode: string) => `Permissions: ${mode}`,
  statusSubagents: (state: string) => `Sub-agents: ${state}`,
  statusKernel: (version: string, note: string | null) =>
    `Kernel: codex ${version}${note ? ` (${note})` : ""}`,
  statusThread: (id: string) => `Conversation: ${id}`,
  statusProject: (path: string) => `Project: ${path}`,
  ctxUsageLine: (used: string, total: string, pct: number, remaining: string) =>
    `${used} / ${total} (${pct}%) · ${remaining}`,
  skillLine: (name: string, disabled: boolean, description: string | null | undefined) =>
    `${name}${disabled ? " (disabled)" : ""}${description ? `: ${description}` : ""}`,
  renameUsage: "/rename <name>",

  // PermissionMenu
  subagentsAutoOffAt: (effort: string) => ` (on at ${effort})`,

  // SlashPalette
  paletteSelect: "Select",
  paletteComplete: "Complete",

  // ShellCurve
  shellCurveLabel: (dLo: string, dHi: string) => `Resolution-shell curves, ${dLo} to ${dHi} Å`,
  shellCurveFullScale: (max: string) => ` (full scale ${max})`,

  // GenericRow
  countItems: (n: number) => `${n} ${n === 1 ? "item" : "items"}`,

  // StatusRail
  railStageVisited: (label: string) => `${label} · done`,

  // CommandCard
  commandRunning: (label: string) => `Running · ${label}`,
  commandDone: (label: string) => label,

  // FolderBrowser
  folderReadFailed: "Could not read the folder",
  folderUp: "Parent folder",
  folderDefault: "Default project directory",
  folderFilter: "Filter folders",
  folderFilterPlaceholder: "Filter folders…",
  folderLoading: "Reading folder…",
  folderNoMatch: "No matching folders",
  folderEmpty: "There are no subfolders here; you can choose the current location.",
  folderTruncated: "Only the first 1000 folders are shown; you can also go back and type the full path directly.",
  folderBackToPath: "Back to path entry",
  folderChoose: "Choose this folder",

  // OpenProjectDialog
  openFailed: "Could not open the project",
  closeProjectPicker: "Close project picker",

  // RightPane
  rightPaneTabs: "Structure workspace tabs",
  rightPaneAlertsTitle: (n: number) => `checkCIF level A alerts: ${n}`,

  // ProjectStatusBoard
  relJustNow: "just now",
  relMinutesAgo: (n: number) => `${n} ${n === 1 ? "minute" : "minutes"} ago`,
  relHoursAgo: (n: number) => `${n} ${n === 1 ? "hour" : "hours"} ago`,
  relDaysAgo: (n: number) => `${n} ${n === 1 ? "day" : "days"} ago`,
};
