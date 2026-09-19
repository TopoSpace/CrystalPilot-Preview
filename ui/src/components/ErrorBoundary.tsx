/** Recoverable error boundary (round-3 R1).
 *
 * One per workbench region (sidebar / chat / crystal pane / app root): a
 * renderer exception blanks only its region, keeps the diagnostics (message,
 * stack, component stack, transcript cursor, node) instead of swallowing
 * them, and offers "重新加载此区域" and "复制诊断". Before this the app had no
 * boundary at all - any throw unmounted #root (forensics 2026-09-05).
 */
import { Component, type ErrorInfo, type ReactNode } from "react";
import {
  formatDiagnostic,
  reportUiDiagnostic,
  type DiagnosticReport,
} from "../lib/diagnostics";
import { zh } from "../lib/zh";

interface Props {
  /** short region name that goes into the diagnostic line */
  area: string;
  children: ReactNode;
  /** changing this value clears a caught error (e.g. the thread id) */
  resetKey?: unknown;
  className?: string;
}

interface State {
  report: DiagnosticReport | null;
  copied: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { report: null, copied: false };

  static getDerivedStateFromError(): Partial<State> {
    // the report itself is built in componentDidCatch (it needs the stack)
    return { copied: false };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    const report = reportUiDiagnostic(
      this.props.area,
      error,
      info.componentStack,
    );
    this.setState({ report });
  }

  componentDidUpdate(prev: Props): void {
    if (prev.resetKey !== this.props.resetKey && this.state.report !== null) {
      this.setState({ report: null, copied: false });
    }
  }

  private retry = (): void => {
    this.setState({ report: null, copied: false });
  };

  private copy = (): void => {
    const r = this.state.report;
    if (!r) return;
    const text = formatDiagnostic(r);
    void navigator.clipboard?.writeText(text).then(
      () => this.setState({ copied: true }),
      () => undefined,
    );
  };

  render(): ReactNode {
    const { report } = this.state;
    if (report === null) return this.props.children;
    return (
      <div
        role="alert"
        data-testid={`error-boundary-${this.props.area}`}
        className={
          this.props.className ??
          "m-3 flex flex-col gap-2 rounded-card border border-danger/40 bg-surface p-4 text-sm text-ink"
        }
      >
        <div className="font-medium text-danger">{zh.errorAreaTitle}</div>
        <div className="font-mono text-2xs break-all text-ink-2">
          {report.message}
        </div>
        <div className="text-2xs text-ink-3">{zh.errorAreaHint}</div>
        <div className="flex flex-wrap gap-2 pt-1">
          <button
            type="button"
            onClick={this.retry}
            className="h-7 rounded-pill bg-accent-fill px-3 text-xs text-bg transition-colors hover:opacity-90"
          >
            {zh.errorAreaRetry}
          </button>
          <button
            type="button"
            onClick={this.copy}
            className="h-7 rounded-pill border border-line px-3 text-xs text-ink-2 transition-colors hover:bg-raised"
          >
            {this.state.copied ? zh.errorAreaCopied : zh.errorAreaCopy}
          </button>
        </div>
        {report.componentStack && (
          <details className="text-2xs text-ink-3">
            <summary className="cursor-pointer select-none">
              {zh.technicalDetails}
            </summary>
            <pre className="mt-1 max-h-48 overflow-auto font-mono whitespace-pre-wrap">
              {report.componentStack.trim()}
            </pre>
          </details>
        )}
      </div>
    );
  }
}
