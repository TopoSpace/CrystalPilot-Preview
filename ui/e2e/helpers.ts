/** Shared helpers for the Playwright evidence tests. */
import type { APIRequestContext, Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export type Theme = "light" | "dark";
export const THEMES: Theme[] = ["light", "dark"];

/** Evidence round label: screenshots go to workdir/ui-evidence/<round>/. */
export const ROUND = process.env.CP_EVIDENCE_ROUND ?? "r0";
const here = path.dirname(fileURLToPath(import.meta.url));
export const EVIDENCE_DIR = path.resolve(here, "..", "..", "workdir", "ui-evidence", ROUND);

export function shotPath(name: string): string {
  fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
  return path.join(EVIDENCE_DIR, `${name}.png`);
}

/** Theme is read from localStorage before first paint (ui/index.html). */
export async function setTheme(page: Page, theme: Theme): Promise<void> {
  await page.addInitScript((t: string) => {
    localStorage.setItem("crystalpilot-theme", t);
  }, theme);
}

export interface Target {
  project: string;
  threadId: string;
}

interface StatusRow {
  path: string;
  n_nodes?: number;
  is_open?: boolean;
}

/** Pick a real project with a node tree: CP_E2E_PROJECT if set, else the
 * most recent project on the status board that has nodes. Returns null when
 * nothing usable exists (tests skip rather than fabricate). */
export async function pickTarget(request: APIRequestContext): Promise<Target | null> {
  const wanted = process.env.CP_E2E_PROJECT;
  const st = await request.get("/api/projects/status");
  if (!st.ok()) return null;
  const rows = (await st.json()) as StatusRow[];
  // the status board reports Windows paths with backslashes; the env var
  // is usually typed with slashes - compare slash- and case-insensitively
  const norm = (s: string) => s.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  const candidates = wanted
    ? rows.filter((r) => norm(r.path) === norm(wanted))
    : rows.filter((r) => (r.n_nodes ?? 0) > 0);
  for (const row of candidates) {
    const th = await request.get(`/api/threads/list?project=${encodeURIComponent(row.path)}`);
    if (!th.ok()) continue;
    const body = (await th.json()) as { threads?: { thread_id: string }[] };
    const first = body.threads?.[0];
    if (first) return { project: row.path, threadId: first.thread_id };
  }
  return null;
}

export function projectUrl(project: string): string {
  return `/?project=${encodeURIComponent(project)}`;
}

export function threadUrl(t: Target): string {
  return `/thread/${encodeURIComponent(t.threadId)}?project=${encodeURIComponent(t.project)}`;
}

export interface ErrorLog {
  pageErrors: string[];
  consoleErrors: string[];
  gpuNoise: string[];
  /** 404s for `/api/wb/artifact?path=<absolute path outside the open
   * project>`. The regression copies under H:\cp-pytest-tmp keep the
   * original transcripts, whose image links carry the original project's
   * absolute path; the artifact route refuses paths outside the open
   * project, which is the intended behaviour, so these are reported here
   * and not as console errors. (A moved project shows the same broken
   * thumbnails: tracked in docs/OPTIMIZATION-BACKLOG-2026-09-16.md.) */
  foreignArtifactLinks: string[];
}

function foreignArtifactLink(url: string): boolean {
  const m = /\/api\/wb\/artifact\?path=([^&]+)/.exec(url);
  if (!m) return false;
  const project = (process.env.CP_E2E_PROJECT ?? "").replace(/\\/g, "/").toLowerCase();
  const path = decodeURIComponent(m[1]).replace(/\\/g, "/").toLowerCase();
  return project !== "" && !path.startsWith(project);
}

/** Collect uncaught page errors and console errors (WebGL/GPU noise from the
 * software renderer is reported separately, not counted). */
export function watchErrors(page: Page): ErrorLog {
  const log: ErrorLog = { pageErrors: [], consoleErrors: [], gpuNoise: [], foreignArtifactLinks: [] };
  page.on("pageerror", (e) => log.pageErrors.push(String(e)));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const text = m.text();
    const url = m.location().url;
    if (/webgl|gpu|swiftshader|angle/i.test(text)) log.gpuNoise.push(text);
    else if (/Failed to load resource/.test(text) && foreignArtifactLink(url)) log.foreignArtifactLinks.push(url);
    else log.consoleErrors.push(text);
  });
  return log;
}
