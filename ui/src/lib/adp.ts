/** ADP anomaly detection for the ellipsoid-anomaly overlay (调研 P0-3).
 *
 * Thresholds mirror the engine's refine ADP audit
 * (crystalpilot/tools/refinement_tools.py: u_eq < 0.002 / > 0.20) plus the
 * classic prolate/oblate axis-ratio hint used to spot "wrong element or
 * unsplit disorder" ellipsoids (cigar/pancake, ratio > 4). Display-level
 * only - flags never mutate the model.
 */
import type { SceneAtom } from "./wbTypes";

export const U_EQ_MIN = 0.002;
export const U_EQ_MAX = 0.2;
export const AXIS_RATIO_MAX = 4;

export interface AdpAnomaly {
  index: number;
  atom: SceneAtom;
  reasons: string[];
}

/** Reasons an atom's displacement looks pathological; [] = healthy. */
export function adpReasons(a: SceneAtom): string[] {
  if (a.adp_known === false || a.u_eq === null || a.elem === "H" || a.flag === "removed") return [];
  const out: string[] = [];
  if (a.ell?.npd) out.push("ADP 非正定（NPD）");
  const r = a.ell?.r;
  if (r && r[2] > 1e-4) {
    const ratio = r[0] / r[2];
    if (ratio > AXIS_RATIO_MAX) {
      out.push(`椭球轴比 ${ratio.toFixed(1)}：疑未拆无序或元素指认错误`);
    }
  }
  if (a.u_eq > U_EQ_MAX) {
    out.push(`U_eq ${a.u_eq.toFixed(3)} 过大：需核对占有率、无序和元素指认`);
  } else if (a.u_eq < U_EQ_MIN) {
    out.push(`U_eq ${a.u_eq.toFixed(4)} 过小：需核对元素指认、数据与标度`);
  }
  return out;
}

/** Anomalies over the asymmetric-unit originals (symmetry copies would
 * duplicate every flag; the shell renders on the original). */
export function adpAnomalies(atoms: SceneAtom[]): AdpAnomaly[] {
  const out: AdpAnomaly[] = [];
  atoms.forEach((a, index) => {
    if (a.sym) return;
    const reasons = adpReasons(a);
    if (reasons.length > 0) out.push({ index, atom: a, reasons });
  });
  return out;
}
