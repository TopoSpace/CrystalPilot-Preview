/** Floating rounded composer card (Codex style): auto-growing textarea
 * (Enter = send, Shift+Enter = newline), + attach, permission chip with the
 * slim mode menu, the model BUTTON (model / effort / provider popover), the
 * context ring, send/stop circle. While a turn is active the input stays
 * enabled and submit routes to steer (插话).
 *
 * "/" opens the command palette (↑/↓, Tab, Enter, Esc); commands mirror the
 * Codex CLI (/model /compact /status /mcp …) and act on the kernel through
 * the same API the settings use, so the CLI and the browser never disagree.
 *
 * Attachments: paste (clipboard images), drag-drop anywhere on the page, or
 * the + menu. Files upload eagerly into <project>/uploads/ and render as
 * removable chips; the message carries {rel, kind} refs - the server feeds
 * images to the model as true multimodal input and extracts text from
 * PDF/Word. */
import { clickedOutside } from "../../lib/outsideClick";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ClipboardEvent,
  type KeyboardEvent,
} from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AlertBanner, Spinner } from "../../components/ui";
import { cx, fmtTokens } from "../../lib/format";
import { anchorTokens, removeAnchorToken, type AnchorToken } from "../../lib/quote";
import {
  filterSlash,
  parseSlash,
  resolveSlash,
  slashActive,
  type SlashCommand,
} from "../../lib/slashCommands";
import {
  compactThread,
  forkThread,
  listSkills,
  mcpStatus,
  probeFramesDir,
  renameThread,
  uploadFiles,
  type FramesProbe,
} from "../../lib/wbApi";
import type { AttachmentRef, SubagentMode } from "../../lib/wbTypes";
import { formatEffort, permissionLabel, zh } from "../../lib/zh";
import { useComposerDraft } from "../../state/ComposerDraft";
import { useThreadOptional } from "../../state/ThreadProvider";
import { useWorkbench } from "../../state/WorkbenchProvider";
import {
  IconChevronDown,
  IconFile,
  IconFolder,
  IconPlus,
  IconSend,
  IconShield,
  IconStop,
  IconX,
} from "../icons";
import { projectHomeUrl, threadUrl } from "../urls";
import { ContextMeter } from "./ContextMeter";
import { ModelMenu, modelDisplayName, type ModelMenuFocus } from "./ModelMenu";
import { PermissionMenu, subagentStateText } from "./PermissionMenu";
import { SlashPalette } from "./SlashPalette";

const MAX_TEXTAREA_PX = 220;
const MAX_ATTACHMENTS = 8;
const MAX_FILE_BYTES = 50 * 1024 * 1024;
const IMAGE_EXT = /\.(png|jpe?g|gif|webp|bmp)$/i;

let draftCounter = 0;

/** One composer attachment: uploads eagerly, renders as a removable chip. */
interface AttachmentDraft {
  id: string;
  name: string;
  status: "uploading" | "ready" | "error";
  /** server-confirmed values (ready only) */
  rel?: string;
  kind?: string;
  /** object URL thumbnail for image files (revoked on remove/send) */
  previewUrl?: string;
  error?: string;
  /** kept for retry after a failed upload */
  file?: File;
}

interface ComposerProps {
  /** Returns an error message, or null on success. */
  onSend: (
    text: string,
    attachments?: AttachmentRef[],
  ) => Promise<string | null>;
  onSteer?: (
    text: string,
    attachments?: AttachmentRef[],
  ) => Promise<string | null>;
  onStop?: () => void;
  turnActive?: boolean;
  autoFocus?: boolean;
}

/** Quote chips (round-3 R6): every `[anchor …]` in the draft, removable;
 * the text stays the source of truth (plain-text fallback). */
