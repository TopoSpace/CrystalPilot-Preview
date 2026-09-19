import { useEffect, useRef, useState } from "react";
import { createViewer, type GLViewer } from "3dmol";
import { fetchCif } from "../lib/api";
import { useTheme } from "../lib/theme";
import { cx } from "../lib/format";
import { Button, Spinner } from "./ui";

const SPIN_SPEED = 0.6;
/** Extra zoom applied after zoomTo() so the cell fills ~80% of the canvas. */
const FIT_ZOOM = 1.2;

/** 3Dmol's CIF parser only reads the legacy `_symmetry_equiv_pos_as_xyz`
 * tag; CrystalPilot CIFs use the modern `_space_group_symop_operation_xyz`
 * (identical loop format). Rename it so symmetry expansion ("Pack cell")
 * works. */
function normalizeCifSymmetry(cif: string): string {
  return cif.includes("_symmetry_equiv_pos_as_xyz")
    ? cif
    : cif.replace(/_space_group_symop_operation_xyz/g, "_symmetry_equiv_pos_as_xyz");
}

export default function StructureViewer({ runId }: { runId: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<GLViewer | null>(null);
  const spinRef = useRef(false);
  const [cif, setCif] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [spin, setSpin] = useState(false);
  const [packed, setPacked] = useState(false);
  const { theme } = useTheme();

  useEffect(() => {
    let cancelled = false;
    const ctrl = new AbortController();
    setCif(null);
    setError(null);
    fetchCif(runId, ctrl.signal)
      .then((text) => {
        if (!cancelled) setCif(normalizeCifSymmetry(text));
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [runId]);

  // (Re)build the scene whenever the CIF, packing mode, or theme changes.
  useEffect(() => {
    const el = containerRef.current;
    if (!el || cif === null) return;
    const dark = theme === "dark";
    const viewer = createViewer(el, {
      backgroundColor: dark ? "#09090b" : "#ffffff",
    });
    viewerRef.current = viewer;
    const model = viewer.addModel(
      cif,
      "cif",
      packed
        ? { doAssembly: true, duplicateAssemblyAtoms: true, normalizeAssembly: true }
        : { doAssembly: false },
    );
    viewer.setStyle({}, { stick: { radius: 0.12 }, sphere: { scale: 0.25 } });
    viewer.addUnitCell(model, {
      box: { color: dark ? "#52525b" : "#a1a1aa" },
      astyle: { hidden: true },
      bstyle: { hidden: true },
      cstyle: { hidden: true },
    });
    const fit = () => {
      viewer.resize();
      viewer.zoomTo();
      viewer.zoom(FIT_ZOOM);
      viewer.render();
    };
    fit();
    // Re-fit on the next frame: the lazy-mounted container may only get its
    // final size after layout settles, which otherwise leaves a tiny model.
    const raf = requestAnimationFrame(fit);
    if (spinRef.current) viewer.spin("y", SPIN_SPEED);

    const onResize = () => viewer.resize();
    window.addEventListener("resize", onResize);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      viewer.spin(false);
      viewer.clear();
      viewerRef.current = null;
      el.innerHTML = "";
    };
  }, [cif, packed, theme]);

  useEffect(() => {
    spinRef.current = spin;
    const viewer = viewerRef.current;
    if (viewer) {
      if (spin) viewer.spin("y", SPIN_SPEED);
      else viewer.spin(false);
    }
  }, [spin]);

  const resetView = () => {
    const viewer = viewerRef.current;
    if (viewer) {
      viewer.resize();
      viewer.zoomTo();
      viewer.zoom(FIT_ZOOM);
      viewer.render();
    }
  };

  if (error) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-zinc-400 dark:text-zinc-500">
        {error}
      </div>
    );
  }

  return (
    <div className="relative h-full min-h-[420px] overflow-hidden rounded-[10px] border border-zinc-200 dark:border-zinc-800">
      <div ref={containerRef} className="absolute inset-0" />
      {cif === null && (
        <div className="absolute inset-0 flex items-center justify-center gap-2.5 text-sm text-zinc-400">
          <Spinner className="text-indigo-500" />
          Loading structure…
        </div>
      )}
      <div className="absolute top-3 right-3 flex gap-1.5">
        <Button
          variant="outline"
          size="sm"
          onClick={resetView}
          className="bg-white/90 backdrop-blur-none dark:bg-zinc-900/90"
        >
          Reset view
        </Button>
        <Button
          variant="outline"
          size="sm"
          aria-pressed={spin}
          onClick={() => setSpin((s) => !s)}
          className={cx(
            "bg-white/90 dark:bg-zinc-900/90",
            spin &&
              "border-indigo-300 text-indigo-700 dark:border-indigo-700 dark:text-indigo-400",
          )}
        >
          Spin
        </Button>
        <Button
          variant="outline"
          size="sm"
          aria-pressed={packed}
          onClick={() => setPacked((p) => !p)}
          className={cx(
            "bg-white/90 dark:bg-zinc-900/90",
            packed &&
              "border-indigo-300 text-indigo-700 dark:border-indigo-700 dark:text-indigo-400",
          )}
        >
          Pack cell
        </Button>
      </div>
    </div>
  );
}
