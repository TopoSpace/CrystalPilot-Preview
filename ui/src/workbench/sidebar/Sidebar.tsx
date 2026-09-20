/** Left sidebar (default 280px, drag the right edge to resize; Codex
 * anatomy): brand row, 新对话, 项目 section, 最近项目, and a footer whose
 * gear opens the settings dialog.
 *
 * Every project folder expands to show its conversations (2026-09-07): the
 * open one from live state, any other fetched on first expand. Clicking a
 * folder only folds/unfolds it - switching projects happens when you pick
 * one of its conversations, or 打开 on hover. Both routes NAVIGATE and let
 * ProjectUrlSync open the project, so the route and the open project change
 * together instead of leaving a render where the thread of project A is
 * mounted under project B. */
import { BrandMark } from "../Brand";
import { useCallback, useEffect, useRef, useState } from "react";
import { hideKey, isScratchProject, splitRecent, useHiddenProjects } from "./hiddenProjects";
import { useSection } from "../crystal/useSection";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Spinner, StatusDot } from "../../components/ui";
import type { RecentProject, ThreadMeta } from "../../lib/wbTypes";
import { cx } from "../../lib/format";
import { listThreads, projectsStatus, renameThread } from "../../lib/wbApi";
import type { ProjectStatus } from "../../lib/wbTypes";
import { t } from "../../lib/i18n";
import { useWorkbench } from "../../state/WorkbenchProvider";
import {
  IconChevronRight,
  IconCompose,
  IconFolder,
  IconPlusCircle,
  IconSettings,
  IconUser,
  IconPanelLeft,
} from "../icons";
import { OpenProjectDialog } from "./OpenProjectDialog";
import { ResizeHandle } from "../ResizeHandle";
import { projectHomeUrl, projectLabel, RECENT_PROJECTS_LIMIT, threadUrl } from "../urls";
import { useResizable } from "../useResizable";
import { PanelReveal } from "../PanelTransition";
import { useTheme } from "../../lib/theme";

function samePath(a: string, b: string): boolean {
  return a.replaceAll("\\", "/").toLowerCase() === b.replaceAll("\\", "/").toLowerCase();
}

/** R1 · nodes · A-alerts for the open project; disk-only endpoint, slow
 * poll that pauses while the tab is hidden. */
function useProjectStatus(path: string | null): ProjectStatus | null {
  const [row, setRow] = useState<ProjectStatus | null>(null);
  const load = useCallback(() => {
    if (!path || document.visibilityState !== "visible") return;
    void projectsStatus()
      .then((rows) => setRow(rows.find((r) => samePath(r.path, path)) ?? null))
      .catch(() => undefined);
  }, [path]);
  useEffect(() => {
    setRow(null);
    load();
    const t = window.setInterval(load, 60_000);
    return () => window.clearInterval(t);
  }, [load]);
  return row;
}

/** Conversations of a project that is not the open one: fetched the first
 * time its folder is unfolded, then kept for the session. */
function useLazyThreads(path: string, enabled: boolean) {
  const [threads, setThreads] = useState<ThreadMeta[] | null>(null);
  useEffect(() => {
    if (!enabled || threads !== null) return undefined;
    let alive = true;
    void listThreads(path)
      .then((r) => {
        if (alive) setThreads(r.threads);
      })
      .catch(() => {
        if (alive) setThreads([]);
      });
    return () => {
      alive = false;
    };
  }, [path, enabled, threads]);
  return threads;
}

function ProjectStatusLine({ status }: { status: ProjectStatus | null }) {
  if (!status) return null;
  if (!status.n_nodes) {
    return (
      <div className="pl-[34px] text-2xs text-ink-3">{t.sidebarStatusNoWork}</div>
    );
  }
  const r1 = status.r1 ?? status.r1_best ?? null;
  const a = status.checkcif?.A ?? null;
  return (
    <div className="flex items-center gap-1.5 pl-[34px] font-mono text-2xs text-ink-3 tabular-nums">
      {r1 !== null && (
        <span>
          <span className="font-serif italic">R</span>
          <sub className="text-[0.8em] not-italic">1</sub> {r1.toFixed(4)}
        </span>
      )}
      <span aria-hidden>·</span>
      <span>
        {status.n_nodes} {t.sidebarStatusNodes}
      </span>
      {a !== null && (
        <>
          <span aria-hidden>·</span>
          <span className={a > 0 ? "font-medium text-danger" : undefined}>
            {t.sidebarStatusAlertsA} {a}
          </span>
        </>
      )}
    </div>
  );
}

