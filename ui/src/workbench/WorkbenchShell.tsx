/** 3-column workbench frame: sidebar 280px | chat flex | right pane 380px.
 * The right pane is collapsible; in P1 it holds the crystal-pane placeholder. */
import { useEffect, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { t } from "../lib/i18n";
import { IconPanelLeft, IconPanelRight, IconFolder } from "./icons";
import { RightPane } from "./RightPane";
import { SettingsDialog } from "./settings/SettingsDialog";
import { useWorkbench, type SettingsSection } from "../state/WorkbenchProvider";
import { takeSettingsSection } from "../lib/settingsReopen";
import { Sidebar } from "./sidebar/Sidebar";
import { useNarrow, useViewportWidth } from "./useViewport";
import { ChromeControls, WorkbenchHeader } from "./WorkbenchHeader";
import { PanelDrawer } from "./PanelTransition";
import { useTheme } from "../lib/theme";

export function WorkbenchShell({ children }: { children: ReactNode }) {
  const { brandName } = useTheme();
  const location = useLocation();
  const wb = useWorkbench();
  // a language switch reloads the page; come back to the settings section it was made in
  useEffect(() => {
    const section = takeSettingsSection();
    if (section) wb.openSettings(section as SettingsSection);
    // once, on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const inThread = location.pathname.startsWith("/thread/");
  const showStructure =
    new URLSearchParams(location.search).get("view") === "structure";
  const compact = useViewportWidth() < 760;
  const [rightOpen, setRightOpen] = useState<boolean | null>(null);
  const showRight = rightOpen ?? ((inThread && !compact) || showStructure);
  useEffect(() => {
    if (showStructure) setRightOpen(true);
  }, [location.search, showStructure]);
  // below 1200 px the sidebar is a slide-over drawer (visual review
  // 2026-09-04: three fixed columns left a 420 px chat on a laptop); the
  // drawer closes on navigation and on Escape
  const narrow = useNarrow();
  // 聚焦 (R2-B): while the right pane is widened, the sidebar becomes a
  // drawer too, so the conversation keeps a column instead of a sliver
  const focus =
    showRight && new URLSearchParams(location.search).get("focus") === "1";
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem("wb.sidebarCollapsed") === "1");
  useEffect(() => { localStorage.setItem("wb.sidebarCollapsed", sidebarCollapsed ? "1" : "0"); }, [sidebarCollapsed]);
  const drawerMode = narrow || focus;
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawerShown = drawerMode && drawerOpen;
  useEffect(() => { if (!drawerMode) setDrawerOpen(false); }, [drawerMode]);
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname, location.search]);
  useEffect(() => {
    if (!drawerOpen) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawerOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  const controls = {
    left: drawerMode || sidebarCollapsed ? <button type="button" className="chrome-button"
      title={t.sidebarOpen} aria-label={t.sidebarOpen} data-testid="sidebar-expand"
      onClick={() => narrow || focus ? setDrawerOpen(true) : setSidebarCollapsed(false)}>
      <IconPanelLeft size={17} />
    </button> : undefined,
    right: !showRight ? <button type="button" className="chrome-button"
      title={t.expand} aria-label={t.expand} data-testid="right-expand"
      onClick={() => setRightOpen(true)}><IconPanelRight size={17} /></button> : undefined,
  };
  return (
    <ChromeControls.Provider value={controls}>
    <div className="relative flex h-dvh min-h-0 overflow-hidden bg-bg text-ink">
      <ErrorBoundary area="sidebar">
        <Sidebar open={!drawerMode && !sidebarCollapsed} onCollapse={() => setSidebarCollapsed(true)} />
      </ErrorBoundary>
      <PanelDrawer open={drawerShown} side="left" onClose={() => setDrawerOpen(false)}>
        <ErrorBoundary area="sidebar"><Sidebar onCollapse={() => setDrawerOpen(false)} /></ErrorBoundary>
      </PanelDrawer>
      <main className="relative flex min-w-0 flex-1 flex-col bg-bg"
        {...{ inert: (compact && showRight) || drawerShown ? "" : undefined }}
        aria-hidden={(compact && showRight) || drawerShown || undefined}>
        {!inThread && <WorkbenchHeader><IconFolder size={16} className="shrink-0 text-ink-3" /><span className="truncate text-sm font-medium">{wb.projectPath?.split(/[\\/]/).pop() ?? brandName}</span></WorkbenchHeader>}
        <ErrorBoundary area="chat" resetKey={location.pathname}>
          {children}
        </ErrorBoundary>
      </main>
      <ErrorBoundary area="crystal" resetKey={location.pathname}>
        {compact ? <PanelDrawer open={showRight} side="right">
          <RightPane onCollapse={() => setRightOpen(false)} compact />
        </PanelDrawer> : <RightPane open={showRight} onCollapse={() => setRightOpen(false)} />}
      </ErrorBoundary>
      {wb.settingsDialog.open && (
        <ErrorBoundary area="settings">
          <SettingsDialog />
        </ErrorBoundary>
      )}
    </div>
    </ChromeControls.Provider>
  );
}
