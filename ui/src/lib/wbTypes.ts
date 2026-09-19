/** Wire types for the workbench backend (crystalpilot/workbench/routes.py).
 *
 * Every SSE / transcript event carries the base fields; `kind` discriminates.
 * Enum-ish strings can arrive as stringified Python enums
 * ("TurnStatus.completed", "CommandExecutionStatus.in_progress") - use
 * `normalizeEnum` before comparing.
 */

export interface TokenCounts {
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
}

interface Base {
  ts: number;
  thread_id?: string;
  task_id?: string;
  /** event identity: 1-based line index in transcript.jsonl (round-3 R1).
   * Absent on live-only events (deltas, fan-out system rows). */
  eid?: number;
}

export interface UserMessageEvent extends Base {
  kind: "user_message";
  text: string;
  steer?: boolean;
  /** display names of files sent with this message */
  attachments?: string[];
}

/** Transcript-only variant of a steered user message. */
export interface UserSteerEvent extends Base {
  kind: "user_steer";
  text: string;
  attachments?: string[];
}

/** round-3 R6: whether a steer REACHED the model (logged right after the
 * user_steer it refers to; the words themselves are never lost). */
export interface SteerReceiptEvent extends Base {
  kind: "steer_receipt";
  steer_eid?: number;
  status: "submitted" | "failed";
  error?: string;
}

export interface AgentDeltaEvent extends Base {
  kind: "agent_delta";
  delta: string;
}

export interface AgentMessageEvent extends Base {
  kind: "agent_message";
  text: string;
}

export interface ReasoningSummaryEvent extends Base {
  kind: "reasoning_summary";
  text: string;
}

export interface ToolLifecycleEvent extends Base {
  kind: "tool_started" | "tool_updated" | "tool_completed";
  server: string | null;
  tool: string;
  args: unknown;
  status: string | null;
  duration_ms: number | null;
  ok: boolean | null;
  result_tail: string | null;
  error: string | null;
  /** codex item id: pairs a completion with the card it started (tools run
   * concurrently; absent on transcripts written before 2026-09-16) */
  item_id?: string | null;
}

export interface ToolProgressEvent extends Base {
  kind: "tool_progress";
  message: string | null;
  item_id?: string | null;
}

export interface CommandLifecycleEvent extends Base {
  kind: "command_started" | "command_updated" | "command_completed";
  command: string;
  status: string | null;
  exit_code: number | null;
  output_tail: string | null;
  /** codex item id; the full output is fetchable by it when stored */
  item_id?: string;
  /** total aggregated output length at completion */
  output_len?: number;
  /** results-relative file holding the full output, null when not stored */
  output_file?: string | null;
}

/** First message on every SSE connection: which numbering the channel's
 * seq belongs to. A different generation than the one the transcript was
 * fetched under means the server-side channel was recreated. */
export interface ChannelHelloEvent extends Base {
  kind: "channel_hello";
  generation: string;
  seq: number;
  after: number;
  /** oldest seq still buffered server-side; a resume cursor older than
   * oldest-1 means events were lost and the client must re-bootstrap */
  oldest?: number;
}

/** Server heartbeat (every ~15 s, a real data event because SSE comments
 * never reach JavaScript): the client treats a missing ping as a dead
 * connection and reconnects. Not an event of the conversation. */
export interface PingEvent extends Base {
  kind: "ping";
}

/** The server closed this channel (project session released, server
 * shutting down): the client must re-open the project and re-bootstrap. */
export interface ChannelClosedEvent extends Base {
  kind: "channel_closed";
  reason?: string;
}

export interface CommandOutputEvent extends Base {
  kind: "command_output";
  delta: string;
  /** which running command this output belongs to (commands run concurrently) */
  item_id?: string;
}

export interface FileChangeEvent extends Base {
  kind: "file_change_started" | "file_change_completed" | "file_change_updated";
  changes: unknown;
  status: string | null;
  item_id?: string | null;
}

/** NB camelCase item types on the wire. */
export interface WebSearchEvent extends Base {
  kind: "webSearch_started" | "webSearch_completed" | "webSearch_updated";
  detail: unknown;
  item_id?: string | null;
}

export interface TodoListEvent extends Base {
  kind: "todoList_started" | "todoList_completed" | "todoList_updated";
  detail: unknown;
  item_id?: string | null;
}

export interface ErrorItemEvent extends Base {
  kind: "error_started" | "error_completed" | "error_updated";
  detail: unknown;
  item_id?: string | null;
}

/** codex 0.154: the model looking at an image (uploaded or produced). */
export interface ImageViewEvent extends Base {
  kind: "imageView_started" | "imageView_completed" | "imageView_updated";
  detail: unknown;
  item_id?: string | null;
}

export interface TurnStartedEvent extends Base {
  kind: "turn_started";
}

export interface TurnCompletedEvent extends Base {
  kind: "turn_completed";
  duration_ms: number | null;
  status: "completed" | "interrupted" | "failed" | string;
  /** Present when status is failed: provider/turn error message. */
  error?: unknown;
}

export interface TurnFailedEvent extends Base {
  kind: "turn_failed";
  error: unknown;
}

export interface TokenUsageEvent extends Base {
  kind: "token_usage";
  last: TokenCounts | null;
  total: TokenCounts | null;
  context_window: number | null;
}

export interface ApprovalRequestEvent extends Base {
  kind: "approval_request";
  approval_id: string;
  method: string;
  detail: unknown;
  item_id?: string | null;
  mcp_server?: string | null;
  mcp_message?: string | null;
  mcp_tool_params?: unknown;
}

export interface ApprovalDecisionEvent extends Base {
  kind: "approval_decision";
  approval_id: string;
  method: string;
  decision: string;
  auto?: boolean;
}

export interface ApprovalTimeoutEvent extends Base {
  kind: "approval_timeout";
  approval_id: string;
}

export interface ClientErrorEvent extends Base {
  kind: "client_error";
  error: string;
}

export interface IdleEvent extends Base {
  kind: "idle";
  task_id: string;
  artifacts: ArtifactEntry[];
}

export interface PermissionModeEvent extends Base {
  kind: "permission_mode";
  mode: string;
  rebuilt: boolean;
}

/** Project-level: enable_specialists flipped (agent service rebuilt). */
export interface SpecialistsToggledEvent extends Base {
  kind: "specialists_toggled";
  enabled: boolean;
}