/** The fold/unfold caret every project folder carries. */
function Caret({ open }: { open: boolean }) {
  return (
    <IconChevronRight
      size={12}
      className={cx("shrink-0 text-ink-3 transition-transform", open && "rotate-90")}
    />
  );
}

/** One conversation: click = open, hover = rename (goes to the kernel
 * through /api/threads/rename, so the CLI sees the same title). */
function ThreadRow({
  thread,
  active,
  project,
  onOpen,
  onRenamed,
}: {
  thread: ThreadMeta;
  active: boolean;
  project: string;
  onOpen: () => void;
  onRenamed: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);
  const begin = () => {
    setDraft(thread.title);
    setError(null);
    setEditing(true);
  };
  const commit = async () => {
    const title = draft.trim();
    if (title === "" || title === thread.title) {
      setEditing(false);
      return;
    }
    try {
      await renameThread(thread.thread_id, title, project);
      setEditing(false);
      onRenamed();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  if (editing) {
    return (
      <div className="pl-[34px] pr-1">
        <input
          ref={inputRef}
          value={draft}
          placeholder={t.threadRenamePlaceholder}
          aria-label={t.renameThread}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void commit();
            if (e.key === "Escape") setEditing(false);
          }}
          onBlur={() => void commit()}
          className="h-8 w-full rounded-lg border border-accent/40 bg-bg px-2 text-base text-ink outline-none"
        />
        {error && <div className="px-1 pt-0.5 text-2xs text-danger">{error}</div>}
      </div>
    );
  }
  return (
    <div
      className={cx(
        "group flex h-8 items-center rounded-lg pr-1 transition-colors",
        active ? "bg-raised text-ink" : "text-ink-2 hover:bg-raised/60 hover:text-ink",
      )}
    >
      <button
        type="button"
        title={thread.title}
        data-testid="thread-row"
        onClick={onOpen}
        className="flex h-8 min-w-0 flex-1 items-center gap-2 rounded-lg py-1.5 pl-[34px] text-base"
      >
        <span className="min-w-0 flex-1 truncate text-left">{thread.title}</span>
        {thread.busy === true && (
          <span title={t.running}>
            <StatusDot tone="green" pulse size={7} />
          </span>
        )}
      </button>
      <button
        type="button"
        title={t.threadRenameTip}
        aria-label={t.renameThread}
        onClick={begin}
        className="h-6 shrink-0 rounded-md px-1.5 text-2xs text-ink-3 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-bg hover:text-ink focus:opacity-100"
      >
        {t.renameThread}
      </button>
    </div>
  );
}

/** The conversation list under a folder (null = still loading). */
function ThreadList({
  threads,
  project,
  activeThreadId,
  onOpenThread,
  onRenamed,
}: {
  threads: ThreadMeta[] | null;
  project: string;
  activeThreadId: string | undefined;
  onOpenThread: (threadId: string) => void;
  onRenamed: () => void;
}) {
  if (threads === null) {
    return (
      <div className="flex items-center gap-1.5 py-1.5 pl-[34px] text-xs text-ink-3">
        <Spinner className="h-3 w-3" />
        {t.loading}
      </div>
    );
  }
  if (threads.length === 0) {
    return (
      <div className="px-2 py-1.5 pl-[34px] text-xs text-ink-3">{t.noThreads}</div>
    );
  }
  return (
    <div className="flex flex-col gap-px">
      {threads.map((t) => (
        <ThreadRow
          key={t.thread_id}
          thread={t}
          active={t.thread_id === activeThreadId}
          project={project}
          onOpen={() => onOpenThread(t.thread_id)}
          onRenamed={onRenamed}
        />
      ))}
    </div>
  );
}

/** The open project: display name (directory name until renamed), the
 * path in the tooltip, an inline rename that lands in the project settings
 * so every other list follows, and a caret that folds its conversations. */
