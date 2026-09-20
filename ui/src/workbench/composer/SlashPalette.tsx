/** The "/" command list above the composer (Codex style): the matching
 * commands, the highlighted one, the Codex CLI counterpart dimmed on the
 * right. Keyboard handling stays in the composer (the textarea has focus);
 * this component only renders.
 *
 * A mouse pick runs on `click`, not `mousedown` (2026-09-16): executing the
 * command inside the mousedown handler unmounted this palette and mounted
 * the model / permission menu while that same mousedown was still
 * bubbling, so the new menu's document-level outside-click listener saw a
 * detached target and closed it in the same tick. `mousedown` now only
 * prevents the textarea from losing focus; the pick goes through the exact
 * function Enter uses (Composer.runSlash). */
import { cx } from "../../lib/format";
import type { SlashCommand } from "../../lib/slashCommands";
import { t } from "../../lib/i18n";

export function SlashPalette({
  items,
  index,
  onHover,
  onPick,
}: {
  items: SlashCommand[];
  index: number;
  onHover: (i: number) => void;
  onPick: (cmd: SlashCommand) => void;
}) {
  return (
    <div
      role="listbox"
      aria-label={t.slashHint}
      data-testid="slash-palette"
      className="workbench-popover absolute right-0 bottom-full left-0 z-30 mb-2 overflow-hidden rounded-card border border-line bg-bg shadow-xl"
    >
      {items.length === 0 ? (
        <div className="px-3 py-2 text-xs text-ink-3">{t.slashNoMatch}</div>
      ) : (
        <div className="max-h-72 overflow-y-auto py-1">
          {items.map((c, i) => (
            <button
              key={c.name}
              type="button"
              role="option"
              aria-selected={i === index}
              onMouseEnter={() => onHover(i)}
              onMouseDown={(e) => {
                // keep the textarea focused; the pick happens on click
                e.preventDefault();
              }}
              onClick={() => onPick(c)}
              data-testid={`slash-item-${c.name}`}
              className={cx(
                "flex h-8 w-full items-center gap-3 px-3 text-left transition-colors",
                i === index ? "bg-raised" : "hover:bg-raised/60",
              )}
            >
              <span className="shrink-0 font-mono text-sm text-ink">
                /{c.name}
                {c.args && <span className="text-ink-3"> {c.args}</span>}
              </span>
              <span className="min-w-0 flex-1 truncate text-xs text-ink-2">{c.desc}</span>
              {c.codex && c.codex !== `/${c.name}` && (
                <span className="shrink-0 font-mono text-2xs text-ink-3">{c.codex}</span>
              )}
            </button>
          ))}
        </div>
      )}
      <div className="border-t border-line px-3 py-1 text-2xs text-ink-3">
        ↑↓ {t.shell.paletteSelect} · Tab {t.shell.paletteComplete} · {t.slashRun} · Esc {t.cancel}
      </div>
    </div>
  );
}