/** Project-level (round-2 R7): the delegation tier flipped - AGENTS.md was
 * re-rendered and the per-project read-only roles written or removed. */
export interface DelegationEvent extends Base {
  kind: "delegation";
  active: boolean;
  agents_md?: string;
  roles_written?: string[];
  roles_removed?: string[];
}

/** The whole settings record after any change (browser, CLI, config edit). */
export interface SettingsEvent extends Base {
  kind: "settings";
  settings: ProjectSettings;
}

/** codex-home/config.toml changed on disk (an editor, a script). */
export interface ConfigChangedEvent extends Base {
  kind: "config_changed";
  mtime?: number;
}

/** codex is compacting the conversation (auto, or /compact). */
export interface CompactionEvent extends Base {
  kind: "compaction_started" | "compaction_completed" | "compaction_requested";
  manual?: boolean;
  legacy?: boolean;
}

export interface ThreadStatusEvent extends Base {
  kind: "thread_status";
  status: string;
}

export interface EngineWarningEvent extends Base {
  kind: "engine_warning";
  level: string;
  message: string;
}

export interface ModelReroutedEvent extends Base {
  kind: "model_rerouted";
  from_model: string | null;
  to_model: string | null;
  reason: string;
}

export interface ThreadRenamedEvent extends Base {
  kind: "thread_renamed";
  title: string;
}

export interface BackgroundTurnEvent extends Base {
  kind: "background_turn_completed";
  status: string;
}

/** Client-local note (slash command output such as /status); never on the
 * wire. */
export interface NoteEvent extends Base {
  kind: "note";
  title: string;
  lines: string[];
}

/** MCP transport death detected (2× transport-error signature) - the agent
 * keeps running but every crystalpilot tool call fails until restart. */
export interface McpDownEvent extends Base {
  kind: "mcp_down";
  message?: string;
  action?: string;
}

export interface EngineRestartedEvent extends Base {
  kind: "engine_restarted";
}

/** The service waited for the crystallography MCP before a thread's first
 * turn (round-3 R2-A): waiting -> ready | timeout. Codex's own
 * mcpServer/startupStatus/updated notifications share the kind with a
 * status string of their own. */
export interface McpStartupEvent extends Base {
  kind: "mcp_startup";
  server?: string | null;
  status: string | null;
  n_tools?: number;
  seconds?: number;
  present?: boolean;
  error?: string | null;
}

/** A detached solver job (run_shelxt detach=true) as mirrored by the
 * service from the tool process's files (2026-09-18). `transition`:
 * started / stage / heartbeat / finished / killed / failed / died /
 * adopted / snapshot (the last one is appended to a transcript
 * bootstrap, live only). Persisted transitions carry an eid. */
export interface BackgroundJobEvent extends Base {
  kind: "background_job";
  job: string;
  tool?: string;
  program?: string;
  transition?: string;
  stage: string;
  running: boolean;
  elapsed_s?: number | null;
  started_at?: string | null;
  started_at_epoch?: number | null;
  finished_at?: string | null;
  laue?: string | null;
  tries_done?: number | null;
  best_cfom?: number | null;
  passed_acceptance?: boolean;
  phasing_finished?: boolean;
  phasing_s?: number | null;
  n_space_groups?: number | null;
  auto_a?: boolean;
  exhaustive_search?: boolean;
  search_elapsed_s?: number | null;
  search_reference?: { n_jobs?: number; median_s?: number; max_s?: number } | null;
  search_grace_extended_s?: number | null;
  has_solution?: boolean;
  adopted_at?: string | null;
  error?: string | null;
  next?: string | null;
}

/** Codex multi-agent activity (spawn_agent / wait / send / resume / close),
 * normalised server-side from collabAgentToolCall items (R6 子代理目录). */
export interface CollabEvent extends Base {
  kind: "collab_started" | "collab_updated" | "collab_completed";
  tool: string | null;
  sender: string | null;
  receivers: string[] | null;
  prompt: string | null;
  model: string | null;
  reasoning_effort: string | null;
  status: string | null;
  agents_states: Record<string, { status?: string; message?: string }> | null;
}

export type WbEvent =
  | UserMessageEvent
  | UserSteerEvent
  | SteerReceiptEvent
  | AgentDeltaEvent
  | AgentMessageEvent
  | ReasoningSummaryEvent
  | ToolLifecycleEvent
  | ToolProgressEvent
  | CommandLifecycleEvent
  | CommandOutputEvent
  | FileChangeEvent
  | WebSearchEvent
  | TodoListEvent
  | ErrorItemEvent
  | TurnStartedEvent
  | TurnCompletedEvent
  | TurnFailedEvent
  | TokenUsageEvent
  | ApprovalRequestEvent
  | ApprovalDecisionEvent
  | ApprovalTimeoutEvent
  | ClientErrorEvent
  | IdleEvent
  | PermissionModeEvent
  | SpecialistsToggledEvent
  | DelegationEvent
  | McpDownEvent
  | EngineRestartedEvent
  | McpStartupEvent
  | BackgroundJobEvent
  | CollabEvent
  | SettingsEvent
  | ConfigChangedEvent
  | CompactionEvent
  | ThreadStatusEvent
  | EngineWarningEvent
  | ModelReroutedEvent
  | ThreadRenamedEvent
  | BackgroundTurnEvent
  | NoteEvent
  | ChannelHelloEvent
  | ImageViewEvent
  | PingEvent
  | ChannelClosedEvent;

export type WbEventKind = WbEvent["kind"];

/** "TurnStatus.completed" -> "completed"; passthrough otherwise. */
export function normalizeEnum(s: string | null | undefined): string {
  if (!s) return "";
  const i = s.lastIndexOf(".");
  return i >= 0 ? s.slice(i + 1) : s;
}

// ---------------------------------------------------------------- REST types

export interface ThreadMeta {
  thread_id: string;
  task_id: string;
  title: string;
  created: number;
  last_active: number;
  busy?: boolean;
  /** the provider the thread was started on (absent = the config default) */
  model_provider?: string | null;
  /** the thread this one was forked from (provider switch mid-conversation) */
  forked_from?: string | null;
}

export interface OpenProjectResponse {
  project: string;
  threads: ThreadMeta[];
  results_dirname: string;
  auto_approve: boolean;
}

export type PermissionMode = "readonly" | "copilot" | "auto" | "full";

