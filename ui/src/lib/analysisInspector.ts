import type {
  InteractionKind,
  InteractionRow,
  SceneResponse,
  UniqueInteractionRow,
} from "./wbTypes";

interface SceneSelection {
  atom: SceneResponse["atoms"][number];
  index: number;
}

const IDENTITY_FIELDS = [
  "d",
  "h",
  "a",
  "c",
  "x",
  "ring",
  "ring_a",
  "ring_b",
  "anion",
  "anion_name",
  "h_seq",
  "c_seq",
] as const;

const normalizeOp = (value: unknown): string =>
  typeof value === "string" ? value.replace(/\s+/g, "") : "";

const fieldValue = (row: UniqueInteractionRow, field: (typeof IDENTITY_FIELDS)[number]): string => {
  const value = row[field];
  return value === null || value === undefined ? "" : String(value);
};

/** Stable scientific identity shared by canonical and display interaction rows. */
export function interactionIdentity(row: UniqueInteractionRow): string {
  // Identity comes from the engine's labels/operator, not a guessed geometry
  // tolerance. Scene rows omit i_seq/j_seq but retain donor/ring and H keys.
  return JSON.stringify([
    row.kind,
    normalizeOp(row.op),
    ...IDENTITY_FIELDS.map((field) => fieldValue(row, field)),
  ]);
}

export interface InteractionInstance {
  sym_i: string;
  sym: string;
}

export function sameInteractionInstance(a: InteractionInstance, b: InteractionInstance): boolean {
  return normalizeOp(a.sym_i) === normalizeOp(b.sym_i) && normalizeOp(a.sym) === normalizeOp(b.sym);
}

export interface RenderedInteractionMatch {
  row: InteractionRow;
  /** Exact scene atom instance at one endpoint, never an ASU substitute. */
  atomIndex: number | null;
}

/**
 * Resolve a symmetry-unique analysis row to one of its genuinely rendered
 * instances. Several translated instances may represent the same canonical
 * row; prefer a complete segment, then a boundary segment with a real atom.
 */
export function findRenderedInteraction(
  scene: SceneResponse | null,
  target: UniqueInteractionRow,
  instance?: InteractionInstance,
): RenderedInteractionMatch | null {
  const rows = scene?.interactions?.rows;
  if (!rows) return null;
  const identity = interactionIdentity(target);
  const matches = rows.filter((row) => interactionIdentity(row) === identity
    && (!instance || sameInteractionInstance(row, instance)));
  matches.sort((a, b) => Number(a.boundary) - Number(b.boundary));
  for (const row of matches) {
    // Prefer the actual partner, which may be a translated symmetry copy.
    // A centroid-only segment has no atom index; do not invent one.
    for (const index of [row.bi, row.ai]) {
      if (typeof index === "number" && scene.atoms[index] !== undefined
        && scene.atoms[index].flag !== "removed") {
        return { row, atomIndex: index };
      }
    }
  }
  return matches[0] ? { row: matches[0], atomIndex: null } : null;
}

/** Re-find the exact selected scene instance after a range/layer refresh. */
export function exactSelectionInScene(
  scene: SceneResponse,
  selection: SceneSelection | null,
): SceneSelection | null {
  if (!selection) return null;
  const wanted = selection.atom;
  const wantedOp = normalizeOp(wanted.symop);
  const index = scene.atoms.findIndex((atom) => {
    if (atom.flag === "removed" || atom.label !== wanted.label || atom.part !== wanted.part) return false;
    if (wanted.sym) return wantedOp !== "" && atom.sym === true && normalizeOp(atom.symop) === wantedOp;
    return atom.sym !== true;
  });
  return index < 0 ? null : { atom: scene.atoms[index], index };
}

export type InteractionOverlay =
  | "hbonds"
  | "ixPipi"
  | "ixChpi"
  | "ixChx"
  | "ixHalogen"
  | "ixAnionPi";

export function overlayForInteraction(kind: InteractionKind): InteractionOverlay {
  switch (kind) {
    case "hbond":
      return "hbonds";
    case "pipi":
      return "ixPipi";
    case "chpi":
      return "ixChpi";
    case "chx":
      return "ixChx";
    case "halogen":
      return "ixHalogen";
    case "anion_pi":
      return "ixAnionPi";
  }
}
