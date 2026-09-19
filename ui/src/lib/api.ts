/** Typed client for the CrystalPilot FastAPI backend (server/app.py). */

export type RunStatus = "running" | "done" | "failed";

export interface RunSummary {
  ok?: boolean | null;
  space_group?: string | null;
  r1?: number | null;
  confidence?: number | null;
  elapsed_s?: number | null;
}

export interface RunListEntry {
  run_id: string;
  mtime: number;
  status: RunStatus;
  summary?: RunSummary;
}

export interface ValidationAlert {
  severity: string;
  code: string;
  message: string;
}

export interface Confidence {
  score?: number;
  grade?: string;
}

export interface Report {
  run_id?: string;
  ok?: boolean;
  symmetry?: {
    space_group?: string;
    n_unique?: number;
    r_int?: number;
    d_min?: number;
    completeness?: number;
  };
  solution?: Record<string, unknown>;
  interpretation?: {
    n_atoms?: number;
    element_counts?: Record<string, number>;
    note?: string;
  };
  refinement?: {
    mode?: string;
    r1_strong?: number;
    r1_all?: number;
    wr2?: number;
    goof?: number;
    n_params?: number;
    n_strong?: number;
    n_reflections?: number;
    diff_map_max?: number;
    diff_map_min?: number;
    n_atoms?: number;
  };
  validation?: {
    n_alerts?: number;
    alerts?: ValidationAlert[];
    framework_dimensionality?: number | null;
    largest_fragment?: {
      n_atoms?: number;
      dimensionality?: number;
      elements?: Record<string, number>;
    };
    confidence?: Confidence;
  };
  elapsed_s?: number;
  refinement_history?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

export interface RunDetail {
  run_id: string;
  status: RunStatus;
  report: Report | null;
  error: string | null;
  has_cif: boolean;
}

export interface EventPayload {
  stage?: string;
  tool?: string;
  params?: Record<string, unknown>;
  ok?: boolean;
  elapsed_s?: number;
  summary?: Record<string, unknown>;
  error?: string | null;
  step?: number;
  text?: string;
  status?: string;
  assessment?: string;
  rationale?: string;
  comment?: string;
  space_group?: string;
  n_unique?: number;
  r_int?: number;
  dataset?: {
    n_reflections?: number;
    unit_cell?: number[];
    cell_volume?: number;
    wavelength?: number;
    d_min?: number;
    d_max?: number;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface RunEvent {
  event_id: string;
  ts: number;
  kind: string;
  payload: EventPayload;
}

export interface EventsResponse {
  events: RunEvent[];
  next: number;
}

export interface SolveRequest {
  hkl_path: string;
  ins_path: string | null;
  mode: "auto" | "copilot" | "standard";
  symmetry: "auto" | "hint";
}

export interface ApprovalRequest {
  event_id: string;
  approve: boolean;
  comment: string;
}

async function toJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = "";
    try {
      const body: unknown = await res.json();
      if (
        body &&
        typeof body === "object" &&
        typeof (body as { detail?: unknown }).detail === "string"
      ) {
        detail = (body as { detail: string }).detail;
      }
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail || `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export async function uploadFiles(files: File[]): Promise<{ paths: string[] }> {
  const form = new FormData();
  for (const f of files) form.append("files", f, f.name);
  return toJson(await fetch("/api/upload", { method: "POST", body: form }));
}

export async function startSolve(req: SolveRequest): Promise<{ run_id: string }> {
  return toJson(
    await fetch("/api/solve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),
  );
}

export async function fetchRuns(signal?: AbortSignal): Promise<RunListEntry[]> {
  return toJson(await fetch("/api/runs", { signal }));
}

export async function fetchRun(
  runId: string,
  signal?: AbortSignal,
): Promise<RunDetail> {
  return toJson(await fetch(`/api/runs/${runId}`, { signal }));
}

export async function fetchEvents(
  runId: string,
  after: number,
  signal?: AbortSignal,
): Promise<EventsResponse> {
  return toJson(
    await fetch(`/api/runs/${runId}/events?after=${after}`, { signal }),
  );
}

export async function approveAction(
  runId: string,
  req: ApprovalRequest,
): Promise<{ ok: boolean }> {
  return toJson(
    await fetch(`/api/runs/${runId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),
  );
}

export function cifUrl(runId: string): string {
  return `/api/runs/${runId}/cif`;
}

export async function fetchCif(
  runId: string,
  signal?: AbortSignal,
): Promise<string> {
  const res = await fetch(cifUrl(runId), { signal });
  if (!res.ok) {
    throw new Error(
      res.status === 404 ? "No CIF is available for this run yet." : res.statusText,
    );
  }
  return res.text();
}
