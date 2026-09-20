/** Humanizer registry for tool cards (P3).
 *
 * Every crystalpilot MCP tool gets a Chinese one-line headline plus metric
 * chips; observe-style tools render as compact gray rows. Summary keys are
 * matched against the REAL result shapes captured from workbench transcripts
 * (see summary.parsed → {ok, summary:{…}, artifacts, error}).
 *
 * The registry is data-first: `humanizeTool(item)` is the only consumer API.
 */
import type { ReactNode } from "react";
import { t } from "./i18n";
import type { ToolCardItem } from "../state/threadReducer";
import { parseCheckcifTail } from "./checkcif";
import { deliveryStatusLabel } from "./delivery";
import { artifactUrl } from "./wbApi";
import { ShellCurve } from "../workbench/chat/ShellCurve";
import type { Shell } from "../workbench/chat/ShellCurve";

export type ToolChipTone = "neutral" | "ok" | "warn" | "danger";

export interface ToolChipSpec {
  text: string;
  tone?: ToolChipTone;
}

export interface ToolHumanized {
  /** Headline (humanized zh); running state gets its own wording. */
  title: ReactNode;
  chips: ToolChipSpec[];
  /** Amber caveat line under the headline. */
  warn: string | null;
  /** Compact gray-row presentation (observe tools). */
  observe: boolean;
  /** Headline tone accent for done state. */
  tone: "ok" | "warn" | "danger" | null;
  /** Always-visible block under the chips (e.g. specialist assessment). */
  body: ReactNode | null;
  /** Humanized block inside 技术详情, above the raw JSON. */
  detail: ReactNode | null;
}

// ---------------------------------------------------------------- helpers

type Rec = Record<string, unknown>;

const isObj = (v: unknown): v is Rec =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** Business payload of a tool result: parsed.summary when present. */
function payload(item: ToolCardItem): Rec {
  const parsed = item.summary?.parsed;
  if (!isObj(parsed)) return {};
  const s = parsed.summary;
  return isObj(s) ? s : parsed;
}

function num(v: unknown): number | undefined {
  return typeof v === "number" && Number.isFinite(v) ? v : undefined;
}

function str(v: unknown): string | undefined {
  return typeof v === "string" && v !== "" ? v : undefined;
}

