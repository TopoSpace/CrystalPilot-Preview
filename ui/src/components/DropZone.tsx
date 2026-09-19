import { useRef, useState, type DragEvent } from "react";
import { cx } from "../lib/format";

export function DropZone({ onFiles }: { onFiles: (files: File[]) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = (e: DragEvent<HTMLButtonElement>) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) onFiles(files);
  };

  return (
    <>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={cx(
          "flex w-full flex-col items-center gap-3 rounded-xl border border-dashed px-8 py-16",
          "transition-colors duration-200",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500",
          dragOver
            ? "border-indigo-500 bg-indigo-50/50 dark:border-indigo-400 dark:bg-indigo-950/20"
            : "border-zinc-300 bg-zinc-50/50 hover:border-zinc-400 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900/40 dark:hover:border-zinc-600 dark:hover:bg-zinc-900/70",
        )}
      >
        <svg
          viewBox="0 0 24 24"
          className={cx(
            "h-6 w-6 transition-colors duration-200",
            dragOver
              ? "text-indigo-500 dark:text-indigo-400"
              : "text-zinc-400 dark:text-zinc-500",
          )}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M12 15V3M7 8l5-5 5 5" />
          <path d="M4 15v3a3 3 0 0 0 3 3h10a3 3 0 0 0 3-3v-3" />
        </svg>
        <div className="text-base font-medium text-zinc-700 dark:text-zinc-200">
          Drop diffraction data
        </div>
        <div className="text-xs text-zinc-400 dark:text-zinc-500">
          .hkl reflection data, optionally with a .ins / .res model - or click
          to browse
        </div>
      </button>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".hkl,.ins,.res"
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length > 0) onFiles(files);
          e.target.value = "";
        }}
      />
    </>
  );
}
