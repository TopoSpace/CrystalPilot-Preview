/** 验证 tab (P4): checkCIF A/B/C/G alert browser.
 *
 * Sources, in layout order:
 * 1. the latest run_checkcif / submit_iucr_checkcif tool result in the thread
 *    event stream (alerts salvaged even from head-truncated result_tail);
 * 1b. fallback: a checkcif*.json artifact from the task deliverables - covers
 *    runs where checkCIF happened outside the MCP stream (observed live: the
 *    W(CO)6 agent finished validation through a direct invoke shim after its
 *    MCP transport died, leaving this panel empty despite full results);
 * 2. VALIDATION.md from the thread artifacts (agent's per-alert explanations)
 *    behind a 查看逐条解释 toggle.
 *
 * Counts header uses letter + color (A red / B orange / C amber / G gray) so
 * the level stays readable without color vision.
 */
import { useEffect, useMemo, useState } from "react";
import { Spinner } from "../../components/ui";
import {
  ALERT_LEVELS,
  checkcifOriginStatus,
  latestCheckcif,
  parseCheckcifTail,
  type CheckcifSource,
  type AlertLevel,
  type CheckcifAlert,
  type CheckcifData,
} from "../../lib/checkcif";
import { artifactUrl, getValidationSource } from "../../lib/wbApi";
import { cx } from "../../lib/format";
import { alertQuote, checkcifQuote, withAnchor } from "../../lib/quote";
import { useCrystal } from "../../state/CrystalProvider";
import { zh } from "../../lib/zh";
import { useComposerDraft } from "../../state/ComposerDraft";
import { useThreadOptional } from "../../state/ThreadProvider";
import { IconChevronRight } from "../icons";
import { MarkdownPreview } from "./ArtifactsPanel";

const LEVEL_LABEL: Record<AlertLevel, string> = {
  A: zh.ccLevelA,
  B: zh.ccLevelB,
  C: zh.ccLevelC,
  G: zh.ccLevelG,
};

/** Chip + accent classes per level (letter is the primary encoding). */
const LEVEL_CHIP: Record<AlertLevel, string> = {
  A: "bg-danger/12 text-danger",
  B: "bg-warn/12 text-warn",
  C: "bg-warn/15 text-warn",
  G: "bg-raised text-ink-3",
};

const LEVEL_DOT: Record<AlertLevel, string> = {
  A: "bg-danger",
  B: "bg-warn",
  C: "bg-warn",
  G: "bg-ink-3",
};

function CountChip({
  level,
  count,
  approx,
}: {
  level: AlertLevel;
  count: number;
  approx: boolean;
}) {
  return (
    <span
      className={cx(
        "inline-flex h-[22px] items-center gap-1 rounded-md px-2 font-mono text-xs font-semibold tabular-nums",
        LEVEL_CHIP[level],
      )}
      title={LEVEL_LABEL[level]}
    >
      {level}
      <span className="font-normal">
        {approx ? "≥" : "×"}
        {count}
      </span>
    </span>
  );
}

function AlertRow({ alert, sourceNode }: { alert: CheckcifAlert; sourceNode?: string | null }) {
  const kb = alert.kb;
  const draft = useComposerDraft();
  return (
    <details className="group border-b border-line/60 last:border-b-0">
      <summary className="flex cursor-pointer list-none items-start gap-2 px-3 py-1.5 select-none hover:bg-raised/40">
        <IconChevronRight
          size={11}
          className="mt-1 shrink-0 text-ink-3 transition-transform group-open:rotate-90"
        />
        <span
          className={cx(
            "mt-1 h-2 w-2 shrink-0 rounded-full",
            LEVEL_DOT[alert.level],
          )}
          aria-hidden="true"
        />
        <span className="shrink-0 font-mono text-2xs font-semibold text-ink">
          {alert.level} {alert.code}
        </span>
        <span className="min-w-0 flex-1 text-2xs leading-snug text-ink-2">
          {alert.text}
        </span>
        {/* an alert is the single most quotable thing in the workbench: it
         * is already a well-posed question with its own evidence attached,
         * and retyping a PLAT code and its numbers by hand is exactly the
         * friction that makes people not ask */}
        <span
          role="button"
          tabIndex={0}
          title={zh.ccQuoteAlertTip}
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            draft.insert(withAnchor(alertQuote(alert), sourceNode));
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.click();
          }}
          className="mt-0.5 shrink-0 rounded-pill px-1.5 py-0.5 text-2xs text-ink-3 opacity-0 transition-colors group-hover:opacity-100 hover:bg-accent/10 hover:text-accent"
        >
          {zh.headerQuote}
        </span>
      </summary>
      <div className="mx-3 mb-2 ml-[34px] rounded-lg bg-surface p-2.5 text-2xs leading-relaxed">
        {kb ? (
          <dl className="flex flex-col gap-1">
            {kb.meaning !== undefined && (
              <div>
                <dt className="inline font-medium text-ink">
                  {zh.ccKbMeaning}：
                </dt>
                <dd className="inline text-ink-2">{kb.meaning}</dd>
              </div>
            )}
            {kb.causes !== undefined && (
              <div>
                <dt className="inline font-medium text-ink">
                  {zh.ccKbCauses}：
                </dt>
                <dd className="inline text-ink-2">{kb.causes}</dd>
              </div>
            )}
            {kb.remedy !== undefined && (
              <div>
                <dt className="inline font-medium text-ink">
                  {zh.ccKbRemedy}：
                </dt>
                <dd className="inline text-ink-2">{kb.remedy}</dd>
              </div>
            )}
          </dl>
        ) : (
          <span className="text-ink-3">{zh.ccNoKb}</span>
        )}
      </div>
    </details>
  );
}

