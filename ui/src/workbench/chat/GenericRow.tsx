/** One-line muted rows for secondary events: file changes, web search, todo
 * lists, error items, client errors, auto approvals - plus centered system
 * rows (family "system": permission_mode / specialists_toggled). */
import { permissionLabel, t } from "../../lib/i18n";
import { IconShield } from "../icons";
import { Spinner } from "../../components/ui";
import { jobRowText, type BackgroundJobInfo } from "../../lib/backgroundJobs";
import { genericGlyph } from "../../lib/activityIcons";
import { ActivityIcon } from "./ActivityIcon";
import { ActivitySummary } from "./ActivitySummary";
import { ProcessDetails } from "./ProcessDetails";
import { MonoBlock } from "./MonoBlock";
import type { GenericItem } from "../../state/threadReducer";

/** "已启用专家子代理" / "权限模式已切换为 自动（agent 服务已重启）". */
export function systemText(item: GenericItem): string {
  const d = (item.detail ?? {}) as Record<string, unknown>;
  if (item.kind === "specialists_toggled") {
    return d.enabled === true ? t.sysSpecialistsOn : t.sysSpecialistsOff;
  }
  if (item.kind === "delegation") {
    return d.active === true ? t.sysDelegationOn : t.sysDelegationOff;
  }
  if (item.kind === "permission_mode") {
    const mode = typeof d.mode === "string" ? d.mode : "";
    return (
      t.sysPermissionPrefix +
      permissionLabel(mode) +
      (d.rebuilt === true ? t.sysRebuilt : "")
    );
  }
  if (item.kind === "mcp_down") return t.sysMcpDown;
  if (item.kind === "background_job") {
    return jobRowText(item.detail as BackgroundJobInfo);
  }
  if (item.kind === "mcp_startup") {
    const d = (item.detail ?? {}) as {
      status?: string;
      n_tools?: number | null;
      seconds?: number | null;
      error?: string | null;
    };
    if (d.status === "waiting") return t.sysMcpWaiting;
    if (d.status === "ready") {
      const facts: string[] = [];
      if (typeof d.n_tools === "number" && Number.isInteger(d.n_tools) && d.n_tools >= 0) facts.push(`${d.n_tools} ${t.sysMcpToolsUnit}`);
      if (typeof d.seconds === "number" && Number.isFinite(d.seconds) && d.seconds >= 0) facts.push(`${d.seconds} s`);
      return t.sysMcpReady + (facts.length > 0 ? t.shell.paren(facts.join(" · ")) : "");
    }
    if (d.status === "failed" || d.status === "error") return `${t.sysMcpFailed}${d.error ? ` · ${d.error}` : ""}`;
    return `${t.sysMcpTimeout}${d.seconds != null ? t.shell.paren(`${d.seconds} s`) : ""}`;
  }
  if (item.kind === "engine_restarted") {
    const reason = typeof d.reason === "string" ? d.reason : "";
    return reason.includes("settings") ? t.sysEngineRestartedSettings : t.sysEngineRestarted;
  }
  if (item.kind === "compaction_requested") return t.sysCompactionRequested;
  if (item.kind === "compaction_started") return t.sysCompacting;
  if (item.kind === "compaction_completed") return t.sysCompacted;
  if (item.kind === "engine_warning") {
    return t.sysEngineWarning + (typeof d.message === "string" ? d.message : "");
  }
  if (item.kind === "model_rerouted") {
    return `${t.sysModelRerouted}${String(d.from_model ?? "")} → ${String(d.to_model ?? "")}${
      typeof d.reason === "string" && d.reason ? t.shell.paren(d.reason) : ""
    }`;
  }
  return item.kind;
}

