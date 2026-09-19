/** A detached SHELXT must be visible while it runs and after it finishes,
 * even though no turn is running (2026-09-18: two NU-1000 turns were
 * stopped by the user 13 minutes into an invisible space-group search).
 *
 * The spec plants a synthetic job under the COPY project's
 * .crystalpilot/refine/shelxt/ (registry + progress.json + a real SHELXT
 * log truncated in the search stage, pid = this test runner so the service
 * sees a live process), then lets the service's watcher pick it up. No model
 * is called; the job files are removed afterwards. Run from ui/:
 *   CP_E2E_PROJECT=<copy> CP_SOL_THREAD=<thread> npx playwright test e2e/background-job.pw.ts */
import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { pickTarget, shotPath, threadUrl, watchErrors, type Target } from "./helpers";

const JOB = "job_e2e_bg";

const LXT_SEARCHING = `
 Command line parameters:  -t4 -d1 job

  4 threads running in parallel

 -a set to extend space group search because atom heavier than Sc expected

 Laue group identified as number 12:   6/mmm

  Try N(iter)  CC   R(weak)   CHEM    CFOM    best  Sig(min) N(P1) Vol/N
    1   100   87.76  0.1480  0.7957  0.7297  0.7297  2.161   618   35.75
    2   100   86.72  0.1380  0.7043  0.7292  0.7297  2.329   640   34.52
    3   100   87.05  0.1399  0.7446  0.7306  0.7306  2.315   628   35.18
    4   100   87.33  0.1452  0.7185  0.7282  0.7306  2.262   592   37.32

       4 attempts, solution  3 selected with best CFOM = 0.7306, Alpha0 = 0.185

 Structure solution:      12.000 secs
`;
const LXT_TAIL = `
   4 Centrosymmetric and  14 non-centrosymmetric space groups evaluated

 Space group determination:      90.000 secs

 Assign elements and isotropic refinement    10.000 secs

 +  SHELXT finished at 17:00:32    Total time:      112.000 secs  +
`;

function shelxtDir(project: string): string {
  return path.join(project, ".crystalpilot", "refine", "shelxt");
}

interface Planted { base: string; job: string; registry: string; backup: string | null }

function plant(project: string): Planted {
  const base = shelxtDir(project);
  const job = path.join(base, JOB);
  fs.mkdirSync(job, { recursive: true });
  const registry = path.join(base, "_jobs.json");
  const backup = fs.existsSync(registry) ? fs.readFileSync(registry, "utf-8") : null;
  const pid = process.pid;
  // psutil's liveness check compares the recorded start with the process
  // start (±120 s): the runner's own uptime gives that to the second
  const t0 = Date.now() / 1000 - process.uptime();
  const budget = { timeout_s: 600, search_grace_s: 900, phasing_grace_s: 600 };
  fs.writeFileSync(path.join(job, "job.lxt"), LXT_SEARCHING, "utf-8");
  fs.writeFileSync(path.join(job, "progress.json"), JSON.stringify({
    detached: true, job: JOB, job_dir: job, pid, started_at: new Date(t0 * 1000).toISOString().slice(0, 19),
    started_at_epoch: t0, budget, stage: "space-group search", running: true,
    updated_at: new Date().toISOString().slice(0, 19), elapsed_s: 30,
  }, null, 1), "utf-8");
  const data = backup ? (JSON.parse(backup) as { jobs?: unknown[] }) : {};
  const jobs = ((data.jobs ?? []) as { job?: string }[]).filter((j) => j.job !== JOB);
  jobs.push({ job: JOB, job_dir: job, pid, started_at: new Date(t0 * 1000).toISOString().slice(0, 19), cmd: ["synthetic"], stage: "running", budget } as never);
  fs.writeFileSync(registry, JSON.stringify({ ...data, jobs }, null, 1), "utf-8");
  return { base, job, registry, backup };
}

