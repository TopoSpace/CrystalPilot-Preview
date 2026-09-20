import {
  BrowserRouter,
  Link,
  Route,
  Routes,
  useSearchParams,
} from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { ErrorBoundary } from "./components/ErrorBoundary";
import LegacyHome from "./legacy/pages/Home";
import LegacyRunView from "./legacy/pages/RunView";
import { ThemeProvider } from "./lib/theme";
import { t } from "./lib/i18n";
import { ProjectHome } from "./workbench/ProjectHome";
import { ThreadView } from "./workbench/ThreadView";
import { WelcomeView } from "./workbench/WelcomeView";
import { WorkbenchLayout } from "./workbench/WorkbenchLayout";

/** "/" renders the welcome hero without ?project=, the project home with. */
function HomeSwitch() {
  const [params] = useSearchParams();
  const project = params.get("project");
  return project ? (
    <ProjectHome key={project} project={project} />
  ) : (
    <WelcomeView />
  );
}

function NotFound() {
  return (
    <div className="flex h-dvh flex-col items-center justify-center gap-2 bg-bg text-ink">
      <div className="text-base font-medium">{t.notFound}</div>
      <Link to="/" className="text-sm font-medium text-accent hover:underline">
        {t.backHome}
      </Link>
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <ErrorBoundary
          area="app"
          className="flex h-dvh flex-col justify-center gap-2 bg-bg p-8 text-sm text-ink"
        >
          <Routes>
            <Route element={<WorkbenchLayout />}>
              <Route path="/" element={<HomeSwitch />} />
              <Route path="/thread/:threadId" element={<ThreadView />} />
            </Route>
            <Route
              path="/legacy"
              element={
                <AppShell>
                  <LegacyHome />
                </AppShell>
              }
            />
            <Route
              path="/legacy/runs/:id"
              element={
                <AppShell>
                  <LegacyRunView />
                </AppShell>
              }
            />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </ErrorBoundary>
      </BrowserRouter>
    </ThemeProvider>
  );
}
