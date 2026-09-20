/** Structure class (owner's ask, 2026-09-04): the analysis tab shows the
 * blocks that make sense for WHAT the crystal is - a framework gets nets /
 * interpenetration / channels, a cage gets its cavity and shape evidence,
 * a macrocycle its largest ring, a salt its ions and hydrogen bonds - so
 * the pane is not a wall of every table for every crystal.
 *
 * The class is the user's declaration (a project setting). When none is
 * set, `suggestStructureClass` proposes one from the analysis product
 * WITH the evidence it used, and the user confirms; nothing is ever
 * hidden without a way to show it (`sectionsFor` only chooses what is
 * open by default; the panel keeps a 显示全部 toggle). */
import type { AnalysisResponse } from "./wbTypes";
import { t } from "./i18n";

export const STRUCTURE_CLASSES = [
  "small_molecule",
  "macrocycle",
  "cage",
  "framework",
  "salt_cocrystal",
] as const;
export type StructureClass = (typeof STRUCTURE_CLASSES)[number];

export function isStructureClass(v: unknown): v is StructureClass {
  return typeof v === "string" && (STRUCTURE_CLASSES as readonly string[]).includes(v);
}

export function structureClassLabel(cls: StructureClass | null): string {
  return cls === null ? t.scAuto : (t.scClasses[cls] ?? cls);
}

export type SectionId =
  | "interactions"
  | "pores"
  | "packing"
  | "guests"
  | "nets"
  | "simplified_net"
  | "helices"
  | "fragments";

export const ALL_SECTIONS: readonly SectionId[] = [
  "interactions",
  "pores",
  "packing",
  "guests",
  "nets",
  "simplified_net",
  "helices",
  "fragments",
];

/** Sections open by default for a class. A framework is the only class for
 * which the net descriptions mean anything; cages and macrocycles are about
 * their finite fragments, cavities and what sits inside; a salt is about its
 * ions and their hydrogen bonds. */
export function sectionsFor(cls: StructureClass): Set<SectionId> {
  switch (cls) {
    case "framework":
      return new Set(ALL_SECTIONS);
    case "cage":
      return new Set(["interactions", "pores", "packing", "guests", "fragments"]);
    case "macrocycle":
      return new Set(["interactions", "pores", "packing", "guests", "fragments"]);
    case "salt_cocrystal":
      return new Set(["interactions", "packing", "guests", "fragments", "pores"]);
    case "small_molecule":
    default:
      return new Set(["interactions", "pores", "packing", "fragments"]);
  }
}

export interface ClassSuggestion {
  cls: StructureClass;
  /** the evidence the suggestion rests on, in the user's language */
  basis: string[];
}

/** Thresholds of the suggestion, named so the basis text can quote them. */
export const CAGE_MIN_ATOMS = 40;
export const CAGE_MIN_SPHERICITY = 0.7;
export const CAGE_MIN_RING = 8;
export const MACROCYCLE_MIN_RING = 12;
export const ION_MIN_ATOMS = 4;

/** Propose a class from the analysis product. Order of evidence: a periodic
 * net (any dimensionality ≥ 1) makes a framework; a large, round host
 * fragment with a ring is a cage; a host with a ≥ 12-membered chordless ring
 * is a macrocycle; two or more sizeable independent fragments with at least
 * one classed as a guest / counter-ion is a salt or cocrystal; else a small
 * molecule. Every branch says what it saw. */
export function suggestStructureClass(d: AnalysisResponse): ClassSuggestion {
  const basis: string[] = [];
  const top = d.topology;
  const nets = top?.nets;
  if (nets && nets.n_nets > 0) {
    const dims = nets.nets.map((n) => n.dimensionality).join("/");
    basis.push(t.libs.scBasisNets(nets.n_nets, dims));
    if (nets.interpenetrated === true) basis.push(t.libs.scBasisInterpenetrated);
    else if (nets.symmetry_related) basis.push(nets.interpenetrated === false ? t.libs.scBasisSymRelatedNot : t.libs.scBasisSymRelatedUnknown);
    return { cls: "framework", basis };
  }
  const frags = top?.finite_fragments ?? [];
  const hosts = frags.filter((f) => f.role === "host");
  const big = hosts[0] ?? frags[0];
  if (big) {
    const ring = big.largest_cycle.size ?? 0;
    const sph = big.shape?.sphericity ?? null;
    if (
      big.n_atoms >= CAGE_MIN_ATOMS &&
      sph !== null &&
      sph >= CAGE_MIN_SPHERICITY &&
      ring >= CAGE_MIN_RING
    ) {
      basis.push(t.libs.scBasisCage(big.fragment, big.n_atoms, sph.toFixed(2), CAGE_MIN_SPHERICITY, ring));
      return { cls: "cage", basis };
    }
    if (ring >= MACROCYCLE_MIN_RING) {
      basis.push(t.libs.scBasisMacrocycle(big.fragment, ring, MACROCYCLE_MIN_RING));
      return { cls: "macrocycle", basis };
    }
  }
  const sizeable = frags.filter((f) => f.n_atoms >= ION_MIN_ATOMS);
  const nGuests = d.guests?.guests.length ?? 0;
  if (sizeable.length >= 2 && nGuests >= 1) {
    basis.push(t.libs.scBasisSalt(sizeable.length, ION_MIN_ATOMS, nGuests));
    return { cls: "salt_cocrystal", basis };
  }
  basis.push(big ? t.libs.scBasisSingle(big.fragment, big.n_atoms) : t.libs.scBasisNothing);
  return { cls: "small_molecule", basis };
}
