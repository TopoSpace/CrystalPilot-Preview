/** Small pill switch (no dependency): track + sliding knob. */
import { cx } from "../../lib/format";

export function Switch({
  checked,
  disabled,
  onToggle,
  label,
  title,
}: {
  checked: boolean;
  disabled?: boolean;
  onToggle: () => void;
  label: string;
  title?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={title}
      disabled={disabled}
      onClick={onToggle}
      className={cx(
        "relative h-[18px] w-[30px] shrink-0 rounded-pill transition-colors disabled:opacity-50",
        checked ? "bg-accent" : "bg-raised border border-line",
      )}
    >
      <span
        className={cx(
          "absolute top-1/2 left-[2px] h-[13px] w-[13px] -translate-y-1/2 rounded-pill bg-bg shadow-sm transition-transform",
          checked && "translate-x-[13px]",
        )}
      />
    </button>
  );
}
