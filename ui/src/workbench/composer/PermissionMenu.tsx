/** The "自动 ▾" popover, slimmed (2026-09-07): the four approval modes and
 * the per-project switches that decide what the agent may do - IUCr upload,
 * the ONE sub-agent switch, knowledge mode, structure class. Explanations
 * live in hover tooltips; model/effort moved to the model button; the rest
 * (specialists, kernel, keys) lives in 设置. */
import { clickedOutside } from "../../lib/outsideClick";
import { useEffect, useRef, useState } from "react";
import { Spinner } from "../../components/ui";
import { cx } from "../../lib/format";
import { structureClassLabel, type StructureClass } from "../../lib/structureClass";
import { PERMISSION_MODES, type SubagentMode } from "../../lib/wbTypes";
import { formatEffort, permissionDesc, permissionLabel, zh } from "../../lib/zh";
import { useWorkbench } from "../../state/WorkbenchProvider";
import { IconCheck } from "../icons";
import { Switch } from "./Switch";

/** "自动 · 当前开（最高档）" etc. - the switch's state in a few words. */
export function subagentStateText(
  mode: SubagentMode,
  active: boolean,
  topEffort: string | null | undefined,
): string {
  if (mode === "on") return zh.subagentsStateOn;
  if (mode === "off") return zh.subagentsStateOff;
  if (active) return zh.subagentsStateAutoOn;
  return topEffort
    ? `${zh.subagentsStateAutoOff}（${formatEffort(topEffort)}档时开）`
    : zh.subagentsStateAutoOff;
}

