/** Typed fetch client for the workbench API (crystalpilot/workbench/routes.py).
 *
 * Windows paths always travel in query strings / JSON bodies; query values go
 * through URLSearchParams (i.e. encodeURIComponent) - never in URL path
 * segments.
 */
import type {
  ApprovalDecisionChoice,
  ArtifactEntry,
  AttachmentRef,
  DataBlockResponse,
  GlobalConfig,
  HealthResponse,
  KernelInfo,
  ModelListResponse,
  ProviderInfo,
  ProviderTestResult,
  ProviderAuthMode,
  SkillInfo,
  SubagentMode,
  NodesResponse,
  NodeComparisonResponse,
  OpenProjectResponse,
  PendingApproval,
  PeaksResponse,
  AnalysisResponse,
  AnalysisJob,
  VoidsResponse,
  ProjectSettings,
  ProjectStatus,
  RecentProject,
  SceneResponse,
  SendResponse,
  SteerResponse,
  ThreadMeta,
  TranscriptResponse,
  UploadedFile,
  ProjectUsage,
  CleanupPlanResponse,
} from "./wbTypes";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined) sp.set(k, String(v));
  }
  return sp.toString();
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body: unknown = await res.json();
      if (body && typeof body === "object" && "detail" in body) {
        const d = (body as { detail: unknown }).detail;
        // FastAPI validation errors ship detail as an object array
        detail = typeof d === "string" ? d : JSON.stringify(d);
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

function post<T>(url: string, body: unknown): Promise<T> {
  return request<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------- projects

export function openProject(
  path: string,
  autoApprove?: boolean,
): Promise<OpenProjectResponse> {
  return post("/api/projects/open", {
    path,
    ...(autoApprove !== undefined ? { auto_approve: autoApprove } : {}),
  });
}

export function importStructureDocument(project: string, file: File, block?: string): Promise<{
  project: string;
  node: string;
  mode: "structure_only";
}> {
  const form = new FormData();
  form.set("project", project);
  form.set("file", file);
  if (block?.trim()) form.set("block", block.trim());
  return request("/api/projects/import-structure", { method: "POST", body: form });
}

export function recentProjects(): Promise<RecentProject[]> {
  return request(`/api/projects/recent`);
}

export function projectsStatus(): Promise<ProjectStatus[]> {
  return request(`/api/projects/status`);
}

/** Directory usage by category + what a cleanup would reclaim (dry run). */
export function projectUsage(path: string): Promise<ProjectUsage> {
  return request(`/api/projects/usage?${qs({ path })}`);
}

/** apply=false: the plan only. apply=true: execute it (409 while a turn runs). */
export function projectCleanup(path: string, apply: boolean, includeCache = false): Promise<CleanupPlanResponse> {
  return post("/api/projects/cleanup", { path, apply, include_cache: includeCache });
}

export function getSettings(path: string): Promise<ProjectSettings> {
  return request(`/api/projects/settings?${qs({ path })}`);
}

export interface SettingsUpdateBody {
  /** sidebar display name; null / "" clears back to the directory name */
  display_name?: string | null;
  allow_iucr_upload?: boolean;
  enable_specialists?: boolean;
  model_override?: string | null;
  effort_override?: string | null;
  /** the provider NEW threads (and forks) start on; null = config default */
  model_provider_override?: string | null;
  /** owner-declared structure class; null clears it */
  structure_class?: string | null;
  /** the sub-agent switch: auto | on | off */
  subagents?: SubagentMode;
  /** ka1 ablation arm ("full" | "tools_only"); 409 while a turn runs */
  knowledge_mode?: string;
  /** per-project context controls; null clears */
  context_window_override?: number | null;
  auto_compact_token_limit?: number | null;
}

export interface SettingsPatch {
  permission_mode?: string;
  /** plain per-project flags (server persists to .crystalpilot-workbench.json) */
  settings?: SettingsUpdateBody;
}

export function setSettings(
  path: string,
  patch: SettingsPatch,
): Promise<ProjectSettings> {
  return post("/api/projects/settings", { path, ...patch });
}

/** Rebuild the project's engine after an MCP transport death (mcp_down).
 * 409 while a turn is running. */
export function restartEngine(path: string): Promise<ProjectSettings> {
  return post("/api/projects/restart_engine", { path });
}

/** Server health incl. the served-bundle stamp (settings menu build line). */
export function health(): Promise<HealthResponse> {
  return request(`/api/health`);
}

// ------------------------------------------------- kernel / providers / models

export function getKernel(): Promise<KernelInfo> {
  return request(`/api/kernel`);
}

export function listProviders(): Promise<{ providers: ProviderInfo[]; default: string | null; config_path: string }> {
  return request(`/api/providers`);
}

export interface ProviderUpsertBody {
  id: string;
  name?: string | null;
  base_url: string;
  wire_api?: string;
  /** Omit for legacy auth preservation; new providers choose an explicit mode. */
  auth_mode?: Exclude<ProviderAuthMode, "legacy">;
  env_key?: string | null;
  /** Blank / omitted keeps the managed key; removal is explicit. */
  api_key?: string | null;
  remove_api_key?: boolean;
  http_headers?: Record<string, string> | null;
  env_http_headers?: Record<string, string> | null;
  query_params?: Record<string, string> | null;
  request_max_retries?: number | null;
  stream_max_retries?: number | null;
  stream_idle_timeout_ms?: number | null;
}

export function upsertProvider(body: ProviderUpsertBody): Promise<ProviderInfo> {
  return post("/api/providers", body);
}

export function deleteProvider(id: string): Promise<{ removed: boolean; id: string; key_parked: string | null }> {
  return request(`/api/providers/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function testProvider(body: {
  id?: string | null;
  base_url?: string | null;
  api_key?: string | null;
  http_headers?: Record<string, string> | null;
  query_params?: Record<string, string> | null;
}): Promise<ProviderTestResult> {
  return post("/api/providers/test", body);
}

export function setDefaultProvider(id: string): Promise<{ model_provider: string }> {
  return post("/api/providers/default", { id });
}

export function listModels(provider?: string | null, refresh = false): Promise<ModelListResponse> {
  return request(`/api/models?${qs({ provider: provider ?? undefined, refresh: refresh ? 1 : undefined })}`);
}

export function getGlobalConfig(): Promise<GlobalConfig> {
  return request(`/api/config`);
}

export function setGlobalConfig(patch: Partial<Record<
  "model" | "model_provider" | "model_reasoning_effort" | "model_reasoning_summary"
  | "model_context_window" | "model_auto_compact_token_limit", string | number | null>>): Promise<GlobalConfig> {
  return post("/api/config", patch);
}

// ---------------------------------------------- codex-backed thread operations

export function compactThread(threadId: string, project?: string | null): Promise<{ ok: boolean }> {
  return post("/api/threads/compact", { thread_id: threadId, project: project ?? null });
}

export function renameThread(threadId: string, title: string, project?: string | null): Promise<{ thread: ThreadMeta; threads: ThreadMeta[] }> {
  return post("/api/threads/rename", { thread_id: threadId, title, project: project ?? null });
}

export function forkThread(threadId: string, project?: string | null, title?: string | null): Promise<{ thread_id: string; task_id: string; threads: ThreadMeta[] }> {
  return post("/api/threads/fork", { thread_id: threadId, project: project ?? null, title: title ?? null });
}

export function listSkills(project: string): Promise<{ skills: SkillInfo[] }> {
  return request(`/api/skills?${qs({ project })}`);
}

export function mcpStatus(project: string): Promise<{ present: boolean; n_tools: number; error: string | null }> {
  return post("/api/projects/mcp_status", { path: project });
}

/** The operating system's folder dialog on the server machine (a local
 * app: same desktop). null when cancelled. */
export function pickFolder(title?: string, initial?: string | null): Promise<{ path: string | null; cancelled: boolean; error?: string }> {
  return post("/api/system/pick_folder", { title: title ?? null, initial: initial ?? null });
}

export function projectFeedUrl(project: string, after = 0): string {
  return `/api/projects/feed?${qs({ path: project, after })}`;
}

export async function uploadFiles(
  path: string,
  files: File[],
): Promise<{ files: UploadedFile[] }> {
  const form = new FormData();
  form.set("path", path);
  for (const f of files) form.append("files", f, f.name);
  return request("/api/projects/upload", { method: "POST", body: form });
}

export interface FramesProbe {
  path: string;
  n_frames: number;
  by_ext: Record<string, number>;
  n_other_files: number;
  total_MB: number;
  sample: string[];
  ok: boolean;
  note: string | null;
}

/** Validate a local raw-frames directory server-side (frames are NOT
 * uploaded; the staged import_frames tool reads them in place). */
export function probeFramesDir(path: string): Promise<FramesProbe> {
  return request(`/api/projects/frames_probe?path=${encodeURIComponent(path)}`);
}

// ----------------------------------------------------------------- threads

export function sendMessage(args: {
  project: string;
  message: string;
  thread_id?: string;
  title?: string;
  attachments?: AttachmentRef[];
}): Promise<SendResponse> {
  // 409 while a turn is running on the thread
  return post("/api/threads/send", args);
}

export function steerThread(
  threadId: string,
  message: string,
  attachments?: AttachmentRef[],
): Promise<SteerResponse> {
  // 409 when the thread is idle - caller should send() instead
  return post("/api/threads/steer", {
    thread_id: threadId,
    message,
    ...(attachments && attachments.length > 0 ? { attachments } : {}),
  });
}

export function interruptThread(
  threadId: string,
): Promise<{ interrupted: boolean }> {
  return post("/api/threads/interrupt", { thread_id: threadId });
}

export function listThreads(project: string): Promise<{ threads: ThreadMeta[] }> {
  return request(`/api/threads/list?${qs({ project })}`);
}

export function getTranscript(
  threadId: string,
  project?: string,
  page?: { before?: number; limit?: number },
): Promise<TranscriptResponse> {
  return request(
    `/api/threads/transcript?${qs({
      thread_id: threadId,
      project,
      before: page?.before,
      limit: page?.limit,
    })}`,
  );
}

/** Full stored output of one shell command (the event carries a tail). */
export async function getCommandOutput(
  threadId: string,
  itemId: string,
  project?: string,
): Promise<string> {
  const res = await fetch(
    `/api/threads/command_output?${qs({ thread_id: threadId, item_id: itemId, project })}`,
  );
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return res.text();
}

export function getArtifacts(threadId: string): Promise<ArtifactEntry[]> {
  return request(`/api/threads/artifacts?${qs({ thread_id: threadId })}`);
}

/** SSE endpoint URL for one thread channel. */
export function eventsUrl(threadId: string, after = 0, project?: string | null): string {
  // the project rides along so the server can index a thread it has not
  // seen in this process instead of answering 404 (a dead channel)
  return `/api/threads/events?${qs({ thread_id: threadId, after, project: project ?? undefined })}`;
}

// --------------------------------------------------------------- approvals

export function getApprovals(path: string): Promise<PendingApproval[]> {
  return request(`/api/approvals?${qs({ path })}`);
}

export function decideApproval(
  approvalId: string,
  decision: ApprovalDecisionChoice,
): Promise<{ ok: boolean }> {
  return post("/api/approvals/decide", {
    approval_id: approvalId,
    decision,
  });
}

// ------------------------------------------------- refinement pane (P2 prep)

export function getRefineNodes(project: string): Promise<NodesResponse> {
  return request(`/api/wb/refine/nodes?${qs({ project })}`);
}

export function getRefineComparison(
  project: string,
  node: string,
  baseline: string,
  signal?: AbortSignal,
): Promise<NodeComparisonResponse> {
  return request(`/api/wb/refine/comparison?${qs({ project, node, baseline })}`, { signal });
}

export function refineFileUrl(
  project: string,
  node: string,
  name: "model.cif" | "model.res",
): string {
  return `/api/wb/refine/file?${qs({ project, node, name })}`;
}

export function refineSceneUrl(
  project: string,
  node: string,
  opts?: {
    mode?: string;
    n?: number;
    hops?: number;
    polyhedra?: 0 | 1;
    diff?: 0 | 1;
    /** diff against this node instead of the parent (any-vs-any) */
    vs?: string;
    /** JSON [{i, op}] of user-grown instances (clicked grow stubs) */
    extra?: string;
    /** include short vdW contacts + contact grow stubs (Olex2 grow -s) */
    contacts?: 0 | 1;
    /** Olex2 grow -w */
    complete?: 0 | 1;
    grow_all?: 0 | 1;
    /** attach the interaction layer (R2.3) */
    interactions?: 0 | 1;
    /** mode=radius: sphere radius (Å) and the ASU atom at its centre */
    radius?: number;
    center?: string;
    /** mode=range: fractional box "a,b,c" */
    lo?: string;
    hi?: string;
  },
): string {
  return `/api/wb/refine/scene?${qs({ project, node, ...opts })}`;
}

export type MapKind = "fofc" | "2fofc";

export function refineMapUrl(
  project: string,
  node: string,
  kind: MapKind = "fofc",
): string {
  return `/api/wb/refine/map?${qs({ project, node, kind })}`;
}

export function getRefineScene(
  project: string,
  node: string,
  opts: {
    mode?: string;
    n?: number;
    hops?: number;
    polyhedra?: 0 | 1;
    diff?: 0 | 1;
    vs?: string;
    extra?: string;
    contacts?: 0 | 1;
    complete?: 0 | 1;
    grow_all?: 0 | 1;
    /** attach the interaction layer (R2.3) */
    interactions?: 0 | 1;
    radius?: number;
    center?: string;
    lo?: string;
    hi?: string;
  },
  signal?: AbortSignal,
): Promise<SceneResponse> {
  return request(refineSceneUrl(project, node, opts), { signal });
}

/** Fo−Fc / 2Fo−Fc CCP4 map as a raw buffer (~MBs; first build per node
 * pays the compute, then disk-cached). */
export async function getRefineMap(
  project: string,
  node: string,
  kind: MapKind = "fofc",
  signal?: AbortSignal,
): Promise<ArrayBuffer> {
  const res = await fetch(refineMapUrl(project, node, kind), { signal });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return res.arrayBuffer();
}

/** Void metadata (count / volumes / electron counts / centres). */
export function getRefineVoids(
  project: string,
  node: string,
  signal?: AbortSignal,
): Promise<VoidsResponse> {
  return request(`/api/wb/refine/voids?${qs({ project, node })}`, { signal });
}

/** Per-node analysis product (R3.5): canonical interaction tables with
 * criteria + h_source, the node's pores, pending blocks with notes.
 * Built lazily server-side and cached next to voids.json. */
export function getRefineAnalysis(
  project: string,
  node: string,
  signal?: AbortSignal,
): Promise<AnalysisResponse> {
  return request(`/api/wb/refine/analysis?${qs({ project, node })}`, { signal });
}

export function startRefineAnalysis(project: string, node: string, observerId?: string, signal?: AbortSignal): Promise<AnalysisJob> {
  return request("/api/wb/refine/analysis/jobs", { method: "POST", signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project, node, observer_id: observerId }) });
}

export function pollRefineAnalysis(project: string, jobId: string, resultRevision?: number, signal?: AbortSignal): Promise<AnalysisJob> {
  return request(`/api/wb/refine/analysis/jobs/${encodeURIComponent(jobId)}?${qs({
    project, since_result_revision: resultRevision,
  })}`, { signal });
}

export function cancelRefineAnalysis(project: string, jobId: string, observerId: string): Promise<AnalysisJob> {
  return post(`/api/wb/refine/analysis/jobs/${encodeURIComponent(jobId)}/cancel`, {
    project, observer_id: observerId,
  });
}

export function releaseRefineAnalysis(project: string, jobId: string, observerId: string): Promise<unknown> {
  return request(`/api/wb/refine/analysis/jobs/${encodeURIComponent(jobId)}/release`, {
    method: "POST", keepalive: true, headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project, observer_id: observerId }),
  });
}

export async function getRefineTopology(project: string, node: string, signal?: AbortSignal): Promise<AnalysisResponse["topology"]> {
  let job = await startRefineAnalysis(project, node, undefined, signal);
  const observer = job.observer_id;
  let result = job.result;
  try {
    for (;;) {
      if (job.stages.topology.status === "ready") {
        if (!result?.topology) throw new Error("Topology marked ready without a result");
        return result.topology;
      }
      if (["error", "unsupported", "cancelled"].includes(job.stages.topology.status)) {
        throw new Error(job.stages.topology.error ?? job.stages.topology.note ?? "Topology unavailable");
      }
      await new Promise<void>((resolve, reject) => {
        const cancel = () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); };
        const timer = setTimeout(() => { signal?.removeEventListener("abort", cancel); resolve(); }, 500);
        if (signal?.aborted) cancel();
        else signal?.addEventListener("abort", cancel, { once: true });
      });
      job = await pollRefineAnalysis(project, job.job_id, job.result_revision, signal);
      result = job.result ?? result;
    }
  } finally {
    if (observer) void releaseRefineAnalysis(project, job.job_id, observer).catch(() => undefined);
  }
}

export function getValidationSource(project: string, cif: string, signal?: AbortSignal): Promise<{
  source: import("./checkcif").CheckcifSource | null;
  status: "recorded" | "missing";
}> {
  return request(`/api/wb/refine/validation-source?${qs({ project, cif })}`, { signal });
}

/** Reflection-data block for one node (Rint / d_min / completeness / …).
 *
 * Separate from the node list on purpose: nodes committed before the data
 * block existed carry `data: null`, and the numbers are recoverable, but
 * only by merging the reflection file - which is far too expensive to do
 * for every node in a 70-node tree on every poll. So it is fetched for the
 * one node being looked at, and only when that node has no record. */
export function getRefineData(
  project: string,
  node: string,
  signal?: AbortSignal,
): Promise<DataBlockResponse> {
  return request(`/api/wb/refine/data?${qs({ project, node })}`, { signal });
}

/** Binarized whole-cell void mask (CCP4) for isosurface display. */
export async function getRefineVoidMap(
  project: string,
  node: string,
  signal?: AbortSignal,
): Promise<ArrayBuffer> {
  const res = await fetch(
    `/api/wb/refine/voidmap?${qs({ project, node })}`,
    { signal },
  );
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return res.arrayBuffer();
}

/** Q-peak table (computed alongside the map by the same one-shot session). */
export function getRefinePeaks(
  project: string,
  node: string,
  signal?: AbortSignal,
): Promise<PeaksResponse> {
  return request(`/api/wb/refine/peaks?${qs({ project, node })}`, { signal });
}

export function artifactUrl(path: string): string {
  return `/api/wb/artifact?${qs({ path })}`;
}