export const PERMISSION_MODES: PermissionMode[] = [
  "readonly",
  "copilot",
  "auto",
  "full",
];

export interface ProjectSettings {
  path: string;
  permission_mode: PermissionMode;
  /** Sidebar display name (null = directory name); absent on old servers. */
  display_name?: string | null;
  /** Effective model/effort for the next turn (override wins over config). */
  model: string | null;
  effort: string | null;
  /** Optional: absent on servers that predate the IUCr-upload toggle. */
  allow_iucr_upload?: boolean;
  /** Optional: read-only specialist subagents (experimental). */
  enable_specialists?: boolean;
  /** Config.toml defaults + per-project overrides (absent on old servers). */
  model_default?: string | null;
  effort_default?: string | null;
  model_override?: string | null;
  effort_override?: string | null;
  effort_choices?: string[];
  /** owner-declared structure class (small_molecule | macrocycle | cage |
   * framework | salt_cocrystal); null / absent = not declared (the analysis
   * tab suggests one from the product) */
  structure_class?: string | null;
  /** the sub-agent switch (2026-09-07): "auto" = on exactly at the top rung
   * of the model's ladder, "on" / "off" = the user's choice */
  subagents?: SubagentMode;
  subagent_choices?: string[];
  /** ka1 ablation switch: which AGENTS.md template the project runs under
   * ("full" | "tools_only"); absent on old servers */
  knowledge_mode?: string;
  knowledge_modes?: string[];
  /** the server's list of declarable structure classes */
  structure_classes?: string[];
  delegation?: {
    active: boolean;
    /** off | aggressive (the hint tier is retired) */
    tier?: string;
    mode?: SubagentMode;
    /** what "auto" resolves to right now */
    auto_default?: boolean;
    aggressive_efforts?: string[];
    top_effort: string | null;
    effective_effort: string | null;
    roles: string[];
  };
  /** the catalog's default level for the effective model, if known */
  effort_default_for_model?: string | null;
  model_info?: {
    display_name: string | null;
    input_modalities: string[] | null;
    context_window: number | null;
    in_catalog: boolean;
  };
  /** the provider the NEXT thread starts on (override wins) */
  model_provider?: string | null;
  model_provider_override?: string | null;
  model_provider_default?: string | null;
  model_providers?: string[];
  /** image input of the effective model: true / false / null = unknown */
  vision?: boolean | null;
  /** per-project context controls (process-level in codex) */
  context_window_override?: number | null;
  auto_compact_token_limit?: number | null;
  /** the running engine (empty when the project is not open) */
  engine?: EngineInfo;
}

export type SubagentMode = "auto" | "on" | "off";

export interface EngineInfo {
  kernel_version?: string | null;
  kernel_path?: string | null;
  multi_agent?: boolean;
  images?: boolean;
  context_window?: number | null;
  auto_compact_limit?: number | null;
  /** the settings ask for a process-level flag the engine lacks: it
   * restarts when the current turn ends (or at once when idle) */
  restart_pending?: boolean;
}

/** Authentication modes CrystalPilot can intentionally configure. Legacy
 * command/inline auth is reported only so an edit can preserve it. */
export type ProviderAuthMode = "managed_api_key" | "environment" | "none" | "legacy";

/** /api/providers - a model provider as the settings dialog sees it (never
 * carries a key or an unmasked sensitive header/query value). */
export interface ProviderInfo {
  id: string;
  name: string;
  base_url: string | null;
  wire_api: string;
  protocol_compatible: boolean;
  kind: "openrouter" | "openai_compatible";
  is_default: boolean;
  auth_kind: "command" | "env_key" | "inline" | "other" | "none";
  auth_mode: ProviderAuthMode;
  env_key?: string | null;
  /** Sensitive values are returned as a stable mask and preserved on submit. */
  http_headers: Record<string, string>;
  env_http_headers: Record<string, string>;
  query_params: Record<string, string>;
  request_max_retries: number | null;
  stream_max_retries: number | null;
  stream_idle_timeout_ms: number | null;
  managed: boolean;
  has_key: boolean;
  cred_file: string | null;
  key_updated: string | null;
}

/** /api/models - one model a provider can run. */
export interface ModelEntry {
  id: string;
  display_name: string;
  description?: string;
  /** the model's OWN reasoning levels, as they are; empty = no control */
  efforts: string[];
  default_effort: string | null;
  input_modalities: string[];
  context_window: number | null;
  in_catalog: boolean;
  hidden?: boolean;
  reasoning?: boolean;
  remote_available?: boolean | null;
  pricing?: { prompt?: string; completion?: string };
  source: string;
}

export interface ModelListResponse {
  provider: string;
  kind: string;
  models: ModelEntry[];
  note?: string | null;
  n_total?: number;
  remote?: { ok: boolean; status?: number | null; error?: string | null; n_models?: number | null } | null;
}

export interface KernelInfo {
  path: string | null;
  version: string | null;
  source: "env" | "npm" | "pip" | null;
  sdk_version: string | null;
  candidates: { path: string; source: string; version: string | null }[];
  python?: string;
  vendor_dir?: string;
  update_hint?: string;
  newest_installed?: string | null;
  catalog?: { n_bundled?: number; n_custom?: number; path?: string; error?: string };
  config_path?: string;
  config_mtime?: number;
  open_projects?: { path: string; kernel_version: string | null; restart_pending: boolean; busy: boolean }[];
}

export interface GlobalConfig {
  model: string | null;
  model_provider: string | null;
  model_reasoning_effort: string | null;
  model_reasoning_summary: string | null;
  model_context_window: number | null;
  model_auto_compact_token_limit: number | null;
  agents: Record<string, unknown>;
  config_path: string;
  config_mtime: number;
  model_catalog_json?: string | null;
}

export interface ProviderTestResult {
  ok: boolean;
  /** This probe only checks GET /models; it never makes a billable invocation. */
  check?: "model_catalogue";
  protocol_compatible?: null;
  status?: number | null;
  error?: string | null;
  n_models?: number;
  sample?: string[];
  latency_ms?: number;
  has_key?: boolean;
  used_stored_key?: boolean;
  key_info?: { label?: string; usage?: number; limit?: number | null; limit_remaining?: number | null; is_free_tier?: boolean };
}

export interface SkillInfo {
  name: string | null;
  description?: string | null;
  path?: string | null;
  scope?: string | null;
  enabled?: boolean;
  error?: string | null;
}

