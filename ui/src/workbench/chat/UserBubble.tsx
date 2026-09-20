/** Right-aligned gray user bubble (Codex style); steer messages get a small
 * 插话 tag plus a receipt (round-3 R6: 发送中 / 已记录 / 已送达模型 / 未送达模型
 * with retry); optimistic (pending) bubbles are slightly translucent.
 * `[anchor …]` tokens render as chips that jump the crystal pane to that
 * node and atom (history view, never a checkout). */
import { cx } from "../../lib/format";
import { ANCHOR_RE, parseAnchor } from "../../lib/quote";
import { t } from "../../lib/i18n";
import { useCrystalOptional, type CrystalContextValue } from "../../state/CrystalProvider";
import type { UserItem } from "../../state/threadReducer";
import { useThreadOptional } from "../../state/ThreadProvider";
import { CopyAction } from "./MonoBlock";

export interface SteerReceipt {
  state: "sending" | "persisted" | "submitted" | "failed";
  label: string;
  title?: string;
}

/** What the bubble says about a steer's fate; null for plain messages. */
export function steerReceipt(item: UserItem): SteerReceipt | null {
  if (!item.steer) return null;
  if (item.pending) return { state: "sending", label: t.receiptSending };
  if (item.receipt === "failed") {
    return { state: "failed", label: t.receiptFailed, title: item.receiptError };
  }
  if (item.receipt === "submitted") return { state: "submitted", label: t.receiptSubmitted };
  return { state: "persisted", label: t.receiptPersisted };
}

export function UserBubble({ item }: { item: UserItem }) {
  const thread = useThreadOptional();
  const crystal = useCrystalOptional();
  const receipt = steerReceipt(item);
  return (
    <div
      className="user-message group flex flex-col items-end"
      data-testid="user-bubble"
      data-steer={item.steer ? "1" : undefined}
      data-receipt={receipt?.state}
    >
      <div
        className={cx(
          "user-message-bubble rounded-bubble bg-raised/70 px-5 py-3.5",
          item.pending && "opacity-60",
        )}
      >
        {item.steer && (
          <span className="mb-1 inline-flex items-center gap-1.5">
            <span className="inline-flex h-[18px] items-center rounded-pill bg-accent/15 px-1.5 text-2xs font-medium text-accent">
              {t.steer}
            </span>
            {receipt !== null && (
              <span
                className={cx("text-2xs", receipt.state === "failed" ? "text-danger" : "text-ink-3")}
                title={receipt.title}
              >
                {receipt.label}
                {receipt.state === "failed" && thread !== null && (
                  <button
                    type="button"
                    onClick={() => void thread.steer(item.text)}
                    className="ml-1 underline decoration-dotted underline-offset-2"
                  >
                    {t.receiptRetry}
                  </button>
                )}
              </span>
            )}
          </span>
        )}
        {item.attachments && item.attachments.length > 0 && (
          <div className="mb-1.5 flex flex-wrap justify-end gap-1">
            {item.attachments.map((name, i) => (
              <span
                key={`${name}-${i}`}
                className="inline-flex max-w-[220px] items-center gap-1 rounded-pill border border-line bg-bg px-2 py-0.5 text-2xs text-ink-2"
                title={name}
              >
                <span aria-hidden="true">📎</span>
                <span className="truncate">{name}</span>
              </span>
            ))}
          </div>
        )}
        <div className="text-md leading-[1.65] whitespace-pre-wrap break-words text-ink">
          {renderWithAnchors(item.text, crystal)}
        </div>
      </div>
      <div className="message-actions justify-end" data-testid="user-copy">
        <CopyAction text={item.text || item.attachments?.join("\n") || ""} />
      </div>
    </div>
  );
}

/** `[anchor node=… atoms=…]` tokens render as chips (the composer keeps them
 * as editable text; only the transcript dresses them up). With a crystal
 * pane mounted the chip is a button: view that node (history, no checkout)
 * and select the first named atom. */
function renderWithAnchors(text: string, crystal: CrystalContextValue | null) {
  const parts: React.ReactNode[] = [];
  let last = 0;
  let k = 0;
  for (const m of text.matchAll(ANCHOR_RE)) {
    const idx = m.index ?? 0;
    if (idx > last) parts.push(text.slice(last, idx));
    const a = parseAnchor(m[1]);
    const cls =
      "mx-0.5 inline-flex max-w-full items-center gap-1 rounded-pill border border-line bg-bg px-1.5 align-baseline font-mono text-2xs text-ink-2";
    const body = (
      <>
        <span className="text-ink-3">{t.anchorChip}</span>
        {a.node && <span>{a.node}</span>}
        {a.atoms.length > 0 && <span className="truncate">{a.atoms.join(" ")}</span>}
      </>
    );
    if (crystal !== null && a.node) {
      const node = a.node;
      parts.push(
        <button
          key={`anc-${k}`}
          type="button"
          className={cx(cls, "cursor-pointer hover:border-accent/60 hover:text-ink")}
          title={t.anchorJump(node)}
          data-testid="anchor-chip"
          onClick={() => {
            if (a.atoms.length > 0) crystal.selectLabel(node, a.atoms[0]);
            else crystal.viewNode(node);
          }}
        >
          {body}
        </button>,
      );
    } else {
      parts.push(
        <span key={`anc-${k}`} className={cls} title={m[0]} data-testid="anchor-chip">
          {body}
        </span>,
      );
    }
    k += 1;
    last = idx + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts.length === 0 ? text : parts;
}
