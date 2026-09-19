/** Interaction rows as text: the label line, the geometry lines and the
 * quote-to-chat wording. Pure functions shared by the viewer card and the
 * composer quote so the two can never disagree. The wording cites atom
 * LABELS and the symmetry operator, never a viewer-local ordinal. */
import type { SceneInteractions, UniqueInteractionRow } from "./wbTypes";

/** A display row (viewer) or a canonical row (analysis product): the
 * canonical one has no `sym` / `boundary` - its operator is `op`. */
export type InteractionRowLike = UniqueInteractionRow;
import { zh } from "./zh";

const IDENTITY = "x,y,z";

export function isIdentityOp(op: string | undefined | null): boolean {
  return (op ?? IDENTITY).replace(/\s+/g, "") === IDENTITY;
}

function num(v: unknown, digits: number): string | null {
  return typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : null;
}

/** "O1–H1···O2", "C3–H3···Cg(C1..C6)", "Cg(A) ⋯ Cg(B)" */
export function interactionLabel(row: InteractionRowLike): string {
  switch (row.kind) {
    case "hbond":
      return `${row.d ?? "?"}–${row.h ?? "?"}···${row.a ?? "?"}`;
    case "chx":
      // the engine files the C-H carrier under `d` (it is the donor of the
      // kind, like an N/O donor is for a hydrogen bond); `c` is the halogen /
      // C-H...pi carrier key
      return `${row.c ?? row.d ?? "?"}–${row.h ?? "?"}···${row.a ?? "?"}`;
    case "halogen":
      return `${row.c ?? "?"}–${row.x ?? "?"}···${row.a ?? "?"}`;
    case "pipi":
      return `环 ${row.ring_a ?? "?"} ⋯ 环 ${row.ring_b ?? "?"}`;
    case "chpi":
      return `${row.c ?? "?"}–${row.h ?? "?"}···环 ${row.ring ?? "?"}`;
    case "anion_pi":
      return `${row.anion_name ?? row.anion ?? "阴离子"} ··· 环 ${row.ring ?? "?"}`;
    default:
      return row.kind;
  }
}

/** [name, value] pairs of the kind's own geometry, in reading order. */
export function interactionGeometry(row: InteractionRowLike): [string, string][] {
  const out: [string, string][] = [];
  const push = (name: string, v: unknown, digits = 2, unit = " Å"): void => {
    const s = num(v, digits);
    if (s !== null) out.push([name, `${s}${unit}`]);
  };
  switch (row.kind) {
    case "hbond":
      push("D···A", row.d_DA);
      if (row.status) {
        out.push(["H", zh.ixHSource.absent]);
      } else {
        push("H···A", row.d_HA);
        push("∠D–H···A", row.angle, 1, "°");
      }
      break;
    case "chx":
      push("C···A", row.d_DA);
      push("H···A", row.d_HA);
      push("∠C–H···A", row.angle, 1, "°");
      break;
    case "halogen":
      push("X···A", row.d_XA);
      push("∠C–X···A", row.angle, 1, "°");
      break;
    case "pipi":
      push("质心距", row.d_cc);
      push("法线夹角 α", row.alpha, 1, "°");
      out.push(["垂直距离 a→b / b→a",
        `${num(row.d_perp_ab, 2) ?? "—"} / ${num(row.d_perp_ba, 2) ?? "—"} Å`]);
      out.push(["滑移 a→b / b→a",
        `${num(row.slip_ab, 2) ?? "—"} / ${num(row.slip_ba, 2) ?? "—"} Å`]);
      break;
    case "chpi":
      push("H···Cg", row.d_HCg);
      push("垂直距离", row.d_perp);
      push("偏移", row.offset);
      push("∠C–H···Cg", row.angle, 1, "°");
      break;
    case "anion_pi":
      push("质心距", row.d_cc);
      push("垂直距离", row.d_perp);
      push("偏移", row.offset);
      if (row.strength) out.push(["强度", String(row.strength)]);
      break;
    default:
      push("d", row.dist);
  }
  return out;
}

/** One line naming the rule set and its thresholds, from the echoed
 * criteria block ("olex2: D···A ≤ 2.9 Å, ∠ ≥ 150°"). */
export function criteriaSummary(
  crit: Record<string, unknown> | undefined,
): string {
  if (!crit) return "";
  const parts: string[] = [];
  for (const [k, v] of Object.entries(crit)) {
    // thresholds carry a unit suffix; the block's other numbers are
    // diagnostics (counts of polar atoms, fallback uses) and stay off the line
    if (typeof v !== "number") continue;
    const unit = k.endsWith("_A") ? " Å" : k.endsWith("_deg") ? "°" : null;
    if (unit === null) continue;
    parts.push(`${k.replace(/_(A|deg)$/, "")} ${v}${unit}`);
  }
  const set = typeof crit.set === "string" ? crit.set : "";
  return `${set}${set && parts.length ? ": " : ""}${parts.join("、")}`;
}

/** Quote-to-chat text for one interaction row. */
export function interactionQuote(
  row: InteractionRowLike,
  meta: Pick<SceneInteractions, "h_source" | "criteria">,
): string {
  const kind = zh.ixKind[row.kind] ?? row.kind;
  const opStr = row.sym ?? row.op;
  const sym = isIdentityOp(opStr) ? "" : `（${zh.ixSymop} ${opStr}）`;
  const geom = interactionGeometry(row)
    .map(([n, v]) => `${n} ${v}`)
    .join("、");
  const crit = criteriaSummary(meta.criteria[row.kind]);
  const verdict = row.passes ? "满足" : "不满足";
  const hNote =
    (row.kind === "hbond" || row.kind === "chx" || row.kind === "chpi")
    && (meta.h_source === "riding" || meta.h_source === "mixed")
      ? `；${zh.ixHSource[meta.h_source]}`
      : "";
  const boundary = row.boundary ? `；${zh.ixBoundary}` : "";
  const intra = row.intra ? `（${zh.anIntra}）` : "";
  const tail =
    row.kind === "hbond"
      ? "这条氢键合理吗？要不要进 HTAB 表？"
      : "这条相互作用可信吗？对堆积的解释有什么影响？";
  return `${kind} ${interactionLabel(row)}${sym}${intra}：${geom}；${verdict}${crit ? ` ${crit} ` : ""}判据${hNote}${boundary}。${tail}`;
}
