/** Artifacts tab (round-3 R2-B): the thread's result files grouped by
 * delivery directory - the top-level delivery, then each sub-delivery
 * (guest-location-update, whole-guest-study, ...) - each group headed by
 * its status (定稿 / 暂定 / 诊断性) and source node from the manifest, the
 * main files (CIF / FCF / RES / SUMMARY / VALIDATION) first and the rest
 * behind "全部 N 个文件". Run logs (command output) sit apart, folded.
 * Markdown and images preview inline; 打开 serves the file. The 2026-09-05
 * review found the old flat list: three deliveries' worth of paths with
 * backslashes, one per line, nothing saying which was which. */
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import { mdComponentsWithBase, mdUrlTransform } from "../../lib/mdLink";
import remarkGfm from "remark-gfm";
import { AlertBanner, Spinner } from "../../components/ui";
import {
  baseName,
  deliveryStatusLabel,
  deliveryTone,
  groupArtifacts,
  markFor,
  normPath,
  type ArtifactGroup,
} from "../../lib/delivery";
import { cx, fmtBytes } from "../../lib/format";
import { artifactUrl } from "../../lib/wbApi";
import type { ArtifactEntry, DeliveryMark } from "../../lib/wbTypes";
import { t } from "../../lib/i18n";
import { useCrystal } from "../../state/CrystalProvider";
import { useThreadOptional } from "../../state/ThreadProvider";

const MD_EXT = /\.(md|markdown)$/i;
const IMG_EXT = /\.(png|jpe?g|gif|svg|webp)$/i;

export function MarkdownPreview({ path }: { path: string }) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const ctrl = new AbortController();
    fetch(artifactUrl(path), { signal: ctrl.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(res.statusText);
        const t = await res.text();
        if (!cancelled) setText(t);
      })
      .catch((e: unknown) => {
        if (!cancelled && !ctrl.signal.aborted) {
          setError(e instanceof Error ? e.message : String(e));
        }
      });
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [path]);

  if (error !== null) {
    return (
      <div className="py-1.5">
        <AlertBanner>{error}</AlertBanner>
      </div>
    );
  }
  if (text === null) {
    return (
      <div className="flex items-center gap-2 py-2 text-2xs text-ink-3">
        <Spinner className="h-3 w-3" />
        {t.loading}
      </div>
    );
  }
  return (
    <div className="md mt-1.5 max-h-80 overflow-y-auto rounded-lg border border-line bg-surface p-3 text-xs">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={mdComponentsWithBase(path)}
        urlTransform={mdUrlTransform}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

function ArtifactRow({ artifact }: { artifact: ArtifactEntry }) {
  const [open, setOpen] = useState(false);
  const isMd = MD_EXT.test(artifact.rel);
  const isImg = IMG_EXT.test(artifact.rel);
  const previewable = isMd || isImg;
  const rel = normPath(artifact.rel);

  return (
    <div className="px-3 py-1" data-testid="artifact-row">
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate font-mono text-2xs text-ink" title={rel}>
          {baseName(rel)}
        </span>
        <span className="shrink-0 text-2xs text-ink-3 tabular-nums">
          {fmtBytes(artifact.size)}
        </span>
        {previewable && (
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
            className={cx(
              "h-5 shrink-0 rounded-md px-1.5 text-2xs transition-colors",
              open ? "bg-raised text-ink" : "text-ink-3 hover:bg-raised hover:text-ink-2",
            )}
          >
            {t.previewArtifact}
          </button>
        )}
        <a
          href={artifactUrl(artifact.path)}
          target="_blank"
          rel="noreferrer"
          className="h-5 shrink-0 rounded-md px-1.5 text-2xs leading-5 text-accent transition-colors hover:bg-accent/10"
        >
          {t.openArtifact}
        </a>
      </div>
      {open && isMd && <MarkdownPreview path={artifact.path} />}
      {open && isImg && (
        <img
          src={artifactUrl(artifact.path)}
          alt={artifact.rel}
          className="mt-1.5 max-h-80 rounded-lg border border-line"
        />
      )}
    </div>
  );
}

function GroupSection({ group, mark }: { group: ArtifactGroup; mark: DeliveryMark | null }) {
  const [all, setAll] = useState(false);
  const n = group.main.length + group.rest.length;
  const label = group.dir === "" ? t.artifactsTopLevel : group.dir;
  return (
    <section className="border-b border-line/60 pb-1 last:border-b-0" data-testid="artifact-group">
      <div className="flex items-baseline gap-2 px-3 pt-2 pb-1">
        <span className="min-w-0 truncate text-xs font-medium text-ink" title={label}>
          {label}
        </span>
        {mark && (
          <span className={cx("shrink-0 rounded-md px-1 text-2xs font-medium", deliveryTone(mark.status))}>
            {deliveryStatusLabel(mark.status)}
          </span>
        )}
        {mark && (
          <span className="shrink-0 font-mono text-2xs text-ink-3">
            {t.deliveryNode} {mark.node}
          </span>
        )}
        <span className="ml-auto shrink-0 text-2xs text-ink-3 tabular-nums">
          {n} {t.deliveryFilesUnit}
        </span>
      </div>
      {group.main.map((a) => (
        <ArtifactRow key={a.rel} artifact={a} />
      ))}
      {group.rest.length > 0 && (
        <>
          <button
            type="button"
            aria-expanded={all}
            onClick={() => setAll((v) => !v)}
            className="mx-3 my-0.5 h-6 rounded-md px-2 text-2xs text-ink-3 transition-colors hover:bg-raised hover:text-ink"
          >
            {all
              ? t.artifactsMainOnly
              : `${t.deliveryAllFiles} ${n} ${t.deliveryFilesUnit}${group.main.length > 0 ? ` (+${group.rest.length})` : ""}`}
          </button>
          {all && group.rest.map((a) => <ArtifactRow key={a.rel} artifact={a} />)}
        </>
      )}
    </section>
  );
}

function LogsSection({ logs }: { logs: ArtifactEntry[] }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="pb-1" data-testid="artifact-logs">
      <button
        type="button"
        aria-expanded={open}
        title={t.artifactsLogsTip}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-baseline gap-2 px-3 pt-2 pb-1 text-left"
      >
        <span className={cx("text-2xs text-ink-3 transition-transform", open && "rotate-90")}>▶</span>
        <span className="text-xs font-medium text-ink-3">{t.artifactsLogs}</span>
        <span className="ml-auto text-2xs text-ink-3 tabular-nums">
          {logs.length} {t.deliveryFilesUnit}
        </span>
      </button>
      {open && logs.map((a) => <ArtifactRow key={a.rel} artifact={a} />)}
    </section>
  );
}

export function ArtifactsPanel() {
  const thread = useThreadOptional();
  const { state: crystal } = useCrystal();
  const artifacts = thread?.state.artifacts ?? [];
  const turnActive = thread?.state.turn.active === true;
  const { groups, logs } = useMemo(() => groupArtifacts(artifacts), [artifacts]);

  if (artifacts.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center text-xs text-ink-3">
        {turnActive ? (
          <>
            <Spinner className="h-3.5 w-3.5" />
            {t.artifactsPending}
          </>
        ) : (
          t.noArtifacts
        )}
      </div>
    );
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto py-1" data-testid="artifacts-panel">
      {groups.map((g) => (
        <GroupSection key={g.dir} group={g} mark={markFor(g, crystal.deliveries)} />
      ))}
      {logs.length > 0 && <LogsSection logs={logs} />}
    </div>
  );
}
