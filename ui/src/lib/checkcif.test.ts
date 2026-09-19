/** checkCIF tail parsing: full-JSON path (new events keep the whole
 * result) and the salvage path for old head-truncated transcripts. */
import { describe, expect, it } from "vitest";
import { checkcifOriginStatus, latestCheckcif, parseCheckcifSource, parseCheckcifTail } from "./checkcif";
import type { ToolCardItem } from "../state/threadReducer";

const FULL = JSON.stringify({
  ok: true,
  summary: {
    target: "outputs/final.cif",
    counts: { A: 2, B: 1, C: 3, G: 0 },
    alerts: [
      { code: "THETM01", level: "A", text: "low theta max",
        kb: { meaning: "resolution", remedy: "recollect" } },
      { code: "PLAT029", level: "A", text: "diffrn ratio" },
      { code: "PLAT213", level: "B", text: "adp ratio" },
      { code: "PLAT910", level: "C", text: "missing refl" },
      { code: "PLAT911", level: "C", text: "missing refl 2" },
      { code: "PLAT912", level: "C", text: "missing refl 3" },
    ],
    note: "local PLATON",
  },
});

describe("parseCheckcifTail - intact JSON", () => {
  it("parses alerts + counts, not partial", () => {
    const d = parseCheckcifTail(FULL);
    expect(d).not.toBeNull();
    expect(d?.partial).toBe(false);
    expect(d?.counts).toEqual({ A: 2, B: 1, C: 3, G: 0 });
    expect(d?.alerts).toHaveLength(6);
    expect(d?.alerts[0].kb?.remedy).toBe("recollect");
    expect(d?.target).toBe("outputs/final.cif");
  });
});

describe("parseCheckcifTail - honest missing or invalid reports", () => {
  it.each([
    {},
    { ok: true, summary: { target: "final.cif" } },
    { ok: false, error: "PLATON did not complete", summary: {} },
    { ok: false, summary: { alerts: [], counts: { A: 0 } } },
    { summary: { counts: {} } },
  ])("does not manufacture zero alerts from %j", (body) => {
    expect(parseCheckcifTail(JSON.stringify(body))).toBeNull();
  });

  it("accepts an explicitly empty complete alert list", () => {
    const d = parseCheckcifTail(JSON.stringify({ ok: true, summary: { alerts: [] } }));
    expect(d?.partial).toBe(false);
    expect(d?.counts).toEqual({ A: 0, B: 0, C: 0, G: 0 });
  });

  it("does not turn unrecognized alert rows into a clean report", () => {
    const d = parseCheckcifTail(JSON.stringify({ alerts: [{ level: "A" }] }));
    expect(d?.partial).toBe(true);
    expect(d?.counts).toBeNull();
  });

  it("keeps contradictory reported counts unknown rather than showing zero", () => {
    const d = parseCheckcifTail(JSON.stringify({ counts: { A: 0 },
      alerts: [{ code: "PLAT029", level: "A", text: "real alert" }] }));
    expect(d?.partial).toBe(true);
    expect(d?.counts).toBeNull();
    expect(d?.salvagedCounts.A).toBe(1);
  });

  it.each([-1, 1.5, "unknown"])("rejects invalid count %s", (count) => {
    const d = parseCheckcifTail(JSON.stringify({ counts: { A: count }, alerts: [] }));
    expect(d?.counts).toBeNull();
    expect(d?.partial).toBe(true);
  });
});

describe("checkCIF execution failures (synthetic records)", () => {
  const source = { kind: "delivery", target: "H:\\fixture\\final.cif",
    node: "n0002", revision: 3, delivery_revision: 4 };
  for (const execution of ["running", "failed", "timeout", "cancelled", "unrecognized"]) {
    it(`keeps ${execution} provenance without zero counts or stale alerts`, () => {
      const record = { execution_status: execution, report_status: "missing", source,
        error: "Synthetic process failure", counts: { A: 0, B: 0, C: 0, G: 0 }, alerts: [] };
      const data = parseCheckcifTail(JSON.stringify(record));
      expect(data?.counts).toBeNull();
      expect(data?.alerts).toEqual([]);
      expect(data?.source).toEqual(source);
      expect(data?.error).toBe("Synthetic process failure");
      expect(data?.execution).not.toBe("completed");
    });
  }
  it("never falls back to a previous successful tool card", () => {
    const success = { type: "tool", tool: "run_checkcif", status: "ok", resultTail: FULL } as ToolCardItem;
    const failure = { ...success, status: "error", resultTail: JSON.stringify({ ok: false,
      summary: { source, execution_status: "timeout", report_status: "partial", counts: null,
        alerts: [], error: "Synthetic timeout" } }) } as ToolCardItem;
    const latest = latestCheckcif([success, failure]);
    expect(latest?.item).toBe(failure);
    expect(latest?.data?.counts).toBeNull();
    expect(latest?.data?.execution).toBe("timeout");
    expect(latest?.data?.source).toEqual(source);
  });
});

describe("checkCIF provenance", () => {
  const source = { kind: "delivery", target: "H:\\project\\delivery\\final.cif",
    node: "n0003", revision: 4, delivery_revision: 2 } as const;
  const data = () => parseCheckcifTail(JSON.stringify({ ...JSON.parse(FULL),
    summary: { ...JSON.parse(FULL).summary, source, checked_at: "2026-09-05 12:00:00" } }));

  it("retains the actual source node, not an active-node guess", () => {
    expect(data()?.source).toEqual(source);
    expect(checkcifOriginStatus(data(), "n0003", source)).toBe("same_node");
    expect(checkcifOriginStatus(data(), "n0009", source)).toBe("different_node");
  });

  it("recognizes a newer export on the same node", () => {
    expect(checkcifOriginStatus(data(), "n0003", { ...source, delivery_revision: 3 })).toBe("outdated_delivery");
  });

  it("does not invent source information for old or missing reports", () => {
    expect(checkcifOriginStatus(parseCheckcifTail(FULL), "n0003")).toBe("unknown");
    expect(checkcifOriginStatus(data(), "n0003", null)).toBe("unknown");
    expect(parseCheckcifSource({ target: "x", kind: "unexpected" })).toBeNull();
  });
});

describe("parseCheckcifTail - head-truncated salvage", () => {
  it("salvages complete alert objects and flags partial", () => {
    // cut mid-alert: counts (serialized before alerts) are gone
    const cut = FULL.slice(FULL.indexOf('"PLAT213"') - 20);
    const d = parseCheckcifTail(cut);
    expect(d).not.toBeNull();
    expect(d?.partial).toBe(true);
    expect(d?.counts).toBeNull();          // unknown, NOT zero
    expect(d?.salvagedCounts.C).toBe(3);
    expect(d?.alerts.some((a) => a.code === "PLAT910")).toBe(true);
  });

  it("returns null for hopeless input", () => {
    expect(parseCheckcifTail("no json here")).toBeNull();
    expect(parseCheckcifTail(null)).toBeNull();
    expect(parseCheckcifTail("")).toBeNull();
  });

  it("ignores escaped braces inside strings", () => {
    const tricky =
      '...,{"code":"PLAT123","level":"B","text":"weird \\"q{uo}te\\" here"}]}';
    const d = parseCheckcifTail(tricky);
    expect(d?.alerts).toHaveLength(1);
    expect(d?.alerts[0].text).toContain("q{uo}te");
  });
});