function finish(p: Planted): void {
  fs.writeFileSync(path.join(p.job, "job.lxt"), LXT_SEARCHING + LXT_TAIL, "utf-8");
  fs.writeFileSync(path.join(p.job, "job_a.res"), "TITL job_a\n", "ascii");
  const prog = JSON.parse(fs.readFileSync(path.join(p.job, "progress.json"), "utf-8")) as Record<string, unknown>;
  fs.writeFileSync(path.join(p.job, "progress.json"), JSON.stringify({
    ...prog, stage: "finished", running: false, elapsed_s: 112.0, has_solution: true,
    updated_at: new Date().toISOString().slice(0, 19), next: `run_shelxt(from_job='${JOB}') adopts the solution`,
  }, null, 1), "utf-8");
  const reg = JSON.parse(fs.readFileSync(p.registry, "utf-8")) as { jobs: { job: string }[] };
  const rec = reg.jobs.find((j) => j.job === JOB) as Record<string, unknown> | undefined;
  if (rec) Object.assign(rec, { stage: "finished", finished_at: new Date().toISOString().slice(0, 19), elapsed_s: 112.0 });
  fs.writeFileSync(p.registry, JSON.stringify(reg, null, 1), "utf-8");
}

function cleanup(p: Planted | null): void {
  if (!p) return;
  fs.rmSync(p.job, { recursive: true, force: true });
  if (p.backup === null) fs.rmSync(p.registry, { force: true });
  else fs.writeFileSync(p.registry, p.backup, "utf-8");
}

test.describe("detached solver job visibility", () => {
  let target: Target | null = null;
  let planted: Planted | null = null;
  test.beforeAll(async ({ request }) => {
    target = await pickTarget(request);
    if (target && process.env.CP_SOL_THREAD) target = { ...target, threadId: process.env.CP_SOL_THREAD };
    if (!target || !fs.existsSync(target.project)) { target = null; return; }
    planted = plant(target.project);
    // the watcher looks for new jobs every 10 s while idle; re-opening the
    // (already open) project is a no-op that keeps the session warm
    await request.post("/api/projects/open", { data: { path: target.project } });
  });
  test.afterAll(() => cleanup(planted));

  test("running after the turn: system row + rail; finished: asks for adoption", async ({ page }) => {
    test.skip(target === null, "no project with a thread on this machine");
    const errors = watchErrors(page);
    await page.goto(threadUrl(target!));
    const row = page.getByTestId("background-job-row");
    await expect(row).toHaveCount(1, { timeout: 30_000 });
    await expect(row).toHaveAttribute("data-running", "true");
    await expect(row).toContainText("SHELXT 后台求解");
    await expect(row).toContainText("空间群搜索");
    await expect(row).toContainText("不输出任何内容");
    const rail = page.getByTestId("status-rail");
    await expect(rail).toHaveAttribute("data-state", "background", { timeout: 10_000 });
    const action = page.getByTestId("rail-action");
    await expect(action).toContainText("SHELXT 后台求解");
    await expect(action).toContainText("回合已结束，后台仍在求解");
    await row.scrollIntoViewIfNeeded();
    await page.screenshot({ path: shotPath("background-job-running") });

    // the tool process finishes the job (files only) - the watcher polls
    // every 3 s while a job runs
    finish(planted!);
    await expect(row).toHaveAttribute("data-running", "false", { timeout: 20_000 });
    await expect(row).toContainText("已完成");
    await expect(row).toContainText("尚未采用");
    await expect(row).toContainText(`run_shelxt(from_job='${JOB}')`);
    await expect(rail).not.toHaveAttribute("data-state", "background");
    await expect(action).toContainText("SHELXT 求解已完成，待采用");
    await page.screenshot({ path: shotPath("background-job-finished") });

    // a reload rebuilds the same single row from transcript + live snapshot
    await page.reload();
    await expect(page.getByTestId("background-job-row")).toHaveCount(1, { timeout: 30_000 });
    await expect(page.getByTestId("background-job-row")).toContainText("尚未采用");
    expect(errors.pageErrors).toEqual([]);
  });
});