function CurrentProjectRow({
  path,
  displayName,
  open,
  onToggle,
  onOpenHome,
  onRename,
}: {
  path: string;
  displayName: string | null;
  open: boolean;
  onToggle: () => void;
  onOpenHome: () => void;
  onRename: (name: string | null) => Promise<string | null>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);
  const begin = () => {
    setDraft(displayName ?? "");
    setError(null);
    setEditing(true);
  };
  const commit = async () => {
    const name = draft.trim();
    const err = await onRename(name === "" ? null : name);
    if (err) setError(err);
    else setEditing(false);
  };
  if (editing) {
    return (
      <div className="px-2">
        <input
          ref={inputRef}
          value={draft}
          placeholder={t.renamePlaceholder}
          aria-label={t.renameProject}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void commit();
            if (e.key === "Escape") setEditing(false);
          }}
          onBlur={() => void commit()}
          className="h-8 w-full rounded-lg border border-accent/40 bg-bg px-2 text-base text-ink outline-none"
        />
        {error && <div className="px-1 pt-0.5 text-2xs text-danger">{error}</div>}
      </div>
    );
  }
  return (
    <div className="group flex h-8 items-center rounded-lg pr-1 transition-colors hover:bg-raised">
      <button
        type="button"
        onClick={onToggle}
        title={path}
        aria-expanded={open}
        className="flex h-8 min-w-0 flex-1 items-center gap-1.5 rounded-lg px-2 text-base text-ink"
      >
        <Caret open={open} />
        <IconFolder size={16} className="shrink-0 text-ink-2" />
        <span className="truncate text-left font-medium" data-testid="project-name">
          {projectLabel(path, displayName)}
        </span>
      </button>
      <button
        type="button"
        title={t.openProjectHome}
        onClick={onOpenHome}
        className="h-6 shrink-0 rounded-md px-1.5 text-2xs text-ink-3 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-bg hover:text-ink focus:opacity-100"
      >
        {t.newThread}
      </button>
      <button
        type="button"
        title={t.renameProjectTip}
        aria-label={t.renameProject}
        onClick={begin}
        className="h-6 shrink-0 rounded-md px-1.5 text-2xs text-ink-3 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-bg hover:text-ink focus:opacity-100"
      >
        {t.renameProject}
      </button>
    </div>
  );
}

/** A project other than the open one: the caret folds its conversations in
 * place (no project switch), 打开 makes it the current project. */
function RecentRow({
  row,
  hidden,
  activeThreadId,
  onOpenProject,
  onOpenThread,
  onToggleHidden,
}: {
  row: RecentProject;
  hidden: boolean;
  activeThreadId: string | undefined;
  onOpenProject: (path: string) => void;
  onOpenThread: (path: string, threadId: string) => void;
  onToggleHidden: (path: string) => void;
}) {
  const [open, toggle] = useSection(`sidebar.proj.${hideKey(row.path)}`, false);
  const threads = useLazyThreads(row.path, open);
  return (
    <div>
      <div className="group flex h-8 items-center rounded-lg pr-1 transition-colors hover:bg-raised">
        <button
          type="button"
          title={row.path}
          aria-expanded={open}
          onClick={toggle}
          className="flex h-8 min-w-0 flex-1 items-center gap-1.5 rounded-lg px-2 text-base text-ink-2 transition-colors hover:text-ink"
        >
          <Caret open={open} />
          <IconFolder size={16} className="shrink-0 text-ink-3" />
          <span className="truncate text-left">{projectLabel(row.path, row.display_name)}</span>
        </button>
        <button
          type="button"
          title={t.openThisProjectTip}
          onClick={() => onOpenProject(row.path)}
          className="h-6 shrink-0 rounded-md px-1.5 text-2xs text-ink-3 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-bg hover:text-ink focus:opacity-100"
        >
          {t.openThisProject}
        </button>
        <button
          type="button"
          title={hidden ? t.unhideProject : t.hideProjectTip}
          aria-label={hidden ? t.unhideProject : t.hideProject}
          onClick={() => onToggleHidden(row.path)}
          className="h-6 shrink-0 rounded-md px-1.5 text-2xs text-ink-3 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-bg hover:text-ink focus:opacity-100"
        >
          {hidden ? t.unhideProject : t.hideProject}
        </button>
      </div>
      {open && (
        <ThreadList
          threads={threads}
          project={row.path}
          activeThreadId={activeThreadId}
          onOpenThread={(id) => onOpenThread(row.path, id)}
          onRenamed={() => undefined}
        />
      )}
    </div>
  );
}

