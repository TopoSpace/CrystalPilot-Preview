/** Modal dialog: enter a project folder path (or pick a recent one) and open. */
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { AlertBanner, Spinner } from "../../components/ui";
import { importStructureDocument } from "../../lib/wbApi";
import { cx } from "../../lib/format";
import { zh } from "../../lib/zh";
import { useWorkbench } from "../../state/WorkbenchProvider";
import { IconFolder, IconX } from "../icons";
import { useDialogFocus } from "../useDialogFocus";
import { FolderBrowser } from "./FolderBrowser";
import { projectHomeUrl, projectLabel } from "../urls";

export function OpenProjectDialog({ onClose }: { onClose: () => void }) {
  const wb = useWorkbench();
  const navigate = useNavigate();
  const [path, setPath] = useState("");
  const [mode, setMode] = useState<"folder" | "cif">("folder");
  const [cif, setCif] = useState<File | null>(null);
  const [block, setBlock] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  useDialogFocus(dialogRef, onClose);

  const browse = () => { setError(null); setPicking(true); };
  const closeBrowser = (chosen?: string) => {
    if (chosen) setPath(chosen);
    setPicking(false);
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const open = async (p: string) => {
    const trimmed = p.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "cif") {
        if (!cif) {
          setError(zh.cifChooseFile);
          return;
        }
        await importStructureDocument(trimmed, cif, block);
      }
      const ok = await wb.openProject(trimmed);
      if (ok) {
        onClose();
        navigate(projectHomeUrl(trimmed) + (mode === "cif" ? "&view=structure" : ""));
      } else {
        setError(wb.openError ?? "打开失败");
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return createPortal(
    <div
      className="dialog-backdrop fixed inset-0 z-50 flex items-center justify-center p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label={zh.openProjectTitle}
    >
      <div ref={dialogRef} tabIndex={-1} className="dialog-surface max-h-[90vh] w-[520px] max-w-[92vw] overflow-y-auto bg-bg p-6">
        <div className="flex items-center justify-between gap-3"><div className="flex items-center gap-2.5 text-lg font-medium"><IconFolder size={20} className="text-accent" />{zh.openProjectTitle}</div>
        <button type="button" className="chrome-button" onClick={onClose} aria-label="关闭项目选择"><IconX size={16} /></button></div>
        {picking && <FolderBrowser initial={path.trim()} onCancel={() => closeBrowser()} onChoose={closeBrowser} />}
        <div hidden={picking}>
        <div className="mt-3 flex gap-1 rounded-lg bg-surface p-1" role="group" aria-label={zh.openProjectMode}>
          {([['folder', zh.openFolderMode], ['cif', zh.openCifMode]] as const).map(([value, label]) => (
            <button key={value} type="button" disabled={busy} aria-pressed={mode === value}
              onClick={() => { setMode(value); setError(null); }}
              className={cx("flex-1 rounded-md px-3 py-1.5 text-sm", mode === value ? "bg-bg text-ink shadow-sm" : "text-ink-2 hover:text-ink")}>
              {label}
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs leading-relaxed text-ink-3">{mode === "cif" ? zh.cifImportHint : zh.openProjectHint}</p>
        {mode === "cif" && (
          <div className="mt-3 space-y-2">
            <label className="block text-xs text-ink-2">
              {zh.cifChooseFile}
              <input type="file" accept=".cif" disabled={busy}
                onChange={(event) => setCif(event.target.files?.[0] ?? null)}
                className="mt-1 block w-full text-xs text-ink-2 file:mr-2 file:rounded-md file:border-0 file:bg-raised file:px-3 file:py-1.5 file:text-ink" />
            </label>
            <details className="text-xs text-ink-3">
              <summary className="cursor-pointer">{zh.cifBlockLabel}</summary>
              <input value={block} onChange={(event) => setBlock(event.target.value)} disabled={busy}
                aria-label={zh.cifBlockLabel} placeholder={zh.cifBlockHint}
                className="mt-1 w-full rounded-md border border-line bg-bg px-2 py-1.5 font-mono text-ink" />
            </details>
            <div className="text-xs text-ink-2">{zh.cifDestination}</div>
          </div>
        )}
        <form
          className="mt-4 grid grid-cols-[1fr_auto] gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void open(path);
          }}
        >
          <input
            ref={inputRef}
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder={wb.kernel?.config_path?.startsWith("/") ? (mode === "cif" ? "/home/…/projects/sample-view" : "/home/…/projects/sample") : mode === "cif" ? zh.cifDestinationHint : zh.pathPlaceholder}
            aria-label={mode === "cif" ? zh.cifDestination : zh.openProjectHint}
            spellCheck={false}
            className="col-span-2 h-10 min-w-0 w-full rounded-lg border border-line bg-bg px-3 font-mono text-sm text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
          />
          <button
            type="button"
            disabled={busy || picking}
            title={zh.browseFolder}
            data-testid="browse-folder"
            onClick={() => void browse()}
            className="h-9 justify-self-start rounded-lg border border-line px-3 text-sm text-ink transition-colors hover:bg-raised disabled:opacity-40"
          >
            {picking ? zh.browsing : zh.browseFolder}
          </button>
          <button
            type="submit"
            disabled={!path.trim() || busy || (mode === "cif" && !cif)}
            className="flex h-9 items-center gap-1.5 rounded-lg bg-ink px-4 text-sm font-medium text-bg transition-opacity hover:opacity-85 disabled:pointer-events-none disabled:opacity-40"
          >
            {busy && <Spinner className="h-3 w-3" />}
            {busy ? zh.opening : mode === "cif" ? zh.cifImport : zh.open}
          </button>
        </form>
        {error && <AlertBanner className="mt-2.5">{error}</AlertBanner>}
        {mode === "folder" && wb.recent.length > 0 && (
          <div className="mt-4 border-t border-line pt-3">
            <div className="text-2xs font-medium text-ink-3">
              {zh.recentProjects}
            </div>
            <div className="mt-1.5 flex max-h-52 flex-col gap-0.5 overflow-y-auto">
              {wb.recent.slice(0, 8).map((r) => (
                <button
                  key={r.path}
                  type="button"
                  disabled={busy}
                  onClick={() => void open(r.path)}
                  className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-raised"
                >
                  <IconFolder size={14} className="shrink-0 text-ink-3" />
                  <span className="min-w-0 flex-1 text-left"><span className="block truncate text-sm text-ink">
                    {projectLabel(r.path, r.display_name)}
                  </span>
                  <span className="mt-0.5 block truncate font-mono text-2xs text-ink-3" title={r.path}>
                    {r.path}
                  </span></span>
                </button>
              ))}
            </div>
          </div>
        )}
        </div>
      </div>
    </div>, document.body
  );
}
