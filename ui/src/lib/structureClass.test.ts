/** Structure-class suggestion: each branch fires on the evidence it names,
 * and the section gate never hides a framework's nets or a cage's fragments. */
import { describe, expect, it } from "vitest";
import {
  isStructureClass,
  sectionsFor,
  suggestStructureClass,
} from "./structureClass";
import type { AnalysisResponse, FiniteFragment } from "./wbTypes";

function frag(
  fragment: string,
  n: number,
  role: "host" | "guest",
  ring: number | null,
  sphericity: number | null,
): FiniteFragment {
  return {
    fragment,
    asu_labels: ["C1"],
    n_atoms: n,
    copies: 1,
    role,
    largest_cycle: { size: ring, truncated: false, n_cycles_basis: ring ? 1 : 0, atoms: [] },
    shape: sphericity === null ? null : { sphericity },
  };
}

function product(over: Partial<AnalysisResponse>): AnalysisResponse {
  const base = {
    v: 4,
    voids_v: 4,
    node: "n0001",
    interactions: {} as AnalysisResponse["interactions"],
    pores: {} as AnalysisResponse["pores"],
    guests: null,
    topology: {
      nets: {
        n_nets: 0,
        nets: [],
        relations: [],
        interpenetrated: false,
        interlocked_1d: false,
        definition: "",
        host: { fragments: [], selection_rule: "" },
        notes: [],
      },
      simplified_net: {
        nodes: [],
        edges: [],
        n_nodes_per_cell: 0,
        n_edges_per_cell: 0,
        node_connectivity_histogram: {},
        linkers: [],
        definition: "",
        rcsr_symbol: null,
        rcsr_status: "未算",
      },
      helices: [],
      finite_fragments: [],
    },
  } as AnalysisResponse;
  return { ...base, ...over };
}

describe("suggestStructureClass", () => {
  it("a periodic net is a framework, interpenetration noted", () => {
    const d = product({});
    d.topology!.nets = {
      ...d.topology!.nets,
      n_nets: 2,
      nets: [
        { id: 1, dimensionality: 3, n_atoms_p1: 24, asu_labels: [], direction: null },
        { id: 2, dimensionality: 3, n_atoms_p1: 24, asu_labels: [], direction: null },
      ],
      interpenetrated: true,
    };
    const s = suggestStructureClass(d);
    expect(s.cls).toBe("framework");
    expect(s.basis).toEqual(["2 个周期网（维度 3/3）", "互穿多网（环穿越判定）"]);
  });

  it("a big round host with a ring is a cage (the Zr3 cage numbers)", () => {
    const d = product({});
    d.topology!.finite_fragments = [frag("F1", 91, "host", 8, 0.81), frag("F3", 6, "guest", 5, 0.12)];
    const s = suggestStructureClass(d);
    expect(s.cls).toBe("cage");
    expect(s.basis[0]).toContain("F1：91 原子、球形度 0.81");
  });

  it("a ≥ 12-membered chordless ring host is a macrocycle", () => {
    const d = product({});
    d.topology!.finite_fragments = [frag("F1", 48, "host", 24, 0.31)];
    expect(suggestStructureClass(d).cls).toBe("macrocycle");
  });

  it("two sizeable fragments with a guest / counter-ion read as salt or cocrystal (dbu)", () => {
    const d = product({
      guests: {
        guests: [{}],
        summary: { channel: 1 },
        host: { fragments: [], selection_rule: "" },
        criteria: {},
        grid_step_A: 0.5,
        probe_A: 1.2,
      } as unknown as AnalysisResponse["guests"],
    });
    d.topology!.finite_fragments = [frag("F1", 37, "host", 6, 0.43), frag("F2", 18, "guest", 5, 0.5)];
    const s = suggestStructureClass(d);
    expect(s.cls).toBe("salt_cocrystal");
    expect(s.basis[0]).toContain("2 种 ≥ 4 原子");
  });

  it("one molecule, no net: small molecule (nm)", () => {
    const d = product({});
    d.topology!.finite_fragments = [frag("F1", 37, "host", 6, 0.43)];
    const s = suggestStructureClass(d);
    expect(s.cls).toBe("small_molecule");
    expect(s.basis[0]).toContain("单一分子片段 F1（37 原子）");
  });

  it("no topology block at all still answers", () => {
    expect(suggestStructureClass(product({ topology: null })).cls).toBe("small_molecule");
  });
});

describe("sectionsFor", () => {
  it("frameworks show the nets, molecules do not, nothing loses its fragments", () => {
    expect(sectionsFor("framework").has("nets")).toBe(true);
    expect(sectionsFor("framework").has("simplified_net")).toBe(true);
    expect(sectionsFor("small_molecule").has("nets")).toBe(false);
    expect(sectionsFor("cage").has("simplified_net")).toBe(false);
    for (const c of ["small_molecule", "macrocycle", "cage", "framework", "salt_cocrystal"] as const) {
      expect(sectionsFor(c).has("fragments")).toBe(true);
      expect(sectionsFor(c).has("interactions")).toBe(true);
    }
    expect(sectionsFor("salt_cocrystal").has("guests")).toBe(true);
  });
  it("validates class strings", () => {
    expect(isStructureClass("cage")).toBe(true);
    expect(isStructureClass("blob")).toBe(false);
    expect(isStructureClass(null)).toBe(false);
  });
});
