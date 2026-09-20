/** Status rail (round-3 R2-A): one row under the thread header that says
 * where work was observed (stages as • / ● / ○) and what is happening now
 * (one action line: breathing spark + humanized current tool + elapsed +
 * "可插话", or waiting-for-approval, or the idle summary of the last
 * turn). It replaces the counting stage track, the header's running badge
 * and the floating "current action" pill - three elements that said the
 * same thing in three places. A stage still opens into the turns that did
 * its work, so the rail is navigation too. Below 1000 px the stage list
 * scrolls horizontally instead of wrapping. */
import { clickedOutside } from "../../lib/outsideClick";
import { useEffect, useMemo, useRef, useState } from "react";
import { Spinner } from "../../components/ui";
import { cx, fmtMmSs } from "../../lib/format";
import {
  motionScrollBehavior,
  useActiveNow,
  useMotionPreference,
} from "../../lib/motion";
import { railModel, type RailStage } from "../../lib/statusRail";
import { t } from "../../lib/i18n";
import { useThread } from "../../state/ThreadProvider";
import { IconShield, IconSpark } from "../icons";
import { turnDigestText } from "./TurnStatusRow";

function StageGlyph({ state }: { state: RailStage["state"] }) {
  if (state === "visited") {
    return (
      <span
        aria-hidden="true"
        className="inline-block h-[7px] w-[7px] shrink-0 rounded-full bg-ink-2/65"
      />
    );
  }
  if (state === "current") {
    return (
      <span
        aria-hidden="true"
        className="inline-block h-[7px] w-[7px] shrink-0 rounded-full bg-accent"
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      className="inline-block h-[7px] w-[7px] shrink-0 rounded-full border border-ink-3/50"
    />
  );
}

export function StatusRail() {
  const { state } = useThread();
  const motion = useMotionPreference();
  // the clock also runs while a detached solver is running after the turn
  const solverRunning = Object.values(state.backgroundJobs).some((j) => j.running);
  const now = useActiveNow(state.turn.active || solverRunning, motion.pageVisible);
  const model = useMemo(() => railModel(state, now), [state, now]);
  const [open, setOpen] = useState<RailStage["id"] | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open === null) return undefined;
    const onDown = (e: MouseEvent) => {
      if (clickedOutside(ref.current, e)) setOpen(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented) {
        e.preventDefault();
        setOpen(null);
        ref.current?.querySelector<HTMLElement>(`[data-stage="${open}"]`)?.focus({ preventScroll: true });
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  if (state.items.length === 0 && state.channel !== "connecting") return null;

  const { action } = model;
  const basisTitle =
    model.basis === "situation_report"
      ? t.stageBasisSituation
      : model.basis === "tool"
        ? t.stageBasisTool
        : "";
  const jump = (id: string) => {
    document.getElementById(`turn-${id}`)?.scrollIntoView({
      behavior: motionScrollBehavior(motion.reducedMotion),
      block: "center",
    });
    setOpen(null);
  };
  const openStage = model.stages.find((s) => s.id === open) ?? null;
  const turnsOf = (s: RailStage) => {
    const byId = new Map<string, string>();
    for (const it of state.items) {
      if (it.type === "turn" && it.summary)
        byId.set(it.id, turnDigestText(it.summary));
    }
    return s.turnIds.map((id) => ({ id, text: byId.get(id) ?? "" }));
  };

  return (
    <div
      ref={ref}
      data-testid="status-rail"
      data-state={action.kind}
      className="relative flex h-9 shrink-0 items-center gap-3 border-b border-line px-5"
    >
      <div
        data-testid="stage-track"
        title={basisTitle}
        className="flex min-w-0 shrink items-center gap-0.5 overflow-x-auto overscroll-x-contain whitespace-nowrap [scrollbar-width:none]"
      >
        {model.stages.map((s, i) => (
          <div key={s.id} className="flex shrink-0 items-center">
            {i > 0 && (
              <span
                className={cx(
                  "mx-0.5 h-px w-2.5",
                  s.state === "pending" ? "bg-line" : "bg-ink-3/50",
                )}
              />
            )}
            <button
              type="button"
              onClick={() => setOpen((o) => (o === s.id ? null : s.id))}
              data-stage={s.id}
              aria-expanded={open === s.id}
              aria-controls={open === s.id ? "stage-history" : undefined}
              aria-current={s.state === "current" ? "step" : undefined}
              title={
                s.state === "visited"
                  ? t.shell.railStageVisited(s.label)
                  : s.nTools > 0
                    ? `${s.label} · ${s.nTools} ${t.stageToolsUnit}`
                    : s.label
              }
              className={cx(
                "flex h-6 items-center gap-1.5 rounded-pill px-2 text-2xs transition-colors",
                s.state === "current" && "font-medium text-ink",
                s.state === "visited" && "text-ink-2 hover:bg-raised",
                s.state === "pending" && "text-ink-3 hover:bg-raised",
              )}
            >
              <StageGlyph state={s.state} />
              {s.label}
            </button>
          </div>
        ))}
      </div>

      <div
        data-testid="rail-action"
        className={cx(
          "ml-auto flex min-w-0 shrink items-center gap-2 text-xs",
          action.kind === "working" && "text-ink-2",
          action.kind === "background" && "text-ink-2",
          action.kind === "compacting" && "text-ink-2",
          (action.kind === "approval" || action.kind === "question" || action.kind === "disconnected") && "text-warn",
          action.kind === "failed" && "text-ink-2",
          action.kind === "interrupted" && "text-warn",
          (action.kind === "idle" ||
            action.kind === "fresh" ||
            action.kind === "connecting") &&
            "text-ink-3",
        )}
      >
        {action.kind === "working" && (
          <IconSpark
            size={13}
            className={cx(
              "shrink-0 text-accent",
              !action.muted && motion.animationsEnabled && "pulse-star",
            )}
            aria-hidden="true"
          />
        )}
        {action.kind === "background" && (
          <Spinner className="h-3 w-3 shrink-0 text-ink-3" />
        )}
        {(action.kind === "connecting" || action.kind === "compacting") && (
          <Spinner className="h-3 w-3 shrink-0 text-ink-3" />
        )}
        {action.kind === "approval" && (
          <IconShield size={13} className="shrink-0" aria-hidden="true" />
        )}
        <span className={cx("min-w-0 truncate", (action.kind === "working" || action.kind === "compacting") && "shimmer-text")} role="status" aria-live="polite">
          {action.text}
        </span>
        {(action.kind === "working" || action.kind === "background") && action.elapsedMs !== null && (
          <span className="shrink-0 font-mono text-2xs text-ink-3 tabular-nums">
            {fmtMmSs(action.elapsedMs)}
          </span>
        )}
        {action.kind === "working" && (
          <span className="hidden shrink-0 text-2xs text-ink-3 sm:inline">
            · {t.railSteerable}
          </span>
        )}
      </div>

      {openStage !== null && (
        <div id="stage-history" className="absolute top-full left-5 z-30 mt-1 w-[26rem] max-w-[90vw] rounded-card border border-line bg-bg p-2 shadow-lg">
          <div className="mb-1 flex items-center gap-2 px-1 text-xs font-medium text-ink">
            {openStage.label}
            <span className="font-mono text-2xs text-ink-3">
              {openStage.nTools} {t.stageToolsUnit}
            </span>
          </div>
          {openStage.turnIds.length === 0 ? (
            <div className="px-1 py-1 text-2xs text-ink-3">
              {t.stageNoTurns}
            </div>
          ) : (
            <ul className="max-h-64 overflow-y-auto">
              {turnsOf(openStage).map((tn) => (
                <li key={tn.id}>
                  <button
                    type="button"
                    onClick={() => jump(tn.id)}
                    className="flex w-full items-baseline gap-2 rounded-md px-1 py-1 text-left hover:bg-raised"
                  >
                    <span className="shrink-0 font-mono text-2xs text-ink-3 tabular-nums">
                      {t.turnDone}
                    </span>
                    <span className="min-w-0 truncate font-mono text-2xs text-ink-2">
                      {tn.text || "—"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