export interface ArtifactEntry {
  rel: string;
  path: string;
  size: number;
}

export interface RecentProject {
  path: string;
  opened: number;
  /** settings.display_name or the context.json title; null = directory name */
  display_name?: string | null;
}

/** /api/projects/usage */
export interface ProjectUsage {
  path: string;
  total_bytes: number;
  /** bytes the disk actually holds (hard links counted once) */
  unique_bytes: number;
  user_bytes: number;
  results_bytes: number;
  system_bytes: number;
  categories: Record<string, { bytes: number; files: number; label: string }>;
  reclaimable_bytes: number;
  reclaimable_by_kind: Record<string, { count: number; bytes: number }>;
  n_actions: number;
  measured_at: number;
}

export interface CleanupAction {
  kind: "link" | "strip" | "delete" | "rmdir" | string;
  path: string;
  bytes: number;
  reason: string;
  target?: string | null;
}

/** /api/projects/cleanup */
export interface CleanupPlanResponse {
  project: string;
  reclaimable_bytes: number;
  n_actions: number;
  by_kind: Record<string, { count: number; bytes: number }>;
  protected: Record<string, string[]>;
  notes: string[];
  actions: CleanupAction[];
  applied: boolean;
  result?: { freed_bytes: number; n_done: number; n_skipped: number; skipped: Array<Record<string, unknown>> };
  usage?: ProjectUsage;
}

/** /api/projects/status - the whole board, read off disk without booting
 * an engine (only `busy` consults the live pool). */
export interface ProjectStatus {
  path: string;
  name: string;
  display_name?: string | null;
  opened?: number | null;
  is_open: boolean;
  busy: boolean;
  n_threads?: number;
  last_active?: number | null;
  last_title?: string | null;
  permission_mode?: string | null;
  n_nodes?: number;
  active_node?: string | null;
  r1?: number | null;
  r1_best?: number | null;
  n_atoms?: number | null;
  last_tool?: string | null;
  checkcif?: { A?: number; B?: number; C?: number; G?: number } | null;
  n_deliveries?: number;
}

export interface UploadedFile {
  rel: string;
  size: number;
  kind: string;
  name: string;
}

/** Reference to an uploaded file sent along with a message; the server
 * confines rel to the project directory and feeds images to the model as
 * multimodal input. */
export interface AttachmentRef {
  rel: string;
  kind: string;
  name?: string;
}

export interface TranscriptResponse {
  thread_id: string;
  task_id: string;
  live_cursor: number;
  /** live channel numbering token; null when the project is not open */
  generation?: string | null;
  events: WbEvent[];
  /** transcript lines on disk */
  total?: number;
  /** eid of the first event in this page; null for an empty page */
  oldest_eid?: number | null;
  /** older lines exist before this page */
  has_more?: boolean;
  /** a turn is running on this thread right now (server truth). A
   * transcript that ends mid-turn while this is false was cut (server
   * restart, crash): the client closes the leftover running rows as
   * "no result" instead of spinning forever. */
  busy?: boolean;
}

export interface SendResponse {
  thread_id: string;
  task_id: string;
}

export interface SteerResponse {
  ok: boolean;
  task_id: string;
  /** round-3 R6: "submitted" | "failed" (absent on old servers) */
  receipt?: string;
  steer_eid?: number;
  error?: string | null;
}

export type ApprovalDecisionChoice = "accept" | "reject" | "accept_for_session";

/** Pending approval as returned by GET /api/approvals (same shape as the
 * approval_request event minus kind/ts). */
export interface PendingApproval {
  approval_id: string;
  method: string;
  detail: unknown;
  thread_id?: string;
  item_id?: string | null;
  mcp_server?: string | null;
  mcp_message?: string | null;
  mcp_tool_params?: unknown;
}

// ------------------------------------------------------- refinement (P2 prep)

export interface ComparisonDecision {
  status: "comparable" | "different" | "unknown";
  reasons: string[];
}

export interface ComparisonConditions {
  observations: {
    revision: string;
    format: string;
    processing: string[];
    scale_applied: number | null;
  } | null;
  basis: {
    cell: number[];
    space_group_operations: string[];
    indexing: string;
  } | null;
  wavelength: number | null;
  hklf: number | null;
  merge: { policy: string; n_obs: number | null; n_unique: number | null } | null;
  cutoff: {
    requested: string[];
    applied: string[] | null;
    selected_reflections?: number | null;
    application: "applied" | "ignored" | "unknown";
  };
  weights: { a: number; b: number; source: string } | null;
  scale: { treatment: string; fitted_value: number | null } | null;
  mask: { state: "none" | "bound" | "unknown"; revision: string | null; params: Record<string, unknown> | null };
  stored_mask?: ComparisonConditions["mask"];
  hydrogens: { treatment: string; groups: unknown[] } | null;
  twin: { matrix: number[] | null; n: number; basf: number[] } | null;
  engine: string | null;
  metric_definition?: string | null;
  experiment?: Record<string, unknown> | null;
  declared_experiment?: Record<string, unknown> | null;
  unknown_fields: string[];
}

export interface NodeComparisonSource {
  node: string;
  model_revision: number | null;
  data_revision: string | null;
  data_binding: "bound" | "legacy_unknown" | "structure_only";
  metrics_current: boolean;
  metrics_source: {
    node: string;
    model_revision: number | null;
    data_revision: string | null;
    engine: string | null;
    job: string | null;
    conditions_token: string | null;
  } | null;
  conditions_token: string | null;
  conditions: ComparisonConditions | null;
  frame: {
    revision: string | null;
    cell: number[] | null;
    space_group_operations: string[] | null;
  };
  evidence: { reflection_recompute: boolean; reason: string | null };
}

export interface NodeComparisonResponse {
  schema: 1;
  node: string;
  baseline: string;
  project_revision: number;
  sources: { node: NodeComparisonSource; baseline: NodeComparisonSource };
  metrics: { r1: ComparisonDecision; wr2: ComparisonDecision; goof: ComparisonDecision };
  frame: { status: "compatible" | "different" | "unknown"; reasons: string[] };
  differences: { field: string; node: unknown; baseline: unknown }[];
  unknown_fields: string[];
}

