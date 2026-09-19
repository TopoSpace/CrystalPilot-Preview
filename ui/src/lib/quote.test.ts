/** Quote-to-chat wording. These strings go into the composer and are read
 * by an agent that cannot see the viewer, so the assertions are about what
 * survives the trip: the numbers, the symmetry operator, and NOT the
 * viewer-local ordinals. */
import { describe, expect, it } from "vitest";
import {
  alertQuote,
  anchor,
  fragmentQuote,
  parseAnchor,
  topologyQuote,
  withAnchor,
  atomQuote,
  checkcifQuote,
  frameQuote,
  measureQuote,
  peakQuote,
  structureQuote,
  guestQuote,
  poreQuote,
  voidQuote,
} from "./quote";
import type { PeakEntry, SceneAtom } from "./wbTypes";

function atom(over: Partial<SceneAtom> = {}): SceneAtom {
  return {
    label: "C11",
    elem: "C",
    xyz: [0, 0, 0],
    occ: 1,
    u_eq: 0.0412,
    sym: false,
    ...over,
  } as SceneAtom;
}

describe("atomQuote", () => {
  it("keeps missing ADPs unknown and asks geometry-only questions for CIF documents", () => {
    const q = atomQuote(atom({ adp_known: false, u_eq: null }), [], "n0000", true);
    expect(q).toContain("ADP 未报告");
    expect(q).not.toContain("U_eq 0");
    expect(q).not.toContain("差值密度");
    expect(q).toContain("无观测反射数据");
  });

  it("carries the numbers the card showed", () => {
    const q = atomQuote(atom());
    expect(q).toContain("C11");
    expect(q).toContain("0.0412");
    // full occupancy is the default; saying so is noise
    expect(q).not.toContain("占有率");
  });

  it("mentions occupancy and PART only when they are not the default", () => {
    const q = atomQuote(atom({ occ: 0.53, part: 2 }));
    expect(q).toContain("0.530");
    expect(q).toContain("PART 2");
  });

  it("names the symmetry operator for a symmetry copy", () => {
    const q = atomQuote(atom({ sym: true, symop: "1-x, -y, 1-z" }));
    expect(q).toContain("对称拷贝");
    expect(q).toContain("1-x, -y, 1-z");
  });

  it("turns ADP flags into the question they raise", () => {
    const q = atomQuote(atom({ u_eq: 0.21 }), ["U_eq 是同元素中位数的 3.1 倍"]);
    expect(q).toContain("3.1 倍");
    expect(q).toContain("无序");
    // the previous quote was "查看 C11 附近的密度与配位" and dropped every
    // reason the user had for clicking
    expect(q).not.toBe("查看 C11 附近的密度与配位");
  });
});

describe("peakQuote", () => {
  const peak = (over: Partial<PeakEntry> = {}): PeakEntry =>
    ({
      site: [0.123, 0.456, 0.789],
      height: 3.42,
      nearest_atom: "Zr1",
      nearest_d: 1.87,
      ...over,
    }) as PeakEntry;

  it("cites position and height, never the viewer's Qn", () => {
    const q = peakQuote(peak());
    expect(q).toContain("Zr1");
    expect(q).toContain("1.87");
    expect(q).toContain("3.42");
    expect(q).not.toMatch(/\bQ\d/);
  });

  it("falls back to fractional coordinates with no nearest atom", () => {
    const q = peakQuote(peak({ nearest_atom: null, nearest_d: null }));
    expect(q).toContain("0.123");
    expect(q).toContain("0.789");
  });
});

describe("measureQuote", () => {
  it("flags the reading as esd-free so it is not mistaken for refined", () => {
    const q = measureQuote("Zr1–O3 2.187 Å");
    expect(q).toContain("Zr1–O3 2.187 Å");
    expect(q).toContain("esd");
  });
});

describe("voidQuote", () => {
  it("does not turn a geometry-only pore into zero residual electrons", () => {
    const q = voidQuote(1284.6, null, "n0000");
    expect(q).toContain("电子数未计算");
    expect(q).not.toContain("残余电子约 0");
    expect(q).not.toContain("SQUEEZE");
  });

  it("asks the modelling question, not just the numbers", () => {
    const q = voidQuote(1284.6, 255.7);
    expect(q).toContain("1285");
    expect(q).toContain("256");
    expect(q).toContain("SQUEEZE");
  });
});

