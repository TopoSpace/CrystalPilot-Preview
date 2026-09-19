/** Project-level workbench state: open project, recent list, settings,
 * thread metadata, pending approvals (rehydrated from GET /api/approvals),
 * providers / kernel info for the settings dialog, and the project feed
 * (SSE) that keeps every view in step with changes made anywhere - the
 * browser, a CLI script, an edit of codex-home/config.toml. */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ApiError,
  getApprovals,
  getKernel,
  getSettings,
  listProviders,
  listThreads,
  openProject as apiOpenProject,
  projectFeedUrl,
  recentProjects,
  setSettings,
  type SettingsUpdateBody,
} from "../lib/wbApi";
import { zh } from "../lib/zh";
import type {
  KernelInfo,
  PendingApproval,
  ProjectSettings,
  ProviderInfo,
  RecentProject,
  SubagentMode,
  ThreadMeta,
  WbEvent,
} from "../lib/wbTypes";

const THREADS_POLL_MS = 30000;

export type SettingsSection =
  | "providers"
  | "models"
  | "context"
  | "appearance"
  | "advanced"
  | "about";

export interface WorkbenchContextValue {
  projectPath: string | null;
  threads: ThreadMeta[];
  settings: ProjectSettings | null;
  recent: RecentProject[];
  pendingApprovals: PendingApproval[];
  opening: boolean;
  openError: string | null;
  openProject: (path: string) => Promise<boolean>;
  refreshThreads: () => Promise<void>;
  refreshApprovals: () => Promise<void>;
  refreshRecent: () => Promise<void>;
  refreshSettings: () => Promise<void>;
  changePermissionMode: (mode: string) => Promise<string | null>;
  changeIucrUpload: (allow: boolean) => Promise<string | null>;
  /** Flipping this transparently rebuilds the project's agent service
   * (~5–10 s); the server 409s while a turn is running. */
  changeSpecialists: (enable: boolean) => Promise<string | null>;
  /** the sub-agent switch: auto | on | off */
  changeSubagents: (mode: SubagentMode) => Promise<string | null>;
  /** round-3 R6: the ka1 ablation switch ("full" | "tools_only"); the
   * server 409s while a turn is running (the template is rewritten). */
  changeKnowledgeMode: (mode: string) => Promise<string | null>;
  /** Per-project model / effort / provider overrides (null clears back to
   * the config.toml default; model and effort travel with the next turn,
   * the provider with the next thread or a fork). */
  changeModelEffort: (patch: {
    model_override?: string | null;
    effort_override?: string | null;
    model_provider_override?: string | null;
  }) => Promise<string | null>;
  /** any plain per-project setting */
  patchSettings: (body: SettingsUpdateBody) => Promise<string | null>;
  /** Sidebar rename: a plain project setting, so every list that shows
   * the project (sidebar, status board, open dialog) follows. null or ""
   * clears back to the directory name. */
  renameProject: (name: string | null) => Promise<string | null>;
  /** Owner-declared structure class (null = not declared). */
  structureClass: string | null;
  changeStructureClass: (cls: string | null) => Promise<string | null>;
  /** providers as config.toml declares them (no keys) */
  providers: ProviderInfo[];
  refreshProviders: () => Promise<void>;
  kernel: KernelInfo | null;
  refreshKernel: () => Promise<void>;
  /** the settings dialog (global) */
  settingsDialog: { open: boolean; section: SettingsSection };
  openSettings: (section?: SettingsSection) => void;
  closeSettings: () => void;
}

const SC_STORAGE_PREFIX = "cp.structureClass:";

function readLocalStructureClass(path: string | null): string | null {
  if (!path) return null;
  try {
    return window.localStorage.getItem(SC_STORAGE_PREFIX + path.toLowerCase());
  } catch {
    return null;
  }
}

function writeLocalStructureClass(path: string, cls: string | null): void {
  try {
    const key = SC_STORAGE_PREFIX + path.toLowerCase();
    if (cls === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, cls);
  } catch {
    /* storage unavailable */
  }
}