export interface RefineNode {
  id: string;
  comparison_source?: NodeComparisonSource;
  revision?: number | null;
  structure_only?: boolean;
  capabilities?: Record<string, boolean> | null;
  reported_reference?: {
    source: string;
    block_name: string;
    status: string;
    values: Record<string, string | number>;
    note: string;
  } | null;
  parent: string | null;
  branch: string;
  tool: string;
  note: string;
  n_atoms: number;
  r1: number | null;
  wr2: number | null;
  goof: number | null;
  /** Fo−Fc peak / hole after the last refine on this lineage (e Å⁻³). */
  diff_map_max: number | null;
  diff_map_min: number | null;
  n_params: number | null;
  metrics_current: boolean;
  /** A node without a measurement of its own (geometry-only commit):
   * the nearest measured ancestor's R factors, named as such. The
   * header shows them dimmed instead of "—". */
  metrics_inherited?: {
    from: string;
    distance: number;
    r1: number | null;
    wr2: number | null;
    goof: number | null;
  } | null;
  n_restraints: number;
  /** ASU sanity red flags recorded at commit (r9): detached fragments /
   * ghost-atom suspects - deliver-blocking review issues. */
  asu?: { detached: number; ghosts: number } | null;
  /** Flack x from the newest SHELXL adopt on this node (non-centro). */
  flack?: number;
  flack_su?: number;
  /** The reflection data this node was fitted against. Moves only when
   * the data move (swap_reflection_data, re-export, SHEL cutoff), but it
   * bounds what R1 can be, so it belongs beside the R factors. */
  data?: {
    r_int?: number;
    n_unique?: number;
    n_obs?: number;
    d_min?: number;
    completeness?: number;
    space_group?: string;
    wavelength?: number;
    hklf?: number;
    shel?: string;
  } | null;
}

export interface NodesResponse {
  nodes: RefineNode[];
  active_node: string | null;
  active_branch: string | null;
  branches: Record<string, string>;
  /** nodes a write_outputs delivered (round-3 R2-B); absent on old servers */
  deliveries?: DeliveryMark[];
}

/** One MANIFEST.json under the results folder, reduced to what the node
 * tree marks: which node, at what status, in which delivery directory. */
export interface DeliveryMark {
  node: string;
  status: string | null;
  rel: string;
  generated?: string | null;
  revision?: number | null;
}

// ------------------------------------------------------------ scene (P2)

export type SceneAtomFlag = "added" | "removed" | "moved" | "element_changed";

export interface SceneAtom {
  label: string;
  elem: string;
  /** Cartesian Å. */
  xyz: [number, number, number];
  occ: number;
  u_eq: number | null;
  adp_known?: boolean;
  adp_note?: string;
  /** true for symmetry-generated copies (cell/grow/supercell modes). */
  sym: boolean;
  /** symmetry operation that generated this copy, e.g. "-x,y-1/2,-z+1" */
  symop?: string;
  /** 50%-probability ADP ellipsoid (aniso atoms): semi-axis radii (Å) +
   * row-major rotation matrix (columns = principal axes). npd = non-
   * positive-definite ADP, render a fallback marker instead. */
  ell?: { r?: [number, number, number]; m?: number[]; npd?: boolean };
  /** disorder PART number (Olex2 showp); absent = PART 0 */
  part?: number;
  /** diff=1 only; removed atoms arrive as appended ghost entries. */
  flag?: SceneAtomFlag;
  /** server-side metal verdict (chem.bonding whitelist); absent = not a
   * metal. The client never decides metal-ness from the element symbol. */
  m?: boolean;
}

/** [i, j, kind]: indices into scene.atoms plus the bond kind code
 * (scene.bond_kinds[kind]: 0 covalent / 1 coordination / 2 eta /
 * 3 metal_metal). Pre-v7 caches carried plain pairs; treat a missing code
 * as covalent. */
export type SceneBond = [number, number, number?];

/** Dangling grow direction (Olex2 mode-grow dashed bond): clicking one
 * materializes the symmetry mate by sending {i, op} back via `extra`. */
export interface SceneStub {
  /** index into atoms[] the stub grows FROM */
  from: number;
  /** i_seq of the target atom in the ASU */
  i: number;
  /** symmetry op producing the target instance, e.g. "x,-y+1/2,z" */
  op: string;
  elem: string;
  label: string;
  xyz: [number, number, number];
  /** "contact" = vdW packing neighbour (Olex2 grow -s); absent = bond stub */
  kind?: "contact";
}

export interface ScenePolyhedron {
  /** index into atoms[] of the central metal. */
  metal: number;
  vertices: [number, number, number][];
  /** triangles as vertex-index triples. */
  faces: [number, number, number][];
}

export interface SceneCell {
  a: number;
  b: number;
  c: number;
  alpha: number;
  beta: number;
  gamma: number;
  volume: number;
}

export interface SceneMeta {
  n_atoms: number;
  n_ghosts: number;
  n_bonds: number;
  n_polyhedra: number;
  truncated: boolean;
}

/** One difference-map Q peak (fractional site; heights in e Å⁻³). */
export interface PeakEntry {
  site: [number, number, number];
  height: number;
  nearest_atom: string | null;
  nearest_d: number | null;
}

export interface PeaksResponse {
  node: string;
  max: number | null;
  min: number | null;
  scale_k: number | null;
  masked: boolean;
  peaks: PeakEntry[];
}

/** One solvent-accessible void (volumes in Å³, positions fractional).
 * voids.json v3 (round-2 R3.0, D17): the flood-fill centroid is reported
 * ONLY for a 0-D cavity - for a channel / layer / network it is the mean of
 * unwrapped grid points and means nothing - while the largest inscribed
 * sphere is defined for every void and its centre is always in the cell. */
export interface VoidEntry {
  void: number;
  volume_A3: number;
  centre_frac: [number, number, number] | null;
  centre_note?: string;
  /** 0 cavity / 1 channel / 2 layer / 3 network */
  dimensionality?: number;
  /** primitive lattice directions of a channel / layer */
  directions?: number[][];
  n_components?: number;
  inscribed_centre_frac?: [number, number, number];
  inscribed_radius_A?: number;
  /** largest cavity diameter = 2 × inscribed radius (grid approximation) */
  lcd_A?: number;
  /** pore-limiting diameter (R3.2): 2 × the free-sphere radius that still
   * percolates, by bisection over ALL paths; null for a 0-D cavity */
  pld_A?: number | null;
  /** error of pld_A = the grid step actually used (after any coarsening) */
  pld_error_A?: number;
  pld_directions?: number[][];
  pld_note?: string;
  /** round-3 R5: pore-limiting diameter along each cell axis (null = the
   * void does not percolate along that axis); absent for cavities and in
   * older products */
  pld_along?: { a: number | null; b: number | null; c: number | null };
  pld_along_error_A?: number;
  pld_along_note?: string;
  grid_step_A?: number;
  nearest_atom?: string;
  electrons?: number;
  masked?: boolean;
}

