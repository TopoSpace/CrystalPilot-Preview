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
import { zh } from "./zh";
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
  if (exec === "timeout") out.push({ text: zh.envTimeout, tone: "warn" });
  if (exec === "cancelled") out.push({ text: zh.envCancelled, tone: "warn" });
  const nc = isObj(env.no_change) ? env.no_change : null;
  if (nc?.value === true) out.push({ text: zh.envNoChange, tone: "warn" });
  const sci = isObj(env.scientific_outcome) ? env.scientific_outcome : null;
  const verdict = sci ? str(sci.verdict) : undefined;
  if (verdict === "inconclusive") out.push({ text: zh.envInconclusive, tone: "warn" });
  if (verdict === "against") out.push({ text: zh.envAgainst, tone: "danger" });
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
  return node === undefined ? null : { text: `节点 ${node}` };
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

const refineModeZh: Record<string, string> = {
  isotropic: "各向同性",
  anisotropic: "各向异性",
  scale_only: "仅标度",
};

const specialtyZh: Record<string, string> = {
  space_group: "空间群",
  chemistry: "化学建模",
  density: "残余密度",
  validation: "结构验证",
  refinement_strategy: "精修策略",
};

const confidenceZh: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
};

/** [a,b,c,α,β,γ] -> "12.34 5.67 8.90 Å". */
function cellChipText(v: unknown): string | undefined {
  if (!Array.isArray(v) || v.length < 3) return undefined;
  const abc = v.slice(0, 3).map((x) => num(x));
  if (abc.some((x) => x === undefined)) return undefined;
  return `晶胞 ${abc.map((x) => (x as number).toFixed(2)).join(" ")} Å`;
}

function strList(v: unknown): string[] {
  return arr(v)
    .map((x) => str(x))
    .filter((x): x is string => x !== undefined);
}

const viewZh: Record<string, string> = {
  a: "沿 a 轴",
  b: "沿 b 轴",
  c: "沿 c 轴",
  oblique: "斜视",
};