describe("frameQuote", () => {
  it("says what the pixels cannot: node, extent, layers", () => {
    const q = frameQuote({
      node: "n0030",
      spaceGroup: "P 6/m m m",
      extent: "生长 2 层",
      nAtoms: 69,
      layers: ["多面体", "密度图"],
    });
    expect(q).toContain("n0030");
    expect(q).toContain("P 6/m m m");
    expect(q).toContain("生长 2 层");
    expect(q).toContain("69 原子");
    // without this the agent cannot tell an Fo-Fc lobe from a void surface
    expect(q).toContain("密度图");
    expect(q).toContain("[anchor node=n0030]");
  });

  it("warns when the frame is only part of the structure", () => {
    const q = frameQuote({
      node: "n0030",
      extent: "超胞 4×4×4",
      nAtoms: 20000,
      truncated: true,
      layers: [],
    });
    expect(q).toContain("截断");
  });

  it("survives a model with no committed node", () => {
    const q = frameQuote({ node: null, extent: "非对称单元", layers: [] });
    expect(q).toContain("当前模型");
    expect(q).not.toContain("null");
    expect(q).not.toContain("[anchor");
  });
});

describe("structureQuote", () => {
  const base = {
    node: "n0030",
    spaceGroup: "P 6/m m m",
    cell: { a: 39.19, b: 39.19, c: 16.61,
            alpha: 90, beta: 90, gamma: 120 },
    r1: 0.0952,
    wr2: 0.3073,
    goof: 0.96,
    nAtoms: 26,
  };

  it("carries cell, group and R factors in one line", () => {
    const q = structureQuote(base);
    expect(q).toContain("n0030");
    expect(q).toContain("P 6/m m m");
    expect(q).toContain("39.190");
    expect(q).toContain("R1 0.0952");
    expect(q).toContain("26 原子");
    expect(q).toContain("[anchor node=n0030]");
  });

  it("does not invent a node when no snapshot exists", () => {
    expect(structureQuote({ ...base, node: null })).not.toContain("[anchor");
  });

  it("brings the data along - it bounds what R1 could ever be", () => {
    const q = structureQuote({
      ...base,
      data: { r_int: 0.572, d_min: 1.0, completeness: 0.948,
              n_unique: 11289 },
    });
    expect(q).toContain("Rint 0.572");
    expect(q).toContain("94.8%");
    expect(q).toContain("11289");
  });

  it("does not punctuate around missing fields", () => {
    const q = structureQuote({ ...base, spaceGroup: undefined,
                               cell: undefined });
    expect(q).not.toContain("：；");
    expect(q).not.toContain("；；");
    expect(q).not.toContain("undefined");
  });

  it("states facts and asks, rather than judging", () => {
    const q = structureQuote(base);
    // the card deliberately does not colour-grade; the quote must not
    // smuggle a verdict back in
    expect(q).not.toMatch(/偏高|太差|不合格|很好/);
    expect(q).toContain("你怎么看");
  });
});

describe("alertQuote", () => {
  const a = {
    level: "A",
    code: "934",
    text: "Number of (Iobs-Icalc)/SigmaW > 10 Reported ......... 14",
  };

  it("carries the code and checkCIF's own numbers", () => {
    const q = alertQuote(a);
    // a bare "934" is as unlookuppable as a viewer-local Q7
    expect(q).toContain("PLAT934");
    expect(q).toContain("14");
    expect(q).toContain("A 级");
  });

  it("asks whether the alert applies rather than assuming it does", () => {
    // an A alert on a framework is routinely explicable; a quote that
    // says "fix this" hands the agent our conclusion instead of the
    // evidence
    expect(alertQuote(a)).not.toMatch(/请修|必须改|错误的/);
    expect(alertQuote(a)).toContain("还是");
  });
});

describe("checkcifQuote", () => {
  // the parser strips the PLAT prefix from numeric codes, so this is the
  // shape the panel actually hands over
  const alerts = [
    { level: "A", code: "934" },
    { level: "A", code: "934" },
    { level: "B", code: "213" },
    { level: "B", code: "ABSTM02" },
    { level: "G", code: "912" },
  ];

  it("lists A and B codes and dedupes them", () => {
    const q = checkcifQuote({
      counts: { A: 2, B: 1, C: 0, G: 1 },
      approx: false,
      alerts,
      target: "final.cif",
    });
    expect(q).toContain("final.cif");
    expect(q).toContain("A ×2");
    expect(q).toContain("PLAT213");
    // an already-whole letter code is not given a second prefix
    expect(q).toContain("ABSTM02");
    expect(q).not.toContain("PLATABSTM02");
    expect(q.match(/PLAT934/g)).toHaveLength(1);
    expect(q).not.toContain("C ×0"); // a zero level is not information
  });

  it("leaves G alerts out of the code list", () => {
    // 20+ G alerts would bury the two that need a decision
    const q = checkcifQuote({ counts: null, approx: false, alerts });
    expect(q).not.toContain("PLAT912");
  });

  it("marks salvaged counts as lower bounds", () => {
    const q = checkcifQuote({
      counts: { A: 2, B: 0, C: 0, G: 0 },
      approx: true,
      alerts,
    });
    expect(q).toContain("A ≥2");
  });
});