/** Interaction layer (round-2 R2.3): one engine (`chem/interactions.py`),
 * rows mapped onto the drawn instances by the scene builder. */
export type InteractionKind =
  "hbond" | "pipi" | "chpi" | "chx" | "halogen" | "anion_pi";

export const INTERACTION_KINDS: readonly InteractionKind[] = [
  "hbond",
  "pipi",
  "chpi",
  "chx",
  "halogen",
  "anion_pi",
];

export interface InteractionRow {
  kind: InteractionKind;
  /** the kind's primary distance (Å): D···A, H···A, X···Y, Cg···Cg, H···Cg */
  dist: number;
  /** distance AND angle criteria met (rows are emitted on distance alone) */
  passes: boolean;
  /** both ends in the same bonded fragment on the identity operator */
  intra?: boolean;
  /** the partner is outside the drawn range: `q` is its position, `sym`
   * the operator that places it */
  boundary: boolean;
  sym: string;
  sym_i: string;
  op: string;
  /** segment endpoints in Å: first object → second object (atom, ring
   * centroid or off-screen partner) */
  p: [number, number, number];
  q: [number, number, number];
  /** scene.atoms indices when the endpoint is a drawn atom */
  ai: number | null;
  bi: number | null;
  /** labels: donor / hydrogen / acceptor / carrier / halogen / rings */
  d?: string;
  h?: string | null;
  a?: string;
  c?: string;
  x?: string;
  ring?: string;
  ring_a?: string;
  ring_b?: string;
  anion?: string;
  anion_name?: string;
  status?: string | null;
  h_xyz?: [number, number, number];
  d_DA?: number;
  d_HA?: number | null;
  d_XA?: number;
  d_HCg?: number;
  d_cc?: number;
  d_perp?: number;
  d_perp_ab?: number;
  d_perp_ba?: number;
  slip_ab?: number;
  slip_ba?: number;
  offset?: number;
  alpha?: number;
  angle?: number | null;
  strength?: string;
  [key: string]: unknown;
}

export interface SceneInteractions {
  h_source: "riding" | "refined" | "absent" | "mixed" | "unknown";
  h_source_note: string;
  /** per kind: the rule set and its thresholds, echoed with sources */
  criteria: Record<string, Record<string, unknown>>;
  counts: {
    rows: Record<string, number>;
    unique: Record<string, number>;
    boundary: Record<string, number>;
    passing: Record<string, number>;
    n_rows: number;
    n_unique: number;
    n_boundary: number;
    n_rings: number;
    n_instances: number;
  };
  truncated: Record<string, { cap: number; found: number }>;
  range: {
    halo_A: number;
    halo_advised_A: number;
    halo_sufficient: boolean;
    halo_capped: boolean;
    n_range: number;
    n_halo: number;
    n_boundary: number;
    boundary_rule: string;
  };
  rings: {
    centroid: [number, number, number];
    normal: [number, number, number];
    radius: number;
    atoms: string[];
    aromatic: boolean;
    in_range: boolean;
  }[];
  rows: InteractionRow[];
}

export interface VoidsResponse {
  node: string;
  n_voids: number;
  voids: VoidEntry[];
  solvent_volume_A3?: number;
  solvent_volume_pct_of_cell?: number;
  total_solvent_electrons_per_cell?: number | null;
  electron_count_note?: string;
  solvent_radius: number;
  shrink_truncation_radius: number;
  map: boolean;
  /** "node" = the mask this node's refinement actually applied;
   * "defaults" = a preview of what masking WOULD find. Different claims
   * about the same picture, so the pane says which one it is drawing. */
  params_source?: "node" | "defaults";
  mask_params?: Record<string, number | null>;
  /** The node's own recorded mask summary, for comparison when the two
   * disagree (they do whenever the model moved after solvent_mask ran). */
  recorded?: Record<string, number | null | string>;
  n_voids_masked?: number;
  dropped_small_voids?: number;
  /** voids.json v4: packing numbers of the whole cell (mask-independent) */
  packing?: PackingNumbers | null;
  pore_note?: string;
  /** voids.json v7: the recount's own BYPASS series - an unconverged
   * recount is not a number to hold against the refinement snapshot */
  bypass?: {
    converged: boolean;
    diverged?: boolean;
    n_cycles?: number;
    kept_cycle?: number | null;
    f000s_first?: number | null;
    f000s_last?: number | null;
  } | null;
  /** voids.json v7: the f'/f'' the recount integrated with, per element */
  anomalous_terms?: Record<string, [number, number]> | null;
}

/** Reflection-data block for one node, from GET /api/wb/refine/data. */
export interface DataBlockResponse {
  node: string;
  /** "node" = the node's own commit-time record. "computed" = merged just
   * now from the project's CURRENT reflection file, because this node
   * predates the field - a weaker claim, since the data can have been
   * swapped since, so the pane marks it. */
  source: "node" | "computed";
  data: NonNullable<RefineNode["data"]>;
  hkl?: string;
  hkl_stamp?: string;
  note?: string;
}

/** Geometric symmetry element in fractional coordinates (P2-3):
 * axes carry a cell-clipped segment, planes a convex polygon, inversion
 * centres a point. Symbols follow ITA (2₁, c, m, -1, 3₂ …). */
export interface SceneSymElement {
  kind: "axis" | "plane" | "point";
  symbol: string;
  /** axes only */
  order?: number;
  screw?: boolean;
  seg?: [number, number, number][];
  centre?: [number, number, number];
  /** planes only */
  glide?: boolean;
  poly?: [number, number, number][];
  /** points only */
  p?: [number, number, number];
}

/** Which lattice tiles the drawn instances occupy (round-2 R2.2, D7). The
 * client instances every per-cell overlay - voids, density map, Q peaks,
 * symmetry elements - over `tiles`; the heavy products themselves stay
 * cached per node. Absent in caches predating the contract. */