function ValidationOrigin({ data }: { data: CheckcifData | null }) {
  const { state, project, viewNode } = useCrystal();
  const thread = useThreadOptional();
  const source = data?.source;
  const [current, setCurrent] = useState<CheckcifSource | null | undefined>(undefined);
  const artifacts = thread?.state.artifacts;
  useEffect(() => {
    if (!project || !source) return undefined;
    const ctrl = new AbortController();
    getValidationSource(project, source.target, ctrl.signal)
      .then((response) => { if (!ctrl.signal.aborted) setCurrent(response.source); })
      .catch(() => { if (!ctrl.signal.aborted) setCurrent(null); });
    return () => ctrl.abort();
  }, [project, source?.target, source?.delivery_revision, artifacts]);
  const status = checkcifOriginStatus(data, state.viewNode ?? state.activeNode, current);
  const warning = status === "different_node" || status === "outdated_delivery";
  const label = { same_node: zh.ccSourceSameNode, different_node: zh.ccSourceDifferentNode,
    outdated_delivery: zh.ccSourceOlderDelivery, unknown: zh.ccSourceUnknown }[status];
  return (
    <div className={cx("mb-2 text-2xs leading-relaxed", warning ? "text-warn" : "text-ink-3")}
      data-testid="validation-origin" data-status={status}>
      <div>{label}</div>
      {source?.node && (
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
          <span className="font-mono">{source.node}{source.revision ? ` · r${source.revision}` : ""}
            {source.delivery_revision ? ` · ${zh.ccDeliveryVersion} ${source.delivery_revision}` : ""}</span>
          {status === "different_node" && state.nodes.some((n) => n.id === source.node) && (
            <button type="button" onClick={() => viewNode(source.node!)}
              className="rounded px-1 text-accent hover:bg-raised">{zh.ccViewSourceNode}</button>
          )}
        </div>
      )}
    </div>
  );
}