describe("poreQuote", () => {
  it("quotes a channel by its inscribed sphere, never a centroid (D17)", () => {
    const q = poreQuote({
      void: 1,
      volume_A3: 17349.6,
      centre_frac: null,
      dimensionality: 3,
      directions: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
      inscribed_centre_frac: [0, 0, 0.204],
      lcd_A: 28.7,
      pld_A: 12.4,
      pld_error_A: 0.31,
      grid_step_A: 0.31,
      electrons: 1234.4,
    });
    expect(q).toContain("PLD 12.4 ± 0.31 Å");
    expect(q).toContain("V1");
    expect(q).toContain("17350 Å³");
    expect(q).toContain("3-D 网络");
    expect(q).toContain("LCD 28.7 Å");
    expect(q).toContain("±0.31 Å");
    expect(q).toContain("内切球心 (0.000, 0.000, 0.204)");
    expect(q).not.toContain("质心");
    expect(q).toContain("1234 e");
  });
  it("quotes a cavity with its centroid", () => {
    const q = poreQuote({
      void: 2,
      volume_A3: 8.6,
      centre_frac: [0.25, 0.5, 0.75],
      dimensionality: 0,
      directions: [],
    });
    expect(q).toContain("孤立空腔");
    expect(q).toContain("质心 (0.250, 0.500, 0.750)");
    expect(q).not.toContain("LCD");
    expect(q).not.toContain("PLD");
  });
});

describe("guestQuote", () => {
  it("names the site, the pore, the nearest host contact and its operator", () => {
    const q = guestQuote({
      fragment: "F3",
      formula: "C2O4",
      copies: 4,
      site: "channel",
      void_id: 1,
      host_fragment: null,
      clearance_A: 0.565,
      nearest_host_contacts: [{ atom: "O7", host_atom: "Zr1", d: 2.21, sym: "-x+1,y,-z+1" }],
    });
    expect(q).toContain("客体 C2O4（F3，4 份）");
    expect(q).toContain("位置 通道中");
    expect(q).toContain("孔 V1");
    expect(q).toContain("O7···Zr1（-x+1,y,-z+1） 2.21 Å");
    expect(q).not.toContain("宿主片段");
  });
});