const WorkbenchContext = createContext<WorkbenchContextValue | null>(null);

export function useWorkbench(): WorkbenchContextValue {
  const ctx = useContext(WorkbenchContext);
  if (ctx === null) {
    throw new Error("useWorkbench must be used inside WorkbenchProvider");
  }
  return ctx;
}

export function WorkbenchProvider({ children }: { children: ReactNode }) {
  const [projectPath, setProjectPath] = useState<string | null>(null);
  const [threads, setThreads] = useState<ThreadMeta[]>([]);
  const [settings, setSettingsState] = useState<ProjectSettings | null>(null);
  const [recent, setRecent] = useState<RecentProject[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState<PendingApproval[]>([]);
  const [opening, setOpening] = useState(false);
  const [openError, setOpenError] = useState<string | null>(null);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [kernel, setKernel] = useState<KernelInfo | null>(null);
  const [settingsDialog, setSettingsDialog] = useState<{ open: boolean; section: SettingsSection }>({
    open: false,
    section: "providers",
  });
  const pathRef = useRef<string | null>(null);
  pathRef.current = projectPath;

  const refreshRecent = useCallback(async () => {
    try {
      setRecent(await recentProjects());
    } catch {
      /* server unreachable; keep the old list */
    }
  }, []);

  const refreshThreads = useCallback(async () => {
    const path = pathRef.current;
    if (!path) return;
    try {
      const res = await listThreads(path);
      if (pathRef.current === path) setThreads(res.threads);
    } catch {
      /* transient */
    }
  }, []);

  const refreshApprovals = useCallback(async () => {
    const path = pathRef.current;
    if (!path) return;
    try {
      const res = await getApprovals(path);
      if (pathRef.current === path) setPendingApprovals(res);
    } catch {
      /* transient */
    }
  }, []);

  const refreshSettings = useCallback(async () => {
    const path = pathRef.current;
    if (!path) return;
    try {
      const s = await getSettings(path);
      if (pathRef.current === path) setSettingsState(s);
    } catch {
      /* transient */
    }
  }, []);

  const refreshProviders = useCallback(async () => {
    try {
      setProviders((await listProviders()).providers);
    } catch {
      /* the dialog shows its own error */
    }
  }, []);

  const refreshKernel = useCallback(async () => {
    try {
      setKernel(await getKernel());
    } catch {
      /* informational */
    }
  }, []);

  const openProject = useCallback(
    async (path: string): Promise<boolean> => {
      setOpening(true);
      setOpenError(null);
      try {
        const res = await apiOpenProject(path);
        setProjectPath(res.project);
        pathRef.current = res.project;
        setThreads(res.threads.map((t) => ({ ...t, busy: t.busy ?? false })));
        try {
          setSettingsState(await getSettings(res.project));
        } catch {
          setSettingsState(null);
        }
        void refreshApprovals();
        void refreshRecent();
        // pick up busy flags (open response has none)
        void refreshThreads();
        return true;
      } catch (e) {
        setOpenError(e instanceof Error ? e.message : String(e));
        return false;
      } finally {
        setOpening(false);
      }
    },
    [refreshApprovals, refreshRecent, refreshThreads],
  );

  /** one path for every plain setting write: the server answers with the
   * whole record, which replaces the local copy */
  const patchSettings = useCallback(
    async (body: SettingsUpdateBody): Promise<string | null> => {
      const path = pathRef.current;
      if (!path) return "没有打开的项目";
      try {
        setSettingsState(await setSettings(path, { settings: body }));
        return null;
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          return zh.settingsSpecialistsBusy;
        }
        return e instanceof Error ? e.message : String(e);
      }
    },
    [],
  );

  const changePermissionMode = useCallback(
    async (mode: string): Promise<string | null> => {
      const path = pathRef.current;
      if (!path) return "没有打开的项目";
      try {
        setSettingsState(await setSettings(path, { permission_mode: mode }));
        return null;
      } catch (e) {
        return e instanceof Error ? e.message : String(e);
      }
    },
    [],
  );

  const changeIucrUpload = useCallback(
    (allow: boolean) => patchSettings({ allow_iucr_upload: allow }),
    [patchSettings],
  );

  const changeModelEffort = useCallback(
    (patch: {
      model_override?: string | null;
      effort_override?: string | null;
      model_provider_override?: string | null;
    }) => patchSettings(patch),
    [patchSettings],
  );

  const renameProject = useCallback(
    async (name: string | null): Promise<string | null> => {
      const err = await patchSettings({ display_name: name });
      if (err === null) await refreshRecent();
      return err;
    },
    [patchSettings, refreshRecent],
  );

  const [localClass, setLocalClass] = useState<string | null>(null);
  useEffect(() => {
    setLocalClass(readLocalStructureClass(projectPath));
  }, [projectPath]);
  const structureClass =
    (typeof settings?.structure_class === "string" && settings.structure_class !== ""
      ? settings.structure_class
      : null) ?? localClass;

  const changeStructureClass = useCallback(
    async (cls: string | null): Promise<string | null> => {
      const path = pathRef.current;
      if (!path) return "没有打开的项目";
      writeLocalStructureClass(path, cls);
      setLocalClass(cls);
      const err = await patchSettings({ structure_class: cls });
      return err === null ? null : `${zh.scSaveFailed}${err}`;
    },
    [patchSettings],
  );

  const changeSubagents = useCallback(
    (mode: SubagentMode) => patchSettings({ subagents: mode }),
    [patchSettings],
  );

  const changeKnowledgeMode = useCallback(
    async (mode: string): Promise<string | null> => {
      const path = pathRef.current;
      if (!path) return "没有打开的项目";
      try {
        setSettingsState(await setSettings(path, { settings: { knowledge_mode: mode } }));
        return null;
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          return zh.settingsKnowledgeModeBusy;
        }
        return e instanceof Error ? e.message : String(e);
      }
    },
    [],
  );

  const changeSpecialists = useCallback(
    async (enable: boolean): Promise<string | null> => {
      const path = pathRef.current;
      if (!path) return "没有打开的项目";
      try {
        setSettingsState(
          await setSettings(path, { settings: { enable_specialists: enable } }),
        );
        return null;
      } catch (e) {
        // rebuild refused while a turn is running (409) / rebuild crash (500)
        if (e instanceof ApiError && (e.status === 409 || e.status === 500)) {
          return zh.settingsSpecialistsBusy;
        }
        return e instanceof Error ? e.message : String(e);
      }
    },
    [],
  );

  const openSettings = useCallback((section?: SettingsSection) => {
    setSettingsDialog((d) => ({ open: true, section: section ?? d.section }));
    void refreshProviders();
    void refreshKernel();
  }, [refreshProviders, refreshKernel]);
  const closeSettings = useCallback(() => {
    setSettingsDialog((d) => ({ ...d, open: false }));
  }, []);

  useEffect(() => {
    void refreshRecent();
    void refreshProviders();
  }, [refreshRecent, refreshProviders]);

  // light polling keeps sidebar busy dots honest
  useEffect(() => {
    if (!projectPath) return undefined;
    const t = window.setInterval(() => {
      // SSE project feed carries the busy-state churn; this poll is only a
      // safety net, so skip it entirely while the tab is hidden
      if (document.visibilityState === "visible") void refreshThreads();
    }, THREADS_POLL_MS);
    return () => window.clearInterval(t);
  }, [projectPath, refreshThreads]);

  // the project feed: settings pushed after ANY change (browser, CLI,
  // config.toml edit), thread renames, engine restarts, busy churn
  useEffect(() => {
    if (!projectPath) return undefined;
    const path = projectPath;
    let es: EventSource | null = null;
    let retry: number | undefined;
    let disposed = false;
    let backoff = 1000;
    const onMessage = (e: MessageEvent<string>) => {
      let ev: WbEvent;
      try {
        ev = JSON.parse(e.data) as WbEvent;
      } catch {
        return;
      }
      if (!ev || typeof ev !== "object" || !("kind" in ev)) return;
      if (pathRef.current !== path) return;
      switch (ev.kind) {
        case "ping":
          return;
        case "channel_closed":
          // the project session was released server-side (idle reaper,
          // shutdown): this feed is an orphan - re-open and dial back in
          es?.close();
          es = null;
          if (!disposed) {
            retry = window.setTimeout(() => {
              void apiOpenProject(path).catch(() => undefined).then(connect);
            }, backoff);
            backoff = Math.min(backoff * 2, 15_000);
          }
          return;
        case "settings":
          setSettingsState(ev.settings);
          return;
        case "config_changed":
          void refreshProviders();
          void refreshSettings();
          void refreshKernel();
          return;
        case "thread_renamed":
        case "user_message":
        case "turn_started":
        case "turn_completed":
        case "turn_failed":
        case "idle":
          void refreshThreads();
          return;
        case "engine_restarted":
        case "permission_mode":
        case "delegation":
        case "specialists_toggled":
          void refreshSettings();
          return;
        case "approval_request":
        case "approval_decision":
        case "approval_timeout":
          void refreshApprovals();
          return;
        default:
          return;
      }
    };
    const connect = () => {
      if (disposed) return;
      es = new EventSource(projectFeedUrl(path));
      es.onopen = () => { backoff = 1000; };
      es.onmessage = onMessage;
      es.onerror = () => {
        // A dropped connection is EventSource's own business (readyState
        // CONNECTING - it retries). A non-2xx reply is not: the browser
        // gives up for good. The server answers 400 "project not open" for
        // the first seconds after a restart, which is exactly when an open
        // tab reconnects, so the feed died silently and the tab stopped
        // seeing settings / approval / rename pushes until a reload (seen
        // live 2026-09-07). Re-open the project, then dial back in.
        if (es?.readyState !== EventSource.CLOSED) return;
        es = null;
        if (disposed) return;
        retry = window.setTimeout(() => {
          void apiOpenProject(path).catch(() => undefined).then(connect);
        }, backoff);
        backoff = Math.min(backoff * 2, 15_000);
      };
    };
    connect();
    return () => {
      disposed = true;
      es?.close();
      if (retry !== undefined) window.clearTimeout(retry);
    };
  }, [projectPath, refreshProviders, refreshSettings, refreshKernel, refreshThreads, refreshApprovals]);

  // coming back to the tab: re-read what may have changed meanwhile
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") {
        void refreshSettings();
        void refreshThreads();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [refreshSettings, refreshThreads]);

  const value = useMemo<WorkbenchContextValue>(
    () => ({
      projectPath,
      threads,
      settings,
      recent,
      pendingApprovals,
      opening,
      openError,
      openProject,
      refreshThreads,
      refreshApprovals,
      refreshRecent,
      refreshSettings,
      changePermissionMode,
      changeIucrUpload,
      changeSpecialists,
      changeSubagents,
      changeKnowledgeMode,
      changeModelEffort,
      patchSettings,
      renameProject,
      structureClass,
      changeStructureClass,
      providers,
      refreshProviders,
      kernel,
      refreshKernel,
      settingsDialog,
      openSettings,
      closeSettings,
    }),
    [
      projectPath,
      threads,
      settings,
      recent,
      pendingApprovals,
      opening,
      openError,
      openProject,
      refreshThreads,
      refreshApprovals,
      refreshRecent,
      refreshSettings,
      changePermissionMode,
      changeIucrUpload,
      changeSpecialists,
      changeSubagents,
      changeKnowledgeMode,
      changeModelEffort,
      patchSettings,
      renameProject,
      structureClass,
      changeStructureClass,
      providers,
      refreshProviders,
      kernel,
      refreshKernel,
      settingsDialog,
      openSettings,
      closeSettings,
    ],
  );

  return (
    <WorkbenchContext.Provider value={value}>
      {children}
    </WorkbenchContext.Provider>
  );
}
