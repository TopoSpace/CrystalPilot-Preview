/** Delivery card (round-3 R2-A): status, node, R1/wR2/GooF at delivery,
 * the four files a reader opens first, and one line for the rest ("全部 N
 * 个文件 → 产物页签"). The old card listed every path under the results
 * folder as a chip wall - run logs included. Facts come from the
 * write_outputs / finalize_delivery results, never from chat prose. */
import { artifactUrl } from "../../lib/wbApi";
import {
  cifGradeLabel,
  deliveryArtifacts,
  deliveryStatusLabel,
  mainFiles,
  type DeliveryFacts,
} from "../../lib/delivery";
import { cx } from "../../lib/format";
import { t } from "../../lib/i18n";
import { useThread } from "../../state/ThreadProvider";

/** Ask the right pane to show a tab (it owns the URL param). */
export function requestRightTab(tab: string): void {
  window.dispatchEvent(new CustomEvent("cp:right-tab", { detail: tab }));
}

const f4 = (v: number | null) => (v === null ? "—" : v.toFixed(4));
const f2 = (v: number | null) => (v === null ? "—" : v.toFixed(2));

export function DeliveryCard({ facts }: { facts: DeliveryFacts }) {
  const { state } = useThread();
  const deliverables = deliveryArtifacts(state.artifacts);
  const main = mainFiles(facts.files, deliverables);
  const total =
    deliverables.length > 0 ? deliverables.length : facts.files.length;
  const statusLabel = deliveryStatusLabel(facts.status);
  const tone =
    facts.status === "final"
      ? "bg-ok/10 text-ok"
      : facts.status === "diagnostic"
        ? "bg-warn/10 text-warn"
        : "bg-raised text-ink-2";

  return (
    <div
      data-testid="delivery-card"
      className="rounded-card border border-line bg-surface px-4 py-3"
    >
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium text-ink">{t.deliveryTitle}</span>
        {statusLabel !== "" && (
          <span
            className={cx(
              "rounded-pill px-1.5 py-px text-2xs font-medium",
              tone,
            )}
            title={facts.status ?? undefined}
          >
            {statusLabel}
          </span>
        )}
        {facts.waived > 0 && (
          <span className="rounded-pill bg-warn/10 px-1.5 py-px text-2xs text-warn">
            {t.deliveryWaived} {facts.waived}
          </span>
        )}
        {facts.node !== null && (
          <span className="font-mono text-2xs text-ink-3">
            {t.deliveryNode} {facts.node}
          </span>
        )}
        {facts.cifGrade !== null && (
          <span
            data-testid="delivery-cif-grade"
            className={cx(
              "rounded-pill px-1.5 py-px text-2xs",
              facts.cifGrade === "model" ? "bg-warn/10 text-warn" : "bg-raised text-ink-3",
            )}
            title={facts.cifGrade === "model" ? t.deliveryCifGradeModelTip : facts.cifGrade}
          >
            {cifGradeLabel(facts.cifGrade)}
          </span>
        )}
        {facts.metrics !== null && (
          <span className="ml-auto font-mono text-2xs text-ink-2 tabular-nums">
            R1 {f4(facts.metrics.r1)} · wR2 {f4(facts.metrics.wr2)} · GooF{" "}
            {f2(facts.metrics.goof)}
          </span>
        )}
      </div>
      {main.length === 0 && total === 0 ? (
        <div className="mt-1.5 text-2xs text-ink-3">{t.deliveryNoFiles}</div>
      ) : (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {main.map(({ name, artifact }) =>
            artifact ? (
              <a
                key={name}
                href={artifactUrl(artifact.path)}
                target="_blank"
                rel="noreferrer"
                className="rounded-pill border border-line bg-bg px-2 py-0.5 font-mono text-2xs text-ink-2 transition-colors hover:bg-raised hover:text-ink"
                title={artifact.path.replace(/\\/g, "/")}
              >
                {name}
              </a>
            ) : (
              <span
                key={name}
                className="rounded-pill border border-line bg-bg px-2 py-0.5 font-mono text-2xs text-ink-3"
              >
                {name}
              </span>
            ),
          )}
          {total > main.length && (
            <button
              type="button"
              onClick={() => requestRightTab("artifacts")}
              className="rounded-pill px-2 py-0.5 text-2xs text-ink-3 transition-colors hover:bg-raised hover:text-ink"
            >
              {t.deliveryAllFiles} {total} {t.deliveryFilesUnit} →{" "}
              {t.deliveryOpenArtifacts}
            </button>
          )}
        </div>
      )}
      {facts.handover !== null && (
        <div
          data-testid="delivery-handover"
          className={cx("mt-1.5 text-2xs", facts.handover.missing.length > 0 ? "text-warn" : "text-ink-2")}
          title={facts.handover.notes.join("\n") || undefined}
        >
          {facts.handover.missing.length === 0
            ? t.deliveryHandoverReady
            : `${t.deliveryHandoverMissing} ${facts.handover.missing.join(" / ")}`}
        </div>
      )}
      <div className="mt-1.5 text-2xs text-ink-3">{t.deliveryFromTools}</div>
    </div>
  );
}
