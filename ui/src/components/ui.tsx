/** Shared primitives. Everything is expressed in the semantic theme tokens
 * from index.css (bg/surface/raised/line, ink/ink-2/ink-3, accent/ok/warn/
 * danger) so the legacy pages and the workbench share one palette and one
 * contrast guard (round-2 R1, defect D16: these used to carry raw zinc/
 * indigo classes). Tone names (green/amber/red/indigo) are kept as the API. */
import type {
  AnchorHTMLAttributes,
  ButtonHTMLAttributes,
  HTMLAttributes,
  ReactNode,
} from "react";
import { cx } from "../lib/format";

/* ------------------------------------------------------------------ Button */

type ButtonVariant = "primary" | "outline" | "ghost";
type ButtonSize = "sm" | "md";

const buttonBase =
  "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium " +
  "transition-colors duration-150 select-none " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent " +
  "disabled:pointer-events-none disabled:opacity-40";

const buttonVariants: Record<ButtonVariant, string> = {
  primary: "bg-accent-fill text-bg hover:bg-accent",
  outline: "border border-line bg-bg text-ink hover:bg-raised",
  ghost: "text-ink-2 hover:bg-raised hover:text-ink",
};

const buttonSizes: Record<ButtonSize, string> = {
  sm: "h-7 px-2.5 text-xs",
  md: "h-9 px-4 text-sm",
};

export function buttonClasses(
  variant: ButtonVariant = "primary",
  size: ButtonSize = "md",
  className?: string,
): string {
  return cx(buttonBase, buttonVariants[variant], buttonSizes[size], className);
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export function Button({
  variant = "primary",
  size = "md",
  className,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={buttonClasses(variant, size, className)}
      {...rest}
    />
  );
}

interface ButtonLinkProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export function ButtonLink({
  variant = "outline",
  size = "md",
  className,
  ...rest
}: ButtonLinkProps) {
  return <a className={buttonClasses(variant, size, className)} {...rest} />;
}

/* -------------------------------------------------------------------- Card */

export function Card({
  className,
  ...rest
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx("rounded-card border border-line bg-surface", className)}
      {...rest}
    />
  );
}

/* -------------------------------------------------------------------- Chip */

export type ChipTone = "neutral" | "green" | "amber" | "red" | "indigo";

const chipTones: Record<ChipTone, string> = {
  neutral: "border-line bg-raised text-ink-2",
  green: "border-ok/30 bg-ok/10 text-ok",
  amber: "border-warn/30 bg-warn/10 text-warn",
  red: "border-danger/30 bg-danger/10 text-danger",
  indigo: "border-accent/30 bg-accent/10 text-accent",
};

export function Chip({
  tone = "neutral",
  className,
  children,
}: {
  tone?: ChipTone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cx(
        "inline-flex h-5 items-center gap-1.5 rounded-md border px-1.5",
        "text-2xs font-medium whitespace-nowrap",
        chipTones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/* -------------------------------------------------------------------- Tabs */

export interface TabDef<T extends string> {
  id: T;
  label: string;
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: TabDef<T>[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div role="tablist" className="flex gap-5 border-b border-line">
      {tabs.map((t) => {
        const active = t.id === value;
        return (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={active}
            onClick={() => onChange(t.id)}
            className={cx(
              "-mb-px border-b-2 pb-2 text-sm font-medium transition-colors duration-150",
              active
                ? "border-accent text-ink"
                : "border-transparent text-ink-2 hover:text-ink",
            )}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

/* ----------------------------------------------------------------- Spinner */

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={cx("h-3.5 w-3.5 animate-spin", className)}
      viewBox="0 0 24 24"
      fill="none"
      aria-label="Loading"
    >
      <circle
        className="opacity-20"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="3"
      />
      <path
        d="M22 12a10 10 0 0 0-10-10"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}

/* ------------------------------------------------------- SegmentedControl */

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  disabled?: boolean;
  title?: string;
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-surface p-0.5">
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            disabled={o.disabled}
            title={o.title}
            aria-pressed={active}
            onClick={() => onChange(o.value)}
            className={cx(
              "h-7 rounded-md px-3 text-xs font-medium transition-colors duration-150",
              "disabled:cursor-not-allowed disabled:opacity-40",
              active
                ? "bg-bg text-ink shadow-none ring-1 ring-line"
                : "text-ink-2 hover:text-ink",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------ Small pieces */

export function SectionLabel({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cx(
        "text-2xs font-medium tracking-[0.08em] uppercase text-ink-3",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function StatusDot({
  tone,
  pulse = false,
  size = 6,
}: {
  tone: "green" | "amber" | "red" | "indigo" | "neutral";
  /** Codex-style quiet breathing (opacity), not an expanding ping ring. */
  pulse?: boolean;
  /** diameter in px */
  size?: number;
}) {
  const color = {
    green: "bg-ok",
    amber: "bg-warn",
    red: "bg-danger",
    indigo: "bg-accent",
    neutral: "bg-line",
  }[tone];
  return (
    <span
      className="relative inline-flex shrink-0"
      style={{ width: size, height: size }}
    >
      <span
        className={cx(
          "inline-flex h-full w-full rounded-full",
          color,
          pulse && "animate-pulse",
        )}
      />
    </span>
  );
}

/** Unified inline error/warning banner (workbench semantic tokens). */
export function AlertBanner({
  tone = "danger",
  className,
  children,
}: {
  tone?: "danger" | "warn";
  className?: string;
  children: ReactNode;
}) {
  const tones = {
    danger: "border-danger/30 bg-danger/10 text-danger",
    warn: "border-warn/30 bg-warn/10 text-warn",
  } as const;
  return (
    <div
      role="alert"
      className={cx(
        "rounded-lg border px-3 py-2 text-xs leading-snug break-words",
        tones[tone],
        className,
      )}
    >
      {children}
    </div>
  );
}

export function gradeTone(grade: string | undefined): ChipTone {
  switch (grade) {
    case "high":
      return "green";
    case "medium":
      return "amber";
    case "low":
      return "red";
    default:
      return "neutral";
  }
}

export function ConfidenceBadge({
  score,
  grade,
}: {
  score: number;
  grade: string;
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="font-mono text-sm tabular-nums">
        {score.toFixed(0)}
        <span className="text-ink-3">/100</span>
      </span>
      <Chip tone={gradeTone(grade)}>{grade}</Chip>
    </span>
  );
}

export function EmptyState({
  title,
  children,
}: {
  title?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-1 px-6 py-12 text-center">
      {title && (
        <div className="text-sm font-medium text-ink-2">{title}</div>
      )}
      {children && <div className="text-xs text-ink-3">{children}</div>}
    </div>
  );
}