/** Client-local note card (slash command output): a title and lines. */
function NoteRow({ item }: { item: GenericItem }) {
  const d = (item.detail ?? {}) as { title?: string; lines?: string[] };
  return (
    <div
      data-testid="note-row"
      className="mx-auto w-full max-w-xl rounded-card border border-line bg-surface/60 px-3.5 py-2.5 text-xs text-ink-2"
    >
      <div className="mb-1 text-2xs font-medium text-ink-3">{d.title ?? ""}</div>
      <div className="flex flex-col gap-0.5 font-mono text-2xs leading-relaxed">
        {(d.lines ?? []).map((ln, i) => (
          <div key={i} className="break-all">
            {ln}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Centered small-print system row (Codex style). */
function SystemRow({ item }: { item: GenericItem }) {
  if (item.kind === "note") return <NoteRow item={item} />;
  const status = (item.detail as { status?: string } | null)?.status;
  const failed = item.kind === "mcp_startup" && (status === "failed" || status === "error" || status === "timeout");
  const job = item.kind === "background_job" ? (item.detail as BackgroundJobInfo | null) : null;
  const jobRunning = job?.running === true;
  const jobWaiting = job !== null && !job.running && job.hasSolution && !job.adopted && !job.error;
  return (
    <div
      className="flex items-center justify-center gap-2 py-0.5"
      {...(job ? { "data-testid": "background-job-row", "data-job": job.job, "data-running": String(jobRunning) } : {})}
    >
      <span className="h-px w-6 bg-line" aria-hidden="true" />
      {failed && <IconShield size={13} className="text-ink-3" />}
      {jobRunning && <Spinner className="h-3 w-3 shrink-0 text-ink-3" />}
      {jobWaiting && <IconShield size={13} className="text-warn" />}
      <span className="text-xs text-ink-3">{systemText(item)}</span>
      <span className="h-px w-6 bg-line" aria-hidden="true" />
    </div>
  );
}

function familyLabel(family: string): string {
  switch (family) {
    case "file_change":
      return t.fileChange;
    case "webSearch":
      return t.webSearch;
    case "todoList":
      return t.todoList;
    case "error":
      return t.errorItem;
    case "imageView":
      return t.imageView;
    case "client_error":
      return t.clientError;
    case "approval_auto":
      return t.approvalAutoSession;
    case "collab":
      return t.collabRow;
    default:
      return family;
  }
}

function detailText(item: GenericItem): string {
  const d = item.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return t.shell.countItems(d.length);
  if (d && typeof d === "object") {
    const rec = d as Record<string, unknown>;
    if (typeof rec.query === "string") return rec.query;
    if (typeof rec.tool === "string" && rec.tool !== "") {
      const who = Array.isArray(rec.receivers) ? rec.receivers.length : 0;
      const what =
        typeof rec.prompt === "string" && rec.prompt
          ? ` · ${rec.prompt.slice(0, 80)}`
          : "";
      return `${rec.tool}${who ? ` ×${who}` : ""}${what}`;
    }
    if (typeof rec.message === "string") return rec.message;
    if (Array.isArray(rec.items)) return t.shell.countItems(rec.items.length);
  }
  return "";
}

export function GenericRow({ item }: { item: GenericItem }) {
  if (item.family === "system") return <SystemRow item={item} />;
  const isError = item.family === "error" || item.family === "client_error";
  const detail = detailText(item);
  const running = !item.done && item.family !== "approval_auto";

  const interrupted = item.phase === "interrupted";
  const noResult = item.phase === "no_result";
  const issue = isError ? t.toolFailed : noResult ? t.toolNoResult : interrupted ? t.toolInterrupted : undefined;
  return (
    <ProcessDetails className="activity-row" running={running} data-testid="generic-row">
      <ActivitySummary icon={<ActivityIcon kind={genericGlyph(item.family)} />}
        running={running} issue={issue} title={detail}>
        {familyLabel(item.family)}{detail && <span className="activity-result"> · {detail}</span>}
      </ActivitySummary>
      <div className="activity-body">
        {issue && <div className="text-sm text-ink-2">{issue}</div>}
        {noResult && <div className="text-sm leading-relaxed text-ink-2" data-testid="tool-boundary-hint">{t.toolNoResultHint}</div>}
        <MonoBlock text={typeof item.detail === "string" ? item.detail : JSON.stringify(item.detail, null, 2) ?? item.kind}
          className="activity-output" />
      </div>
    </ProcessDetails>
  );
}
