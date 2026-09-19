import type { RunDetail } from "../../lib/api";
import { cifUrl } from "../../lib/api";
import { ButtonLink, Card, EmptyState, SectionLabel } from "../../components/ui";

export function ReportTab({ run }: { run: RunDetail }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <SectionLabel>Structure report</SectionLabel>
        {run.has_cif && (
          <ButtonLink
            href={cifUrl(run.run_id)}
            download={`${run.run_id}.cif`}
            size="sm"
          >
            <svg
              viewBox="0 0 24 24"
              className="h-3.5 w-3.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M12 3v12M7 10l5 5 5-5" />
              <path d="M4 17v1a3 3 0 0 0 3 3h10a3 3 0 0 0 3-3v-1" />
            </svg>
            Download CIF
          </ButtonLink>
        )}
      </div>
      {run.report ? (
        <Card className="overflow-hidden">
          <pre className="overflow-x-auto px-4 py-4 font-mono text-xs leading-relaxed whitespace-pre text-zinc-700 dark:text-zinc-300">
            {JSON.stringify(run.report, null, 2)}
          </pre>
        </Card>
      ) : (
        <Card>
          <EmptyState title="No report yet">
            {run.status === "running"
              ? "The report is written when the run completes."
              : "This run finished without producing a report."}
          </EmptyState>
        </Card>
      )}
    </div>
  );
}