/** Recent projects: the named/real ones first, the UI's own scratch
 * imports (ui-import-<epoch>) and anything the user hid folded under 更多
 * (visual review 2026-09-05: the list was a wall of hashes). */
function RecentList({
  rows,
  activeThreadId,
  onOpenProject,
  onOpenThread,
}: {
  rows: RecentProject[];
  activeThreadId: string | undefined;
  onOpenProject: (path: string) => void;
  onOpenThread: (path: string, threadId: string) => void;
}) {
  const [hidden, toggleHidden] = useHiddenProjects();
  const [moreOpen, toggleMore] = useSection("sidebar.more", false);
  const { primary, more } = splitRecent(rows, hidden, RECENT_PROJECTS_LIMIT);
  return (
    <div className="mt-5">
      <div className="px-2 pb-1 text-xs font-medium text-ink-3">{t.recentProjects}</div>
      <div className="flex flex-col gap-px" data-testid="recent-primary">
        {primary.map((r) => (
          <RecentRow
            key={r.path}
            row={r}
            hidden={false}
            activeThreadId={activeThreadId}
            onOpenProject={onOpenProject}
            onOpenThread={onOpenThread}
            onToggleHidden={toggleHidden}
          />
        ))}
      </div>
      {more.length > 0 && (
        <div className="mt-1">
          <button
            type="button"
            aria-expanded={moreOpen}
            title={t.moreProjectsTip}
            onClick={toggleMore}
            className="flex h-7 w-full items-center gap-1.5 rounded-lg px-2 text-xs text-ink-3 transition-colors hover:bg-raised hover:text-ink"
          >
            <span className={cx("text-2xs transition-transform", moreOpen && "rotate-90")}>▶</span>
            {t.moreProjects}
            <span className="font-mono text-2xs tabular-nums">{more.length}</span>
          </button>
          {moreOpen && (
            <div className="flex flex-col gap-px" data-testid="recent-more">
              {more.map((r) => (
                <RecentRow
                  key={r.path}
                  row={r}
                  hidden={hidden.has(hideKey(r.path)) || isScratchProject(r.path, r.display_name)}
                  activeThreadId={activeThreadId}
                  onOpenProject={onOpenProject}
                  onOpenThread={onOpenThread}
                  onToggleHidden={toggleHidden}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function Sidebar({ onCollapse, open = true }: { onCollapse?: () => void; open?: boolean }) {
  const { brandName } = useTheme();
  const wb = useWorkbench();
  const navigate = useNavigate();
  const { threadId: activeThreadId } = useParams();
  const [dialogOpen, setDialogOpen] = useState(false);
  const status = useProjectStatus(wb.projectPath);
  const [currentOpen, toggleCurrent] = useSection("sidebar.currentProject", true);

  // 新对话 = the composer on the project home; the first message creates
  // the thread INSIDE the open project. Without a project, pick one first.
  const newThread = () => {
    if (wb.projectPath) navigate(projectHomeUrl(wb.projectPath));
    else setDialogOpen(true);
  };

  // Navigate and let ProjectUrlSync open the project: the route and the
  // open project then change in ONE step, instead of leaving a render where
  // the previous project's thread is still mounted under the new project.
  const openProject = (path: string) => navigate(projectHomeUrl(path));
  const openThread = (path: string, threadId: string) =>
    navigate(threadUrl(threadId, path));

  const otherRecent = wb.recent.filter(
    (r) => wb.projectPath === null || !samePath(r.path, wb.projectPath),
  );

  const resize = useResizable("wb.sidebarWidth", 280, 200, 480, "right");

  return (
    <PanelReveal open={open} width={resize.width} side="left" resizing={resize.dragging}>
    <nav
      style={{ width: resize.width }}
      className="relative flex max-w-[85vw] shrink-0 flex-col border-r border-line bg-surface"
    >
      <ResizeHandle edge="right" resizable={resize} />
      {/* brand row */}
      <div className="flex h-12 shrink-0 items-center justify-between gap-2 px-4">
        <Link to="/" className="flex min-w-0 items-center gap-2 text-lg font-semibold tracking-tight text-ink" title={brandName} data-testid="workbench-brand">
          <BrandMark size={22} />
          <span className="min-w-0 truncate">{brandName}</span>
        </Link>
        {onCollapse && <button type="button" className="chrome-button" onClick={onCollapse}
          aria-label={t.sidebarClose} title={t.sidebarClose} data-testid="sidebar-collapse"><IconPanelLeft size={17} /></button>}
      </div>

      {/* new thread */}
      <div className="px-2 pt-1">
        <button
          type="button"
          data-testid="new-thread"
          title={
            wb.projectPath
              ? `${t.newThreadIn} ${projectLabel(wb.projectPath, wb.settings?.display_name)}`
              : t.newThreadNoProject
          }
          onClick={newThread}
          className="group flex h-8 w-full items-center gap-2.5 rounded-lg px-2 text-base text-ink transition-colors hover:bg-raised"
        >
          <IconCompose size={16} className="text-ink-2" />
          <span className="flex-1 text-left">{t.newThread}</span>
          <IconPlusCircle size={16} className="text-ink-3" />
        </button>
      </div>

      {/* projects */}
      <div className="mt-4 min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        <div className="flex items-center justify-between px-2 pb-1">
          <span className="text-xs font-medium text-ink-3">{t.projects}</span>
          <button
            type="button"
            title={t.openProject}
            aria-label={t.openProject}
            onClick={() => setDialogOpen(true)}
            className="flex h-6 w-6 items-center justify-center rounded-md text-ink-3 transition-colors hover:bg-raised hover:text-ink"
          >
            <IconPlusCircle size={15} />
          </button>
        </div>

        {wb.projectPath !== null ? (
          <div>
            <CurrentProjectRow
              path={wb.projectPath}
              displayName={wb.settings?.display_name ?? status?.display_name ?? null}
              open={currentOpen}
              onToggle={toggleCurrent}
              onOpenHome={() => navigate(projectHomeUrl(wb.projectPath as string))}
              onRename={wb.renameProject}
            />
            {currentOpen && (
              <>
                <ProjectStatusLine status={status} />
                <div className="mt-1">
                  <ThreadList
                    threads={wb.threads}
                    project={wb.projectPath}
                    activeThreadId={activeThreadId}
                    onOpenThread={(id) => openThread(wb.projectPath as string, id)}
                    onRenamed={() => void wb.refreshThreads()}
                  />
                </div>
              </>
            )}
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setDialogOpen(true)}
            className="flex h-8 w-full items-center gap-2.5 rounded-lg px-2 text-base text-ink-2 transition-colors hover:bg-raised hover:text-ink"
          >
            <IconFolder size={16} className="text-ink-3" />
            {t.openProject}
          </button>
        )}

        {otherRecent.length > 0 && (
          <RecentList
            rows={otherRecent}
            activeThreadId={activeThreadId}
            onOpenProject={openProject}
            onOpenThread={openThread}
          />
        )}
      </div>

      {/* footer: local user + settings */}
      <div className="relative flex h-12 shrink-0 items-center gap-2.5 border-t border-line px-4">
        <span className="flex h-6 w-6 items-center justify-center rounded-pill bg-raised text-ink-2">
          <IconUser size={14} />
        </span>
        <span className="flex-1 truncate text-sm text-ink">{t.localUser}</span>
        <button
          type="button"
          title={t.settings}
          aria-label={t.settings}
          data-testid="open-settings"
          aria-expanded={wb.settingsDialog.open}
          onClick={() => wb.openSettings()}
          className={cx(
            "flex h-7 w-7 items-center justify-center rounded-lg transition-colors hover:bg-raised hover:text-ink",
            wb.settingsDialog.open ? "bg-raised text-ink" : "text-ink-3",
          )}
        >
          <IconSettings size={16} />
        </button>
      </div>

      {dialogOpen && <OpenProjectDialog onClose={() => setDialogOpen(false)} />}
    </nav>
    </PanelReveal>
  );
}