function AnchorRail({
  anchors,
  onRemove,
}: {
  anchors: AnchorToken[];
  onRemove: (token: string) => void;
}) {
  if (anchors.length === 0) return null;
  return (
    <div
      role="group"
      aria-label={zh.anchorRailLabel}
      data-testid="anchor-rail"
      className="flex flex-wrap gap-1.5 px-3.5 pt-3"
    >
      {anchors.map((a, i) => (
        <span
          key={`${a.token}-${i}`}
          className="inline-flex max-w-[260px] items-center gap-1 rounded-pill border border-line bg-raised/60 pl-2 pr-1 font-mono text-2xs text-ink-2"
          title={a.token}
        >
          <span className="text-ink-3">{zh.anchorChip}</span>
          {a.node && <span>{a.node}</span>}
          {a.atoms.length > 0 && <span className="truncate">{a.atoms.join(" ")}</span>}
          <button
            type="button"
            aria-label={zh.anchorRemove}
            title={zh.anchorRemove}
            onClick={() => onRemove(a.token)}
            className="ml-0.5 flex h-4 w-4 items-center justify-center rounded-full text-ink-3 hover:bg-raised hover:text-ink"
          >
            <IconX size={10} />
          </button>
        </span>
      ))}
    </div>
  );
}

/** Removable attachment chips above the textarea: image thumbnails, file
 * chips, per-item upload state (spinner / error + retry). */
function AttachmentRail({
  drafts,
  onRemove,
  onRetry,
}: {
  drafts: AttachmentDraft[];
  onRemove: (id: string) => void;
  onRetry: (id: string) => void;
}) {
  if (drafts.length === 0) return null;
  return (
    <div
      role="group"
      aria-label={zh.attachedPrefix}
      className="flex flex-wrap gap-1.5 px-3.5 pt-3"
    >
      {drafts.map((d) => (
        <div
          key={d.id}
          className={cx(
            "group relative flex items-center overflow-hidden rounded-xl border",
            d.status === "error"
              ? "border-danger/60 bg-danger/5"
              : "border-line bg-raised/60",
          )}
          title={d.status === "error" ? `${d.name}：${d.error}` : d.name}
        >
          {d.previewUrl ? (
            <img
              src={d.previewUrl}
              alt={d.name}
              className="h-12 w-12 object-cover"
            />
          ) : (
            <span className="flex h-9 max-w-[180px] items-center gap-1.5 px-2.5">
              <IconFile size={14} className="shrink-0 text-ink-3" />
              <span className="truncate text-xs text-ink-2">{d.name}</span>
            </span>
          )}
          {d.status === "uploading" && (
            <span className="absolute inset-0 flex items-center justify-center bg-bg/60">
              <Spinner className="h-3.5 w-3.5" />
            </span>
          )}
          {d.status === "error" && (
            <button
              type="button"
              onClick={() => onRetry(d.id)}
              className="px-1.5 text-2xs font-medium text-danger hover:underline"
            >
              {zh.attachRetry}
            </button>
          )}
          <button
            type="button"
            aria-label={`${zh.attachRemove}：${d.name}`}
            onClick={() => onRemove(d.id)}
            className={cx(
              "flex h-4.5 w-4.5 shrink-0 items-center justify-center rounded-pill bg-ink/70 text-bg transition-opacity hover:bg-ink",
              d.previewUrl
                ? "absolute top-0.5 right-0.5 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"
                : "mr-1.5",
            )}
          >
            <IconX size={10} />
          </button>
        </div>
      ))}
    </div>
  );
}

/** "+" menu: upload small files, or reference a raw-frames DIRECTORY by
 * path (frames stay on disk - thousands of images must not go through an
 * upload; import_frames reads them in place). The path is validated
 * server-side and inserted into the draft as a structured line. */
