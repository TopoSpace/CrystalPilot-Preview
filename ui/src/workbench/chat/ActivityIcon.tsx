import type { ActivityGlyph } from "../../lib/activityIcons";
import {
  IconSolve, IconRefine, IconDensity, IconSymmetry, IconMolecule, IconGeometry,
  IconValidation, IconDiffraction, IconIndexing, IconIntegration, IconChart, IconBranch, IconCompare,
  IconBook, IconSearch, IconGlobe, IconList, IconActivityGroup, IconFile, IconFolder,
  IconPencil, IconDownload, IconSend, IconFocus, IconUser, IconCrystal, IconTerminal, IconTool,
} from "../icons";

const GLYPHS = {
  solve: IconSolve, refine: IconRefine, density: IconDensity, symmetry: IconSymmetry,
  molecule: IconMolecule, geometry: IconGeometry, validation: IconValidation,
  diffraction: IconDiffraction, indexing: IconIndexing, integration: IconIntegration,
  chart: IconChart, branch: IconBranch, compare: IconCompare,
  book: IconBook, search: IconSearch, globe: IconGlobe, list: IconList, group: IconActivityGroup,
  file: IconFile, folder: IconFolder, edit: IconPencil, download: IconDownload,
  delivery: IconSend, view: IconFocus, user: IconUser, crystal: IconCrystal,
  terminal: IconTerminal, tool: IconTool,
} satisfies Record<ActivityGlyph, typeof IconTool>;

export function ActivityIcon({ kind, scientific = false }: { kind: ActivityGlyph; scientific?: boolean }) {
  const Icon = GLYPHS[kind];
  return <Icon size={17} data-activity-icon={kind} className={scientific ? "research-glyph" : undefined} />;
}
