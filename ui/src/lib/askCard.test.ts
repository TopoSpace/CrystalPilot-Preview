/** Question cards: the fence is parsed leniently, the reply carries the
 * [prior] key the template reads, and "still open" means exactly one
 * thing - the last agent message asked and nobody answered yet. */
import { describe, expect, it } from "vitest";
import {
  isPriorReply,
  latestOpenAsk,
  parseAskBlocks,
  parseAskBody,
  priorReply,
} from "./askCard";

const CARD = `骨架已稳定。

\`\`\`ask
{"settled": "已确认 P6/mmm，Zr6 簇由两组重原子峰支持",
 "dispute": "孔内 Q1 3.2 eÅ⁻³ 距 O3 2.1 Å：可能是对溴苯乙酸的 Br，也可能是无序 DMF",
 "question": "合成时是否加入了对溴苯乙酸？",
 "options": ["有", "没有", "不知道"],
 "fallback": "不知道则按溶剂掩膜处理，客体假设进 open_directions"}
\`\`\`
`;

describe("parseAskBlocks", () => {
  it("reads the JSON card with every field", () => {
    const [ask] = parseAskBlocks(CARD);
    expect(ask.question).toBe("合成时是否加入了对溴苯乙酸？");
    expect(ask.options).toEqual(["有", "没有", "不知道"]);
    expect(ask.settled).toContain("P6/mmm");
    expect(ask.dispute).toContain("Q1 3.2");
    expect(ask.fallback).toContain("溶剂掩膜");
  });

  it("degrades a non-JSON fence to a question-only card", () => {
    const [ask] = parseAskBlocks("```ask\n请问投料里有没有溴？\n```");
    expect(ask.question).toBe("请问投料里有没有溴？");
    expect(ask.options).toEqual([]);
    expect(ask.settled).toBeNull();
  });

  it("caps options at four and drops blanks; a missing question falls back to the body", () => {
    const ask = parseAskBody('{"options": ["a", "", "b", "c", "d", "e"]}');
    expect(ask.options).toEqual(["a", "b", "c", "d"]);
    expect(ask.question).toBe('{"options": ["a", "", "b", "c", "d", "e"]}');
  });

  it("ignores empty fences and other languages", () => {
    expect(parseAskBlocks("```ask\n\n```\n```json\n{}\n```")).toEqual([]);
  });
});

describe("priorReply", () => {
  it("starts with the [prior] key and repeats the question", () => {
    const [ask] = parseAskBlocks(CARD);
    const text = priorReply(ask, " 有 ");
    expect(text).toBe("[prior] 问题：合成时是否加入了对溴苯乙酸？\n回答：有");
    expect(isPriorReply(text)).toBe(true);
    expect(isPriorReply("有")).toBe(false);
  });
});

describe("latestOpenAsk", () => {
  const agent = (id: string, text: string, streaming = false) => ({ type: "agent", id, text, streaming });
  const user = (id: string) => ({ type: "user", id, text: "…" });
  const tool = (id: string) => ({ type: "tool", id });

  it("is the card of the last agent message when nothing follows it", () => {
    const open = latestOpenAsk([user("u1"), agent("a1", CARD), tool("t1")]);
    expect(open?.itemId).toBe("a1");
    expect(open?.ask.options).toHaveLength(3);
  });

  it("closes once the user answers", () => {
    expect(latestOpenAsk([agent("a1", CARD), user("u2")])).toBeNull();
  });

  it("closes when the agent moved on without waiting", () => {
    expect(latestOpenAsk([agent("a1", CARD), agent("a2", "按 fallback 继续。")])).toBeNull();
  });

  it("waits for the message to finish streaming", () => {
    expect(latestOpenAsk([agent("a1", CARD, true)])).toBeNull();
  });

  it("is null when no card was ever asked", () => {
    expect(latestOpenAsk([user("u1"), agent("a1", "没有问题。")])).toBeNull();
  });
});
