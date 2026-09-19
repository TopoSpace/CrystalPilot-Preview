import type { ReactNode } from "react";
import { cx } from "../../lib/format";
import { IconChevronDown, IconShield } from "../icons";

/** Shared, text-sized disclosure. Its chevron belongs to the text, not the row edge. */
export function ActivitySummary({ icon, children, running = false, issue, title }: {
  icon: ReactNode;
  children: ReactNode;
  running?: boolean;
  issue?: string;
  title?: string;
}) {
  return (
    <summary className="activity-summary" title={title}>
      <span className="activity-icon">{icon}</span>
      <span className="activity-copy">
        <span className={cx("activity-label", running && "shimmer-text")}>{children}</span>
        {issue && <span className="activity-issue" role="img" aria-label={issue} title={issue}><IconShield size={13} /></span>}
        <IconChevronDown size={13} className="activity-chevron" />
      </span>
    </summary>
  );
}
