import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { startSolve, uploadFiles } from "../../lib/api";
import { fmtBytes } from "../../lib/format";
import { DropZone } from "../../components/DropZone";
import { RecentRuns } from "../components/RecentRuns";
import { Button, Card, Segmented, Spinner } from "../../components/ui";

type Mode = "auto" | "copilot" | "standard";
type Symmetry = "auto" | "hint";

interface Pairing {
  hkl?: File;
  ins?: File;
  ignored: File[];
}

function pairFiles(files: File[]): Pairing {
  const hkl = files.filter((f) => /\.hkl$/i.test(f.name)).at(-1);
  const ins = files.filter((f) => /\.(ins|res)$/i.test(f.name)).at(-1);
  const ignored = files.filter((f) => f !== hkl && f !== ins);
  return { hkl, ins, ignored };
}

function basename(path: string): string {
  return path.replaceAll("\\", "/").split("/").pop() ?? path;
}

function FileSlot({
  label,
  file,
  missingNote,
}: {
  label: string;
  file: File | undefined;
  missingNote: string;
}) {
  return (
    <div className="flex items-baseline gap-3">
      <span className="w-36 shrink-0 text-[11px] font-medium tracking-[0.08em] text-zinc-400 uppercase dark:text-zinc-500">
        {label}
      </span>
      {file ? (
        <span className="flex min-w-0 items-baseline gap-2">
          <span className="truncate font-mono text-[13px] text-zinc-800 dark:text-zinc-200">
            {file.name}
          </span>
          <span className="shrink-0 text-[11px] text-zinc-400 tabular-nums">
            {fmtBytes(file.size)}
          </span>
        </span>
      ) : (
        <span className="text-[12px] text-zinc-400 dark:text-zinc-500">
          {missingNote}
        </span>
      )}
    </div>
  );
}

export default function Home() {
  const navigate = useNavigate();
  const [files, setFiles] = useState<File[]>([]);
  const [mode, setMode] = useState<Mode>("auto");
  const [symmetry, setSymmetry] = useState<Symmetry>("auto");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pairing = useMemo(() => pairFiles(files), [files]);

  const addFiles = (incoming: File[]) => {
    setError(null);
    setFiles((prev) => [...prev, ...incoming]);
  };

  const reset = () => {
    setFiles([]);
    setError(null);
    setSymmetry("auto");
  };

  const solve = async () => {
    const { hkl, ins } = pairing;
    if (!hkl || busy) return;
    setBusy(true);
    setError(null);
    try {
      const toSend = ins ? [hkl, ins] : [hkl];
      const { paths } = await uploadFiles(toSend);
      const pathFor = (f: File) =>
        paths.find((p) => basename(p) === f.name) ?? null;
      const hklPath = pathFor(hkl);
      if (!hklPath) throw new Error("Upload did not return a path for the .hkl file.");
      const insPath = ins ? pathFor(ins) : null;
      const { run_id } = await startSolve({
        hkl_path: hklPath,
        ins_path: insPath,
        mode,
        symmetry: insPath ? symmetry : "auto",
      });
      navigate(`/legacy/runs/${run_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-screen-lg px-6 pt-16 pb-24">
        <div className="mx-auto max-w-2xl">
          <h1 className="text-center text-[32px] leading-tight font-semibold tracking-tight text-balance">
            From diffraction data to a validated structure.
          </h1>
          <p className="mx-auto mt-3 max-w-xl text-center text-[14px] text-zinc-500 dark:text-zinc-400">
            Drop single-crystal XRD data. CrystalPilot determines symmetry,
            solves and refines the model, validates the chemistry - and shows
            its reasoning at every step.
          </p>

          <div className="mt-10">
            {files.length === 0 ? (
              <DropZone onFiles={addFiles} />
            ) : (
              <Card className="p-5">
                <div className="flex flex-col gap-2.5">
                  <FileSlot
                    label="Reflection data"
                    file={pairing.hkl}
                    missingNote="missing - a .hkl file is required"
                  />
                  <FileSlot
                    label="Structure model"
                    file={pairing.ins}
                    missingNote="none - symmetry will be determined from the data"
                  />
                  {pairing.ignored.length > 0 && (
                    <div className="text-[11px] text-zinc-400 dark:text-zinc-500">
                      Ignored:{" "}
                      {pairing.ignored.map((f) => f.name).join(", ")}:
                      unrecognized file type
                    </div>
                  )}
                </div>

                <div className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-3 border-t border-zinc-100 pt-4 dark:border-zinc-800">
                  <div className="flex items-center gap-2.5">
                    <span className="text-[11px] font-medium tracking-[0.08em] text-zinc-400 uppercase dark:text-zinc-500">
                      Mode
                    </span>
                    <Segmented<Mode>
                      value={mode}
                      onChange={setMode}
                      options={[
                        {
                          value: "auto",
                          label: "Auto",
                          title: "AI agent solves end to end",
                        },
                        {
                          value: "copilot",
                          label: "Copilot",
                          title: "AI agent asks for approval before key actions",
                        },
                        {
                          value: "standard",
                          label: "Standard",
                          title: "Deterministic pipeline, no AI",
                        },
                      ]}
                    />
                  </div>
                  <div className="flex items-center gap-2.5">
                    <span className="text-[11px] font-medium tracking-[0.08em] text-zinc-400 uppercase dark:text-zinc-500">
                      Symmetry
                    </span>
                    <Segmented<Symmetry>
                      value={pairing.ins ? symmetry : "auto"}
                      onChange={setSymmetry}
                      options={[
                        { value: "auto", label: "Auto-determine" },
                        {
                          value: "hint",
                          label: "Trust input",
                          disabled: !pairing.ins,
                          title: pairing.ins
                            ? undefined
                            : "Requires a .ins / .res file",
                        },
                      ]}
                    />
                  </div>
                </div>

                <div className="mt-5 flex items-center gap-3">
                  <Button onClick={() => void solve()} disabled={!pairing.hkl || busy}>
                    {busy && <Spinner className="text-white" />}
                    {busy ? "Starting run…" : "Solve structure"}
                  </Button>
                  <Button variant="ghost" onClick={reset} disabled={busy}>
                    Clear
                  </Button>
                  {!pairing.hkl && (
                    <span className="text-[12px] text-amber-600 dark:text-amber-500">
                      Add a .hkl reflection file to continue.
                    </span>
                  )}
                </div>

                {error && (
                  <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-400">
                    {error}
                  </div>
                )}

                <div className="mt-4 border-t border-zinc-100 pt-3 dark:border-zinc-800">
                  <DropZoneCompact onFiles={addFiles} />
                </div>
              </Card>
            )}
          </div>
        </div>

        <div className="mx-auto mt-16 max-w-2xl">
          <RecentRuns />
        </div>
      </div>
    </div>
  );
}

/** Slim add-more affordance shown under the pairing card. */
function DropZoneCompact({ onFiles }: { onFiles: (files: File[]) => void }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-1.5 text-[12px] text-zinc-400 transition-colors duration-150 hover:text-indigo-600 dark:text-zinc-500 dark:hover:text-indigo-400">
      <svg
        viewBox="0 0 24 24"
        className="h-3.5 w-3.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        aria-hidden="true"
      >
        <path d="M12 5v14M5 12h14" />
      </svg>
      Add or replace files
      <input
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
    </label>
  );
}
