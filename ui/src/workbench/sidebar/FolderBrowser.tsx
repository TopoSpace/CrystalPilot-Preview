import { useEffect, useState } from "react";
import { IconChevronRight, IconFolder, IconRefresh } from "../icons";
import { t } from "../../lib/i18n";

interface Folders { path: string; parent: string | null; directories: { name: string; path: string }[]; truncated: boolean }

export function FolderBrowser({ initial, onChoose, onCancel }: {
  initial: string; onChoose: (path: string) => void; onCancel: () => void;
}) {
  const [path, setPath] = useState(initial);
  const [data, setData] = useState<Folders | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    setData(null); setError(null); setQuery("");
    fetch(`/api/folders${path ? `?path=${encodeURIComponent(path)}` : ""}`, { signal: abort.signal })
      .then(async response => {
        const value = await response.json();
        if (!response.ok) throw new Error(value.detail ?? t.shell.folderReadFailed);
        if (!abort.signal.aborted) setData(value);
      })
      .catch(err => { if (!abort.signal.aborted) setError(String(err.message)); });
    return () => abort.abort();
  }, [path]);
  return <div className="mt-4 flex flex-col gap-3" data-testid="folder-browser">
    <div className="flex items-center gap-2">
      <button type="button" className="chrome-button" title={t.shell.folderUp} aria-label={t.shell.folderUp}
        disabled={!data?.parent} onClick={() => setPath(data!.parent!)}><IconChevronRight size={16} className="rotate-180" /></button>
      <span className="min-w-0 flex-1 truncate font-mono text-xs text-ink-2" title={data?.path ?? path}>{data?.path ?? path}</span>
      <button type="button" className="chrome-button" title={t.shell.folderDefault} aria-label={t.shell.folderDefault} onClick={() => setPath("")}><IconRefresh size={15} /></button>
    </div>
    <input aria-label={t.shell.folderFilter} placeholder={t.shell.folderFilterPlaceholder} value={query} onChange={e => setQuery(e.target.value)}
      className="h-9 rounded-lg border border-line bg-bg px-3 text-sm outline-none focus:border-accent" />
    <div className="max-h-64 min-h-32 overflow-y-auto rounded-xl border border-line p-1">
      {error ? <p className="p-3 text-sm text-ink-2">{error}</p> : data === null ? <p className="p-3 text-sm text-ink-3">{t.shell.folderLoading}</p> : <>
        {data.directories.filter(d => d.name.toLowerCase().includes(query.toLowerCase())).map(d => <button key={d.path} type="button"
          className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm text-ink-2 hover:bg-raised"
          onClick={() => setPath(d.path)}><IconFolder size={16} /><span className="min-w-0 flex-1 truncate">{d.name}</span><IconChevronRight size={13} className="text-ink-3" /></button>)}
        {!data.directories.some(d => d.name.toLowerCase().includes(query.toLowerCase())) && <p className="p-3 text-sm text-ink-3">{query ? t.shell.folderNoMatch : t.shell.folderEmpty}</p>}
      </>}
    </div>
    {data?.truncated && <p className="text-xs text-ink-3">{t.shell.folderTruncated}</p>}
    <div className="flex justify-between gap-2">
      <button type="button" className="h-9 rounded-lg px-3 text-sm text-ink-2 hover:bg-raised" onClick={onCancel}>{t.shell.folderBackToPath}</button>
      <button type="button" disabled={!data} className="h-9 rounded-lg bg-ink px-4 text-sm text-bg disabled:opacity-40" onClick={() => data && onChoose(data.path)}>{t.shell.folderChoose}</button>
    </div>
  </div>;
}