export function PermissionMenu({
  current,
  onPick,
  onClose,
}: {
  current: string;
  onPick: (mode: string) => void;
  onClose: () => void;
}) {
  const wb = useWorkbench();
  const ref = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (clickedOutside(ref.current, e)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const run = async (key: string, fn: () => Promise<string | null>) => {
    if (busy !== null) return;
    setBusy(key);
    setError(null);
    const err = await fn();
    setBusy(null);
    if (err !== null) setError(err);
  };

  const s = wb.settings;
  const iucrOn = s?.allow_iucr_upload ?? false;
  const subMode: SubagentMode = s?.subagents ?? "auto";
  const delegation = s?.delegation;
  const subActive = delegation?.active ?? false;
  const knowledgeMode = s?.knowledge_mode ?? "full";
  const knowledgeModes = s?.knowledge_modes ?? ["full", "tools_only"];
  const structureClasses = s?.structure_classes ?? [];

  const rowCls = "flex h-8 items-center justify-between gap-3 rounded-lg px-2.5";
  const selectCls =
    "h-6 max-w-40 shrink-0 rounded-md border border-line bg-surface px-1 text-xs text-ink-2 outline-none focus:border-accent/60 disabled:opacity-50";

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label={zh.permTitle}
      data-testid="permission-menu"
      className="workbench-popover absolute bottom-full left-0 z-30 mb-2 w-72 rounded-card border border-line bg-bg p-1.5 shadow-xl"
    >
      <div className="px-2.5 py-1.5 text-xs font-medium text-ink-2">{zh.permTitle}</div>
      {PERMISSION_MODES.map((mode) => {
        const active = mode === current;
        const full = mode === "full";
        return (
          <button
            key={mode}
            type="button"
            title={permissionDesc(mode)}
            onClick={() => onPick(mode)}
            className="flex h-8 w-full items-center gap-2.5 rounded-lg px-2.5 text-left transition-colors hover:bg-raised"
          >
            <span className={cx("flex-1 text-sm font-medium", full ? "text-warn" : "text-ink")}>
              {permissionLabel(mode)}
            </span>
            {active && (
              <IconCheck size={14} className={cx("shrink-0", full ? "text-warn" : "text-ink")} />
            )}
          </button>
        );
      })}

      <div className="mt-1 border-t border-line pt-1">
        <div className="px-2.5 py-1.5 text-xs font-medium text-ink-2">{zh.permProjectSection}</div>

        {/* IUCr upload opt-in */}
        <div className={rowCls} data-testid="settings-iucr">
          <span className="min-w-0 flex-1 truncate text-sm text-ink" title={zh.iucrTip}>
            {zh.settingsIucrTitle}
          </span>
          <Switch
            checked={iucrOn}
            disabled={busy !== null}
            title={zh.iucrTip}
            onToggle={() => void run("iucr", () => wb.changeIucrUpload(!iucrOn))}
            label={zh.settingsIucrTitle}
          />
        </div>

        {/* THE sub-agent switch: auto (top rung => on) / on / off */}
        <div className="rounded-lg px-2.5 py-1" data-testid="settings-subagents">
          <div className="flex h-6 items-center justify-between gap-3">
            <span className="min-w-0 flex-1 truncate text-sm text-ink" title={zh.subagentsTip}>
              {zh.subagentsSwitch}
            </span>
            {busy === "subagents" && <Spinner className="h-3 w-3 text-ink-3" />}
            <Switch
              checked={subActive}
              disabled={busy !== null}
              title={zh.subagentsTip}
              onToggle={() => void run("subagents", () => wb.changeSubagents(subActive ? "off" : "on"))}
              label={zh.subagentsSwitch}
            />
          </div>
          <div className="flex items-center justify-between gap-2 pt-0.5">
            <span
              className="min-w-0 truncate text-2xs text-ink-3"
              data-testid="subagents-state"
              title={zh.subagentsTip}
            >
              {subagentStateText(subMode, subActive, delegation?.top_effort)}
            </span>
            {subMode !== "auto" && (
              <button
                type="button"
                title={zh.subagentsAutoTip}
                disabled={busy !== null}
                onClick={() => void run("subagents", () => wb.changeSubagents("auto"))}
                className="shrink-0 rounded-md border border-line px-1.5 text-2xs text-ink-2 transition-colors hover:bg-raised hover:text-ink disabled:opacity-50"
              >
                {zh.subagentsAutoLabel}
              </button>
            )}
          </div>
        </div>

        {/* knowledge mode (ablation arm) */}
        <div className={rowCls} data-testid="settings-knowledge-mode">
          <span className="min-w-0 flex-1 truncate text-sm text-ink" title={zh.knowledgeTip}>
            {zh.settingsKnowledgeMode}
          </span>
          <select
            value={knowledgeMode}
            disabled={busy !== null}
            aria-label={zh.settingsKnowledgeMode}
            title={zh.knowledgeTip}
            onChange={(e) => void run("km", () => wb.changeKnowledgeMode(e.target.value))}
            className={selectCls}
          >
            {knowledgeModes.map((m) => (
              <option key={m} value={m}>
                {zh.knowledgeModeLabels[m] ?? m}
              </option>
            ))}
          </select>
        </div>

        {/* owner-declared structure class */}
        <div className={rowCls} data-testid="settings-structure-class">
          <span className="min-w-0 flex-1 truncate text-sm text-ink" title={zh.structureClassTip}>
            {zh.settingsStructureClass}
          </span>
          <select
            value={wb.structureClass ?? ""}
            disabled={busy !== null}
            aria-label={zh.settingsStructureClass}
            title={zh.structureClassTip}
            onChange={(e) => {
              const v = e.target.value;
              void run("sc", () => wb.changeStructureClass(v === "" ? null : v));
            }}
            className={selectCls}
          >
            <option value="">{zh.settingsStructureClassNone}</option>
            {structureClasses.map((c) => (
              <option key={c} value={c}>
                {structureClassLabel(c as StructureClass)}
              </option>
            ))}
          </select>
        </div>

        {error !== null && (
          <div className="px-2.5 pt-1 text-2xs leading-snug text-danger">{error}</div>
        )}
      </div>

      <div className="mt-1 border-t border-line pt-1">
        <button
          type="button"
          onClick={() => {
            onClose();
            wb.openSettings("providers");
          }}
          className="flex h-8 w-full items-center rounded-lg px-2.5 text-left text-xs text-ink-2 transition-colors hover:bg-raised hover:text-ink"
        >
          {zh.openSettingsLink}
        </button>
      </div>
    </div>
  );
}