export interface SceneRange {
  /** fractional bounding box of the drawn instances */
  frac_lo: [number, number, number];
  frac_hi: [number, number, number];
  /** integer translations whose unit box meets that bounding box */
  tiles: [number, number, number][];
  /** how many tiles the range needed BEFORE truncation */
  n_tiles: number;
  /** more than the drawing budget: only the centre-most tiles are named */
  tiles_truncated: boolean;
  /** Cartesian centroid of the drawn instances */
  centre_cart: [number, number, number];
}

/** Olex2 `grow` (grow all) outcome, present when requested with
 * grow_all=1: how many bonded images were lattice repeats (the fragment is
 * periodic there), how many of those were drawn once as caps, and whether
 * the atom budget stopped the growth. */
export interface SceneGrowAll {
  periodic_edges: number;
  caps: number;
  n_added: number;
  budget_hit: boolean;
  complete: boolean;
}

export interface SceneResponse {
  mode: string;
  /** grow-all closure report (present when requested with grow_all=1) */
  grow_all?: SceneGrowAll;
  atoms: SceneAtom[];
  bonds: SceneBond[];
  /** names of the bond kind codes, index = code (absent in old caches) */
  bond_kinds?: string[];
  /** interaction layer, present when requested with interactions=1 */
  interactions?: SceneInteractions;
  /** htab-style D···A contacts: [i, j, distance Å] (absent in old caches) */
  hbonds?: [number, number, number][];
  /** short vdW contacts [i, j, d] (present when requested with contacts=1) */
  contacts?: [number, number, number][];
  /** dangling grow directions (asu/grow modes; absent in old caches) */
  stubs?: SceneStub[];
  polyhedra: ScenePolyhedron[];
  /** space-group symmetry elements (absent in caches predating P2-3) */
  sym_elements?: SceneSymElement[];
  /** lattice extent of the drawn instances (absent in caches predating R2.2) */
  range?: SceneRange;
  cell: SceneCell;
  space_group: string;
  meta: SceneMeta;
  node: string;
}

// ---------------------------------------------------------------- health

/** /api/health -> ui_build: is the served bundle the one in the tree?
 * (round-2 plan R0, defect D1). */
export interface UiBuildInfo {
  present: boolean;
  built_at?: string;
  version?: string | null;
  src_newest_at?: string | null;
  src_newest_file?: string | null;
  /** a UI source file is newer than dist/index.html -> rebuild + restart */
  stale?: boolean;
}

export interface HealthResponse {
  ok: boolean;
  llm_configured: boolean;
  ui_build?: UiBuildInfo;
}

/** Round-2 R3.5: the per-node analysis product (GET /api/wb/refine/analysis).
 * `interactions.unique` is the symmetry-unique table - a property of the
 * crystal, independent of the viewer's range; rows carry the operator that
 * places the partner (`op`) but none of the display-only fields. */
export type UniqueInteractionRow = Partial<InteractionRow> &
  Pick<InteractionRow, "kind" | "dist" | "passes" | "op">;

export interface AnalysisInteractions {
  scope: "canonical";
  scope_note: string;
  h_source: SceneInteractions["h_source"];
  h_source_note: string;
  criteria: SceneInteractions["criteria"];
  unique: Partial<Record<InteractionKind, UniqueInteractionRow[]>>;
  counts: {
    unique: Partial<Record<InteractionKind, number>>;
    passing: Partial<Record<InteractionKind, number>>;
    intra?: Partial<Record<InteractionKind, number>>;
    n_unique: number;
  };
  truncated: Partial<Record<InteractionKind, { cap: number; found: number }>>;
  rings: {
    atoms: string[];
    aromatic: boolean;
    centroid: number[];
    radius: number;
  }[];
  range: { halo_A: number; halo_advised_A: number; halo_sufficient: boolean };
}

/** Packing numbers (R3.3) - null until the block is computed. */
export interface PackingNumbers {
  /** Kitaigorodskii packing coefficient = volume of the UNION of the vdW
   * spheres / V_cell × 100, grid-counted (overlaps once); typical 65–77 % */
  packing_index_pct: number;
  /** upper bound of the grid-counting error, in % of the cell */
  packing_index_error_pct?: number | null;
  packing_grid_step_A?: number | null;
  vdw_union_volume_A3?: number | null;
  /** raw Σ occ·(4/3)πr³ / V × 100 - no overlap correction, reads high */
  vdw_sum_pct?: number | null;
  vdw_volume_A3?: number;
  cell_volume_A3?: number;
  n_atoms_p1?: number;
  n_non_h_atoms_p1?: number;
  /** V_cell / n(non-H atoms in P1), against the ~18 Å³ rule - a reading */
  volume_per_non_h_atom_A3: number;
  reading?: string;
  note?: string;
  method?: string;
}

export interface AnalysisPores extends VoidsResponse {
  packing: PackingNumbers | null;
  packing_note?: string;
  pore_note?: string;
}

export interface AnalysisResponse {
  v: number;
  voids_v: number;
  node: string;
  interactions: AnalysisInteractions | null;
  pores: AnalysisPores | null;
  /** guest / counter-ion sites (R3.4); null with `guests_note` /
   * `guests_error` when the block could not be computed */
  guests: GuestsBlock | null;
  guests_note?: string;
  guests_error?: string;
  /** topology (R4): nets / interpenetration, simplified net (+ Systre when
   * installed), helices, finite-fragment macrocycles + shape evidence;
   * null with `topology_note` / `topology_error` when it failed */
  topology: AnalysisTopology | null;
  topology_note?: string;
  topology_error?: string;
}

export type AnalysisStageName =
  "interactions" | "topology" | "guests" | "pores";
export interface AnalysisStage {
  status:
    "waiting" | "running" | "ready" | "error" | "unsupported" | "cancelled";
  elapsed_s: number;
  error: string | null;
  note: string | null;
}
export interface AnalysisJob {
  job_id: string;
  observer_id?: string;
  node: string;
  source_revision: number | null;
  status:
    | "queued"
    | "running"
    | "ready"
    | "partial"
    | "error"
    | "cancelling"
    | "cancelled";
  revision: number;
  result_revision: number;
  elapsed_s: number;
  cache_hit: boolean;
  cache_error: string | null;
  observers: number;
  cancellation_requested: boolean;
  stages: Record<AnalysisStageName, AnalysisStage>;
  result: AnalysisResponse | null;
}

