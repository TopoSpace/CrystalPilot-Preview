/** Asymmetric-unit formula in Hill order, occupancy-weighted.
 *
 * Counting atoms instead of summing occupancies shows a two-position
 * disorder twice (reg10-dbu, 2026-09-05: the identity bar said C18H24N4O6
 * while the CIF's _chemical_formula_sum is C16H20N4O6 - C14/C15 and their
 * H are split 0.71:0.29 over two PARTs). Only identity-operator atoms are
 * counted, so the line stays the ASU's content in every display mode.
 * Fractional totals (a site on a special position at sof 0.5, an
 * under-occupied solvent) are shown with two decimals rather than rounded
 * away - they are what the model says. */
export interface FormulaTerm {
  elem: string;
  count: number;
}

export function hillFormula(
  atoms: ReadonlyArray<{ elem: string; occ?: number; sym?: boolean }>,
): FormulaTerm[] | null {
  const n = new Map<string, number>();
  for (const a of atoms) {
    if (a.sym) continue;
    const occ = typeof a.occ === "number" && Number.isFinite(a.occ) ? a.occ : 1;
    n.set(a.elem, (n.get(a.elem) ?? 0) + occ);
  }
  if (n.size === 0) return null;
  const rest = [...n.keys()].filter((e) => e !== "C" && e !== "H").sort();
  const order = [...(n.has("C") ? ["C"] : []), ...(n.has("H") ? ["H"] : []), ...rest];
  return order.map((e) => ({ elem: e, count: Math.round((n.get(e) as number) * 100) / 100 }));
}

/** `16`, or `0.5` - never `16.00`. */
export function formulaCount(count: number): string {
  return Number.isInteger(count) ? String(count) : count.toFixed(2).replace(/0+$/, "");
}