const stateZh: Record<string, string> = {
  asu: "不对称单元",
  cell: "单胞（P1 展开）",
  supercell: "2×2×2 堆积",
};

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
          title={im.label === "" ? "点击查看原图" : `${im.label} · 点击查看原图`}
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
      return `正在最小二乘精修${m ? `（${refineModeZh[m] ?? m}）` : ""}…`;
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
            精修完成：{metricDelta("R1", prev, r1)}
            {mask ? "，含溶剂掩膜" : ""}
          </>
        ),
        chips: chips(
          chip(f4(num(s.wr2) ?? item.summary?.wr2)?.replace(/^/, "wR2 ")),
          chip(f2(goof)?.replace(/^/, "GooF ")),
          chip(peak !== undefined ? `残差 ${peak.toFixed(2)} eÅ⁻³` : undefined),
          nodeChip(s, item),
        ),
      };
    },
  },

  run_shelxl: {
    running: (a) => a.mode === "adopt" || a.mode === "adopt_wght" ? "正在进行 SHELXL 精修…" : "正在运行 SHELXL 交叉验证…",
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
        nRevoke > 0 ? `无序 ${nRevoke} 组应撤销`
          : nInc > 0 ? `无序 ${nInc} 组未定`
            : nSup > 0 ? `无序 ${nSup} 组占比可测` : undefined;
      const occupancyChips = arr(s.site_occupancies).filter(isObj).slice(0, 3).map((row) => {
        const value = num(row.occupancy), su = num(row.su);
        return chip(value === undefined ? undefined
          : `${str(row.atom) ?? "原子"} 占有率 ${value.toFixed(4)}${su === undefined ? "（s.u. 未定）" : ` ± ${su.toPrecision(2)}`}`);
      });
      return {
        title: `${adopted ? "SHELXL 精修" : "SHELXL 交叉验证"}：${r1 === undefined ? "指标摘要未保留" : `R1 ${f4(r1)}`}${
          !adopted && agrees !== null && d !== undefined ? `（Δ ${dTxt}，${agrees ? "一致" : "分歧"}）` : ""}`,
        tone: nRevoke > 0 || agrees === false ? "warn" : agrees === true ? "ok" : null,
        warn: r1 === undefined ? "当前记录没有完整的精修摘要；请展开原始结果，或查看该次精修节点的指标。" : null,
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
    running: () => "正在按配体模板拟合原子…",
    done: (s, _a, item) => {
      const added = arr(s.added);
      const refused = arr(s.refused);
      return {
        title: `按配体模板补入 ${added.length} 个原子`,
        warn:
          refused.length > 0
            ? `拒绝 ${refused.length} 个（密度不支持）`
            : null,
        chips: chips(nodeChip(s, item)),
      };
    },
  },

  add_atoms_from_difference_map: {
    running: () => "正在从差值图挑选峰位补原子…",
    done: (s, _a, item) => {
      const added = arr(s.added);
      const labels = added
        .map((x) => (isObj(x) ? str(x.label) : undefined))
        .filter((x): x is string => x !== undefined);
      return {
        title: `从差值图补入 ${added.length} 个原子`,
        chips: chips(
          chip(labels.length > 0 ? labels.join(" · ") : undefined),
          nodeChip(s, item),
        ),
      };
    },
  },

  edit_atoms: {
    running: () => "正在编辑模型…",
    done: (s, _a, item) => {
      const applied = arr(s.applied);
      const parts = applied
        .map((x) =>
          isObj(x) ? `${str(x.action) ?? "?"}×${num(x.n) ?? 1}` : undefined,
        )
        .filter((x): x is string => x !== undefined);
      return {
        title: `编辑模型（${applied.length} 项操作）`,
        chips: chips(
          chip(parts.length > 0 ? parts.join(" · ") : undefined),
          nodeChip(s, item),
        ),
      };
    },
  },

  add_hydrogens: {
    running: () => "正在添加骑乘氢…",
    done: (s, args, item) => {
      const n = num(s.n_h_added) ?? 0;
      const elements = arr(args.elements)
        .map((e) => str(e))
        .filter((e): e is string => e !== undefined);
      return {
        title: `添加 ${n} 个骑乘氢${elements.length > 0 ? `（${elements.join("、")}）` : ""}`,
        chips: chips(
          chip(
            num(s.n_carriers) !== undefined
              ? `载体 ${num(s.n_carriers)}`
              : undefined,
          ),
          nodeChip(s, item),
        ),
      };
    },
  },

  optimize_weights: {
    running: () => "正在优化权重方案…",
    done: (s, _a, item) => {
      const goofAfter = num(s.goof_after) ?? num(s.goof);
      const w = isObj(s.weights) ? s.weights : {};
      return {
        title: (
          <>
            权重优化：
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
    running: () => "正在计算溶剂掩膜…",
    done: (s, _a, item) => {
      const nMasked = num(s.n_voids_masked) ?? 0;
      const e = num(s.total_solvent_electrons_per_cell);
      const pct = num(s.solvent_volume_pct_of_cell);
      return {
        title: `溶剂掩膜：${nMasked} 个孔洞${e !== undefined ? ` · ~${Math.round(e)} e⁻` : ""}`,
        chips: chips(
          chip(pct !== undefined ? `溶剂体积 ${pct.toFixed(1)}%` : undefined),
          nodeChip(s, item),
        ),
      };
    },
  },

  search_fragment_pose: {
    observe: true,
    running: () => "正在搜索整片段姿态…",
    done: (s) => {
      const cands = arr(s.candidates).filter(isObj);
      const top = cands[0];
      const direct = top ? (num(top.n_direct) ?? 0) : 0;
      const weak = top ? (num(top.n_weak) ?? 0) : 0;
      const geo = top ? (num(top.n_geometry_only) ?? 0) : 0;
      const frag = isObj(s.fragment) ? s.fragment : null;
      const formula = frag ? (str(frag.formula) ?? str(frag.smiles)) : undefined;
      const folded = top && isObj(top.symmetry_folded) ? num(top.symmetry_folded.n_unique) : undefined;
      const tail = formula ? `（${formula}）` : "";
      return {
        title: cands.length === 0 ? `片段姿态搜索：无候选${tail}` : `片段姿态搜索：${cands.length} 个候选${tail}`,
        chips: chips(
          chip(top ? `首选 ${str(top.id) ?? "c01"} · 直接峰 ${direct} · 弱密度 ${weak} · 仅几何 ${geo}` : undefined),
          chip(folded !== undefined ? `对称折叠 → ${folded} 个独立原子` : undefined),
        ),
        tone: cands.length === 0 ? "warn" : geo > 0 ? "warn" : "ok",
        warn: str(s.timeout) ?? (geo > 0 ? `${geo} 个原子只有几何支持，密度不支持` : null),
      };
    },
  },
  accept_fragment_pose: {
    running: () => "正在把候选片段收入模型…",
    done: (s, _a, item) => {
      const added = arr(s.added);
      const fv = num(s.fvar_index);
      const occ = num(s.occupancy);
      const part = num(s.part);
      const cards = arr(s.cards_added);
      return {
        title: `接受片段候选 ${str(s.candidate_id) ?? ""}：加入 ${added.length} 个原子`,
        chips: chips(
          chip(fv !== undefined ? `FVAR${fv} = ${occ === undefined ? "?" : occ.toFixed(2)}` : occ === undefined ? undefined : `占有率 ${occ.toFixed(2)}`),
          chip(part === undefined ? undefined : `PART ${part}`),
          chip(cards.length > 0 ? "EADP" : undefined),
          nodeChip(s, item),
        ),
        warn: str(s.card_warning) ?? null,
      };
    },
  },
  set_restraints: {
    running: () => "正在更新约束…",
    done: (s, args, item) => {
      const action = str(args.action) ?? "";
      const n = arr(s.restraints).length;
      const conflicts = preflightConflicts(s);
      return {
        title: `约束 ${action}：现有 ${n} 条`,
        chips: chips(nodeChip(s, item)),
        tone: conflicts > 0 ? "warn" : null,
        warn: conflicts > 0 ? `${conflicts} 项跨非零 PART，SHELXL 不会施加` : null,
      };
    },
  },
  preflight_restraints: {
    observe: true,
    running: () => "正在预检约束…",
    done: (s) => {
      const pf = isObj(s.restraints_preflight) ? s.restraints_preflight : {};
      const n = num(pf.requested) ?? 0;
      const conflicts = arr(pf.shelx_part_conflicts).length;
      const bad = arr(pf.not_representable).length;
      const warns = arr(pf.warnings).length;
      const parts: string[] = [`${n} 条`];
      if (conflicts > 0) parts.push(`跨 PART ${conflicts} 项`);
      if (bad > 0) parts.push(`不可表达 ${bad} 项`);
      if (warns > 0) parts.push(`提示 ${warns} 条`);
      return {
        title: `约束预检：${parts.join(" · ")}`,
        tone: conflicts > 0 || bad > 0 ? "warn" : "ok",
        warn: conflicts > 0 ? `SHELXL 不施加跨非零 PART 的距离/平面约束（${conflicts} 项）` : null,
      };
    },
  },

  branch: {
    running: () => "正在新建分支…",
    done: (s) => ({
      title: `新建分支 ${str(s.branch) ?? "—"}（自 ${str(s.at) ?? "—"}）`,
    }),
  },

  checkout: {
    running: () => "正在检出节点…",
    done: (s, _a, item) => ({
      title: `检出 ${str(s.node) ?? item.summary?.node ?? "—"}${
        str(s.branch) !== undefined ? `（${str(s.branch)}）` : ""
      }`,
    }),
  },

  run_checkcif: {
    running: () => "正在运行 checkCIF…",
    done: (s, _a, item) => checkcifHumanized("checkCIF", s, item),
  },

  submit_iucr_checkcif: {
    running: () => "正在提交 IUCr 官方 checkCIF…",
    done: (s, _a, item) => checkcifHumanized("IUCr 官方 checkCIF", s, item),
  },

  // -------------------------------------------------- specialist subagent
  consult_specialist: {
    running: (args) => {
      const sp = str(args.specialty);
      return `正在咨询${sp !== undefined ? (specialtyZh[sp] ?? sp) : ""}专家…`;
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
          ? `${num(cost.n_tool_calls)} 次工具调用`
          : null,
        tokens > 0 ? `${tokens.toLocaleString()} tokens` : null,
      ].filter((x): x is string => x !== null);
      const evidence = strList(v.evidence);
      const risks = strList(v.risks);
      return {
        title: `专家咨询（${specialtyZh[sp] ?? sp}）完成`,
        chips: chips(
          chip(`置信度 ${confidenceZh[conf] ?? conf}`, confTone),
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
                <span className="font-medium text-ink-2">建议：</span>
                {str(v.recommendation)}
              </div>
            )}
            {evidence.length > 0 && (
              <div>
                <span className="font-medium text-ink-2">证据：</span>
                <ul className="mt-0.5 list-disc pl-4">
                  {evidence.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              </div>
            )}
            {risks.length > 0 && (
              <div>
                <span className="font-medium text-ink-2">风险：</span>
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
    running: () => "正在审计空间群对称性…",
    done: (s) => {
      const extra = arr(s.extra_ops_matched).length;
      const suggested = str(s.suggested_space_group);
      return {
        title: str(s.verdict) ?? "对称性审计完成",
        tone: extra > 0 ? "warn" : null,
        chips: chips(
          chip(
            str(s.current_space_group) !== undefined
              ? `当前 ${str(s.current_space_group)}`
              : undefined,
          ),
          chip(
            extra > 0 && suggested !== undefined
              ? `建议 ${suggested}`
              : undefined,
            "warn",
          ),
          chip(
            s.metric_pseudo_symmetry === true ? "晶格存在赝对称" : undefined,
          ),
        ),
        warn:
          extra > 0
            ? "模型服从额外对称操作，需在更高对称群中重精修验证，并如实披露"
            : null,
      };
    },
  },

  rename_atoms: {
    running: () => "正在规范重标号…",
    done: (s) => {
      if (s.no_state_change === true) {
        return { title: "原子标号已规范，无需重命名" };
      }
      const renames = isObj(s.renames) ? s.renames : {};
      const pairs = Object.entries(renames).filter(
        (kv): kv is [string, string] => typeof kv[1] === "string",
      );
      return {
        title: `规范重标号 ${num(s.n_renamed) ?? pairs.length} 个原子`,
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
    running: () => "正在导入外部 CIF 结构…",
    done: (s) => {
      const notes = strList(s.conversion_notes);
      return {
        title: `导入外部结构：${num(s.imported_atoms) ?? "?"} 原子，空间群 ${str(s.space_group) ?? "—"}`,
        chips: chips(
          chip(
            num(s.n_aniso) !== undefined && (num(s.n_aniso) as number) > 0
              ? `各向异性 ${num(s.n_aniso)}`
              : undefined,
          ),
          chip(
            num(s.wavelength_A) !== undefined
              ? `λ ${num(s.wavelength_A)} Å`
              : undefined,
          ),
          chip(str(s.start_node) !== undefined ? `节点 ${str(s.start_node)}` : undefined),
        ),
        detail:
          notes.length > 0 ? (
            <ul className="list-disc pl-4">
              {notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          ) : null,
        warn: notes.length > 0 ? `${notes.length} 条转换说明（展开技术详情查看）` : null,
      };
    },
  },

  // ------------------------------------------ raw frames pipeline (DIALS)
  import_frames: {
    running: () => "正在导入衍射帧…",
    done: (s) => ({
      title: `导入衍射帧：${num(s.n_images) ?? "?"} 张图像${
        num(s.n_sweeps) !== undefined ? `（${num(s.n_sweeps)} 个扫描）` : ""
      }`,
      chips: chips(
        chip(strList(s.formats).join("/") || undefined),
        chip(str(s.vendor_software)),
        chip(
          num(s.n_background) !== undefined && (num(s.n_background) as number) > 0
            ? `本底 ${num(s.n_background)}`
            : undefined,
        ),
      ),
    }),
  },

  find_spots: {
    running: () => "正在寻找衍射斑点…",
    done: (s) => ({
      title: `寻峰：${num(s.n_strong_spots)?.toLocaleString() ?? "?"} 个强斑点`,
      chips: chips(
        chip(
          num(s.d_min) !== undefined ? `d_min ${num(s.d_min)} Å` : undefined,
        ),
      ),
    }),
  },

  index_frames: {
    running: () => "正在指标化…",
    done: (s) => ({
      title: `指标化：${num(s.n_indexed)?.toLocaleString() ?? "?"} 个反射${
        num(s.pct_indexed) !== undefined ? `（${num(s.pct_indexed)}%）` : ""
      }`,
      chips: chips(chip(cellChipText(s.cell))),
      warn:
        num(s.pct_indexed) !== undefined && (num(s.pct_indexed) as number) < 50
          ? "指标化率偏低，晶胞/取向可能有误"
          : null,
    }),
  },

  integrate_frames: {
    running: () => "正在积分强度…",
    done: (s) => ({
      title: `积分：${num(s.n_integrated)?.toLocaleString() ?? "?"} 个反射`,
      chips: chips(chip(cellChipText(s.cell_refined))),
    }),
  },

  scale_and_export: {
    running: () => "正在标定并导出…",
    done: (s) => {
      const sc = isObj(s.scaling) ? s.scaling : {};
      const parts = [
        num(sc.cc_half) !== undefined ? `CC½ ${num(sc.cc_half)}` : null,
        num(sc.r_merge) !== undefined ? `Rmerge ${num(sc.r_merge)}` : null,
        num(sc.completeness) !== undefined
          ? `完整度 ${num(sc.completeness)}%`
          : null,
      ].filter((x): x is string => x !== null);
      return {
        title: `标定导出${parts.length > 0 ? `：${parts.join(" · ")}` : "完成"}`,
        chips: chips(
          chip(
            num(sc.d_min) !== undefined ? `分辨率 ${num(sc.d_min)} Å` : undefined,
          ),
          chip(
            num(sc.i_over_sigma) !== undefined
              ? `I/σ ${num(sc.i_over_sigma)}`
              : undefined,
          ),
          chip(
            num(sc.n_unique) !== undefined
              ? `独立反射 ${num(sc.n_unique)?.toLocaleString()}`
              : undefined,
          ),
          chip(
            str(s.space_group_suggestion) !== undefined
              ? `建议空间群 ${str(s.space_group_suggestion)}`
              : undefined,
          ),
        ),
        warn: str(s.symmetry_warning) ?? null,
      };
    },
  },

  create_start_model: {
    running: () => "正在构建初始模型…",
    done: (s) => ({
      title: `初始模型：${num(s.n_atoms) ?? "?"} 原子（粗解 R1 ${
        f4(num(s.solved_r1)) ?? "—"
      }）`,
      chips: chips(
        chip(str(s.space_group)),
        chip(
          num(s.z_estimated) !== undefined ? `Z=${num(s.z_estimated)}` : undefined,
        ),
        chip(str(s.node) !== undefined ? `节点 ${str(s.node)}` : undefined),
      ),
    }),
  },

  finalize_delivery: {
    running: () => "正在封存交付…",
    done: (s) => {
      const waived = arr(s.waived);
      return {
        title: s.status === "diagnostic" ? "诊断性交付已封存" : s.status === "final" ? "交付已定稿" : `交付：${deliveryStatusLabel(str(s.status) ?? null) || "状态未报告"}`,
        chips: chips(
          chip(str(s.delivery) ? str(s.delivery)!.split(/[\\/]/).slice(-1)[0] : undefined),
          chip(waived.length > 0 ? `豁免 ${waived.length} 项` : undefined),
        ),
        warn: waived.length > 0 ? "有豁免项：理由已记入 REPORT.json，报告里须逐条说明" : null,
      };
    },
  },
  ghost_test: {
    running: (args) => `正在做幽灵原子批量测试（${strList(args.atoms).length || "?"} 个）…`,
    done: (s) => {
      const rows = arr(s.rows).filter(isObj);
      const n = (v: string) => rows.filter((r) => str(r.verdict) === v).length;
      const notTested = arr(s.not_tested);
      return {
        title: `幽灵测试：${num(s.n_tested) ?? rows.length} 个原子，真 ${n("real")} / 幽灵 ${n("ghost")} / 不定 ${n("inconclusive")}`,
        chips: chips(
          chip(notTested.length > 0 ? `未测 ${notTested.length}（预算）` : undefined),
          chip(isObj(s.baseline) && str((s.baseline as Record<string, unknown>).node)
            ? `基线 ${str((s.baseline as Record<string, unknown>).node)}` : undefined),
        ),
        warn: notTested.length > 0 ? "超出时间预算：未测候选已列出，再调一次即可" : null,
      };
    },
  },
  element_scan: {
    running: (args) => `正在扫描 ${str(args.site) ?? "位点"} 的候选元素…`,
    done: (s) => {
      const rows = arr(s.rows).filter(isObj);
      const readiness = isObj(s.readiness) ? s.readiness : {};
      const blockers = strList(readiness.blockers);
      const tied = strList(s.tied_at_top);
      const top = rows[0] ?? {};
      return {
        title: `元素扫描：${num(s.n_tested) ?? rows.length} 个候选，证据首位 ${
          str(top.element) ?? "?"
        }${tied.length > 1 ? `（并列：${tied.join("/")}）` : ""}`,
        chips: chips(
          chip(blockers.length > 0 ? `未就绪 ${blockers.length}` : "就绪"),
          chip(arr(s.not_tested).length > 0 ? `未测 ${arr(s.not_tested).length}` : undefined),
        ),
        warn: blockers.length > 0
          ? `R 差在此模型上无意义：${blockers.slice(0, 2).join("；")}`
          : "元素由化学定（配位数/键长/簇型/吸收边），R 只是旁证",
      };
    },
  },
  probe_site: {
    running: (args) => {
      const els = [str(args.element), ...strList(args.elements)].filter(
        (e): e is string => e !== undefined,
      );
      return `正在试建 ${els.length > 0 ? els.join("/") : "候选原子"}（占有率自由精修）…`;
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
        title: `低占有试建：${rows.length} 个候选，支持 ${n("supported")} / 不支持 ${n("not_supported")} / 临界 ${n("borderline")}`,
        tone: n("supported") > 0 ? "ok" : n("borderline") > 0 ? "warn" : null,
        chips: chips(
          chip(
            str(best.element) !== undefined && occ !== undefined
              ? `${str(best.element)} 占有 ${occ.toFixed(3)}${e !== undefined ? `（${e.toFixed(1)} e）` : ""}`
              : undefined,
          ),
          chip(maskOff ? "掩膜已关（位点在空腔内）" : undefined, "warn"),
          chip(notTested.length > 0 ? `未测 ${notTested.length}（预算）` : undefined),
          chip(isObj(s.baseline) && str((s.baseline as Rec).node)
            ? `基线 ${str((s.baseline as Rec).node)}` : undefined),
        ),
        warn: notTested.length > 0
          ? "超出时间预算：未测候选已列出，再调一次即可"
          : "占有率×Z 才是数据钉住的量：低占有重原子只有几个电子，别拿满占有电子数当尺子",
      };
    },
  },
  write_outputs: {
    running: () => "正在写出成果文件…",
    done: (s, _a, item) => {
      const files = arr(s.files);
      const pub = s.publication_cif === true;
      const metrics = isObj(s.metrics) ? s.metrics : {};
      return {
        title: `输出 ${files.length} 个成果文件${pub ? "（发表级 CIF+fcf）" : ""}`,
        chips: chips(
          chip(f4(num(metrics.r1_strong))?.replace(/^/, "R1 ")),
          nodeChip(s, item),
        ),
      };
    },
  },

  fourier_complete: {
    running: () => "正在做傅里叶补全…",
    done: (s, _a, item) => {
      const added = arr(s.added);
      return {
        title: `傅里叶补全：补入 ${added.length} 个原子`,
        chips: chips(nodeChip(s, item)),
      };
    },
  },

  // ------------------------------------------------------- observe tools
  get_project_brief: {
    observe: true,
    running: () => "正在读取项目简报…",
    done: () => ({ title: "读取项目简报" }),
  },
  inspect_model: {
    observe: true,
    running: () => "正在查看模型…",
    done: (s) => {
      const n = num(s.n_atoms);
      const suspects = Array.isArray(s.suspects) ? s.suspects.length : undefined;
      const isolated = Array.isArray(s.isolated_atoms) ? s.isolated_atoms.length : undefined;
      return {
        title: `查看模型${n !== undefined ? `（${n} 原子）` : ""}`,
        chips: chips(chip(str(s.space_group)),
          chip(suspects !== undefined ? `可疑原子 ${suspects}` : undefined),
          chip(isolated !== undefined ? `孤立原子 ${isolated}` : undefined)),
        tone: (suspects ?? 0) > 0 || (isolated ?? 0) > 0 ? "warn" : null,
      };
    },
  },
  inspect_map: {
    observe: true,
    running: () => "正在检查差值密度…",
    done: (s) => ({ title: "检查差值密度", chips: chips(
      chip(f2(num(s.diff_map_max)) !== undefined ? `Δρ max ${f2(num(s.diff_map_max))} e/Å³` : undefined),
      chip(f2(num(s.diff_map_min)) !== undefined ? `min ${f2(num(s.diff_map_min))} e/Å³` : undefined),
    ) }),
  },
  check_ligand: {
    observe: true,
    running: () => "正在比对配体模板…",
    done: () => ({ title: "比对配体" }),
  },
  get_geometry: {
    observe: true,
    running: () => "正在生成几何表…",
    done: (s) => {
      const nb = num(s.n_bonds) ?? 0;
      const na = num(s.n_angles) ?? 0;
      const esd = str(s.esd_source) !== undefined;
      return {
        title: `几何表：${nb} 键 ${na} 角${esd ? "（含 SHELXL esd）" : "（无 esd）"}${
          s.truncated === true ? "，已截断" : ""
        }`,
      };
    },
  },
  analyze_packing: {
    observe: true,
    running: () => "正在生成堆积 / 孔道 / 相互作用测量表…",
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
        title: `堆积分析：相互作用 ${nIx} 行 · 孔道 ${nV}${
          pi !== undefined ? ` · 堆积 ${pi.toFixed(1)} %` : ""
        }${cards ? ` · HTAB 卡 ${cards}` : ""}`,
      };
    },
  },
  validate_structure: {
    observe: true,
    running: () => "正在做结构验证…",
    done: (s) => {
      const n = num(s.n_alerts) ?? 0;
      return {
        title: `结构验证：${n} 项提醒`,
        tone: n > 0 ? "warn" : null,
      };
    },
  },
  audit_reflection_data: {
    observe: true,
    running: () => "正在体检反射数据（孪晶/对称性征兆）…",
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
          ? `反射数据体检：孪晶警示征 ×${nSigns}`
          : clean
            ? "反射数据体检：无孪晶/对称性征兆"
            : `反射数据体检：${hints.length} 条提示`,
        tone: alarm ? "warn" : clean ? "ok" : hints.length > 0 ? "warn" : null,
        warn: alarm ? (str(hints[hints.length - 1]) ?? null) : null,
      };
    },
  },
  integrate_difference_density: {
    observe: true,
    running: () => "正在积分区域残差电子数…",
    done: (s) => {
      const pos = num(s.electrons_positive);
      const neg = num(s.electrons_negative);
      const claimed = num(s.modeled_electrons_omitted);
      const expected = num(s.expected_electrons);
      const bits: string[] = [];
      if (pos !== undefined && neg !== undefined) {
        bits.push(`+${pos.toFixed(1)}e / ${neg.toFixed(1)}e`);
      }
      if (claimed !== undefined) bits.push(`模型声称 ${claimed.toFixed(1)}e`);
      if (expected !== undefined) bits.push(`期望 ${expected.toFixed(1)}e`);
      return {
        title: `残差电子数积分${bits.length > 0 ? `：${bits.join(" · ")}` : ""}`,
      };
    },
  },
  audit_element_assignment: {
    observe: true,
    running: () => "正在审计 C/N/O 元素指认证据…",
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
            ? `元素指认证据：${n} 处需判读（闲置 N/O ×${idle}）`
            : "元素指认证据：无异常信号",
        tone: n > 0 ? "warn" : "ok",
      };
    },
  },
  // ------------------------------------------------ data ingest / reduction
  ingest_vendor_data: {
    running: () => "正在摄入厂商数据…",
    done: (s, _args, item) => {
      const merge = isObj(s.merge) ? s.merge : {};
      const chosen = isObj(s.chosen) ? s.chosen : {};
      const mismatch = str(s.hklf_mismatch) ?? str(s.twin_data_note);
      const hklf5 = isObj(s.hklf5) ? s.hklf5 : null;
      return {
        title: `摄入厂商数据：${str(chosen.hkl) ?? "?"}`,
        chips: chips(
          chip(hklf5 !== null ? `HKLF5 · ${num(hklf5.n_domains) ?? "?"} 域` : undefined,
               hklf5 !== null ? "warn" : undefined),
          chip(str(merge.space_group)),
          chip(num(merge.r_int) === undefined ? undefined : `Rint ${f4(num(merge.r_int))}`),
          chip(num(s.n_atoms) === undefined ? undefined : `${num(s.n_atoms)} 原子`),
          nodeChip(s, item),
        ),
        warn: mismatch ?? null,
      };
    },
  },
  reduce_with_crysalis: {
    running: () => "正在用 CrysAlisPro 还原数据（峰搜 / 索引 / 积分）…",
    done: (s) => {
      const steps = arr(s.steps).filter(isObj);
      const evidence = steps
        .flatMap((st) => strList(st.evidence))
        .filter((t) => /Best cell|profiles|UB fit/i.test(t));
      const secs = steps.reduce((a, st) => a + (num(st.elapsed_s) ?? 0), 0);
      const hkl = str(s.hkl);
      return {
        title: `CrysAlisPro 还原完成：${
          num(s.n_hkl_rows)?.toLocaleString() ?? "?"
        } 行反射`,
        chips: chips(
          chip(hkl ? hkl.split(/[\\/]/).pop() : undefined),
          chip(secs > 0 ? `${Math.round(secs)} s` : undefined),
          chip(`${steps.length} 步`),
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
    running: () => "正在评估分辨率截断证据…",
    done: (s) => {
      const d = num(s.suggested_d_min);
      const cur = num(s.current_d_min);
      const shells = arr(s.shells).filter(isObj) as unknown as Shell[];
      return {
        title:
          d === undefined
            ? "分辨率评估：无 shell 达标（数据弱或已合并）"
            : `分辨率评估：建议 d_min ${d.toFixed(2)} Å${
                cur === undefined ? "" : `（当前 ${cur.toFixed(2)}）`
              }`,
        chips: chips(
          chip(shells.length > 0 ? `${shells.length} 壳层` : undefined),
          chip(str(s.centring_inferred) === undefined
            ? undefined : `点阵 ${str(s.centring_inferred)}`),
          chip(str(s.merge_laue_class)),
        ),
        warn: str(s.warning) ?? null,
        body: shells.length >= 3 ? <ShellCurve shells={shells} /> : null,
      };
    },
  },
  export_twin_hklf5: {
    running: () => "正在导出双域 HKLF5 数据…",
    done: (s) => {
      const c = isObj(s.overlap_census) ? s.overlap_census : {};
      const sc = isObj(s.scaling) ? s.scaling : {};
      const a = isObj(sc.domain_A) ? sc.domain_A : {};
      return {
        title: `导出 HKLF5：${num(c.composites)?.toLocaleString() ?? "?"} 复合 · ${
          num(c.major_clean)?.toLocaleString() ?? "?"
        } 主域净反射`,
        chips: chips(
          chip(num(a.completeness) === undefined
            ? undefined : `完整度 ${(num(a.completeness) as number).toFixed(3)}`),
          chip(num(a.r_meas) === undefined ? undefined : `Rmeas ${f4(num(a.r_meas))}`),
          chip(s.reused_integration === true ? "复用积分缓存" : undefined),
        ),
        warn: str(s.disclosure_note) ?? str(s.completeness_note) ?? null,
      };
    },
  },
  swap_reflection_data: {
    running: (args) => `正在换用反射数据 ${str(args.hkl) ?? ""}…`,
    done: (s) => {
      const merge = isObj(s.merge) ? s.merge : {};
      return {
        title: `换用数据：${str(s.swapped_to) ?? "?"}（HKLF${num(s.hklf) ?? "?"}${
          num(s.n_domains) === undefined ? "" : ` · ${num(s.n_domains)} 域`
        }）`,
        chips: chips(
          chip(num(s.n_obs)?.toLocaleString() === undefined
            ? undefined : `${num(s.n_obs)?.toLocaleString()} 观测`),
          chip(num(merge.n_unique) === undefined
            ? undefined : `${num(merge.n_unique)?.toLocaleString()} 独立`),
          chip(num(merge.r_int) === undefined ? undefined : `Rint ${f4(num(merge.r_int))}`),
        ),
        warn: str(s.mask_cleared) ?? str(s.hklf5_note) ?? null,
      };
    },
  },
  set_experiment: {
    running: () => "正在登记实验元数据…",
    done: (s) => {
      const rec = isObj(s.recorded) ? Object.keys(s.recorded) : [];
      const absent = strList(s.remove_requested_but_absent);
      return {
        title: `登记实验元数据：${rec.length > 0 ? rec.join(" / ") : "（无）"}`,
        chips: chips(chip(strList(s.removed).length > 0
          ? `删除 ${strList(s.removed).length} 项` : undefined)),
        warn: absent.length > 0 ? `请求删除但不存在：${absent.join(" ")}` : null,
      };
    },
  },

  // ------------------------------------------------------ structure solution
  solve_charge_flipping: {
    running: () => "正在电荷翻转求解…",
    done: (s) => ({
      title: `电荷翻转求解：图相关 ${f2(num(s.map_correlation)) ?? "?"} · ${
        num(s.n_peaks) ?? "?"
      } 个峰`,
      chips: chips(
        chip(num(s.seed) === undefined ? undefined : `种子 ${num(s.seed)}`),
        chip(num(s.d_min) === undefined ? undefined : `d_min ${num(s.d_min)} Å`),
        chip(num(s.elapsed_s) === undefined
          ? undefined : `${(num(s.elapsed_s) as number).toFixed(0)} s`),
      ),
    }),
  },
  solve_superflip: {
    running: () => "正在用 Superflip 求解…",
    done: (s) => {
      const sym = isObj(s.symmetry_agreement) ? s.symmetry_agreement : {};
      const overall = num(sym.overall);
      // >~0.25 means the model density does NOT obey the assumed operators
      const bad = overall !== undefined && overall > 0.25;
      return {
        title: `Superflip 求解：R ${
          num(s.final_r_percent)?.toFixed(1) ?? "?"
        }% · ${num(s.n_peaks) ?? "?"} 个峰`,
        chips: chips(
          chip(overall === undefined ? undefined : `对称一致性 ${f2(overall)}`,
               bad ? "warn" : "ok"),
          chip(num(s.n_cycles) === undefined ? undefined : `${num(s.n_cycles)} 轮`),
        ),
        tone: bad ? "warn" : null,
        warn: bad
          ? "密度不遵守假定的对称算符，空间群存疑，先查对称再继续"
          : null,
      };
    },
  },
  run_shelxt: {
    running: () => "正在用 SHELXT 双空间求解…",
    done: (s) => {
      const sols = arr(s.solutions).filter(isObj);
      const best = sols[0] ?? {};
      const adopted = s.adopted === true;
      return {
        title: adopted
          ? `SHELXT 求解并采纳：${str(s.space_group) ?? "?"} · ${
              num(s.n_atoms) ?? "?"
            } 原子`
          : `SHELXT 求解：${sols.length} 个候选（未采纳）`,
        chips: chips(
          chip(num(best.r1) === undefined ? undefined : `R1 ${f4(num(best.r1))}`),
          chip(num(best.rweak) === undefined ? undefined : `Rweak ${f2(num(best.rweak))}`),
          chip(str(best.space_group) === undefined
            ? undefined : `最佳 ${str(best.space_group)}`),
        ),
        warn: adopted ? null : (str(s.note) ?? null),
      };
    },
  },
  interpret_peaks: {
    running: () => "正在把峰列表解释为原子…",
    done: (s) => {
      const counts = isObj(s.element_counts) ? s.element_counts : {};
      const comp = Object.entries(counts)
        .map(([el, n]) => `${el}${num(n) ?? ""}`)
        .join(" ");
      const unassigned = num(s.n_probable_unassigned_heavy_sites) ?? 0;
      return {
        title: `解释峰为原子：${num(s.n_atoms) ?? "?"} 个${comp ? `（${comp}）` : ""}`,
        chips: chips(
          chip(num(s.n_symmetry_ghosts_removed) === undefined
            ? undefined : `剔对称幽灵 ${num(s.n_symmetry_ghosts_removed)}`),
          chip(s.composition_known === false ? "组成未知" : undefined, "warn"),
        ),
        tone: unassigned > 0 ? "warn" : null,
        warn:
          unassigned > 0
            ? `${unassigned} 个疑似未指认重原子位，元素指认可能有误`
            : null,
      };
    },
  },

  // ---------------------------------------------------------------- symmetry
  screen_space_groups: {
    observe: true,
    running: () => "正在筛查候选空间群…",
    done: (s) => {
      const cands = arr(s.candidates).filter(isObj);
      const top = cands[0] ?? {};
      const est = isObj(s.e_statistics) ? s.e_statistics : {};
      const hint = str(est.hint);
      return {
        title: `空间群筛查：首选 ${str(top.space_group) ?? "?"}（${
          cands.length
        }/${num(s.n_candidates_total) ?? "?"} 候选）`,
        chips: chips(
          chip(hint === "centrosymmetric"
            ? "E 统计偏心"
            : hint === "non_centrosymmetric"
              ? "E 统计偏非心"
              : undefined),
          chip(str(s.laue_class_used)),
          chip(num(top.violation_rate) === undefined
            ? undefined : `违背率 ${((num(top.violation_rate) as number) * 100).toFixed(1)}%`),
        ),
        // the metric Laue class can exceed the true symmetry - the tool
        // says so in `note`; surface it instead of burying it in JSON
        warn: /METRIC|metric/.test(str(s.note) ?? "") ? (str(s.note) ?? null) : null,
      };
    },
  },
  audit_heavy_sites: {
    observe: true,
    running: () => "正在审计重原子位点…",
    done: (s) => {
      const readiness = isObj(s.readiness) ? s.readiness : {};
      const anomalous = isObj(s.anomalous) ? s.anomalous : {};
      const edge = anomalous.edge_at_lambda;
      const edgeList = Array.isArray(edge) ? strList(edge) : edge ? [String(edge)] : [];
      const blockers = strList(readiness.blockers);
      const ready = readiness.ready_for_r_vs_z === true;
      return {
        title: `重位点审计：${num(s.n_sites) ?? "?"} 个位点，R-vs-Z ${
          ready ? "可做" : "未就绪"
        }`,
        chips: chips(
          chip(edgeList.length > 0 ? `吸收边：${edgeList.join("/")}` : undefined),
          chip(blockers.length > 0 ? `阻碍 ${blockers.length}` : undefined),
          chip(num(anomalous.wavelength_A) !== undefined
            ? `λ ${num(anomalous.wavelength_A)} Å` : undefined),
        ),
        warn: !ready && blockers.length > 0 ? blockers.slice(0, 2).join("；") : null,
      };
    },
  },
  reflection_statistics: {
    observe: true,
    running: () => "正在统计反射数据…",
    done: (s) => {
      const merge = isObj(s.merge) ? s.merge : {};
      const est = isObj(s.e_statistics) ? s.e_statistics : {};
      const hint = str(est.hint);
      const centring = str(s.centring_implied_by_file);
      return {
        title: `反射统计：${str(s.laue_class) ?? "?"} 类，${
          num(merge.n_unique)?.toLocaleString() ?? "?"
        } 独立`,
        chips: chips(
          chip(num(merge.r_int) === undefined ? undefined : `Rint ${f4(num(merge.r_int))}`),
          chip(num(merge.completeness) === undefined
            ? undefined : `完整度 ${((num(merge.completeness) as number) * 100).toFixed(1)}%`),
          chip(num(est.mean_abs_e2_minus_1) === undefined
            ? undefined : `⟨|E²−1|⟩ ${(num(est.mean_abs_e2_minus_1) as number).toFixed(3)}`),
          chip(hint === "centrosymmetric"
            ? "E 统计偏心"
            : hint === "non_centrosymmetric"
              ? "E 统计偏非心"
              : undefined),
          chip(centring && centring !== "P" ? `文件含 ${centring} 心` : undefined),
          chip(arr(s.laue_scan).length > 0 ? `劳厄扫描 ${arr(s.laue_scan).length} 类` : undefined),
        ),
      };
    },
  },
  change_space_group: {
    running: (args) => `正在改用空间群 ${str(args.space_group) ?? ""}…`,
    done: (s) => {
      if (str(s.mode) === "atomless_declaration") {
        const merge = isObj(s.merge) ? s.merge : {};
        return {
          title: `声明空间群：${str(s.declared_space_group) ?? "?"}`,
          chips: chips(
            chip(num(merge.r_int) === undefined ? undefined : `Rint ${f4(num(merge.r_int))}`),
            chip(num(merge.n_unique) === undefined
              ? undefined : `${num(merge.n_unique)?.toLocaleString()} 独立`),
          ),
        };
      }
      const dropped = strList(s.dropped_metadata);
      const ops = arr(s.added_ops_verified).filter(isObj);
      return {
        title: `改换空间群：${str(s.old_space_group) ?? "?"} → ${
          str(s.new_space_group) ?? "?"
        }`,
        chips: chips(
          chip(num(s.n_atoms_before) !== undefined && num(s.n_atoms_after) !== undefined
            ? `原子 ${num(s.n_atoms_before)} → ${num(s.n_atoms_after)}`
            : undefined),
          chip(ops.length > 0 ? `新增算符 ${ops.length} 已验证` : undefined),
          chip(num(s.n_h_stripped) !== undefined && (num(s.n_h_stripped) as number) > 0
            ? `剥氢 ${num(s.n_h_stripped)}` : undefined),
        ),
        warn:
          dropped.length > 0
            ? `丢失会话状态：${dropped.join(" / ")}（需重建）`
            : (str(s.adp_note) ?? null),
      };
    },
  },
  ncs_audit: {
    observe: true,
    running: () => "正在审计赝对称（平移/反演假设）…",
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
          ? `赝对称审计：${best.k === "inversion" ? "反演" : "平移"}假设匹配 ${
              ((frac ?? 0) * 100).toFixed(0)
            }%`
          : "赝对称审计",
        chips: chips(
          chip(best && num(best.v.rmsd_A) !== undefined
            ? `rmsd ${(num(best.v.rmsd_A) as number).toFixed(3)} Å` : undefined),
          chip(rational ? "算符落在有理分数" : undefined, "warn"),
          chip(best ? str(best.v.operator) : undefined),
        ),
        tone: strong && rational ? "warn" : null,
        warn: strong && rational
          ? "强匹配 + 有理算符 = 可能漏了晶体学对称，先查对称/怀疑晶胞"
          : null,
      };
    },
  },
  assemble_asu: {
    running: () => "正在装配连贯的不对称单元…",
    done: (s) => {
      const ghosts = arr(s.ghost_suspects_remaining).filter(isObj);
      if (s.no_state_change === true && s.dry_run !== true) {
        return {
          title: `ASU 已连贯（${num(s.n_fragments) ?? "?"} 个碎片）`,
          tone: "ok",
        };
      }
      const plan = arr(s.dry_run === true ? s.plan : s.applied).filter(isObj);
      const before = num(s.n_detached_atoms_before) ?? num(s.n_detached_atoms);
      const after = num(s.n_detached_atoms_after);
      return {
        title:
          s.dry_run === true
            ? `ASU 装配预演：${plan.length} 步（离散原子 ${before ?? "?"}）`
            : `装配 ASU：${plan.length} 步，离散原子 ${before ?? "?"} → ${after ?? "?"}`,
        chips: chips(
          chip(num(s.n_atoms) === undefined ? undefined : `${num(s.n_atoms)} 原子`),
          chip(arr(s.occupancy_rescaled).length > 0
            ? `占据重标 ${arr(s.occupancy_rescaled).length}` : undefined),
        ),
        warn:
          ghosts.length > 0
            ? `仍有 ${ghosts.length} 个幽灵原子嫌疑：${ghosts
                .slice(0, 3)
                .map((g) => str(g.label) ?? "?")
                .join(" ")}`
            : null,
      };
    },
  },

  // ------------------------------------------------- refinement / twin state
  run_olex2: {
    running: () => "正在用 olex2.refine 独立复核…",
    done: (s) => {
      const r1 = num(s.r1_gt) ?? num(s.r1_console);
      const d = num(s.delta_r1_vs_session);
      const diverged = d !== undefined && Math.abs(d) > 0.01;
      return {
        title: `olex2 独立复核：R1 ${f4(r1) ?? "?"}`,
        chips: chips(
          chip(num(s.wr2) === undefined ? undefined : `wR2 ${f4(num(s.wr2))}`),
          chip(num(s.goof) === undefined ? undefined : `GooF ${f2(num(s.goof))}`),
          chip(d === undefined ? undefined : `与本会话差 ${d >= 0 ? "+" : ""}${f4(d)}`,
               diverged ? "warn" : "ok"),
        ),
        tone: diverged ? "warn" : null,
        warn: diverged ? (str(s.note) ?? null) : null,
      };
    },
  },
  set_weights: {
    running: () => "正在设置权重方案…",
    done: (s) => {
      const o = isObj(s.old) ? s.old : {};
      const n = isObj(s.new) ? s.new : {};
      return {
        title: `设置权重 WGHT：${f4(num(o.a)) ?? "?"}/${f4(num(o.b)) ?? "?"} → ${
          f4(num(n.a)) ?? "?"
        }/${f4(num(n.b)) ?? "?"}`,
        warn: str(s.warning) ?? null,
        tone: str(s.warning) !== undefined ? "warn" : null,
      };
    },
  },
  set_resolution_limit: {
    running: (args) =>
      args.d_min === null
        ? "正在移除分辨率截断…"
        : `正在设置分辨率截断 d_min ${str(args.d_min) ?? num(args.d_min) ?? ""}…`,
    done: (s) => ({
      title:
        s.removed === true
          ? "移除分辨率截断（恢复全分辨率）"
          : `分辨率截断：${str(s.shel) ?? "?"}`,
      chips: chips(chip(str(s.reason))),
    }),
  },
  set_z: {
    running: () => "正在设置 Z 值…",
    done: (s) => ({
      title: `设置 Z：${num(s.old_z) ?? "?"} → ${num(s.new_z) ?? "?"}（Z' ${
        num(s.z_prime)?.toFixed(2) ?? "?"
      }）`,
      chips: chips(
        chip(num(s.sg_order) === undefined ? undefined : `群阶 ${num(s.sg_order)}`),
        chip(str(s.reason)),
      ),
      warn: str(s.warning) ?? null,
      tone: str(s.warning) !== undefined ? "warn" : null,
    }),
  },
  model_disorder: {
    running: (args) =>
      str(args.undo) !== undefined
        ? `正在撤销无序拆分（${str(args.undo)}）…`
        : `正在拆分无序位点${strList(args.atoms).length > 0
          ? `（${strList(args.atoms).slice(0, 4).join(" ")}）` : ""}…`,
    done: (s) => {
      if (str(s.undone) !== undefined) {
        const merged = arr(s.merged).filter(isObj);
        const gone = strList(s.deleted_atoms);
        return {
          title: `撤销无序拆分 ${str(s.undone)}：${merged.length} 对合并回单一位点`,
          chips: chips(
            chip(gone.length > 0 ? `删除 ${gone.slice(0, 4).join(" ")}` : undefined),
            chip(num(s.n_atoms) === undefined ? undefined : `${num(s.n_atoms)} 原子`),
            chip(isObj(s.fvar_renumbered) ? "FVAR 重新编号" : undefined),
          ),
          warn: arr(s.restraints_pruned).length > 0
            ? `同时清理了 ${arr(s.restraints_pruned).length} 条指向被删原子的限制` : null,
        };
      }
      const split = arr(s.split).filter(isObj);
      const folded = split.filter((x) => str(x.note) !== undefined).length;
      return {
        title: `拆分无序：${split.length} 个位点（PART 1/2，占比待 SHELXL 精修判定）`,
        chips: chips(
          chip(num(s.occupancy_a) === undefined
            ? undefined : `A 占据 ${f2(num(s.occupancy_a))}（起始值）`),
          chip(num(s.fvar_index) === undefined
            ? undefined : `FVAR ${num(s.fvar_index)}`),
          chip(num(s.n_atoms) === undefined ? undefined : `${num(s.n_atoms)} 原子`),
          chip(isObj(s.restraint_suggestion) ? "附 SADI/SIMU 建议" : undefined),
        ),
        warn: folded > 0 ? `${folded} 个 B 位点经对称折算到胞内` : null,
      };
    },
  },
  set_twin: {
    running: (args) => {
      const law = str(args.law);
      return law === "suggest"
        ? "正在列举可能的孪晶定律…"
        : law === "remove"
          ? "正在移除孪晶设置…"
          : "正在设置孪晶定律…";
    },
    done: (s) => {
      if (arr(s.candidates).length > 0) {
        return {
          title: `孪晶定律候选：${arr(s.candidates).length} 条（未应用）`,
          chips: chips(chip("仅列举")),
        };
      }
      if (isObj(s.removed)) return { title: "移除孪晶设置" };
      if (s.no_state_change === true) return { title: "孪晶设置未改变" };
      const t = isObj(s.twin) ? s.twin : {};
      const basf = arr(t.basf).map((x) => num(x)).filter((x) => x !== undefined);
      return {
        title: `设置孪晶：${num(t.n) ?? 2} 组分`,
        chips: chips(
          chip(basf.length > 0
            ? `BASF ${basf.map((b) => (b as number).toFixed(3)).join(" ")}` : undefined),
          chip(arr(t.matrix).length === 9
            ? arr(t.matrix).slice(0, 9).map((x) => num(x)).join(" ") : undefined),
        ),
        warn: "孪晶激活期间 smtbx refine 不可用，精修走 run_shelxl",
      };
    },
  },
  set_adp: {
    running: () => "正在转换原子 ADP…",
    done: (s) => ({
      title: s.no_state_change === true ? "ADP 表示未改变" : `${s.mode === "anisotropic" ? "各向异性" : "各向同性"} ADP：${arr(s.atoms).length} 个原子`,
      chips: chips(chip("保留 AFIX 与孪晶")),
    }),
  },
  set_afix: {
    running: () => "正在更新刚体约束…",
    done: (s) => ({
      title: `刚体约束：${arr(s.groups).length} 组`,
      chips: chips(chip(isObj(s.group) ? `AFIX ${num(s.group.afix)}` : undefined)),
    }),
  },
  set_site_occupancy: {
    running: () => "正在设置单点占有率…",
    done: (s) => ({
      title: `${str(s.atom) ?? "原子"}：${s.mode === "free" ? "自由占有率" : "固定占有率"}`,
      chips: chips(chip(num(s.occupancy) === undefined ? undefined : `${s.mode === "free" ? "初值" : "占有率"} ${num(s.occupancy)?.toFixed(4)}`)),
    }),
  },
  invert_structure: {
    running: () => "正在反转结构手性…",
    done: (s) => ({
      title: `反转手性：${str(s.operation) ?? "?"} → ${str(s.space_group) ?? "?"}`,
      chips: chips(
        chip(num(s.n_atoms) === undefined ? undefined : `${num(s.n_atoms)} 原子`),
        chip(s.group_changed === true ? "空间群已变（对映体对）" : undefined, "warn"),
      ),
      warn: s.group_changed === true ? (str(s.note) ?? null) : null,
    }),
  },

  // ---------------------------------------------------------------- evidence
  audit_guest_evidence: {
    observe: true,
    running: () => "正在做客体三项检验…",
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
        title: `客体证据：支持 ${supports} · 反对/警示 ${against}${open > 0 ? ` · 未定 ${open}` : ""}`,
        chips: chips(
          chip(work === undefined || work >= 0.995 ? undefined : `工作占有率 ${work.toFixed(2)}`),
          chip(modeled === undefined ? undefined : `模型 ${modeled.toFixed(1)}e`),
          chip(expected === undefined ? undefined : `期望 ${expected.toFixed(1)}e`),
          chip(prior ? "受限制/共享变量约束" : undefined),
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
    running: () => "正在检索技能卡…",
    done: (s) => {
      const n = num(s.n_skills) ?? 0;
      const miss = isObj(s.near_misses_per_word);
      return {
        title: n === 0 ? "技能检索：无匹配" : `技能检索：${n} 张卡`,
        chips: chips(
          chip(
            arr(s.skills).length > 0
              ? strList(arr(s.skills).filter(isObj).map((x) => (x as Rec).name))
                  .slice(0, 3)
                  .join(" · ")
              : undefined,
          ),
        ),
        warn: miss ? "无卡同时命中全部关键词，已给出逐词近邻建议" : null,
      };
    },
  },
  read_skill: {
    observe: true,
    running: (args) => `正在读技能卡 ${str(args.name) ?? ""}…`,
    done: (s, args) => ({
      title: `读技能卡：${str(s.name) ?? str(args.name) ?? "?"}`,
      chips: chips(
        chip(num(s.n_chars_total) === undefined
          ? undefined : `${num(s.n_chars_total)?.toLocaleString()} 字符`),
        chip(s.truncated === true ? "已分页（需续读）" : undefined, "warn"),
      ),
    }),
  },
  set_investigation: {
    running: () => "正在记录研究目标与未试方向…",
    done: (s) => {
      const inv = isObj(s.investigation) ? s.investigation : {};
      const tiers = isObj(inv.tiers) ? inv.tiers : {};
      const unmet = strList(inv.unmet_tiers);
      const dirs = strList(inv.open_directions);
      const changed = strList(s.changed);
      const goal = str(inv.goal);
      const zh: Record<string, string> = { unmet: "未达", met: "已达", not_applicable: "不适用" };
      return {
        title: changed.length === 0 ? "研究目标：无新内容" : `研究目标已记录${goal ? `：${goal}` : ""}`,
        chips: chips(
          chip(`候选完整 ${zh[str(tiers.candidate_complete) ?? "unmet"] ?? "未达"}`),
          chip(`科学确立 ${zh[str(tiers.scientifically_established) ?? "unmet"] ?? "未达"}`),
          chip(num(inv.n_ruled_out) ? `已否决 ${num(inv.n_ruled_out)}` : undefined),
          chip(dirs.length > 0 ? `未试方向 ${dirs.length}` : undefined),
        ),
        tone: unmet.length > 0 && dirs.length === 0 && changed.length > 0 ? "warn" : "ok",
        warn: unmet.length > 0 && dirs.length === 0 && changed.length > 0
          ? "有未达层级但没有记录未试方向"
          : null,
      };
    },
  },
  save_skill: {
    running: (args) => `正在保存技能卡 ${str(args.name) ?? ""}…`,
    done: (s) => ({
      title: `${str(s.action) === "updated" ? "更新" : "新建"}技能卡：${
        str(s.saved) ?? "?"
      }`,
      chips: chips(chip(str(s.reason))),
    }),
  },
  delete_skill: {
    running: (args) => `正在删除技能卡 ${str(args.name) ?? ""}…`,
    done: (s) => ({
      title: `删除技能卡：${str(s.deleted) ?? "?"}`,
      chips: chips(chip(str(s.reason)), chip("可从 git 历史恢复")),
    }),
  },

  // --- vision: the pictures the model looked at, shown to the user too ---
  view_structure: {
    running: (args) => {
      const st = str(args.state) ?? "asu";
      return `正在渲染结构图（${stateZh[st] ?? st}）…`;
    },
    done: (s, args) => {
      const st = str(s.state) ?? str(args.state) ?? "asu";
      const views = strList(s.views).map((v) => viewZh[v] ?? v);
      const n = num(s.n_atoms_drawn);
      const hi = strList(args.highlight);
      return {
        title: `看结构：${stateZh[st] ?? st}${
          views.length > 0 ? `（${views.join(" / ")}）` : ""
        }`,
        chips: chips(
          chip(n === undefined ? undefined : `${n} 原子`),
          chip(hi.length > 0 ? `标记 ${hi.slice(0, 4).join(" ")}` : undefined),
        ),
        body: viewStrip(s.images, stateZh[st]),
      };
    },
  },
  situation_report: {
    running: () => "正在汇总全局现状（数据 / 模型 / 轨迹 / 交叉证据）…",
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
            ? `全局现状：${conflicts.length} 处证据冲突`
            : "全局现状综述",
        tone: conflicts.length > 0 ? "warn" : null,
        chips: chips(
          chip(r1 === undefined ? undefined : `R1 ${f4(r1)}`),
          chip(
            compl === undefined
              ? undefined
              : `完整度 ${(compl * (compl <= 1 ? 100 : 1)).toFixed(1)}%`,
          ),
          chip(nAtoms === undefined ? undefined : `${nAtoms} 原子`),
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
    running: () => "正在查看节点列表…",
    done: () => ({ title: "查看节点列表" }),
  },
  compare_nodes: {
    observe: true,
    running: () => "正在对比节点…",
    done: (_s, args) => {
      const a = str(args.a);
      const b = str(args.b);
      return {
        title: `对比节点${a !== undefined && b !== undefined ? ` ${a} ↔ ${b}` : ""}`,
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
      title: `${prefix}：A×${a} · B×${b} · C×${c}`,
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
      title: `${prefix}：${parts.length > 0 ? parts.join(" · ") : "已完成"}`,
      tone: sc.A > 0 ? "danger" : sc.B > 0 ? "warn" : null,
      warn:
        salvaged.partial
          ? "结果尾部被截断，仅恢复部分警报；完整列表见右侧「验证」页"
          : null,
    };
  }
  return { title: `${prefix} 完成（结果不可解析，见「验证」页）` };
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
      chip(s?.node !== undefined ? `节点 ${s.node}` : undefined),
      chip(s?.r1 !== undefined ? `R1 ${s.r1.toFixed(4)}` : undefined),
      chip(s?.wr2 !== undefined ? `wR2 ${s.wr2.toFixed(4)}` : undefined),
      chip(s?.goof !== undefined ? `GooF ${s.goof.toFixed(2)}` : undefined),
      chip(s?.nAtoms !== undefined ? `${s.nAtoms} 原子` : undefined),
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
      warn: item.status === "no_result" ? zh.toolNoResult : zh.toolInterrupted,
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
      (item.summary?.ok === false ? "工具返回 ok=false" : "失败");
    // defensive refusals state that the model was left untouched - they are
    // "the guard worked", not a crash; tone them amber, not red
    const refusal =
      /Re-run |rejected|refused|no model change|未改变模型|not applied/i.test(
        msg,
      );
    return {
      title: def?.running ? def.running(args).replace(/^正在|…$/g, "") : item.tool,
      chips: refusal ? [{ text: "已拒绝执行，模型未改动", tone: "warn" }] : [],
      warn: firstLine(msg),
      observe: false,
      tone: refusal ? "warn" : "danger",
      body: null,
      detail: null,
    };
  }

  if (item.status === "running") {
    return {
      title: def?.running ? def.running(args) : `正在运行 ${item.tool}…`,
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