/** Round-2 R4 (chem/topology.py, chem/shape.py): descriptions with their
 * definition text - never a verdict. */
export interface NetEntry {
  id: number;
  dimensionality: number;
  n_atoms_p1: number;
  asu_labels: string[];
  /** primitive lattice direction of a 1-D net, else null */
  direction: number[] | null;
}

export interface NetRelation {
  a: number;
  b: number;
  /** Symmetry mapping only; neither a mapping nor its absence proves threading. */
  relation: string;
  op: string | null;
  shift: number[] | null;
}

export interface IndependentNets {
  n_nets: number;
  nets: NetEntry[];
  relations: NetRelation[];
  /** Legacy caches used these as symmetry flags; current products use null for untested topology. */
  interpenetrated: boolean | null;
  interlocked_1d: boolean | null;
  symmetry_related?: boolean;
  symmetry_related_1d?: boolean;
  /** round-3 R5: "tested" = the ring-threading test finished for every
   * compared pair (interpenetrated is then a real true/false);
   * "inconclusive" / "not_testable" explain a null; older products say
   * "not_tested". */
  interpenetration_status?: "tested" | "inconclusive" | "not_testable" | "not_tested" | "not_applicable" | string;
  /** ring-threading report per compared pair (absent in older products) */
  threading?: {
    method: string | null;
    max_ring_size?: number;
    pairs: {
      a: number;
      b: number;
      dims: [number, number];
      status: "threaded" | "not_threaded" | "inconclusive" | "not_testable";
      reason?: string;
      a_windows?: number;
      a_windows_threaded_by_b?: number;
      b_windows?: number;
      b_windows_threaded_by_a?: number;
      truncated?: boolean;
      example?: { window: number[]; window_size: number; bond: [string, string]; bond_shift: number[] } | null;
    }[];
  };
  definition: string;
  definition_en?: string;
  host: {
    fragments: {
      key: string;
      formula: string;
      n_atoms: number;
      dimensionality: number;
      role: string;
    }[];
    selection_rule: string;
  };
  notes: string[];
}

export interface NetNode {
  id: number;
  kind: string;
  atoms: string[];
  n_atoms_p1: number;
  centroid_frac: [number, number, number];
  connectivity: number;
  /** a periodic (rod) cluster contracted to one point - a contested simplification */
  periodic?: number;
}

/** [node a, node b, lattice shift of b] */
export type NetEdge = [number, number, [number, number, number]];

export interface SimplifiedNet {
  nodes: NetNode[];
  edges: NetEdge[];
  n_nodes_per_cell: number;
  n_edges_per_cell: number;
  node_connectivity_histogram: Record<string, number>;
  linkers: {
    id: string;
    atoms: string[];
    n_atoms_p1: number;
    n_nodes_touched: number;
    role: string;
    node_id?: number;
  }[];
  definition: string;
  definition_en?: string;
  confidence?: string;
  note?: string;
  rcsr_symbol: string | null;
  rcsr_status: string;
  /** one RCSR symbol per connected component of the simplified net (an
   * interpenetrated structure has several; product v5) */
  rcsr_symbols?: string[];
  systre_error?: string;
  systre_output?: string;
  /** links reaching the same (u, v, shift) through more than one linker:
   * counted in the histogram, written once to Systre's .cgd */
  n_parallel_edges?: number;
  n_simple_edges_per_cell?: number;
}

/** A ring `find_rings` cannot represent (it closes through a symmetry
 * element, e.g. benzene on an inversion centre): the pi-pi / C-H...pi
 * tables silently lack every row that would involve it, so the engine
 * counts them and names them (validation 2026-09). */
export interface RingThroughSymmetry {
  key: string;
  size: number;
  asu_atoms: number;
  op: string;
  op_order: number;
}

export interface HelixEntry {
  fragment: string;
  asu_labels: string[];
  n_atoms_p1: number;
  dimensionality: number;
  axis_direction: number[];
  chain_direction: number[];
  screw: string;
  order: number;
  handedness: "right" | "left" | null;
  pitch_A: number;
  axis_repeat_A: number;
  racemic: boolean;
  definition?: string;
  note?: string;
}

export interface FiniteFragment {
  fragment: string;
  asu_labels: string[];
  n_atoms: number;
  copies: number;
  role: "host" | "guest";
  largest_cycle: {
    size: number | null;
    truncated: boolean;
    n_cycles_basis: number;
    note?: string;
    atoms: string[];
  };
  shape: {
    inertia_ratios?: number[] | null;
    sphericity?: number | null;
    hull_volume_A3?: number | null;
    hull_area_A2?: number | null;
    longest_axis_A?: number | null;
    aspect?: number[] | null;
    mass_weighted?: boolean;
    method?: string;
    note?: string;
  } | null;
}

export interface AnalysisTopology {
  nets: IndependentNets;
  simplified_net: SimplifiedNet;
  helices: HelixEntry[];
  finite_fragments: FiniteFragment[];
  note?: string;
}

export type GuestSite = "cage_cavity" | "channel" | "cavity" | "interstitial";

export interface GuestContact {
  atom: string;
  host_atom: string;
  d: number;
  sym: string;
  clearance_A?: number;
}

export interface GuestEntry {
  fragment: string;
  formula: string;
  copies: number;
  n_atoms?: number;
  role?: string;
  identity?: string | null;
  site: GuestSite;
  void_id: number | null;
  host_fragment: string | null;
  centroid_frac?: [number, number, number];
  d_to_inscribed_centre_A?: number | null;
  nearest_host_contacts?: GuestContact[];
  clearance_A?: number | null;
  straddles_regions?: boolean;
  criteria_used?: Record<string, unknown>;
  parts?: number[];
}

export interface GuestsBlock {
  /** the four site definitions verbatim + the numbers used */
  criteria: Record<string, unknown> & {
    cage_cavity?: string;
    channel?: string;
    cavity?: string;
    interstitial?: string;
    probe_A?: number;
    grid_step_A?: number;
    min_void_volume_A3?: number;
    note?: string;
  };
  host: {
    fragments: {
      key: string;
      formula: string;
      n_atoms: number;
      copies: number;
      dimensionality: number;
      role: string;
    }[];
    n_atoms: number;
    selection_rule: string;
  };
  guests: GuestEntry[];
  summary: Record<GuestSite, number>;
  grid_step_A: number;
  probe_A: number;
}