export function ValidationPanel() {
  const thread = useThreadOptional();
  const draft = useComposerDraft();
  const items = thread?.state.items;
  const artifacts = thread?.state.artifacts ?? [];
  const [showReport, setShowReport] = useState(false);

  const latest = useMemo(
    () => (items !== undefined ? latestCheckcif(items) : null),
    [items],
  );
  const validationMd =
    artifacts.find((a) => /(^|\/)VALIDATION\.md$/i.test(a.rel)) ?? null;

  // 1b. deliverable-artifact fallback (checkCIF ran outside the MCP stream)
  const ccArtifact =
    artifacts.find((a) => /checkcif.*\.json$/i.test(a.rel)) ?? null;
  const [artifactData, setArtifactData] = useState<CheckcifData | null>(null);
  useEffect(() => {
    setArtifactData(null);
    if (latest !== null || ccArtifact === null) return undefined;
    const ctrl = new AbortController();
    fetch(artifactUrl(ccArtifact.path), { signal: ctrl.signal, cache: "no-store" })
      .then(async (res) => {
        if (!res.ok) throw new Error(res.statusText);
        const text = await res.text();
        if (!ctrl.signal.aborted) setArtifactData(parseCheckcifTail(text));
      })
      .catch(() => {
        /* fallback is best-effort */
      });
    return () => ctrl.abort();
  }, [latest, ccArtifact]);

  // ---------------------------------------------------------------- empty
  if (latest === null && artifactData === null && validationMd === null) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-1.5 px-6 text-center">
        <div className="text-sm font-medium text-ink-2">
          {zh.ccEmptyTitle}
        </div>
        <div className="text-xs text-ink-3">{zh.ccEmptyDesc}</div>
      </div>
    );
  }

  const data = latest !== null ? latest.data : artifactData;
  const running = latest?.item.status === "running" || data?.execution === "running";
  const failed = latest?.item.status === "error" || (data?.execution !== undefined
    && data.execution !== "completed" && data.execution !== "running");
  const counts = data === null || running || failed ? null : (data.counts ?? data.salvagedCounts);
  const approx = data !== null && data.counts === null;
  const isIucr = latest?.item.tool === "submit_iucr_checkcif";

  const grouped: Record<AlertLevel, CheckcifAlert[]> = { A: [], B: [], C: [], G: [] };
  for (const a of data?.alerts ?? []) grouped[a.level].push(a);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto" data-testid="validation-panel">
      {/* header: counts + source + report toggle */}
      <div className="shrink-0 border-b border-line px-3 py-2">
        <p className="mb-2 text-2xs leading-relaxed text-ink-3" role="note">
          {zh.ccReportScope}
        </p>
        {data !== null && <ValidationOrigin key={`${data?.source?.target ?? "unknown"}:${data?.source?.delivery_revision ?? ""}`} data={data} />}
        <div className="flex flex-wrap items-center gap-1.5">
          {counts !== null ? (
            <>
              {ALERT_LEVELS.map((lv) =>
                // partial salvage: a hard 0 would be a guess - only show
                // levels actually seen (lower bounds)
                approx && counts[lv] === 0 ? null : (
                  <CountChip
                    key={lv}
                    level={lv}
                    count={counts[lv]}
                    approx={approx}
                  />
                ),
              )}
              {approx && (
                <span className="text-2xs text-ink-3">
                  {zh.ccCountsUnknown}
                </span>
              )}
            </>
          ) : running ? (
            <span className="flex items-center gap-2 text-xs text-ink-3">
              <Spinner className="h-3 w-3" />
              {zh.ccRunning}
            </span>
          ) : failed ? (
            <span className="text-xs text-danger">{zh.ccFailed}</span>
          ) : (
            <span className="text-xs text-ink-3">{zh.ccCountsUnknown}</span>
          )}
          {(data?.alerts.length ?? 0) > 0 && (
            <button
              type="button"
              title={zh.ccQuoteAllTip}
              onClick={() =>
                draft.insert(
                  withAnchor(checkcifQuote({
                    counts,
                    approx,
                    alerts: data?.alerts ?? [],
                    target: data?.target,
                  }), data?.source?.node),
                )
              }
              className="ml-auto shrink-0 rounded-pill px-1.5 py-0.5 text-2xs text-ink-3 transition-colors hover:bg-accent/10 hover:text-accent"
            >
              {zh.headerQuote}
            </button>
          )}
          {latest !== null && (
            <span
              className={cx(
                "shrink-0 text-2xs text-ink-3",
                (data?.alerts.length ?? 0) === 0 && "ml-auto",
              )}
            >
              {isIucr ? zh.ccSourceIucr : zh.ccSourceLocal}
            </span>
          )}
        </div>
        {failed && data?.error && (
          <div role="status" className="mt-2 break-words text-xs text-danger">
            {data.execution === "timeout" ? "检查超时 · " : data.execution === "cancelled" ? "检查已取消 · " : ""}
            {data.error}
          </div>
        )}
        {data?.target != null && (
          <div
            className="mt-1 truncate font-mono text-2xs text-ink-3"
            title={data.target}
          >
            {data.target}
          </div>
        )}
        {validationMd !== null && (
          <button
            type="button"
            aria-pressed={showReport}
            onClick={() => setShowReport((v) => !v)}
            className={cx(
              "mt-1.5 h-6 rounded-pill border px-2.5 text-2xs font-medium transition-colors",
              showReport
                ? "border-accent/40 bg-accent/10 text-accent"
                : "border-line text-ink-2 hover:bg-raised",
            )}
          >
            {showReport ? zh.ccViewAlerts : zh.ccViewReport}
          </button>
        )}
      </div>

      {/* body */}
      {showReport && validationMd !== null ? (
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
          <MarkdownPreview path={validationMd.path} />
        </div>
      ) : (
        <div className="min-h-0 flex-1">
          {data?.partial && (
            <div className="border-b border-warn/25 bg-warn/8 px-3 py-1.5 text-2xs leading-snug text-warn">
              {zh.ccPartialNote}
            </div>
          )}
          {data === null && !running && !failed && validationMd !== null && (
            <div className="px-3 py-2 text-xs text-ink-3">
              {zh.ccEmptyDesc}
            </div>
          )}
          {ALERT_LEVELS.map((lv) =>
            grouped[lv].length === 0 ? null : (
              <section key={lv}>
                <div className="flex items-center gap-1.5 bg-surface/80 px-3 py-1 text-2xs font-medium text-ink-3">
                  <span
                    className={cx("h-2 w-2 rounded-full", LEVEL_DOT[lv])}
                    aria-hidden="true"
                  />
                  {LEVEL_LABEL[lv]}
                  <span className="font-mono tabular-nums">
                    {approx ? "≥" : ""}
                    {grouped[lv].length}
                  </span>
                </div>
                {grouped[lv].map((a, i) => (
                  <AlertRow key={`${a.code}-${i}`} alert={a} sourceNode={data?.source?.node} />
                ))}
              </section>
            ),
          )}
        </div>
      )}
    </div>
  );
}

/** A-alert count for the tab badge. null = no badge (nothing ran, or the
 * true count is unknown after a truncated tail salvaged zero A alerts -
 * displaying a hard 0 there would be a guess). */
export function useValidationBadge(): number | null {
  const thread = useThreadOptional();
  const items = thread?.state.items;
  return useMemo(() => {
    if (items === undefined) return null;
    const latest = latestCheckcif(items);
    if (latest?.data == null || (latest.data.execution !== undefined
        && latest.data.execution !== "completed")) return null;
    if (latest.data.counts !== null) return latest.data.counts.A;
    const a = latest.data.salvagedCounts.A;
    return a > 0 ? a : null; // lower bound is still true when positive
  }, [items]);
}