function AttachMenu({
  onUpload,
  onInsert,
  onClose,
}: {
  onUpload: () => void;
  onInsert: (line: string) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [framesMode, setFramesMode] = useState(false);
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [probe, setProbe] = useState<FramesProbe | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (clickedOutside(ref.current, e)) onClose();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [onClose]);

  const doProbe = async () => {
    const p = path.trim();
    if (p === "" || busy) return;
    setBusy(true);
    setError(null);
    setProbe(null);
    try {
      setProbe(await probeFramesDir(p));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const doInsert = () => {
    if (!probe) return;
    const exts = Object.entries(probe.by_ext)
      .map(([k, v]) => `${v}×${k}`)
      .join(" + ");
    onInsert(
      `原始衍射帧目录：${probe.path}（${exts}，共 ${probe.total_MB} MB）。` +
        `请从 import_frames 开始分阶段还原，逐段汇报统计再前进。`,
    );
    onClose();
  };

  return (
    <div
      ref={ref}
      className="absolute bottom-full left-0 z-30 mb-2 w-[340px] rounded-card border border-line bg-bg p-1.5 shadow-xl"
    >
      {!framesMode ? (
        <>
          <button
            type="button"
            onClick={() => {
              onClose();
              onUpload();
            }}
            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm text-ink transition-colors hover:bg-raised"
          >
            <IconPlus size={14} className="text-ink-3" />
            {zh.attachUpload}
          </button>
          <button
            type="button"
            onClick={() => setFramesMode(true)}
            className="flex w-full flex-col gap-0.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-raised"
          >
            <span className="flex items-center gap-2 text-sm text-ink">
              <IconFolder size={14} className="text-ink-3" />
              {zh.attachFramesDir}
            </span>
            <span className="pl-[22px] text-2xs leading-snug text-ink-3">
              {zh.attachFramesDirDesc}
            </span>
          </button>
        </>
      ) : (
        <div className="flex flex-col gap-2 p-2">
          <div className="text-xs font-medium text-ink-2">
            {zh.attachFramesDir}
          </div>
          <div className="flex gap-1.5">
            <input
              value={path}
              onChange={(e) => setPath(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void doProbe();
              }}
              placeholder={zh.framesDirPlaceholder}
              autoFocus
              className="h-8 min-w-0 flex-1 rounded-lg border border-line bg-transparent px-2.5 font-mono text-xs text-ink outline-none placeholder:text-ink-3 focus:border-accent"
            />
            <button
              type="button"
              disabled={busy || path.trim() === ""}
              onClick={() => void doProbe()}
              className="h-8 shrink-0 rounded-lg border border-line px-2.5 text-xs font-medium text-ink transition-colors hover:bg-raised disabled:opacity-40"
            >
              {busy ? <Spinner className="h-3 w-3" /> : zh.framesProbe}
            </button>
          </div>
          {error !== null && (
            <div className="text-2xs leading-snug text-danger">{error}</div>
          )}
          {probe !== null && (
            <div className="flex flex-col gap-1.5">
              <div className="text-2xs leading-snug text-ink-2">
                {probe.ok
                  ? `${probe.n_frames} ${zh.framesFound} · ${probe.total_MB} MB · ${probe.sample.join(", ")}…`
                  : (probe.note ?? zh.framesNone)}
              </div>
              {probe.ok && (
                <button
                  type="button"
                  onClick={doInsert}
                  className="h-7 self-start rounded-lg bg-ink px-3 text-xs font-medium text-bg transition-opacity hover:opacity-85"
                >
                  {zh.framesInsert}
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Slash-command output when there is no thread to put a card into
 * (project home): a dismissible note above the composer. */
function LocalNote({
  note,
  onClose,
}: {
  note: { title: string; lines: string[] };
  onClose: () => void;
}) {
  return (
    <div
      data-testid="note-row"
      className="mb-2 rounded-card border border-line bg-surface/60 px-3.5 py-2.5 text-xs text-ink-2"
    >
      <div className="mb-1 flex items-center justify-between">
        <span className="text-2xs font-medium text-ink-3">{note.title}</span>
        <button
          type="button"
          aria-label={zh.settingsClose}
          onClick={onClose}
          className="flex h-4 w-4 items-center justify-center rounded-full text-ink-3 hover:bg-raised hover:text-ink"
        >
          <IconX size={10} />
        </button>
      </div>
      <div className="flex flex-col gap-0.5 font-mono text-2xs leading-relaxed">
        {note.lines.map((ln, i) => (
          <div key={i} className="break-all">
            {ln}
          </div>
        ))}
      </div>
    </div>
  );
}

export function Composer({
  onSend,
  onSteer,
  onStop,
  turnActive = false,
  autoFocus = false,
}: ComposerProps) {
  const wb = useWorkbench();
  const thread = useThreadOptional();
  const navigate = useNavigate();
  const { threadId } = useParams<{ threadId: string }>();
  const [text, setText] = useState("");
  const anchors = useMemo(() => anchorTokens(text), [text]);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [modelFocus, setModelFocus] = useState<ModelMenuFocus>("model");
  const [attachOpen, setAttachOpen] = useState(false);
  const [attachments, setAttachments] = useState<AttachmentDraft[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [localNote, setLocalNote] = useState<{ title: string; lines: string[] } | null>(null);
  const [slashIndex, setSlashIndex] = useState(0);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const draft = useComposerDraft();

  useEffect(() => {
    if (autoFocus) taRef.current?.focus();
  }, [autoFocus]);

  // ------------------------------------------------------------ attachments
  const projectPath = wb.projectPath;
  const attachmentsRef = useRef(attachments);
  attachmentsRef.current = attachments;

  const uploadOne = useCallback(
    (id: string, file: File) => {
      if (!projectPath) return;
      void uploadFiles(projectPath, [file])
        .then((res) => {
          const up = res.files[0];
          setAttachments((prev) =>
            prev.map((d) =>
              d.id === id
                ? {
                    ...d,
                    status: "ready",
                    rel: up.rel,
                    kind: up.kind,
                    name: up.name || d.name,
                    file: undefined,
                  }
                : d,
            ),
          );
        })
        .catch((e: unknown) => {
          setAttachments((prev) =>
            prev.map((d) =>
              d.id === id
                ? {
                    ...d,
                    status: "error",
                    error:
                      e instanceof Error ? e.message : zh.attachUploadFailed,
                  }
                : d,
            ),
          );
        });
    },
    [projectPath],
  );

  const intakeFiles = useCallback(
    (files: File[]) => {
      if (files.length === 0 || !projectPath) return;
      // whole-batch validation: never partially add (no submit-time surprises)
      if (attachmentsRef.current.length + files.length > MAX_ATTACHMENTS) {
        setError(zh.attachTooMany);
        return;
      }
      const oversize = files.find((f) => f.size > MAX_FILE_BYTES);
      if (oversize) {
        setError(`${oversize.name}：${zh.attachTooLarge}`);
        return;
      }
      setError(null);
      const drafts = files.map((f): AttachmentDraft => {
        draftCounter += 1;
        const isImage =
          f.type.startsWith("image/") || IMAGE_EXT.test(f.name);
        // clipboard screenshots arrive as generic "image.png" - stamp them
        const name =
          f.name && f.name !== "image.png"
            ? f.name
            : `粘贴图片-${new Date().toTimeString().slice(0, 8).replaceAll(":", "")}.png`;
        return {
          id: `att${draftCounter}`,
          name,
          status: "uploading",
          previewUrl: isImage ? URL.createObjectURL(f) : undefined,
          file: f,
        };
      });
      setAttachments((prev) => [...prev, ...drafts]);
      drafts.forEach((d, i) => {
        const f = files[i];
        const named =
          f.name === d.name ? f : new File([f], d.name, { type: f.type });
        uploadOne(d.id, named);
      });
    },
    [projectPath, uploadOne],
  );

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => {
      const target = prev.find((d) => d.id === id);
      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((d) => d.id !== id);
    });
  }, []);

  const retryAttachment = useCallback(
    (id: string) => {
      const target = attachmentsRef.current.find((d) => d.id === id);
      if (!target?.file) return;
      setAttachments((prev) =>
        prev.map((d) =>
          d.id === id ? { ...d, status: "uploading", error: undefined } : d,
        ),
      );
      uploadOne(id, target.file);
    },
    [uploadOne],
  );

  // revoke thumbnail object URLs when the composer unmounts
  useEffect(
    () => () => {
      for (const d of attachmentsRef.current) {
        if (d.previewUrl) URL.revokeObjectURL(d.previewUrl);
      }
    },
    [],
  );

  const onPaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    const files: File[] = [];
    for (const item of e.clipboardData?.items ?? []) {
      if (item.kind === "file") {
        const f = item.getAsFile();
        if (f) files.push(f);
      }
    }
    if (files.length > 0) {
      // consume the file part; plain-text pastes fall through untouched
      e.preventDefault();
      intakeFiles(files);
    }
  };

  // page-level drag-drop with a depth counter (nested dragenter/leave would
  // flicker a naive boolean); gated on real OS file drags
  useEffect(() => {
    if (!projectPath) return undefined;
    let depth = 0;
    const hasFiles = (e: globalThis.DragEvent) =>
      Array.from(e.dataTransfer?.types ?? []).includes("Files");
    const onEnter = (e: globalThis.DragEvent) => {
      if (!hasFiles(e)) return;
      depth += 1;
      setDragOver(true);
    };
    const onLeave = (e: globalThis.DragEvent) => {
      if (!hasFiles(e)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setDragOver(false);
    };
    const onOver = (e: globalThis.DragEvent) => {
      if (hasFiles(e)) e.preventDefault();
    };
    const onDrop = (e: globalThis.DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth = 0;
      setDragOver(false);
      intakeFiles(Array.from(e.dataTransfer?.files ?? []));
    };
    document.addEventListener("dragenter", onEnter);
    document.addEventListener("dragleave", onLeave);
    document.addEventListener("dragover", onOver);
    document.addEventListener("drop", onDrop);
    return () => {
      document.removeEventListener("dragenter", onEnter);
      document.removeEventListener("dragleave", onLeave);
      document.removeEventListener("dragover", onOver);
      document.removeEventListener("drop", onDrop);
    };
  }, [projectPath, intakeFiles]);

  const uploadsPending = attachments.some((d) => d.status === "uploading");
  const readyAttachments = attachments.filter(
    (d): d is AttachmentDraft & { rel: string } =>
      d.status === "ready" && d.rel !== undefined,
  );

  // crystal-pane snippet requests (在对话中引用 / 检出) append to the draft
  const pendingInsert = draft.pending;
  useEffect(() => {
    if (pendingInsert === null) return;
    setText((t) =>
      t.trim() === "" ? pendingInsert.text : `${t.trimEnd()}\n${pendingInsert.text}`,
    );
    draft.consume();
    requestAnimationFrame(() => {
      autoGrow();
      taRef.current?.focus();
    });
    // autoGrow is stable (closure over refs only)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingInsert]);

  // the viewer hands over a rendered frame the same way the + menu hands
  // over a file, so it inherits the whole path: size/count validation,
  // eager upload, thumbnail chip, retry on failure
  const pendingFiles = draft.pendingFiles;
  useEffect(() => {
    if (pendingFiles === null) return;
    intakeFiles(pendingFiles.files);
    draft.consumeFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingFiles]);

  const autoGrow = () => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, MAX_TEXTAREA_PX)}px`;
  };

  const submit = async () => {
    const trimmed = text.trim();
    const hasAtts = readyAttachments.length > 0;
    if ((trimmed === "" && !hasAtts) || sending) return;
    if (uploadsPending) {
      setError(zh.attachWaitUploading);
      return;
    }
    setSending(true);
    setError(null);
    const refs: AttachmentRef[] | undefined = hasAtts
      ? readyAttachments.map((d) => ({
          rel: d.rel,
          kind: d.kind ?? "other",
          name: d.name,
        }))
      : undefined;
    const fn = turnActive && onSteer ? onSteer : onSend;
    const err = await fn(trimmed, refs);
    setSending(false);
    if (err === null) {
      setText("");
      for (const d of attachmentsRef.current) {
        if (d.previewUrl) URL.revokeObjectURL(d.previewUrl);
      }
      setAttachments([]);
      requestAnimationFrame(autoGrow);
    } else {
      setError(err);
    }
  };

  // ---------------------------------------------------------- slash commands
  const slashMode = slashActive(text);
  const slashItems = useMemo(() => (slashMode ? filterSlash(text) : []), [slashMode, text]);
  useEffect(() => {
    setSlashIndex(0);
  }, [text]);

  const showNote = useCallback(
    (title: string, lines: string[]) => {
      if (thread) thread.note(title, lines);
      else setLocalNote({ title, lines });
    },
    [thread],
  );

  const statusLines = (): string[] => {
    const s = wb.settings;
    const lines: string[] = [];
    lines.push(`模型：${s?.model ?? "—"}（${s?.model_provider ?? "—"}）`);
    lines.push(
      `推理档位：${s?.effort ? `${formatEffort(s.effort)} ${s.effort}` : zh.effortNoneLabel}` +
        (s?.effort_choices?.length ? `，可选 ${s.effort_choices.join(" / ")}` : ""),
    );
    lines.push(`权限：${permissionLabel(s?.permission_mode ?? "auto")}`);
    lines.push(
      `子代理：${subagentStateText(s?.subagents ?? "auto", s?.delegation?.active ?? false, s?.delegation?.top_effort)}`,
    );
    if (s?.engine?.kernel_version) {
      lines.push(
        `内核：codex ${s.engine.kernel_version}${s.engine.restart_pending ? `（${zh.modelRestartPending}）` : ""}`,
      );
    }
    if (threadId) lines.push(`对话：${threadId}`);
    if (wb.projectPath) lines.push(`项目：${wb.projectPath}`);
    return lines;
  };

  const contextLines = (): string[] => {
    const u = thread?.state.usage ?? null;
    const lines: string[] = [];
    const win = u?.contextWindow ?? wb.settings?.engine?.context_window ?? null;
    if (!u?.total) {
      lines.push(win ? `${zh.ctxTipTotal} ${fmtTokens(win)}` : zh.ctxTipNoWindow);
    } else {
      const cur = u.last ?? u.total;
      const used = cur.input_tokens + cur.output_tokens;
      lines.push(
        win
          ? `${zh.ctxTipUsed} ${fmtTokens(used)} / ${zh.ctxTipTotal} ${fmtTokens(win)}（${Math.round((used / win) * 100)}%）· ${zh.ctxTipRemaining} ${fmtTokens(Math.max(0, win - used))}`
          : `${zh.ctxTipUsed} ${fmtTokens(used)}（${zh.ctxTipNoWindow}）`,
      );
      lines.push(`${zh.tokensUsed} ${fmtTokens(u.total.input_tokens + u.total.output_tokens)}`);
    }
    const lim = wb.settings?.engine?.auto_compact_limit ?? wb.settings?.auto_compact_token_limit ?? null;
    if (lim) lines.push(`${zh.ctxAutoCompact} ${fmtTokens(lim)}`);
    lines.push(zh.ctxTipCompaction);
    return lines;
  };

  const runSlash = async (name: string, args: string) => {
    const cmd = resolveSlash(name);
    setText("");
    requestAnimationFrame(autoGrow);
    if (!cmd) {
      showNote(zh.noteUnknownCommand, [`/${name}`]);
      return;
    }
    const project = wb.projectPath;
    const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));
    switch (cmd.name) {
      case "model":
        setModelFocus("model");
        setModelOpen(true);
        return;
      case "effort":
        setModelFocus("effort");
        setModelOpen(true);
        return;
      case "permissions":
        setMenuOpen(true);
        return;
      case "subagents": {
        const a = args.trim().toLowerCase();
        if (a === "on" || a === "off" || a === "auto") {
          const err = await wb.changeSubagents(a as SubagentMode);
          if (err !== null) setError(err);
        } else {
          setMenuOpen(true);
        }
        return;
      }
      case "compact":
        if (!threadId) {
          showNote(zh.noteNeedThread, [`/${cmd.name}`]);
          return;
        }
        try {
          await compactThread(threadId, project);
        } catch (e) {
          fail(e);
        }
        return;
      case "context":
        showNote(zh.noteContextTitle, contextLines());
        return;
      case "status":
        showNote(zh.noteStatusTitle, statusLines());
        return;
      case "mcp": {
        if (!project) return;
        try {
          const r = await mcpStatus(project);
          showNote(
            zh.noteMcpTitle,
            r.present
              ? [`${r.n_tools} ${zh.sysMcpToolsUnit}`, ...(r.error ? [r.error] : [])]
              : [zh.noteMcpAbsent],
          );
        } catch (e) {
          fail(e);
        }
        return;
      }
      case "skills": {
        if (!project) return;
        try {
          const r = await listSkills(project);
          const lines = r.skills
            .filter((s) => s.name)
            .map(
              (s) =>
                `${s.name}${s.enabled === false ? "（已停用）" : ""}${s.description ? `：${s.description}` : ""}`,
            );
          showNote(zh.noteSkillsTitle, lines.length > 0 ? lines : [zh.noteNoSkills]);
        } catch (e) {
          fail(e);
        }
        return;
      }
      case "new":
        if (project) navigate(projectHomeUrl(project));
        return;
      case "rename": {
        if (!threadId) {
          showNote(zh.noteNeedThread, [`/${cmd.name}`]);
          return;
        }
        const title = args.trim();
        if (title === "") {
          showNote(zh.renameThread, ["/rename <名称>"]);
          return;
        }
        try {
          await renameThread(threadId, title, project);
          void wb.refreshThreads();
          showNote(zh.noteRenamed, [title]);
        } catch (e) {
          fail(e);
        }
        return;
      }
      case "fork": {
        if (!threadId || !project) {
          showNote(zh.noteNeedThread, [`/${cmd.name}`]);
          return;
        }
        try {
          const r = await forkThread(threadId, project);
          void wb.refreshThreads();
          navigate(threadUrl(r.thread_id, project));
        } catch (e) {
          fail(e);
        }
        return;
      }
      case "stop":
        onStop?.();
        return;
      case "settings":
        wb.openSettings();
        return;
      default:
        return;
    }
  };

  const completeSlash = (cmd: SlashCommand) => {
    setText(`/${cmd.name}${cmd.args ? " " : ""}`);
    requestAnimationFrame(() => taRef.current?.focus());
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing) return;
    if (slashMode) {
      const n = slashItems.length;
      if (e.key === "ArrowDown" && n > 0) {
        e.preventDefault();
        setSlashIndex((i) => (i + 1) % n);
        return;
      }
      if (e.key === "ArrowUp" && n > 0) {
        e.preventDefault();
        setSlashIndex((i) => (i - 1 + n) % n);
        return;
      }
      if (e.key === "Tab" && n > 0) {
        e.preventDefault();
        completeSlash(slashItems[slashIndex] ?? slashItems[0]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setText("");
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        const chosen = slashItems[slashIndex] ?? slashItems[0];
        if (chosen) void runSlash(chosen.name, "");
        else void runSlash(text.slice(1), "");
        return;
      }
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const parsed = parseSlash(text.trim());
      if (parsed) {
        void runSlash(parsed.name, parsed.args);
        return;
      }
      void submit();
    }
  };

  const onPickFiles = (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    intakeFiles(files);
  };

  const pickMode = async (mode: string) => {
    setMenuOpen(false);
    const err = await wb.changePermissionMode(mode);
    if (err !== null) setError(err);
  };

  const s = wb.settings;
  const mode = s?.permission_mode ?? "auto";
  const modelName = modelDisplayName(s?.model, s?.model_info?.display_name);
  const effortLabel = formatEffort(s?.effort);
  const restartPending = s?.engine?.restart_pending === true;
  const hasText = text.trim() !== "";
  const hasContent = hasText || readyAttachments.length > 0;
  const showStop = turnActive && !hasContent;

  return (
    <div className="relative" data-testid="composer">
      {localNote !== null && (
        <LocalNote note={localNote} onClose={() => setLocalNote(null)} />
      )}
      {slashMode && (
        <SlashPalette
          items={slashItems}
          index={slashIndex}
          onHover={setSlashIndex}
          onPick={(cmd) => void runSlash(cmd.name, "")}
        />
      )}
      <div className="rounded-[22px] border border-line/80 bg-bg shadow-[0_3px_20px_rgba(0,0,0,0.035)] dark:shadow-[0_3px_20px_rgba(0,0,0,0.2)]">
        {dragOver && (
          <div
            role="status"
            className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center bg-bg/70 backdrop-blur-[2px]"
          >
            <div className="rounded-card border-2 border-dashed border-accent bg-bg px-8 py-6 text-center shadow-xl">
              <div className="text-md font-medium text-ink">
                {zh.dropToAttach}
              </div>
              <div className="mt-1 text-xs text-ink-3">
                {zh.attachImageHint}
              </div>
            </div>
          </div>
        )}
        <AttachmentRail
          drafts={attachments}
          onRemove={removeAttachment}
          onRetry={retryAttachment}
        />
        <AnchorRail
          anchors={anchors}
          onRemove={(token) => {
            setText((t) => removeAnchorToken(t, token));
            requestAnimationFrame(autoGrow);
          }}
        />
        <textarea
          ref={taRef}
          rows={1}
          value={text}
          placeholder={zh.composerPlaceholder}
          aria-label={zh.composerPlaceholder}
          onChange={(e) => {
            setText(e.target.value);
            autoGrow();
          }}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
          className="block max-h-[220px] w-full resize-none bg-transparent px-4 pt-3.5 pb-1 text-base leading-[1.5] text-ink outline-none placeholder:text-ink-3"
        />
        <div className="flex items-center gap-2 px-2.5 pt-1 pb-2.5">
          {/* attach */}
          <div className="relative">
            <button
              type="button"
              title={zh.attach}
              aria-label={zh.attach}
              disabled={!wb.projectPath}
              onClick={() => setAttachOpen((o) => !o)}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-pill text-ink-2 transition-colors hover:bg-raised hover:text-ink disabled:opacity-40"
            >
              <IconPlus size={17} />
            </button>
            {attachOpen && (
              <AttachMenu
                onUpload={() => fileRef.current?.click()}
                onInsert={(line) => {
                  setText((t) =>
                    t.trim() === "" ? line : `${t.trimEnd()}\n${line}`,
                  );
                  requestAnimationFrame(() => {
                    autoGrow();
                    taRef.current?.focus();
                  });
                }}
                onClose={() => setAttachOpen(false)}
              />
            )}
          </div>
          <input
            ref={fileRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => void onPickFiles(e)}
          />

          {/* permission chip */}
          <div className="relative">
            <button
              type="button"
              data-testid="permission-chip"
              aria-haspopup="dialog"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((o) => !o)}
              className={cx(
                "flex h-8 items-center gap-1.5 rounded-pill px-2.5 text-sm font-medium transition-colors",
                mode === "full"
                  ? "text-warn hover:bg-warn/10"
                  : "text-ink-2 hover:bg-raised hover:text-ink",
              )}
            >
              <IconShield size={14} />
              {permissionLabel(mode)}
            </button>
            {menuOpen && (
              <PermissionMenu
                current={mode}
                onPick={(m) => void pickMode(m)}
                onClose={() => setMenuOpen(false)}
              />
            )}
          </div>

          {turnActive && (
            <span className="text-2xs text-ink-3">{zh.steer}</span>
          )}
          {!turnActive && !hasText && (
            <span className="hidden text-2xs text-ink-3 sm:inline">{zh.slashHint}</span>
          )}

          <div className="flex-1" />

          {/* context utilisation ring */}
          <ContextMeter />

          {/* model button: model · effort, opens the model menu */}
          {(modelName !== "" || effortLabel !== "") && (
            <div className="relative">
              <button
                type="button"
                data-testid="model-button"
                title={zh.modelMenuTitle}
                aria-haspopup="dialog"
                aria-expanded={modelOpen}
                onClick={() => {
                  setModelFocus("model");
                  setModelOpen((o) => !o);
                }}
                className="flex h-8 max-w-[260px] items-center gap-1 rounded-pill px-2 text-sm text-ink-2 transition-colors hover:bg-raised hover:text-ink"
              >
                <span className="truncate">{modelName}</span>
                {effortLabel !== "" && (
                  <span className="shrink-0 text-ink-3">· {effortLabel}</span>
                )}
                {restartPending && (
                  <span
                    className="h-1.5 w-1.5 shrink-0 rounded-full bg-warn"
                    title={zh.modelRestartPending}
                  />
                )}
                <IconChevronDown size={13} className="shrink-0 text-ink-3" />
              </button>
              {modelOpen && (
                <ModelMenu focus={modelFocus} onClose={() => setModelOpen(false)} />
              )}
            </div>
          )}

          {/* stop while running with text typed (steer stays primary) */}
          {turnActive && hasContent && onStop && (
            <button
              type="button"
              title={zh.stop}
              aria-label={zh.stop}
              onClick={onStop}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-pill text-ink-2 transition-colors hover:bg-raised hover:text-ink"
            >
              <IconStop size={15} />
            </button>
          )}

          {/* send / stop circle */}
          {showStop ? (
            <button
              type="button"
              title={zh.stop}
              aria-label={zh.stop}
              onClick={onStop}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-pill bg-ink text-bg transition-opacity hover:opacity-85"
            >
              <IconStop size={16} />
            </button>
          ) : (
            <button
              type="button"
              title={turnActive ? zh.steer : zh.send}
              aria-label={turnActive ? zh.steer : zh.send}
              disabled={!hasContent || sending || uploadsPending}
              onClick={() => {
                const parsed = parseSlash(text.trim());
                if (parsed) void runSlash(parsed.name, parsed.args);
                else void submit();
              }}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-pill bg-ink text-bg transition-opacity hover:opacity-85 disabled:opacity-30"
            >
              {sending ? <Spinner className="h-3.5 w-3.5" /> : <IconSend size={16} />}
            </button>
          )}
        </div>
        {error !== null && (
          <div className="px-2.5 pb-2.5">
            <AlertBanner>{error}</AlertBanner>
          </div>
        )}
      </div>
      <p className="mt-2 text-center text-[10px] leading-none text-ink-3" data-testid="workbench-copyright">
        © 2026 TopoSpace. All rights reserved.
      </p>
    </div>
  );
}