describe("topologyQuote / fragmentQuote (R4)", () => {
  const nets = {
    n_nets: 2,
    nets: [
      { id: 1, dimensionality: 3, n_atoms_p1: 24, asu_labels: ["C1"], direction: null },
      { id: 2, dimensionality: 3, n_atoms_p1: 24, asu_labels: ["C1"], direction: null },
    ],
    relations: [{ a: 1, b: 2, relation: "translation", op: null, shift: [0.5, 0.5, 0.5] }],
    interpenetrated: true,
    interlocked_1d: false,
    definition: "d",
    host: { fragments: [], selection_rule: "r" },
    notes: [],
  };
  const net = {
    nodes: [],
    edges: [],
    n_nodes_per_cell: 1,
    n_edges_per_cell: 3,
    node_connectivity_histogram: { "6": 1 },
    linkers: [],
    definition: "d",
    rcsr_symbol: null,
    rcsr_status: "未算（未安装 Systre）",
  };
  it("names the relation that makes two nets interpenetrated, and the Systre status", () => {
    const q = topologyQuote({ nets, simplified_net: net, helices: [], finite_fragments: [] });
    expect(q).toContain("独立网 2 个（维度 3/3）");
    expect(q).toContain("互穿（环穿越判定），网间对称关系：网1↔网2 晶格平移相关（0.5, 0.5, 0.5）");
    expect(q).toContain("1 节点 / 3 边（6-连接 ×1）");
    expect(q).toContain("未算（未安装 Systre）");
    expect(q).toContain("描述，不是判定");
  });
  it("names every component's RCSR symbol when Systre split an interpenetrated net", () => {
    const q = topologyQuote({
      nets,
      simplified_net: { ...net, rcsr_symbol: "pcu", rcsr_symbols: ["pcu", "pcu"], rcsr_status: "已算（Systre）：简化网不连通，2 个分量都是 pcu" },
      helices: [],
      finite_fragments: [],
    });
    expect(q).toContain("RCSR pcu × 2（2 个分量）");
    // one component: the plain symbol, no count
    const one = topologyQuote({ nets, simplified_net: { ...net, rcsr_symbol: "dia", rcsr_symbols: ["dia"] }, helices: [], finite_fragments: [] });
    expect(one).toContain("RCSR dia");
    expect(one).not.toContain("分量");
  });
  it("says independent when the nets are not symmetry-related", () => {
    const q = topologyQuote({
      nets: { ...nets, interpenetrated: false, relations: [{ a: 1, b: 2, relation: "independent", op: null, shift: null }] },
      simplified_net: { ...net, n_nodes_per_cell: 0 },
      helices: [{ fragment: "F1", asu_labels: ["C1"], n_atoms_p1: 6, dimensionality: 1, axis_direction: [0, 0, 1], chain_direction: [0, 0, 1], screw: "3_1", order: 3, handedness: "right", pitch_A: 6, axis_repeat_A: 6, racemic: false }],
      finite_fragments: [],
    });
    expect(q).toContain("不互穿（环穿越未发现）");
    expect(q).not.toContain("节点 /");
    expect(q).toContain("螺旋链 3_1 右手 螺距 6.00 Å");
  });
  it("quotes a finite fragment by its labels and evidence, never a viewer ordinal", () => {
    const q = fragmentQuote({
      fragment: "F1",
      asu_labels: ["Zr1", "Zr2", "O1", "O2", "C1", "C2", "C3", "C4"],
      n_atoms: 91,
      copies: 2,
      role: "host",
      largest_cycle: { size: 8, truncated: false, n_cycles_basis: 12, atoms: [] },
      shape: { sphericity: 0.8104, aspect: [0.71, 0.93], longest_axis_A: 14.2 },
    });
    expect(q).toContain("有限片段 F1（Zr1 Zr2 O1 O2 C1 C2 …）");
    expect(q).toContain("91 个原子、宿主、2 份、最大无弦环 8 元、球形度 0.81、纵横比 0.71 / 0.93、最长轴 14.2 Å");
  });
});


describe("quote anchors (R6)", () => {
  it("anchors an atom to the displayed node and symmetry image", () => {
    const q = atomQuote(atom({ sym: true, symop: "-x, y+1/2, -z" }), [], "n0003");
    expect(q).toContain("Å²");
    expect(q).toContain("[anchor node=n0003 atoms=C11(-x,y+1/2,-z)]");
  });

  it("keeps a peak's coordinates even when several peaks share a nearest atom", () => {
    const q = peakQuote({ site: [0.1234, 0.4567, 0.7891], height: 3.42,
      nearest_atom: "Zr1", nearest_d: 1.87 } as PeakEntry, "n0007");
    expect(q).toContain("0.1234, 0.4567, 0.7891");
    expect(q).toContain("[anchor node=n0007 atoms=Zr1]");
    expect(q).not.toMatch(/\bQ\d/);
  });

  it("preserves both periodic images of a measurement", () => {
    const q = measureQuote("C11–C11 4.00 Å", "n0003", [
      atom(), atom({ sym: true, symop: "x+1,y,z" }),
    ]);
    expect(q).toContain("[anchor node=n0003 atoms=C11,C11(x+1,y,z)]");
    expect(q).toContain("未带 esd");
  });

  it("labels pore totals as per-cell, not as totals over a supercell picture", () => {
    const q = voidQuote(1284.6, 255.7, "n0003");
    expect(q).toContain("每晶胞");
    expect(q).toContain("[anchor node=n0003]");
  });

  it("formats node and atoms with operators, and is absent without a node", () => {
    expect(anchor("n0025", ["O1", "N2 (-x, y+1/2, -z)"])).toBe("[anchor node=n0025 atoms=O1,N2(-x,y+1/2,-z)]");
    expect(anchor("n0025")).toBe("[anchor node=n0025]");
    expect(anchor(null, ["O1"])).toBe("");
    expect(withAnchor("请看 O1", null)).toBe("请看 O1");
    expect(withAnchor("请看 O1", "n0003", ["O1"])).toBe("请看 O1 [anchor node=n0003 atoms=O1]");
  });
  it("parses back, keeping operator commas inside the atom", () => {
    const a = parseAnchor("node=n0025 atoms=O1,N2(-x,y+1/2,-z),C3");
    expect(a.node).toBe("n0025");
    expect(a.atoms).toEqual(["O1", "N2(-x,y+1/2,-z)", "C3"]);
    expect(parseAnchor("node=n0001")).toEqual({ node: "n0001", atoms: [] });
  });
});
