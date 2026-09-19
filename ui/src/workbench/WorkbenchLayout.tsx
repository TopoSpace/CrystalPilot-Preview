/** Layout route for the workbench: providers + 3-col shell + URL→project sync
 * (the ?project= query param is the source of truth for the open project).
 *
 * Provider nesting (outermost first):
 *   ViewModeProvider - global 简洁/详细 display density (localStorage)
 *   WorkbenchProvider - project/threads/settings
 *   ComposerDraftProvider - crystal-pane → composer snippet bridge
 *   MaybeThreadProvider - ThreadProvider when the route is /thread/:threadId,
 *     lifted here so BOTH the chat column and the right (crystal) pane see
 *     thread state (crystalSignal, usage, artifacts, approvals)
 *   CrystalProvider - project-scoped crystal pane state
 */
import { useEffect, useRef, type ReactNode } from "react";
import { matchPath, Outlet, useLocation, useSearchParams } from "react-router-dom";
import { ComposerDraftProvider } from "../state/ComposerDraft";
import { CrystalProvider } from "../state/CrystalProvider";
import { ThreadProvider } from "../state/ThreadProvider";
import { ViewModeProvider } from "../state/ViewMode";
import { useWorkbench, WorkbenchProvider } from "../state/WorkbenchProvider";
import { WorkbenchShell } from "./WorkbenchShell";

function normPath(p: string): string {
  return p.replaceAll("\\", "/").replace(/\/+$/, "").toLowerCase();
}

function ProjectUrlSync() {
  const wb = useWorkbench();
  const [params] = useSearchParams();
  const urlProject = params.get("project");
  const attemptedRef = useRef<string | null>(null);

  const current = wb.projectPath;
  useEffect(() => {
    if (!urlProject) return;
    if (current !== null && normPath(current) === normPath(urlProject)) return;
    if (attemptedRef.current === urlProject) return; // avoid retry loops
    attemptedRef.current = urlProject;
    void wb.openProject(urlProject);
  }, [urlProject, current, wb]);

  return null;
}

function MaybeThreadProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [params] = useSearchParams();
  const match = matchPath("/thread/:threadId", location.pathname);
  const threadId = match?.params.threadId ?? null;
  const project = params.get("project");

  if (!threadId) return <>{children}</>;
  return (
    <ThreadProvider key={threadId} threadId={threadId} project={project}>
      {children}
    </ThreadProvider>
  );
}

function CrystalScope({ children }: { children: ReactNode }) {
  const wb = useWorkbench();
  return (
    <CrystalProvider key={wb.projectPath ?? ""} project={wb.projectPath}>
      {children}
    </CrystalProvider>
  );
}

export function WorkbenchLayout() {
  return (
    <ViewModeProvider>
      <WorkbenchProvider>
        <ProjectUrlSync />
        <ComposerDraftProvider>
          <MaybeThreadProvider>
            <CrystalScope>
              <WorkbenchShell>
                <Outlet />
              </WorkbenchShell>
            </CrystalScope>
          </MaybeThreadProvider>
        </ComposerDraftProvider>
      </WorkbenchProvider>
    </ViewModeProvider>
  );
}