function arr(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

const f4 = (v: number | undefined): string | undefined =>
  v === undefined ? undefined : v.toFixed(4);
const f2 = (v: number | undefined): string | undefined =>
  v === undefined ? undefined : v.toFixed(2);

function chip(
  text: string | undefined,
  tone?: ToolChipTone,
): ToolChipSpec | null {
  return text === undefined ? null : { text, ...(tone ? { tone } : {}) };
}

function chips(...cs: Array<ToolChipSpec | null>): ToolChipSpec[] {
  return cs.filter((c): c is ToolChipSpec => c !== null);
}

/** Round-3 WP1: the layered status under summary.tool_status. "It ran" and
 * "it found something" are different facts; the row says which, first. */
export function envelopeChips(s: Rec): ToolChipSpec[] {
  const env = isObj(s.tool_status) ? s.tool_status : null;
  if (!env) return [];
  const out: ToolChipSpec[] = [];
  const exec = str(env.execution);
  if (exec === "timeout") out.push({ text: t.envTimeout, tone: "warn" });
  if (exec === "cancelled") out.push({ text: t.envCancelled, tone: "warn" });
  const nc = isObj(env.no_change) ? env.no_change : null;
  if (nc?.value === true) out.push({ text: t.envNoChange, tone: "warn" });
  const sci = isObj(env.scientific_outcome) ? env.scientific_outcome : null;
  const verdict = sci ? str(sci.verdict) : undefined;
  if (verdict === "inconclusive") out.push({ text: t.envInconclusive, tone: "warn" });
  if (verdict === "against") out.push({ text: t.envAgainst, tone: "danger" });
  return out;
}

/** Round-3 WP3: cross-PART restraint terms SHELXL would drop, from the
 * restraints_preflight block set_restraints / run_shelxl attach. */
function preflightConflicts(s: Rec): number {
  const pf = isObj(s.restraints_preflight) ? s.restraints_preflight : null;
  return pf ? arr(pf.shelx_part_conflicts).length : 0;
}

function nodeChip(s: Rec, item: ToolCardItem): ToolChipSpec | null {
  const node = str(s.node) ?? str(s.final_node) ?? item.summary?.node;
  return node === undefined ? null : { text: t.toolCards.nodeChip(node) };
}

/** "R1 0.1036 → 0.0618 ▼" with a tone-colored direction glyph. */
function metricDelta(
  label: string,
  before: number | undefined,
  after: number | undefined,
  digits = 4,
): ReactNode {
  if (after === undefined) return null;
  const cur = after.toFixed(digits);
  if (before === undefined || Math.abs(before - after) < 0.5 / 10 ** digits) {
    return (
      <>
        {label} <span className="tabular-nums">{cur}</span>
      </>
    );
  }
  const improved = after < before; // lower is better for R metrics
  return (
    <>
      {label} <span className="tabular-nums">{before.toFixed(digits)}</span>
      <span className="text-ink-3"> → </span>
      <span className="tabular-nums">{cur}</span>{" "}
      <span className={improved ? "text-ok" : "text-danger"}>
        {improved ? "▼" : "▲"}
      </span>
    </>
  );
}

const refineModeZh: Record<string, string> = t.toolCards.refineModes;

const specialtyZh: Record<string, string> = t.toolCards.specialties;

const confidenceZh: Record<string, string> = t.toolCards.confidence;

/** [a,b,c,α,β,γ] -> "12.34 5.67 8.90 Å". */
function cellChipText(v: unknown): string | undefined {
  if (!Array.isArray(v) || v.length < 3) return undefined;
  const abc = v.slice(0, 3).map((x) => num(x));
  if (abc.some((x) => x === undefined)) return undefined;
  return t.toolCards.cellChip(abc.map((x) => (x as number).toFixed(2)).join(" "));
}

function strList(v: unknown): string[] {
  return arr(v)
    .map((x) => str(x))
    .filter((x): x is string => x !== undefined);
}

const viewZh: Record<string, string> = t.toolCards.views;

const stateZh: Record<string, string> = t.toolCards.states;

export interface ViewImage {
  path: string;
  label: string;
}

/** Normalize the two shapes the render tools emit: view_structure gives
 * `[{view, path}]`, situation_report gives bare paths (state encoded in
 * the filename, e.g. `sit_supercell_c.png`). */
export function parseViewImages(
  images: unknown,
  fallbackState?: string,
): ViewImage[] {
  const out: ViewImage[] = [];
  for (const im of arr(images)) {
    const path = typeof im === "string" ? im : isObj(im) ? str(im.path) : undefined;
    if (path === undefined) continue;
    const view = isObj(im) ? str(im.view) : undefined;
    const state = path.match(/_(asu|cell|supercell)_/)?.[1];
    const parts = [
      state === undefined ? fallbackState : stateZh[state],
      view === undefined ? undefined : (viewZh[view] ?? view),
    ].filter((x): x is string => x !== undefined && x !== "");
    out.push({ path, label: parts.join(" · ") });
  }
  return out;
}

/** Rendered structure views. The model is shown these pictures through the
 * MCP image channel; this is the user's copy of the same look. */
function viewStrip(images: unknown, fallbackState?: string): ReactNode {
  const items = parseViewImages(images, fallbackState);
  if (items.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {items.map((im) => (
        <a
          key={im.path}
          href={artifactUrl(im.path)}
          target="_blank"
          rel="noreferrer"
          className="group/img block"
          title={im.label === "" ? t.toolCards.viewOpenFull : `${im.label} · ${t.toolCards.viewOpenFull}`}
        >
          <img
            src={artifactUrl(im.path)}
            alt={im.label === "" ? "structure view" : im.label}
            loading="lazy"
            className="h-36 w-auto rounded-lg border border-line bg-white
                       transition-colors group-hover/img:border-accent"
          />
          {im.label !== "" && (
            <div className="mt-0.5 text-center text-2xs text-ink-3">
              {im.label}
            </div>
          )}
        </a>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- registry

interface ToolDef {
  observe?: boolean;
  running?: (args: Rec) => string;
  done?: (s: Rec, args: Rec, item: ToolCardItem) => Partial<ToolHumanized>;
}

const registry: Record<string, ToolDef> = {
  refine: {
    running: (args) => {
      const m = str(args.mode);
      return t.toolCards.refineRunning(m ? (refineModeZh[m] ?? m) : undefined);
    },
    done: (s, _args, item) => {
      const r1 = num(s.r1_strong) ?? item.summary?.r1;
      const prev = item.metricsBefore?.r1;
      const mask = s.solvent_mask_used === true;
      const goof = num(s.goof_restrained) ?? num(s.goof) ?? item.summary?.goof;
      const peak = num(s.diff_map_max) ?? item.summary?.diffMapMax;
      return {
        title: (
          <>
            {t.toolCards.refineDone}{metricDelta("R1", prev, r1)}
            {mask ? t.toolCards.refineWithMask : ""}
          </>
        ),
        chips: chips(
          chip(f4(num(s.wr2) ?? item.summary?.wr2)?.replace(/^/, "wR2 ")),
          chip(f2(goof)?.replace(/^/, "GooF ")),
          chip(peak !== undefined ? t.toolCards.residualPeak(peak.toFixed(2)) : undefined),
          nodeChip(s, item),
        ),
      };
    },
  },

  run_shelxl: {
    running: (a) => a.mode === "adopt" || a.mode === "adopt_wght" ? t.toolCards.shelxlRefineRunning : t.toolCards.shelxlCrossRunning,
    done: (s, a, item) => {
      const sh = isObj(s.shelxl) ? s.shelxl : {};
      const r1 = num(sh.r1_strong) ?? item.summary?.r1;
      const d = num(s.delta_r1);
      const agrees = typeof s.agrees_with_engine === "boolean" ? s.agrees_with_engine : null;
      const adopted = a.mode === "adopt" || a.mode === "adopt_wght";
      const dTxt =
        d !== undefined ? `${d > 0 ? "+" : ""}${d.toFixed(4)}` : "—";
      // 无序占有率判词：只有 SHELXL 精修出的 FVAR 与其 s.u. 能说话
      const dv = isObj(s.disorder_verdict) ? s.disorder_verdict : {};
      const counts = isObj(dv.verdicts) ? dv.verdicts : {};
      const nRevoke = num(counts.revoke) ?? 0;
      const nInc = num(counts.inconclusive) ?? 0;
      const nSup = num(counts.supported) ?? 0;
      const disChip =
        nRevoke > 0 ? t.toolCards.disorderRevoke(nRevoke)
          : nInc > 0 ? t.toolCards.disorderUndecided(nInc)
            : nSup > 0 ? t.toolCards.disorderMeasurable(nSup) : undefined;
      const occupancyChips = arr(s.site_occupancies).filter(isObj).slice(0, 3).map((row) => {
        const value = num(row.occupancy), su = num(row.su);
        return chip(value === undefined ? undefined
          : t.toolCards.siteOccupancy(str(row.atom) ?? t.toolCards.atomFallback, value.toFixed(4), su === undefined ? undefined : su.toPrecision(2)));
      });
      return {
        title: t.toolCards.shelxlTitle(
          adopted ? t.toolCards.shelxlRefine : t.toolCards.shelxlCross,
          r1 === undefined ? t.toolCards.metricsMissing : `R1 ${f4(r1)}`,
          !adopted && agrees !== null && d !== undefined ? t.toolCards.shelxlDelta(dTxt, agrees) : "",
        ),
        tone: nRevoke > 0 || agrees === false ? "warn" : agrees === true ? "ok" : null,
        warn: r1 === undefined ? t.toolCards.shelxlNoSummary : null,
        chips: chips(
          chip(f4(num(sh.wr2))?.replace(/^/, "wR2 ")),
          chip(f2(num(sh.goof))?.replace(/^/, "GooF ")),
          chip(disChip),
          ...occupancyChips,
        ),
      };
    },
  },

  fit_fragment: {
    running: () => t.toolCards.fitFragmentRunning,
    done: (s, _a, item) => {
      const added = arr(s.added);
      const refused = arr(s.refused);
      return {
        title: t.toolCards.fitFragmentTitle(added.length),
        warn:
          refused.length > 0
            ? t.toolCards.fitFragmentRefused(refused.length)
            : null,
        chips: chips(nodeChip(s, item)),
      };
    },
  },

  add_atoms_from_difference_map: {
    running: () => t.toolCards.addFromMapRunning,
    done: (s, _a, item) => {
      const added = arr(s.added);
      const labels = added
        .map((x) => (isObj(x) ? str(x.label) : undefined))
        .filter((x): x is string => x !== undefined);
      return {
        title: t.toolCards.addFromMapTitle(added.length),
        chips: chips(
          chip(labels.length > 0 ? labels.join(" · ") : undefined),
          nodeChip(s, item),
        ),
      };
    },
  },

  edit_atoms: {
    running: () => t.toolCards.editAtomsRunning,
    done: (s, _a, item) => {
      const applied = arr(s.applied);
      const parts = applied
        .map((x) =>
          isObj(x) ? `${str(x.action) ?? "?"}×${num(x.n) ?? 1}` : undefined,
        )
        .filter((x): x is string => x !== undefined);
      return {
        title: t.toolCards.editAtomsTitle(applied.length),
        chips: chips(
          chip(parts.length > 0 ? parts.join(" · ") : undefined),
          nodeChip(s, item),
        ),
      };
    },
  },

  add_hydrogens: {
    running: () => t.toolCards.addHRunning,
    done: (s, args, item) => {
      const n = num(s.n_h_added) ?? 0;
      const elements = arr(args.elements)
        .map((e) => str(e))
        .filter((e): e is string => e !== undefined);
      return {
        title: t.toolCards.addHTitle(n, elements),
        chips: chips(
          chip(
            num(s.n_carriers) !== undefined
              ? t.toolCards.carriers(num(s.n_carriers) as number)
              : undefined,
          ),
          nodeChip(s, item),
        ),
      };
    },
  },

  optimize_weights: {
    running: () => t.toolCards.optimizeWeightsRunning,
    done: (s, _a, item) => {
      const goofAfter = num(s.goof_after) ?? num(s.goof);
      const w = isObj(s.weights) ? s.weights : {};
      return {
        title: (
          <>
            {t.toolCards.weightsOptimized}
            {metricDelta("GooF", num(s.goof_before), goofAfter, 2) ?? "GooF - "}
          </>
        ),
        chips: chips(
          chip(f4(num(s.r1_after))?.replace(/^/, "R1 ")),
          chip(f4(num(s.wr2_after))?.replace(/^/, "wR2 ")),
          chip(
            num(w.a) !== undefined
              ? `a=${num(w.a)} b=${num(w.b) ?? 0}`
              : undefined,
          ),
          nodeChip(s, item),
        ),
      };
    },
  },

  solvent_mask: {
    running: () => t.toolCards.solventMaskRunning,
    done: (s, _a, item) => {
      const nMasked = num(s.n_voids_masked) ?? 0;
      const e = num(s.total_solvent_electrons_per_cell);
      const pct = num(s.solvent_volume_pct_of_cell);
      return {
        title: t.toolCards.solventMaskTitle(nMasked, e !== undefined ? Math.round(e) : undefined),
        chips: chips(
          chip(pct !== undefined ? t.toolCards.solventVolume(pct.toFixed(1)) : undefined),
          nodeChip(s, item),
        ),
      };
    },
  },

  search_fragment_pose: {
    observe: true,
    running: () => t.toolCards.searchPoseRunning,
    done: (s) => {
      const cands = arr(s.candidates).filter(isObj);
      const top = cands[0];
      const direct = top ? (num(top.n_direct) ?? 0) : 0;
      const weak = top ? (num(top.n_weak) ?? 0) : 0;
      const geo = top ? (num(top.n_geometry_only) ?? 0) : 0;
      const frag = isObj(s.fragment) ? s.fragment : null;
      const formula = frag ? (str(frag.formula) ?? str(frag.smiles)) : undefined;
      const folded = top && isObj(top.symmetry_folded) ? num(top.symmetry_folded.n_unique) : undefined;
      return {
        title: t.toolCards.searchPoseTitle(cands.length, formula),
        chips: chips(
          chip(top ? t.toolCards.searchPoseTop(str(top.id) ?? "c01", direct, weak, geo) : undefined),
          chip(folded !== undefined ? t.toolCards.searchPoseFolded(folded) : undefined),
        ),
        tone: cands.length === 0 ? "warn" : geo > 0 ? "warn" : "ok",
        warn: str(s.timeout) ?? (geo > 0 ? t.toolCards.searchPoseGeoOnly(geo) : null),
      };
    },
  },
  accept_fragment_pose: {
    running: () => t.toolCards.acceptPoseRunning,
    done: (s, _a, item) => {
      const added = arr(s.added);
      const fv = num(s.fvar_index);
      const occ = num(s.occupancy);
      const part = num(s.part);
      const cards = arr(s.cards_added);
      return {
        title: t.toolCards.acceptPoseTitle(str(s.candidate_id) ?? "", added.length),
        chips: chips(
          chip(fv !== undefined ? `FVAR${fv} = ${occ === undefined ? "?" : occ.toFixed(2)}` : occ === undefined ? undefined : t.toolCards.occupancyChip(occ.toFixed(2))),
          chip(part === undefined ? undefined : `PART ${part}`),
          chip(cards.length > 0 ? "EADP" : undefined),
          nodeChip(s, item),
        ),
        warn: str(s.card_warning) ?? null,
      };
    },
  },
  set_restraints: {
    running: () => t.toolCards.setRestraintsRunning,
    done: (s, args, item) => {
      const action = str(args.action) ?? "";
      const n = arr(s.restraints).length;
      const conflicts = preflightConflicts(s);
      return {
        title: t.toolCards.setRestraintsTitle(action, n),
        chips: chips(nodeChip(s, item)),
        tone: conflicts > 0 ? "warn" : null,
        warn: conflicts > 0 ? t.toolCards.restraintsCrossPart(conflicts) : null,
      };
    },
  },
  preflight_restraints: {
    observe: true,
    running: () => t.toolCards.preflightRunning,
    done: (s) => {
      const pf = isObj(s.restraints_preflight) ? s.restraints_preflight : {};
      const n = num(pf.requested) ?? 0;
      const conflicts = arr(pf.shelx_part_conflicts).length;
      const bad = arr(pf.not_representable).length;
      const warns = arr(pf.warnings).length;
      const parts: string[] = [t.toolCards.preflightCount(n)];
      if (conflicts > 0) parts.push(t.toolCards.preflightCrossPart(conflicts));
      if (bad > 0) parts.push(t.toolCards.preflightNotRepresentable(bad));
      if (warns > 0) parts.push(t.toolCards.preflightWarnings(warns));
      return {
        title: t.toolCards.preflightTitle(parts.join(" · ")),
        tone: conflicts > 0 || bad > 0 ? "warn" : "ok",
        warn: conflicts > 0 ? t.toolCards.preflightCrossPartWarn(conflicts) : null,
      };
    },
  },

  branch: {
    running: () => t.toolCards.branchRunning,
    done: (s) => ({
      title: t.toolCards.branchTitle(str(s.branch) ?? "—", str(s.at) ?? "—"),
    }),
  },

  checkout: {
    running: () => t.toolCards.checkoutRunning,
    done: (s, _a, item) => ({
      title: t.toolCards.checkoutTitle(str(s.node) ?? item.summary?.node ?? "—", str(s.branch)),
    }),
  },

  run_checkcif: {
    running: () => t.ccRunning,
    done: (s, _a, item) => checkcifHumanized("checkCIF", s, item),
  },

  submit_iucr_checkcif: {
    running: () => t.toolCards.iucrRunning,
    done: (s, _a, item) => checkcifHumanized(t.toolCards.iucrPrefix, s, item),
  },

  // -------------------------------------------------- specialist subagent
  consult_specialist: {
    running: (args) => {
      const sp = str(args.specialty);
      return t.toolCards.consultRunning(sp !== undefined ? (specialtyZh[sp] ?? sp) : "");
    },
    done: (s, args) => {
      const sp = str(s.specialty) ?? str(args.specialty) ?? "";
      const v = isObj(s.verdict) ? s.verdict : {};
      const conf = str(v.confidence) ?? "low";
      const confTone: ToolChipTone =
        conf === "high" ? "ok" : conf === "medium" ? "warn" : "neutral";
      const assessment = str(v.assessment) ?? "";
      const cost = isObj(s.specialist_cost) ? s.specialist_cost : {};
      const tokens =
        (num(cost.input_tokens) ?? 0) + (num(cost.output_tokens) ?? 0);
      const costParts = [
        num(cost.n_tool_calls) !== undefined
          ? t.toolCards.toolCalls(num(cost.n_tool_calls) as number)
          : null,
        tokens > 0 ? `${tokens.toLocaleString()} tokens` : null,
      ].filter((x): x is string => x !== null);
      const evidence = strList(v.evidence);
      const risks = strList(v.risks);
      return {
        title: t.toolCards.consultTitle(specialtyZh[sp] ?? sp),
        chips: chips(
          chip(t.toolCards.confidenceChip(confidenceZh[conf] ?? conf), confTone),
          chip(costParts.length > 0 ? costParts.join(" · ") : undefined),
        ),
        body:
          assessment !== "" ? (
            <span>
              {assessment.length > 200
                ? `${assessment.slice(0, 200)}…`
                : assessment}
            </span>
          ) : null,
        detail: (
          <div className="flex flex-col gap-1.5">
            {str(v.recommendation) !== undefined && (
              <div>
                <span className="font-medium text-ink-2">{t.toolCards.recommendationLabel}</span>
                {str(v.recommendation)}
              </div>
            )}
            {evidence.length > 0 && (
              <div>
                <span className="font-medium text-ink-2">{t.toolCards.evidenceLabel}</span>
                <ul className="mt-0.5 list-disc pl-4">
                  {evidence.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              </div>
            )}
            {risks.length > 0 && (
              <div>
                <span className="font-medium text-ink-2">{t.toolCards.risksLabel}</span>
                <ul className="mt-0.5 list-disc pl-4">
                  {risks.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ),
      };
    },
  },

  // ----------------------------------------------- analysis / model tools
  check_symmetry: {
    running: () => t.toolCards.checkSymmetryRunning,
    done: (s) => {
      const extra = arr(s.extra_ops_matched).length;
      const suggested = str(s.suggested_space_group);
      return {
        title: str(s.verdict) ?? t.toolCards.checkSymmetryDone,
        tone: extra > 0 ? "warn" : null,
        chips: chips(
          chip(
            str(s.current_space_group) !== undefined
              ? t.toolCards.currentSg(str(s.current_space_group) as string)
              : undefined,
          ),
          chip(
            extra > 0 && suggested !== undefined
              ? t.toolCards.suggestedSg(suggested)
              : undefined,
            "warn",
          ),
          chip(
            s.metric_pseudo_symmetry === true ? t.toolCards.metricPseudoSymmetry : undefined,
          ),
        ),
        warn:
          extra > 0
            ? t.toolCards.extraSymmetryWarn
            : null,
      };
    },
  },

  rename_atoms: {
    running: () => t.toolCards.renameRunning,
    done: (s) => {
      if (s.no_state_change === true) {
        return { title: t.toolCards.renameNoChange };
      }
      const renames = isObj(s.renames) ? s.renames : {};
      const pairs = Object.entries(renames).filter(
        (kv): kv is [string, string] => typeof kv[1] === "string",
      );
      return {
        title: t.toolCards.renameTitle(num(s.n_renamed) ?? pairs.length),
        detail:
          pairs.length > 0 ? (
            <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 font-mono text-2xs sm:grid-cols-3">
              {pairs.map(([a, b]) => (
                <span key={a} className="whitespace-nowrap">
                  {a} <span className="text-ink-3">→</span> {b}
                </span>
              ))}
            </div>
          ) : null,
      };
    },
  },

  import_cif_model: {
    running: () => t.toolCards.importCifRunning,
    done: (s) => {
      const notes = strList(s.conversion_notes);
      return {
        title: t.toolCards.importCifTitle(num(s.imported_atoms) ?? "?", str(s.space_group) ?? "—"),
        chips: chips(
          chip(
            num(s.n_aniso) !== undefined && (num(s.n_aniso) as number) > 0
              ? t.toolCards.anisoCount(num(s.n_aniso) as number)
              : undefined,
          ),
          chip(
            num(s.wavelength_A) !== undefined
              ? `λ ${num(s.wavelength_A)} Å`
              : undefined,
          ),
          chip(str(s.start_node) !== undefined ? t.toolCards.nodeChip(str(s.start_node) as string) : undefined),
        ),
        detail:
          notes.length > 0 ? (
            <ul className="list-disc pl-4">
              {notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          ) : null,
        warn: notes.length > 0 ? t.toolCards.conversionNotes(notes.length) : null,
      };
    },
  },

  // ------------------------------------------ raw frames pipeline (DIALS)
  import_frames: {
    running: () => t.toolCards.importFramesRunning,
    done: (s) => ({
      title: t.toolCards.importFramesTitle(num(s.n_images) ?? "?", num(s.n_sweeps)),
      chips: chips(
        chip(strList(s.formats).join("/") || undefined),
        chip(str(s.vendor_software)),
        chip(
          num(s.n_background) !== undefined && (num(s.n_background) as number) > 0
            ? t.toolCards.backgroundFrames(num(s.n_background) as number)
            : undefined,
        ),
      ),
    }),
  },

  find_spots: {
    running: () => t.toolCards.findSpotsRunning,
    done: (s) => ({
      title: t.toolCards.findSpotsTitle(num(s.n_strong_spots)?.toLocaleString() ?? "?"),
      chips: chips(
        chip(
          num(s.d_min) !== undefined ? `d_min ${num(s.d_min)} Å` : undefined,
        ),
      ),
    }),
  },

  index_frames: {
    running: () => t.toolCards.indexRunning,
    done: (s) => ({
      title: t.toolCards.indexTitle(num(s.n_indexed)?.toLocaleString() ?? "?", num(s.pct_indexed)),
      chips: chips(chip(cellChipText(s.cell))),
      warn:
        num(s.pct_indexed) !== undefined && (num(s.pct_indexed) as number) < 50
          ? t.toolCards.indexLowWarn
          : null,
    }),
  },

  integrate_frames: {
    running: () => t.toolCards.integrateRunning,
    done: (s) => ({
      title: t.toolCards.integrateTitle(num(s.n_integrated)?.toLocaleString() ?? "?"),
      chips: chips(chip(cellChipText(s.cell_refined))),
    }),
  },

  scale_and_export: {
    running: () => t.toolCards.scaleRunning,
    done: (s) => {
      const sc = isObj(s.scaling) ? s.scaling : {};
      const parts = [
        num(sc.cc_half) !== undefined ? `CC½ ${num(sc.cc_half)}` : null,
        num(sc.r_merge) !== undefined ? `Rmerge ${num(sc.r_merge)}` : null,
        num(sc.completeness) !== undefined
          ? t.toolCards.completenessPct(num(sc.completeness) as number)
          : null,
      ].filter((x): x is string => x !== null);
      return {
        title: t.toolCards.scaleTitle(parts.length > 0 ? parts.join(" · ") : null),
        chips: chips(
          chip(
            num(sc.d_min) !== undefined ? t.toolCards.resolutionChip(num(sc.d_min) as number) : undefined,
          ),
          chip(
            num(sc.i_over_sigma) !== undefined
              ? `I/σ ${num(sc.i_over_sigma)}`
              : undefined,
          ),
          chip(
            num(sc.n_unique) !== undefined
              ? t.toolCards.uniqueReflections((num(sc.n_unique) as number).toLocaleString())
              : undefined,
          ),
          chip(
            str(s.space_group_suggestion) !== undefined
              ? t.toolCards.suggestedSpaceGroup(str(s.space_group_suggestion) as string)
              : undefined,
          ),
        ),
        warn: str(s.symmetry_warning) ?? null,
      };
    },
  },

  create_start_model: {
    running: () => t.toolCards.startModelRunning,
    done: (s) => ({
      title: t.toolCards.startModelTitle(num(s.n_atoms) ?? "?", f4(num(s.solved_r1)) ?? "—"),
      chips: chips(
        chip(str(s.space_group)),
        chip(
          num(s.z_estimated) !== undefined ? `Z=${num(s.z_estimated)}` : undefined,
        ),
        chip(str(s.node) !== undefined ? t.toolCards.nodeChip(str(s.node) as string) : undefined),
      ),
    }),
  },

  finalize_delivery: {
    running: () => t.toolCards.finalizeRunning,
    done: (s) => {
      const waived = arr(s.waived);
      return {
        title: s.status === "diagnostic" ? t.toolCards.deliveryDiagnosticSealed : s.status === "final" ? t.toolCards.deliveryFinal : t.toolCards.deliveryTitle(deliveryStatusLabel(str(s.status) ?? null) || t.toolCards.statusUnreported),
        chips: chips(
          chip(str(s.delivery) ? str(s.delivery)!.split(/[\\/]/).slice(-1)[0] : undefined),
          chip(waived.length > 0 ? t.toolCards.waivedCount(waived.length) : undefined),
        ),
        warn: waived.length > 0 ? t.toolCards.waivedWarn : null,
      };
    },
  },
  ghost_test: {
    running: (args) => t.toolCards.ghostRunning(strList(args.atoms).length || "?"),
    done: (s) => {
      const rows = arr(s.rows).filter(isObj);
      const n = (v: string) => rows.filter((r) => str(r.verdict) === v).length;
      const notTested = arr(s.not_tested);
      return {
        title: t.toolCards.ghostTitle(num(s.n_tested) ?? rows.length, n("real"), n("ghost"), n("inconclusive")),
        chips: chips(
          chip(notTested.length > 0 ? t.toolCards.notTestedBudget(notTested.length) : undefined),
          chip(isObj(s.baseline) && str((s.baseline as Record<string, unknown>).node)
            ? t.toolCards.baselineChip(str((s.baseline as Record<string, unknown>).node) as string) : undefined),
        ),
        warn: notTested.length > 0 ? t.toolCards.budgetExceededWarn : null,
      };
    },
  },
  element_scan: {
    running: (args) => t.toolCards.elementScanRunning(str(args.site) ?? t.toolCards.siteFallback),
    done: (s) => {
      const rows = arr(s.rows).filter(isObj);
      const readiness = isObj(s.readiness) ? s.readiness : {};
      const blockers = strList(readiness.blockers);
      const tied = strList(s.tied_at_top);
      const top = rows[0] ?? {};
      return {
        title: t.toolCards.elementScanTitle(num(s.n_tested) ?? rows.length, str(top.element) ?? "?", tied),
        chips: chips(
          chip(blockers.length > 0 ? t.toolCards.notReadyCount(blockers.length) : t.toolCards.ready),
          chip(arr(s.not_tested).length > 0 ? t.toolCards.notTested(arr(s.not_tested).length) : undefined),
        ),
        warn: blockers.length > 0
          ? t.toolCards.elementScanBlocked(blockers.slice(0, 2).join(t.toolCards.listSeparator))
          : t.toolCards.elementScanHint,
      };
    },
  },
  probe_site: {
    running: (args) => {
      const els = [str(args.element), ...strList(args.elements)].filter(
        (e): e is string => e !== undefined,
      );
      return t.toolCards.probeRunning(els.length > 0 ? els.join("/") : t.toolCards.candidateAtomFallback);
    },
    done: (s) => {
      const rows = arr(s.rows).filter(isObj);
      const n = (v: string) => rows.filter((r) => str(r.verdict) === v).length;
      const mask = isObj(s.mask_handling) ? s.mask_handling : {};
      const maskOff = mask.session_has_mask === true && mask.mask_used === false;
      const best =
        rows.find((r) => str(r.verdict) === "supported") ?? rows[0] ?? {};
      const occ = num(best.occupancy_refined);
      const e = num(best.electrons_refined);
      const notTested = arr(s.not_tested);
      return {
        title: t.toolCards.probeTitle(rows.length, n("supported"), n("not_supported"), n("borderline")),
        tone: n("supported") > 0 ? "ok" : n("borderline") > 0 ? "warn" : null,
        chips: chips(
          chip(
            str(best.element) !== undefined && occ !== undefined
              ? t.toolCards.probeOccupancy(str(best.element) as string, occ.toFixed(3), e !== undefined ? e.toFixed(1) : undefined)
              : undefined,
          ),
          chip(maskOff ? t.toolCards.maskOffInVoid : undefined, "warn"),
          chip(notTested.length > 0 ? t.toolCards.notTestedBudget(notTested.length) : undefined),
          chip(isObj(s.baseline) && str((s.baseline as Rec).node)
            ? t.toolCards.baselineChip(str((s.baseline as Rec).node) as string) : undefined),
        ),
        warn: notTested.length > 0
          ? t.toolCards.budgetExceededWarn
          : t.toolCards.probeHint,
      };
    },
  },
  write_outputs: {
    running: () => t.toolCards.writeOutputsRunning,
    done: (s, _a, item) => {
      const files = arr(s.files);
      const pub = s.publication_cif === true;
      const metrics = isObj(s.metrics) ? s.metrics : {};
      return {
        title: t.toolCards.writeOutputsTitle(files.length, pub),
        chips: chips(
          chip(f4(num(metrics.r1_strong))?.replace(/^/, "R1 ")),
          nodeChip(s, item),
        ),
      };
    },
  },

  fourier_complete: {
    running: () => t.toolCards.fourierRunning,
    done: (s, _a, item) => {
      const added = arr(s.added);
      return {
        title: t.toolCards.fourierTitle(added.length),
        chips: chips(nodeChip(s, item)),
      };
    },
  },

  // ------------------------------------------------------- observe tools
  get_project_brief: {
    observe: true,
    running: () => t.toolCards.briefRunning,
    done: () => ({ title: t.toolCards.briefTitle }),
  },
  inspect_model: {
    observe: true,
    running: () => t.toolCards.inspectModelRunning,
    done: (s) => {
      const n = num(s.n_atoms);
      const suspects = Array.isArray(s.suspects) ? s.suspects.length : undefined;
      const isolated = Array.isArray(s.isolated_atoms) ? s.isolated_atoms.length : undefined;
      return {
        title: t.toolCards.inspectModelTitle(n),
        chips: chips(chip(str(s.space_group)),
          chip(suspects !== undefined ? t.toolCards.suspectAtoms(suspects) : undefined),
          chip(isolated !== undefined ? t.toolCards.isolatedAtoms(isolated) : undefined)),
        tone: (suspects ?? 0) > 0 || (isolated ?? 0) > 0 ? "warn" : null,
      };
    },
  },
  inspect_map: {
    observe: true,
    running: () => t.toolCards.inspectMapRunning,
    done: (s) => ({ title: t.toolCards.inspectMapTitle, chips: chips(
      chip(f2(num(s.diff_map_max)) !== undefined ? `Δρ max ${f2(num(s.diff_map_max))} e/Å³` : undefined),
      chip(f2(num(s.diff_map_min)) !== undefined ? `min ${f2(num(s.diff_map_min))} e/Å³` : undefined),
    ) }),
  },
  check_ligand: {
    observe: true,
    running: () => t.toolCards.checkLigandRunning,
    done: () => ({ title: t.toolCards.checkLigandTitle }),
  },
  get_geometry: {
    observe: true,
    running: () => t.toolCards.geometryRunning,
    done: (s) => {
      const nb = num(s.n_bonds) ?? 0;
      const na = num(s.n_angles) ?? 0;
      const esd = str(s.esd_source) !== undefined;
      return {
        title: t.toolCards.geometryTitle(nb, na, esd, s.truncated === true),
      };
    },
  },
  analyze_packing: {
    observe: true,
    running: () => t.toolCards.packingRunning,
    done: (s) => {
      const ix = isObj(s.interactions) ? (s.interactions as Rec) : null;
      const counts = ix && isObj(ix.counts) ? (ix.counts as Rec) : null;
      const nIx = counts ? (num(counts.shown_total) ?? 0) : 0;
      const pores = isObj(s.pores) ? (s.pores as Rec) : null;
      const nV = pores ? (num(pores.n_voids) ?? 0) : 0;
      const cards = isObj(s.suggested_cards)
        ? (num((s.suggested_cards as Rec).n_cards) ?? 0)
        : 0;
      const pk = isObj(s.packing) ? (s.packing as Rec) : null;
      const pi = pk ? num(pk.packing_index_pct) : undefined;
      return {
        title: t.toolCards.packingTitle(nIx, nV, pi !== undefined ? pi.toFixed(1) : undefined, cards),
      };
    },
  },
  validate_structure: {
    observe: true,
    running: () => t.toolCards.validateRunning,
    done: (s) => {
      const n = num(s.n_alerts) ?? 0;
      return {
        title: t.toolCards.validateTitle(n),
        tone: n > 0 ? "warn" : null,
      };
    },
  },
  audit_reflection_data: {
    observe: true,
    running: () => t.toolCards.auditReflRunning,
    done: (s) => {
      const alarm = isObj(s.twin_alarm);
      const hints = Array.isArray(s.hints) ? s.hints : [];
      const clean =
        hints.length <= 1 && !alarm && /no twin/.test(str(hints[0]) ?? "");
      const signs = alarm
        ? (s.twin_alarm as Rec).signs
        : undefined;
      const nSigns = Array.isArray(signs) ? signs.length : 0;
      return {
        title: alarm
          ? t.toolCards.auditReflTwin(nSigns)
          : clean
            ? t.toolCards.auditReflClean
            : t.toolCards.auditReflHints(hints.length),
        tone: alarm ? "warn" : clean ? "ok" : hints.length > 0 ? "warn" : null,
        warn: alarm ? (str(hints[hints.length - 1]) ?? null) : null,
      };
    },
  },
  integrate_difference_density: {
    observe: true,
    running: () => t.toolCards.integrateDensityRunning,
    done: (s) => {
      const pos = num(s.electrons_positive);
      const neg = num(s.electrons_negative);
      const claimed = num(s.modeled_electrons_omitted);
      const expected = num(s.expected_electrons);
      const bits: string[] = [];
      if (pos !== undefined && neg !== undefined) {
        bits.push(`+${pos.toFixed(1)}e / ${neg.toFixed(1)}e`);
      }
      if (claimed !== undefined) bits.push(t.toolCards.modelClaims(claimed.toFixed(1)));
      if (expected !== undefined) bits.push(t.toolCards.expectedElectrons(expected.toFixed(1)));
      return {
        title: t.toolCards.integrateDensityTitle(bits.length > 0 ? bits.join(" · ") : null),
      };
    },
  },
  audit_element_assignment: {
    observe: true,
    running: () => t.toolCards.auditElementRunning,
    done: (s) => {
      const idle = Array.isArray(s.idle_n_o) ? s.idle_n_o.length : 0;
      const hi = Array.isArray(s.ueq_high_vs_neighbours)
        ? s.ueq_high_vs_neighbours.length
        : 0;
      const lo = Array.isArray(s.ueq_low_vs_neighbours)
        ? s.ueq_low_vs_neighbours.length
        : 0;
      const n = idle + hi + lo;
      return {
        title:
          n > 0
            ? t.toolCards.auditElementTitle(n, idle)
            : t.toolCards.auditElementClean,
        tone: n > 0 ? "warn" : "ok",
      };
    },
  },
  // ------------------------------------------------ data ingest / reduction
  ingest_vendor_data: {
    running: () => t.toolCards.ingestRunning,
    done: (s, _args, item) => {
      const merge = isObj(s.merge) ? s.merge : {};
      const chosen = isObj(s.chosen) ? s.chosen : {};
      const mismatch = str(s.hklf_mismatch) ?? str(s.twin_data_note);
      const hklf5 = isObj(s.hklf5) ? s.hklf5 : null;
      return {
        title: t.toolCards.ingestTitle(str(chosen.hkl) ?? "?"),
        chips: chips(
          chip(hklf5 !== null ? t.toolCards.hklf5Domains(num(hklf5.n_domains) ?? "?") : undefined,
               hklf5 !== null ? "warn" : undefined),
          chip(str(merge.space_group)),
          chip(num(merge.r_int) === undefined ? undefined : `Rint ${f4(num(merge.r_int))}`),
          chip(num(s.n_atoms) === undefined ? undefined : t.toolCards.atomsCount(num(s.n_atoms) as number)),
          nodeChip(s, item),
        ),
        warn: mismatch ?? null,
      };
    },
  },
  reduce_with_crysalis: {
    running: () => t.toolCards.crysalisRunning,
    done: (s) => {
      const steps = arr(s.steps).filter(isObj);
      const evidence = steps
        .flatMap((st) => strList(st.evidence))
        .filter((t) => /Best cell|profiles|UB fit/i.test(t));
      const secs = steps.reduce((a, st) => a + (num(st.elapsed_s) ?? 0), 0);
      const hkl = str(s.hkl);
      return {
        title: t.toolCards.crysalisTitle(num(s.n_hkl_rows)?.toLocaleString() ?? "?"),
        chips: chips(
          chip(hkl ? hkl.split(/[\\/]/).pop() : undefined),
          chip(secs > 0 ? `${Math.round(secs)} s` : undefined),
          chip(t.toolCards.stepsCount(steps.length)),
        ),
        warn: strList(s.existing_model_in_directory).length > 0
          ? str(s.independence_note) ?? null
          : null,
        detail:
          evidence.length > 0 ? (
            <ul className="list-disc pl-4">
              {evidence.slice(0, 4).map((t, i) => (
                <li key={i} className="font-mono text-2xs">
                  {t}
                </li>
              ))}
            </ul>
          ) : null,
      };
    },
  },
  estimate_resolution: {
    // NOT observe: the shell curves are the point, and a collapsed gray
    // row would hide them
    running: () => t.toolCards.estimateResRunning,
    done: (s) => {
      const d = num(s.suggested_d_min);
      const cur = num(s.current_d_min);
      const shells = arr(s.shells).filter(isObj) as unknown as Shell[];
      return {
        title:
          d === undefined
            ? t.toolCards.estimateResNone
            : t.toolCards.estimateResTitle(d.toFixed(2), cur === undefined ? undefined : cur.toFixed(2)),
        chips: chips(
          chip(shells.length > 0 ? t.toolCards.shellsCount(shells.length) : undefined),
          chip(str(s.centring_inferred) === undefined
            ? undefined : t.toolCards.latticeChip(str(s.centring_inferred) as string)),
          chip(str(s.merge_laue_class)),
        ),
        warn: str(s.warning) ?? null,
        body: shells.length >= 3 ? <ShellCurve shells={shells} /> : null,
      };
    },
  },
  export_twin_hklf5: {
    running: () => t.toolCards.exportHklf5Running,
    done: (s) => {
      const c = isObj(s.overlap_census) ? s.overlap_census : {};
      const sc = isObj(s.scaling) ? s.scaling : {};
      const a = isObj(sc.domain_A) ? sc.domain_A : {};
      return {
        title: t.toolCards.exportHklf5Title(
          num(c.composites)?.toLocaleString() ?? "?",
          num(c.major_clean)?.toLocaleString() ?? "?",
        ),
        chips: chips(
          chip(num(a.completeness) === undefined
            ? undefined : t.toolCards.completenessValue((num(a.completeness) as number).toFixed(3))),
          chip(num(a.r_meas) === undefined ? undefined : `Rmeas ${f4(num(a.r_meas))}`),
          chip(s.reused_integration === true ? t.toolCards.reusedIntegration : undefined),
        ),
        warn: str(s.disclosure_note) ?? str(s.completeness_note) ?? null,
      };
    },
  },
  swap_reflection_data: {
    running: (args) => t.toolCards.swapRunning(str(args.hkl) ?? ""),
    done: (s) => {
      const merge = isObj(s.merge) ? s.merge : {};
      return {
        title: t.toolCards.swapTitle(str(s.swapped_to) ?? "?", num(s.hklf) ?? "?", num(s.n_domains)),
        chips: chips(
          chip(num(s.n_obs)?.toLocaleString() === undefined
            ? undefined : t.toolCards.observations((num(s.n_obs) as number).toLocaleString())),
          chip(num(merge.n_unique) === undefined
            ? undefined : t.toolCards.uniqueCount((num(merge.n_unique) as number).toLocaleString())),
          chip(num(merge.r_int) === undefined ? undefined : `Rint ${f4(num(merge.r_int))}`),
        ),
        warn: str(s.mask_cleared) ?? str(s.hklf5_note) ?? null,
      };
    },
  },
  set_experiment: {
    running: () => t.toolCards.setExperimentRunning,
    done: (s) => {
      const rec = isObj(s.recorded) ? Object.keys(s.recorded) : [];
      const absent = strList(s.remove_requested_but_absent);
      return {
        title: t.toolCards.setExperimentTitle(rec.length > 0 ? rec.join(" / ") : null),
        chips: chips(chip(strList(s.removed).length > 0
          ? t.toolCards.removedCount(strList(s.removed).length) : undefined)),
        warn: absent.length > 0 ? t.toolCards.removeAbsent(absent.join(" ")) : null,
      };
    },
  },

  // ------------------------------------------------------ structure solution
  solve_charge_flipping: {
    running: () => t.toolCards.chargeFlipRunning,
    done: (s) => ({
      title: t.toolCards.chargeFlipTitle(f2(num(s.map_correlation)) ?? "?", num(s.n_peaks) ?? "?"),
      chips: chips(
        chip(num(s.seed) === undefined ? undefined : t.toolCards.seedChip(num(s.seed) as number)),
        chip(num(s.d_min) === undefined ? undefined : `d_min ${num(s.d_min)} Å`),
        chip(num(s.elapsed_s) === undefined
          ? undefined : `${(num(s.elapsed_s) as number).toFixed(0)} s`),
      ),
    }),
  },
  solve_superflip: {
    running: () => t.toolCards.superflipRunning,
    done: (s) => {
      const sym = isObj(s.symmetry_agreement) ? s.symmetry_agreement : {};
      const overall = num(sym.overall);
      // >~0.25 means the model density does NOT obey the assumed operators
      const bad = overall !== undefined && overall > 0.25;
      return {
        title: t.toolCards.superflipTitle(num(s.final_r_percent)?.toFixed(1) ?? "?", num(s.n_peaks) ?? "?"),
        chips: chips(
          chip(overall === undefined ? undefined : t.toolCards.symmetryAgreement(f2(overall) as string),
               bad ? "warn" : "ok"),
          chip(num(s.n_cycles) === undefined ? undefined : t.toolCards.cyclesCount(num(s.n_cycles) as number)),
        ),
        tone: bad ? "warn" : null,
        warn: bad
          ? t.toolCards.superflipSymWarn
          : null,
      };
    },
  },
  run_shelxt: {
    running: () => t.toolCards.shelxtRunning,
    done: (s) => {
      const sols = arr(s.solutions).filter(isObj);
      const best = sols[0] ?? {};
      const adopted = s.adopted === true;
      return {
        title: adopted
          ? t.toolCards.shelxtAdoptedTitle(str(s.space_group) ?? "?", num(s.n_atoms) ?? "?")
          : t.toolCards.shelxtTitle(sols.length),
        chips: chips(
          chip(num(best.r1) === undefined ? undefined : `R1 ${f4(num(best.r1))}`),
          chip(num(best.rweak) === undefined ? undefined : `Rweak ${f2(num(best.rweak))}`),
          chip(str(best.space_group) === undefined
            ? undefined : t.toolCards.bestChip(str(best.space_group) as string)),
        ),
        warn: adopted ? null : (str(s.note) ?? null),
      };
    },
  },
  interpret_peaks: {
    running: () => t.toolCards.interpretRunning,
    done: (s) => {
      const counts = isObj(s.element_counts) ? s.element_counts : {};
      const comp = Object.entries(counts)
        .map(([el, n]) => `${el}${num(n) ?? ""}`)
        .join(" ");
      const unassigned = num(s.n_probable_unassigned_heavy_sites) ?? 0;
      return {
        title: t.toolCards.interpretTitle(num(s.n_atoms) ?? "?", comp),
        chips: chips(
          chip(num(s.n_symmetry_ghosts_removed) === undefined
            ? undefined : t.toolCards.symmetryGhostsRemoved(num(s.n_symmetry_ghosts_removed) as number)),
          chip(s.composition_known === false ? t.toolCards.compositionUnknown : undefined, "warn"),
        ),
        tone: unassigned > 0 ? "warn" : null,
        warn:
          unassigned > 0
            ? t.toolCards.unassignedHeavyWarn(unassigned)
            : null,
      };
    },
  },

  // ---------------------------------------------------------------- symmetry
  screen_space_groups: {
    observe: true,
    running: () => t.toolCards.screenSgRunning,
    done: (s) => {
      const cands = arr(s.candidates).filter(isObj);
      const top = cands[0] ?? {};
      const est = isObj(s.e_statistics) ? s.e_statistics : {};
      const hint = str(est.hint);
      return {
        title: t.toolCards.screenSgTitle(str(top.space_group) ?? "?", cands.length, num(s.n_candidates_total) ?? "?"),
        chips: chips(
          chip(hint === "centrosymmetric"
            ? t.toolCards.eStatsCentro
            : hint === "non_centrosymmetric"
              ? t.toolCards.eStatsNonCentro
              : undefined),
          chip(str(s.laue_class_used)),
          chip(num(top.violation_rate) === undefined
            ? undefined : t.toolCards.violationRate(((num(top.violation_rate) as number) * 100).toFixed(1))),
        ),
        // the metric Laue class can exceed the true symmetry - the tool
        // says so in `note`; surface it instead of burying it in JSON
        warn: /METRIC|metric/.test(str(s.note) ?? "") ? (str(s.note) ?? null) : null,
      };
    },
  },
  audit_heavy_sites: {
    observe: true,
    running: () => t.toolCards.auditHeavyRunning,
    done: (s) => {
      const readiness = isObj(s.readiness) ? s.readiness : {};
      const anomalous = isObj(s.anomalous) ? s.anomalous : {};
      const edge = anomalous.edge_at_lambda;
      const edgeList = Array.isArray(edge) ? strList(edge) : edge ? [String(edge)] : [];
      const blockers = strList(readiness.blockers);
      const ready = readiness.ready_for_r_vs_z === true;
      return {
        title: t.toolCards.auditHeavyTitle(num(s.n_sites) ?? "?", ready),
        chips: chips(
          chip(edgeList.length > 0 ? t.toolCards.absorptionEdges(edgeList.join("/")) : undefined),
          chip(blockers.length > 0 ? t.toolCards.blockersCount(blockers.length) : undefined),
          chip(num(anomalous.wavelength_A) !== undefined
            ? `λ ${num(anomalous.wavelength_A)} Å` : undefined),
        ),
        warn: !ready && blockers.length > 0 ? blockers.slice(0, 2).join(t.toolCards.listSeparator) : null,
      };
    },
  },
  reflection_statistics: {
    observe: true,
    running: () => t.toolCards.reflStatsRunning,
    done: (s) => {
      const merge = isObj(s.merge) ? s.merge : {};
      const est = isObj(s.e_statistics) ? s.e_statistics : {};
      const hint = str(est.hint);
      const centring = str(s.centring_implied_by_file);
      return {
        title: t.toolCards.reflStatsTitle(str(s.laue_class) ?? "?", num(merge.n_unique)?.toLocaleString() ?? "?"),
        chips: chips(
          chip(num(merge.r_int) === undefined ? undefined : `Rint ${f4(num(merge.r_int))}`),
          chip(num(merge.completeness) === undefined
            ? undefined : t.toolCards.completenessPct(((num(merge.completeness) as number) * 100).toFixed(1))),
          chip(num(est.mean_abs_e2_minus_1) === undefined
            ? undefined : `⟨|E²−1|⟩ ${(num(est.mean_abs_e2_minus_1) as number).toFixed(3)}`),
          chip(hint === "centrosymmetric"
            ? t.toolCards.eStatsCentro
            : hint === "non_centrosymmetric"
              ? t.toolCards.eStatsNonCentro
              : undefined),
          chip(centring && centring !== "P" ? t.toolCards.fileCentring(centring) : undefined),
          chip(arr(s.laue_scan).length > 0 ? t.toolCards.laueScan(arr(s.laue_scan).length) : undefined),
        ),
      };
    },
  },
  change_space_group: {
    running: (args) => t.toolCards.changeSgRunning(str(args.space_group) ?? ""),
    done: (s) => {
      if (str(s.mode) === "atomless_declaration") {
        const merge = isObj(s.merge) ? s.merge : {};
        return {
          title: t.toolCards.declareSgTitle(str(s.declared_space_group) ?? "?"),
          chips: chips(
            chip(num(merge.r_int) === undefined ? undefined : `Rint ${f4(num(merge.r_int))}`),
            chip(num(merge.n_unique) === undefined
              ? undefined : t.toolCards.uniqueCount((num(merge.n_unique) as number).toLocaleString())),
          ),
        };
      }
      const dropped = strList(s.dropped_metadata);
      const ops = arr(s.added_ops_verified).filter(isObj);
      return {
        title: t.toolCards.changeSgTitle(str(s.old_space_group) ?? "?", str(s.new_space_group) ?? "?"),
        chips: chips(
          chip(num(s.n_atoms_before) !== undefined && num(s.n_atoms_after) !== undefined
            ? t.toolCards.atomsDelta(num(s.n_atoms_before) as number, num(s.n_atoms_after) as number)
            : undefined),
          chip(ops.length > 0 ? t.toolCards.opsVerified(ops.length) : undefined),
          chip(num(s.n_h_stripped) !== undefined && (num(s.n_h_stripped) as number) > 0
            ? t.toolCards.hStripped(num(s.n_h_stripped) as number) : undefined),
        ),
        warn:
          dropped.length > 0
            ? t.toolCards.droppedState(dropped.join(" / "))
            : (str(s.adp_note) ?? null),
      };
    },
  },
  ncs_audit: {
    observe: true,
    running: () => t.toolCards.ncsRunning,
    done: (s) => {
      const hyp = isObj(s.hypotheses) ? s.hypotheses : {};
      const rows = ["translation", "inversion"]
        .map((k) => ({ k, v: isObj(hyp[k]) ? (hyp[k] as Rec) : null }))
        .filter((r): r is { k: string; v: Rec } => r.v !== null);
      const best = rows.sort(
        (a, b) => (num(b.v.match_fraction) ?? 0) - (num(a.v.match_fraction) ?? 0),
      )[0];
      const frac = best ? num(best.v.match_fraction) : undefined;
      const rational = best && isObj(best.v.rational)
        ? (best.v.rational as Rec).is_rational === true
        : false;
      const strong = (frac ?? 0) >= 0.7;
      return {
        title: best
          ? t.toolCards.ncsTitle(best.k === "inversion", ((frac ?? 0) * 100).toFixed(0))
          : t.toolCards.ncsTitlePlain,
        chips: chips(
          chip(best && num(best.v.rmsd_A) !== undefined
            ? `rmsd ${(num(best.v.rmsd_A) as number).toFixed(3)} Å` : undefined),
          chip(rational ? t.toolCards.rationalOperator : undefined, "warn"),
          chip(best ? str(best.v.operator) : undefined),
        ),
        tone: strong && rational ? "warn" : null,
        warn: strong && rational
          ? t.toolCards.ncsWarn
          : null,
      };
    },
  },
  assemble_asu: {
    running: () => t.toolCards.assembleRunning,
    done: (s) => {
      const ghosts = arr(s.ghost_suspects_remaining).filter(isObj);
      if (s.no_state_change === true && s.dry_run !== true) {
        return {
          title: t.toolCards.asuCoherent(num(s.n_fragments) ?? "?"),
          tone: "ok",
        };
      }
      const plan = arr(s.dry_run === true ? s.plan : s.applied).filter(isObj);
      const before = num(s.n_detached_atoms_before) ?? num(s.n_detached_atoms);
      const after = num(s.n_detached_atoms_after);
      return {
        title:
          s.dry_run === true
            ? t.toolCards.asuDryRun(plan.length, before ?? "?")
            : t.toolCards.asuAssembled(plan.length, before ?? "?", after ?? "?"),
        chips: chips(
          chip(num(s.n_atoms) === undefined ? undefined : t.toolCards.atomsCount(num(s.n_atoms) as number)),
          chip(arr(s.occupancy_rescaled).length > 0
            ? t.toolCards.occupancyRescaled(arr(s.occupancy_rescaled).length) : undefined),
        ),
        warn:
          ghosts.length > 0
            ? t.toolCards.ghostSuspects(ghosts.length, ghosts
                .slice(0, 3)
                .map((g) => str(g.label) ?? "?")
                .join(" "))
            : null,
      };
    },
  },

  // ------------------------------------------------- refinement / twin state
  run_olex2: {
    running: () => t.toolCards.olex2Running,
    done: (s) => {
      const r1 = num(s.r1_gt) ?? num(s.r1_console);
      const d = num(s.delta_r1_vs_session);
      const diverged = d !== undefined && Math.abs(d) > 0.01;
      return {
        title: t.toolCards.olex2Title(f4(r1) ?? "?"),
        chips: chips(
          chip(num(s.wr2) === undefined ? undefined : `wR2 ${f4(num(s.wr2))}`),
          chip(num(s.goof) === undefined ? undefined : `GooF ${f2(num(s.goof))}`),
          chip(d === undefined ? undefined : t.toolCards.deltaVsSession(`${d >= 0 ? "+" : ""}${f4(d)}`),
               diverged ? "warn" : "ok"),
        ),
        tone: diverged ? "warn" : null,
        warn: diverged ? (str(s.note) ?? null) : null,
      };
    },
  },
  set_weights: {
    running: () => t.toolCards.setWeightsRunning,
    done: (s) => {
      const o = isObj(s.old) ? s.old : {};
      const n = isObj(s.new) ? s.new : {};
      return {
        title: t.toolCards.setWeightsTitle(
          `${f4(num(o.a)) ?? "?"}/${f4(num(o.b)) ?? "?"}`,
          `${f4(num(n.a)) ?? "?"}/${f4(num(n.b)) ?? "?"}`,
        ),
        warn: str(s.warning) ?? null,
        tone: str(s.warning) !== undefined ? "warn" : null,
      };
    },
  },
  set_resolution_limit: {
    running: (args) =>
      args.d_min === null
        ? t.toolCards.removeResRunning
        : t.toolCards.setResRunning(str(args.d_min) ?? num(args.d_min) ?? ""),
    done: (s) => ({
      title:
        s.removed === true
          ? t.toolCards.removeResTitle
          : t.toolCards.setResTitle(str(s.shel) ?? "?"),
      chips: chips(chip(str(s.reason))),
    }),
  },
  set_z: {
    running: () => t.toolCards.setZRunning,
    done: (s) => ({
      title: t.toolCards.setZTitle(num(s.old_z) ?? "?", num(s.new_z) ?? "?", num(s.z_prime)?.toFixed(2) ?? "?"),
      chips: chips(
        chip(num(s.sg_order) === undefined ? undefined : t.toolCards.groupOrder(num(s.sg_order) as number)),
        chip(str(s.reason)),
      ),
      warn: str(s.warning) ?? null,
      tone: str(s.warning) !== undefined ? "warn" : null,
    }),
  },
  model_disorder: {
    running: (args) =>
      str(args.undo) !== undefined
        ? t.toolCards.undoDisorderRunning(str(args.undo) as string)
        : t.toolCards.splitDisorderRunning(strList(args.atoms).slice(0, 4).join(" ")),
    done: (s) => {
      if (str(s.undone) !== undefined) {
        const merged = arr(s.merged).filter(isObj);
        const gone = strList(s.deleted_atoms);
        return {
          title: t.toolCards.undoDisorderTitle(str(s.undone) as string, merged.length),
          chips: chips(
            chip(gone.length > 0 ? t.toolCards.deletedAtoms(gone.slice(0, 4).join(" ")) : undefined),
            chip(num(s.n_atoms) === undefined ? undefined : t.toolCards.atomsCount(num(s.n_atoms) as number)),
            chip(isObj(s.fvar_renumbered) ? t.toolCards.fvarRenumbered : undefined),
          ),
          warn: arr(s.restraints_pruned).length > 0
            ? t.toolCards.restraintsPruned(arr(s.restraints_pruned).length) : null,
        };
      }
      const split = arr(s.split).filter(isObj);
      const folded = split.filter((x) => str(x.note) !== undefined).length;
      return {
        title: t.toolCards.splitDisorderTitle(split.length),
        chips: chips(
          chip(num(s.occupancy_a) === undefined
            ? undefined : t.toolCards.occupancyAStart(f2(num(s.occupancy_a)) as string)),
          chip(num(s.fvar_index) === undefined
            ? undefined : `FVAR ${num(s.fvar_index)}`),
          chip(num(s.n_atoms) === undefined ? undefined : t.toolCards.atomsCount(num(s.n_atoms) as number)),
          chip(isObj(s.restraint_suggestion) ? t.toolCards.restraintSuggestion : undefined),
        ),
        warn: folded > 0 ? t.toolCards.bSitesFolded(folded) : null,
      };
    },
  },
  set_twin: {
    running: (args) => {
      const law = str(args.law);
      return law === "suggest"
        ? t.toolCards.twinSuggestRunning
        : law === "remove"
          ? t.toolCards.twinRemoveRunning
          : t.toolCards.twinSetRunning;
    },
    done: (s) => {
      if (arr(s.candidates).length > 0) {
        return {
          title: t.toolCards.twinCandidatesTitle(arr(s.candidates).length),
          chips: chips(chip(t.toolCards.listOnly)),
        };
      }
      if (isObj(s.removed)) return { title: t.toolCards.twinRemovedTitle };
      if (s.no_state_change === true) return { title: t.toolCards.twinUnchanged };
      const tw = isObj(s.twin) ? s.twin : {};
      const basf = arr(tw.basf).map((x) => num(x)).filter((x) => x !== undefined);
      return {
        title: t.toolCards.twinSetTitle(num(tw.n) ?? 2),
        chips: chips(
          chip(basf.length > 0
            ? `BASF ${basf.map((b) => (b as number).toFixed(3)).join(" ")}` : undefined),
          chip(arr(tw.matrix).length === 9
            ? arr(tw.matrix).slice(0, 9).map((x) => num(x)).join(" ") : undefined),
        ),
        warn: t.toolCards.twinRefineWarn,
      };
    },
  },
  set_adp: {
    running: () => t.toolCards.setAdpRunning,
    done: (s) => ({
      title: s.no_state_change === true ? t.toolCards.adpUnchanged : t.toolCards.adpTitle(s.mode === "anisotropic", arr(s.atoms).length),
      chips: chips(chip(t.toolCards.keepsAfixTwin)),
    }),
  },
  set_afix: {
    running: () => t.toolCards.setAfixRunning,
    done: (s) => ({
      title: t.toolCards.setAfixTitle(arr(s.groups).length),
      chips: chips(chip(isObj(s.group) ? `AFIX ${num(s.group.afix)}` : undefined)),
    }),
  },
  set_site_occupancy: {
    running: () => t.toolCards.setOccRunning,
    done: (s) => ({
      title: t.toolCards.setOccTitle(str(s.atom) ?? t.toolCards.atomFallback, s.mode === "free"),
      chips: chips(chip(num(s.occupancy) === undefined ? undefined : t.toolCards.setOccChip(s.mode === "free", (num(s.occupancy) as number).toFixed(4)))),
    }),
  },
  invert_structure: {
    running: () => t.toolCards.invertRunning,
    done: (s) => ({
      title: t.toolCards.invertTitle(str(s.operation) ?? "?", str(s.space_group) ?? "?"),
      chips: chips(
        chip(num(s.n_atoms) === undefined ? undefined : t.toolCards.atomsCount(num(s.n_atoms) as number)),
        chip(s.group_changed === true ? t.toolCards.groupChangedEnantiomorph : undefined, "warn"),
      ),
      warn: s.group_changed === true ? (str(s.note) ?? null) : null,
    }),
  },

  // ---------------------------------------------------------------- evidence
  audit_guest_evidence: {
    observe: true,
    running: () => t.toolCards.guestRunning,
    done: (s) => {
      const verdict = strList(s.verdict);
      const against = verdict.filter((v) => /AGAINST|WARNS/.test(v)).length;
      const supports = verdict.filter((v) => /SUPPORTS/.test(v)).length;
      const open = verdict.filter((v) => /INCONCLUSIVE/.test(v)).length;
      const modeled = num(s.modeled_electrons);
      const expected = num(s.expected_electrons);
      // round-3 WP4: the denominator the verdict was read against
      const acc = isObj(s.accounting) ? s.accounting : null;
      const den = acc && isObj(acc.denominators) ? acc.denominators : null;
      const work = den && isObj(den.working_occupancy) ? num(den.working_occupancy.occupancy_mean) : undefined;
      const prior = isObj(s.conditioned_by_prior) && s.conditioned_by_prior.value === true;
      return {
        title: t.toolCards.guestTitle(supports, against, open),
        chips: chips(
          chip(work === undefined || work >= 0.995 ? undefined : t.toolCards.workingOccupancy(work.toFixed(2))),
          chip(modeled === undefined ? undefined : t.toolCards.modelElectrons(modeled.toFixed(1))),
          chip(expected === undefined ? undefined : t.toolCards.expectedElectrons(expected.toFixed(1))),
          chip(prior ? t.toolCards.conditionedByPrior : undefined),
        ),
        tone: against > 0 ? "warn" : open > 0 ? "warn" : supports > 0 ? "ok" : null,
        warn: str(s.mask_warning) ?? (against > 0
          ? (verdict.find((v) => /AGAINST|WARNS/.test(v)) ?? null)
          : open > 0 ? (verdict.find((v) => /INCONCLUSIVE/.test(v)) ?? null) : null),
      };
    },
  },

  // ------------------------------------------------------------------ skills
  list_skills: {
    observe: true,
    running: () => t.toolCards.listSkillsRunning,
    done: (s) => {
      const n = num(s.n_skills) ?? 0;
      const miss = isObj(s.near_misses_per_word);
      return {
        title: n === 0 ? t.toolCards.listSkillsNone : t.toolCards.listSkillsTitle(n),
        chips: chips(
          chip(
            arr(s.skills).length > 0
              ? strList(arr(s.skills).filter(isObj).map((x) => (x as Rec).name))
                  .slice(0, 3)
                  .join(" · ")
              : undefined,
          ),
        ),
        warn: miss ? t.toolCards.listSkillsNearMiss : null,
      };
    },
  },
  read_skill: {
    observe: true,
    running: (args) => t.toolCards.readSkillRunning(str(args.name) ?? ""),
    done: (s, args) => ({
      title: t.toolCards.readSkillTitle(str(s.name) ?? str(args.name) ?? "?"),
      chips: chips(
        chip(num(s.n_chars_total) === undefined
          ? undefined : t.toolCards.charsCount((num(s.n_chars_total) as number).toLocaleString())),
        chip(s.truncated === true ? t.toolCards.paginated : undefined, "warn"),
      ),
    }),
  },
  set_investigation: {
    running: () => t.toolCards.investigationRunning,
    done: (s) => {
      const inv = isObj(s.investigation) ? s.investigation : {};
      const tiers = isObj(inv.tiers) ? inv.tiers : {};
      const unmet = strList(inv.unmet_tiers);
      const dirs = strList(inv.open_directions);
      const changed = strList(s.changed);
      const goal = str(inv.goal);
      const tierLabels = t.toolCards.tierLabels;
      return {
        title: changed.length === 0 ? t.toolCards.investigationNoChange : t.toolCards.investigationTitle(goal),
        chips: chips(
          chip(t.toolCards.tierCandidateComplete(tierLabels[str(tiers.candidate_complete) ?? "unmet"] ?? tierLabels.unmet)),
          chip(t.toolCards.tierScientificallyEstablished(tierLabels[str(tiers.scientifically_established) ?? "unmet"] ?? tierLabels.unmet)),
          chip(num(inv.n_ruled_out) ? t.toolCards.ruledOut(num(inv.n_ruled_out) as number) : undefined),
          chip(dirs.length > 0 ? t.toolCards.openDirections(dirs.length) : undefined),
        ),
        tone: unmet.length > 0 && dirs.length === 0 && changed.length > 0 ? "warn" : "ok",
        warn: unmet.length > 0 && dirs.length === 0 && changed.length > 0
          ? t.toolCards.investigationWarn
          : null,
      };
    },
  },
  save_skill: {
    running: (args) => t.toolCards.saveSkillRunning(str(args.name) ?? ""),
    done: (s) => ({
      title: t.toolCards.saveSkillTitle(str(s.action) === "updated", str(s.saved) ?? "?"),
      chips: chips(chip(str(s.reason))),
    }),
  },
  delete_skill: {
    running: (args) => t.toolCards.deleteSkillRunning(str(args.name) ?? ""),
    done: (s) => ({
      title: t.toolCards.deleteSkillTitle(str(s.deleted) ?? "?"),
      chips: chips(chip(str(s.reason)), chip(t.toolCards.recoverableFromGit)),
    }),
  },

  // --- vision: the pictures the model looked at, shown to the user too ---
  view_structure: {
    running: (args) => {
      const st = str(args.state) ?? "asu";
      return t.toolCards.viewStructureRunning(stateZh[st] ?? st);
    },
    done: (s, args) => {
      const st = str(s.state) ?? str(args.state) ?? "asu";
      const views = strList(s.views).map((v) => viewZh[v] ?? v);
      const n = num(s.n_atoms_drawn);
      const hi = strList(args.highlight);
      return {
        title: t.toolCards.viewStructureTitle(stateZh[st] ?? st, views.join(" / ")),
        chips: chips(
          chip(n === undefined ? undefined : t.toolCards.atomsCount(n)),
          chip(hi.length > 0 ? t.toolCards.highlighted(hi.slice(0, 4).join(" ")) : undefined),
        ),
        body: viewStrip(s.images, stateZh[st]),
      };
    },
  },
  situation_report: {
    running: () => t.toolCards.situationRunning,
    done: (s) => {
      const conflicts = strList(s.conflicts);
      const narrative = strList(s.narrative);
      const data = isObj(s.data_side) ? s.data_side : {};
      const model = isObj(s.model_side) ? s.model_side : {};
      const r1 = num(data.r1) ?? num(s.r1);
      const compl = num(data.completeness);
      const nAtoms = num(model.n_atoms);
      return {
        title:
          conflicts.length > 0
            ? t.toolCards.situationConflicts(conflicts.length)
            : t.toolCards.situationTitle,
        tone: conflicts.length > 0 ? "warn" : null,
        chips: chips(
          chip(r1 === undefined ? undefined : `R1 ${f4(r1)}`),
          chip(
            compl === undefined
              ? undefined
              : t.toolCards.completenessPct((compl * (compl <= 1 ? 100 : 1)).toFixed(1)),
          ),
          chip(nAtoms === undefined ? undefined : t.toolCards.atomsCount(nAtoms)),
        ),
        warn: conflicts.length > 0 ? conflicts[0] : null,
        body: (
          <>
            {narrative.length > 0 && (
              <div className="mb-1.5 space-y-1">
                {narrative.slice(0, 2).map((t, i) => (
                  <div key={i}>{t}</div>
                ))}
              </div>
            )}
            {viewStrip(s.images)}
          </>
        ),
      };
    },
  },
  list_nodes: {
    observe: true,
    running: () => t.toolCards.listNodesRunning,
    done: () => ({ title: t.toolCards.listNodesTitle }),
  },
  compare_nodes: {
    observe: true,
    running: () => t.toolCards.compareNodesRunning,
    done: (_s, args) => {
      const a = str(args.a);
      const b = str(args.b);
      return {
        title: t.toolCards.compareNodesTitle(a, b),
      };
    },
  },
};

/** Tools whose success renders as a quiet row (read-only observations) -
 * also the set MessageList may fold into a collapsed action group. */
export const OBSERVE_TOOLS: ReadonlySet<string> = new Set(
  Object.entries(registry)
    .filter(([, def]) => def.observe === true)
    .map(([name]) => name),
);

export function isCrystalTool(item: ToolCardItem): boolean {
  return item.server === "crystalpilot" || (item.server === null && item.tool in registry);
}

function checkcifHumanized(
  prefix: string,
  s: Rec,
  item: ToolCardItem,
): Partial<ToolHumanized> {
  const counts = isObj(s.counts) ? s.counts : null;
  if (counts !== null) {
    const a = num(counts.A) ?? 0;
    const b = num(counts.B) ?? 0;
    const c = num(counts.C) ?? 0;
    return {
      title: t.toolCards.checkcifCounts(prefix, a, b, c),
      tone: a > 0 ? "danger" : b > 0 ? "warn" : "ok",
    };
  }
  // result_tail head-truncated (counts serialize before alerts): salvage the
  // surviving alerts instead of lying "A×0" - only levels actually seen are
  // shown, as lower bounds
  const salvaged = parseCheckcifTail(item.resultTail);
  if (salvaged !== null && salvaged.alerts.length > 0) {
    const sc = salvaged.counts ?? salvaged.salvagedCounts;
    const ge = salvaged.counts === null ? "≥" : "×";
    const parts = (["A", "B", "C", "G"] as const)
      .filter((lv) => sc[lv] > 0)
      .map((lv) => `${lv}${ge}${sc[lv]}`);
    return {
      title: t.toolCards.checkcifSalvaged(prefix, parts.length > 0 ? parts.join(" · ") : null),
      tone: sc.A > 0 ? "danger" : sc.B > 0 ? "warn" : null,
      warn:
        salvaged.partial
          ? t.toolCards.checkcifTruncated
          : null,
    };
  }
  return { title: t.toolCards.checkcifUnparsed(prefix) };
}

// ------------------------------------------------------------- entry point

function firstLine(s: string): string {
  const nl = s.indexOf("\n");
  const line = nl >= 0 ? s.slice(0, nl) : s;
  return line.length > 160 ? `${line.slice(0, 160)}…` : line;
}

/** Generic fallback: tool name + whatever metrics the tail parser found. */
function genericHumanized(item: ToolCardItem): ToolHumanized {
  const s = item.summary;
  return {
    title: item.tool,
    chips: chips(
      chip(s?.node !== undefined ? t.toolCards.nodeChip(s.node) : undefined),
      chip(s?.r1 !== undefined ? `R1 ${s.r1.toFixed(4)}` : undefined),
      chip(s?.wr2 !== undefined ? `wR2 ${s.wr2.toFixed(4)}` : undefined),
      chip(s?.goof !== undefined ? `GooF ${s.goof.toFixed(2)}` : undefined),
      chip(s?.nAtoms !== undefined ? t.toolCards.atomsCount(s.nAtoms) : undefined),
    ),
    warn: null,
    observe: false,
    tone: null,
    body: null,
    detail: null,
  };
}

// Humanization runs for every tool item on every transcript render
// (grouping via isMinor + the cards themselves); on thousand-item
// campaign transcripts that repeats JSON digging per SSE event. The
// reducer replaces item objects on every patch (threadReducer.update),
// so caching per item identity is safe and self-invalidating.
const HUMANIZE_CACHE = new WeakMap<ToolCardItem, ToolHumanized>();

export function humanizeTool(item: ToolCardItem): ToolHumanized {
  const hit = HUMANIZE_CACHE.get(item);
  if (hit) return hit;
  const out = humanizeToolUncached(item);
  HUMANIZE_CACHE.set(item, out);
  return out;
}

function humanizeToolUncached(item: ToolCardItem): ToolHumanized {
  const def = registry[item.tool];
  const args = isObj(item.args) ? item.args : {};

  if (item.status === "interrupted" || item.status === "no_result") {
    return {
      title: def?.running
        ? def.running(args).replace(/^正在|…$/g, "")
        : item.tool,
      chips: [],
      warn: item.status === "no_result" ? t.toolNoResult : t.toolInterrupted,
      observe: false,
      tone: "warn",
      body: null,
      detail: null,
    };
  }

  if (item.status === "error") {
    // the real reason usually lives INSIDE the result payload
    // ({"ok": false, "error": "refinement failed: …"}), not in the
    // transport-level error field - dig it out instead of the useless
    // "工具返回 ok=false" (user report, r11 case-c refine refusal)
    const parsed = item.summary?.parsed;
    const payloadError =
      isObj(parsed) && typeof parsed.error === "string" && parsed.error !== ""
        ? parsed.error
        : undefined;
    const msg =
      item.error ??
      payloadError ??
      (item.summary?.ok === false ? t.toolCards.toolReturnedNotOk : t.toolFailed);
    // defensive refusals state that the model was left untouched - they are
    // "the guard worked", not a crash; tone them amber, not red
    const refusal =
      /Re-run |rejected|refused|no model change|未改变模型|not applied/i.test(
        msg,
      );
    return {
      title: def?.running ? def.running(args).replace(/^正在|…$/g, "") : item.tool,
      chips: refusal ? [{ text: t.toolCards.refusedNoChange, tone: "warn" }] : [],
      warn: firstLine(msg),
      observe: false,
      tone: refusal ? "warn" : "danger",
      body: null,
      detail: null,
    };
  }

  if (item.status === "running") {
    return {
      title: def?.running ? def.running(args) : t.toolCards.runningTool(item.tool),
      chips: [],
      warn: null,
      observe: def?.observe ?? false,
      tone: null,
      body: null,
      detail: null,
    };
  }

  // done ok
  const envelope = envelopeChips(payload(item));
  if (!def?.done) {
    const g = genericHumanized(item);
    return { ...g, chips: [...envelope, ...g.chips] };
  }
  const partial = def.done(payload(item), args, item);
  return {
    title: partial.title ?? item.tool,
    chips: [...envelope, ...(partial.chips ?? [])],
    warn: partial.warn ?? null,
    observe: def.observe ?? false,
    tone: partial.tone ?? null,
    body: partial.body ?? null,
    detail: partial.detail ?? null,
  };
}
