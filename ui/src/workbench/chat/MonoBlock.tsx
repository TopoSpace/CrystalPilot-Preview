/** Mono <pre> block with a hover copy button (wave 2 - every expanded
 * command/tool payload is one click from the clipboard, Codex style).
 * CopyAction is the shared hover copy control (also used under agent
 * prose). The button pins to the wrapper, not the pre, so it stays put
 * while long output scrolls. */
import { useState } from "react";
import { t } from "../../lib/i18n";
import { IconCheck, IconCopy } from "../icons";

export function CopyAction({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const onCopy = () => {
    void navigator.clipboard
      .writeText(text)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => undefined);
  };
  return (
    <button
      type="button"
      title={copied ? t.copied : t.copyMessage}
      aria-label={t.copyMessage}
      onClick={onCopy}
      className="flex h-6 w-6 items-center justify-center rounded-md text-ink-3 transition-colors hover:bg-raised hover:text-ink"
    >
      {copied ? (
        <IconCheck size={13} className="text-ok" />
      ) : (
        <IconCopy size={13} />
      )}
    </button>
  );
}

export function MonoBlock({
  text,
  className,
  wrapClassName,
  copyText,
}: {
  text: string;
  /** classes for the <pre> itself (bg, size, palette) */
  className?: string;
  /** classes for the relative wrapper (margins live here so the copy
   * button tracks the block, not the offset) */
  wrapClassName?: string;
  /** what the button copies when it differs from the shown text
   * (e.g. a truncated error tail copying the full output) */
  copyText?: string;
}) {
  return (
    <div className={`group/pre relative ${wrapClassName ?? ""}`}>
      <pre className={className}>{text}</pre>
      <div className="absolute top-1 right-1 rounded-md bg-surface/70 opacity-0 backdrop-blur-sm transition-opacity group-hover/pre:opacity-100 focus-within:opacity-100">
        <CopyAction text={copyText ?? text} />
      </div>
    </div>
  );
}
