import { describe, expect, it } from "vitest";
import type { ChatItem, ReasoningItem } from "../../state/threadReducer";
import {
  currentActionText,
  digestLabel,
  foldCompletedTurns,
  foldCounts,
  foldLabel,
  foldWorkRuns,
  isMinor,
  projectBlocks,
  spanMs,
  toBlocks,
  type Block,
} from "./MessageList";
import { humanTurnError } from "./TurnStatusRow";

let seq = 0;
function cmd(
  over: Partial<Extract<ChatItem, { type: "command" }>> = {},
): ChatItem {
  seq += 1;
  return {
    type: "command",
    id: `c${seq}`,
    ts: seq,
    command: "powershell -Command dir",
    status: "completed",
    exitCode: 0,
    output: "",
    done: true,
    itemId: null,
    outputLen: null,
    outputFile: null,
    raw: [],
    ...over,
  };
}

function tool(
  name: string,
  status: "ok" | "error" | "running" | "interrupted" = "ok",
): ChatItem {
  seq += 1;
  return {
    type: "tool",
    id: `t${seq}`,
    ts: seq,
    server: "crystalpilot",
    tool: name,
    args: {},
    status,
    rawStatus: "completed",
    durationMs: 100,
    ok: status === "ok",
    resultTail: null,
    error: null,
    progressLine: null,
    summary: null,
    metricsBefore: null,
    itemId: null,
    raw: [],
  };
}

function agent(text: string): ChatItem {
  seq += 1;
  return { type: "agent", id: `a${seq}`, ts: seq, text, streaming: false };
}

describe("synthetic narrative safeguards", () => {
  it("never folds questions, interrupted tools, failed commands or steers into completed work", () => {
    const question = agent('```ask\n{"question":"synthetic prior?"}\n```');
    const interrupted = tool("refine", "interrupted");
    const failed = cmd({ status: "failed", exitCode: null });
    const steer = { ...user("synthetic steer"), steer: true } as ChatItem;
    const rows = [user("synthetic task"), reasoning("one"), cmd(), question, interrupted, failed, steer, cmd(), reasoning("two"), agent("synthetic reply"), turnDone()];
    const blocks = projectBlocks(rows, false);
    for (const item of [question, interrupted, failed, steer]) {
      expect(blocks.some((b) => b.kind === "item" && b.item.id === item.id)).toBe(true);
    }
  });
  it("keeps warnings about missing scientific output outside completed folds", () => {
    const incomplete = tool("run_shelxl");
    const blocks = projectBlocks([user("synthetic"), reasoning("one"), cmd(), incomplete, cmd(), reasoning("two"), turnDone()], false);
    expect(blocks.some((b) => b.kind === "item" && b.item.id === incomplete.id)).toBe(true);
  });
  it("preserves a focused reasoning block when the turn finishes, with fresh text", () => {
    const thought = reasoning("synthetic initial");
    const rows = [user("synthetic task"), thought, cmd(), cmd()];
    const focused = projectBlocks(rows, true).find((b) => b.kind === "reasoning")!;
    const finalRows = rows.map((it) => it.id === thought.id ? { ...thought, text: "synthetic updated" } : it);
    finalRows.push(agent("synthetic final reply"), turnDone());
    const held = projectBlocks(finalRows, false, focused).find((b) => b.kind === "reasoning");
    expect(held?.kind === "reasoning" && held.items[0].text).toBe("synthetic updated");
    expect(projectBlocks(finalRows, false).some((b) => b.kind === "work")).toBe(true);
  });
});

describe("isMinor", () => {
  it("done-ok commands and observe tools are minor", () => {
    expect(isMinor(cmd())).toBe(true);
    expect(isMinor(tool("inspect_model"))).toBe(false);
  });

  it("failures, running items and milestone tools stay standalone", () => {
    expect(isMinor(cmd({ exitCode: 1 }))).toBe(false);
    expect(isMinor(cmd({ done: false }))).toBe(false);
    expect(isMinor(tool("refine"))).toBe(false); // milestone domain card
    expect(isMinor(tool("inspect_model", "error"))).toBe(false);
  });
});

describe("toBlocks action grouping", () => {
  it("folds consecutive minors into one group, >=2 only", () => {
    const items = [
      agent("开始"),
      cmd(),
      cmd(),
      tool("inspect_model"),
      tool("refine"), // milestone breaks the group
      cmd(),
    ];
    const blocks = toBlocks(items);
    const kinds = blocks.map((b) =>
      b.kind === "actions"
        ? `actions(${b.items.length})`
        : b.kind === "item"
          ? (b as { item: ChatItem }).item.type
          : b.kind,
    );
    expect(kinds).toEqual(["agent", "actions(2)", "tool", "tool", "command"]);
  });

  it("a failed command splits the group and stays loud", () => {
    const items = [cmd(), cmd(), cmd({ exitCode: 2 }), cmd(), cmd()];
    const blocks = toBlocks(items);
    expect(blocks.map((b) => b.kind)).toEqual(["actions", "item", "actions"]);
  });
});

function reasoning(text: string): ReasoningItem {
  seq += 1;
  return { type: "reasoning", id: `r${seq}`, ts: seq, text };
}

describe("foldWorkRuns turn collapse", () => {
  const workRun = (): Block[] =>
    toBlocks([
      reasoning("想一想"),
      cmd(),
      cmd(),
      reasoning("再想"),
      cmd(),
      cmd(),
      agent("结论"),
    ] as ChatItem[]);

  it("folds a >=2-block run into one work block when idle", () => {
    const folded = foldWorkRuns(workRun(), false);
    expect(folded.map((b) => b.kind)).toEqual(["work", "item"]);
    const work = folded[0] as Extract<Block, { kind: "work" }>;
    expect(work.blocks.map((b) => b.kind)).toEqual([
      "reasoning",
      "actions",
      "reasoning",
      "actions",
    ]);
  });

  it("keeps the live tail run open while the turn is active", () => {
    const blocks = toBlocks([
      agent("前言"),
      reasoning("想"),
      cmd(),
      cmd(),
    ] as ChatItem[]);
    const folded = foldWorkRuns(blocks, true);
    expect(folded.map((b) => b.kind)).toEqual(["item", "reasoning", "actions"]);
    // …but the same tail folds once the turn completes
    expect(foldWorkRuns(blocks, false).map((b) => b.kind)).toEqual([
      "item",
      "work",
    ]);
  });

  it("a single reasoning or actions block stays as-is", () => {
    const blocks = toBlocks([reasoning("想"), agent("好")] as ChatItem[]);
    expect(foldWorkRuns(blocks, false).map((b) => b.kind)).toEqual([
      "reasoning",
      "item",
    ]);
  });

  it("milestone cards break runs and stay outside folds", () => {
    const blocks = toBlocks([
      reasoning("想"),
      cmd(),
      tool("refine"), // milestone
      reasoning("看结果"),
      cmd(),
      cmd(),
    ] as ChatItem[]);
    const folded = foldWorkRuns(blocks, false);
    expect(folded.map((b) => b.kind)).toEqual(["work", "item", "work"]);
  });
});

describe("digestLabel", () => {
  it("counts commands and observes", () => {
    const label = digestLabel([cmd(), cmd(), tool("inspect_model")]);
    expect(label).toContain("2");
    expect(label).toContain("条命令");
    expect(label).toContain("1");
    expect(label).toContain("次检视");
  });
});

describe("warning observations stay loud", () => {
  it("an audit with twin_alarm does not fold into groups", () => {
    seq += 1;
    const audit: ChatItem = {
      type: "tool",
      id: `t${seq}`,
      ts: seq,
      server: "crystalpilot",
      tool: "audit_reflection_data",
      args: {},
      status: "ok",
      rawStatus: "completed",
      durationMs: 100,
      ok: true,
      resultTail: null,
      error: null,
      progressLine: null,
      summary: {
        parsed: {
          twin_alarm: { signs: ["flat_e_statistics"] },
          hints: ["mean |E^2-1| low", "twin warning signs present"],
        },
      } as never,
      metricsBefore: null,
      itemId: null,
      raw: [],
    };
    expect(isMinor(audit)).toBe(false);
    // A successful audit remains scientific evidence as well.
    const quiet = {
      ...audit,
      id: "tq",
      summary: {
        parsed: { hints: ["no twin / symmetry symptoms"] },
      } as never,
    } as ChatItem;
    expect(isMinor(quiet)).toBe(false);
  });
});

describe("currentActionText (sticky 当前动作行, P1-5)", () => {
  it("newest running tool wins with its humanized running title", () => {
    const items = [tool("inspect_model"), tool("run_shelxl", "running")];
    const txt = currentActionText(items);
    expect(String(txt)).toContain("SHELXL");
  });

  it("running command shows its humanized label", () => {
    const items = [cmd({ done: false, command: "powershell rg -n foo" })];
    expect(String(currentActionText(items))).toContain("rg");
  });

  it("pending approval blocks and wins", () => {
    const items: ChatItem[] = [
      tool("refine", "running"),
      {
        type: "approval",
        id: "ap1",
        ts: 999,
        approvalId: "x",
        method: "commandExecution",
        detail: null,
        mcpServer: null,
        mcpMessage: null,
        mcpToolParams: null,
        status: "pending",
      },
    ];
    expect(currentActionText(items)).toBe("等待审批…");
  });

  it("nothing in flight falls back to thinking", () => {
    expect(currentActionText([tool("refine"), agent("done")])).toBe("思考中…");
  });
});

describe("humanTurnError (P1-9)", () => {
  it("digs the innermost message out of JSON envelopes", () => {
    const raw =
      'stream error: {"type":"error","error":{"message":"quota exhausted for org"}}';
    expect(humanTurnError(raw)).toBe("quota exhausted for org");
  });

  it("translates rate limits and timeouts", () => {
    expect(humanTurnError("HTTP 429 rate limit exceeded")).toContain("429");
    expect(humanTurnError("upstream request timed out")).toContain("超时");
  });

  it("truncates monsters and passes short prose through", () => {
    expect(humanTurnError("普通错误")).toBe("普通错误");
    expect(humanTurnError("x".repeat(500)).length).toBeLessThan(220);
  });
});

describe("currentActionText", () => {
  const running = {
    type: "tool",
    id: "t9",
    ts: 1,
    server: "crystalpilot",
    tool: "run_shelxl",
    args: {},
    status: "running",
    rawStatus: "in_progress",
    durationMs: null,
    ok: null,
    resultTail: null,
    error: null,
    progressLine: null,
    summary: null,
    metricsBefore: null,
  } as unknown as ChatItem;

  it("names the running tool and appends its progress line when there is one", () => {
    const plain = String(currentActionText([running]));
    expect(plain.length).toBeGreaterThan(0);
    const withProgress = String(
      currentActionText([
        {
          ...(running as object),
          progressLine: "等待 SHELXL 作业 · 42 s",
        } as ChatItem,
      ]),
    );
    expect(withProgress.startsWith(plain)).toBe(true);
    expect(withProgress).toContain("等待 SHELXL 作业 · 42 s");
  });

  it("falls back to thinking when nothing is in flight", () => {
    expect(currentActionText([])).toBe("思考中…");
  });
});

function user(text: string): ChatItem {
  seq += 1;
  return {
    type: "user",
    id: `u${seq}`,
    ts: seq,
    text,
    steer: false,
    pending: false,
  };
}
function turnDone(): ChatItem {
  seq += 1;
  return {
    type: "turn",
    id: `n${seq}`,
    ts: seq,
    phase: "completed",
    status: "completed",
    durationMs: 5000,
    error: null,
  };
}

describe("foldCompletedTurns (R6 turn process folding)", () => {
  it("folds a completed turn's process into one row and keeps the final reply out", () => {
    const items: ChatItem[] = [
      user("请解这个结构"),
      reasoning("想一想"),
      tool("read_skill"),
      tool("list_skills"),
      cmd(),
      agent("最终答复"),
      turnDone(),
    ];
    const blocks = foldCompletedTurns(foldWorkRuns(toBlocks(items), false));
    const kinds = blocks.map((b) => b.kind);
    expect(kinds).toEqual(["item", "work", "item", "item"]);
    const fold = blocks[1];
    if (fold.kind !== "work") throw new Error("expected a work group");
    const counts = foldCounts(fold.blocks);
    expect(counts.tools).toBe(2);
    expect(counts.thinks).toBe(1);
    expect(counts.commands).toBe(1);
    expect(foldLabel(counts)).toContain("2 次工具");
    expect(blocks[2].kind === "item" && blocks[2].item.type === "agent").toBe(
      true,
    );
  });

  it("failures stay loud outside the fold, in event order; the live turn is untouched", () => {
    const items: ChatItem[] = [
      user("go"),
      tool("refine"),
      tool("run_shelxl", "error"),
      tool("edit_atoms"),
      agent("reply"),
      turnDone(),
      user("next"),
      tool("refine"),
      tool("refine"),
    ];
    const blocks = foldCompletedTurns(foldWorkRuns(toBlocks(items), true));
    const kinds = blocks.map((b) => b.kind);
    // refine, the failed card, edit_atoms (single quiet blocks are never
    // folded and a fold never crosses the failure), reply, divider, then
    // the live turn as-is
    expect(kinds.slice(0, 6)).toEqual([
      "item",
      "item",
      "item",
      "item",
      "item",
      "item",
    ]);
    const failed = blocks[2];
    expect(
      failed.kind === "item" &&
        failed.item.type === "tool" &&
        failed.item.status === "error",
    ).toBe(true);
    expect(
      blocks[3].kind === "item" &&
        blocks[3].item.type === "tool" &&
        blocks[3].item.tool === "edit_atoms",
    ).toBe(true);
    expect(kinds.slice(6)).toEqual(["item", "item", "item"]);
  });

  it("a delivery card follows a turn that wrote the product", () => {
    const items: ChatItem[] = [
      user("交付"),
      tool("write_outputs"),
      tool("finalize_delivery"),
      agent("done"),
      turnDone(),
    ];
    const blocks = foldCompletedTurns(foldWorkRuns(toBlocks(items), false));
    expect(blocks.map((b) => b.kind)).toEqual([
      "item",
      "item",
      "item",
      "item",
      "delivery",
      "item",
    ]);
  });

  it("a single process block is not folded", () => {
    const items: ChatItem[] = [
      user("q"),
      tool("refine"),
      agent("a"),
      turnDone(),
    ];
    const blocks = foldCompletedTurns(foldWorkRuns(toBlocks(items), false));
    expect(blocks.map((b) => b.kind)).toEqual(["item", "item", "item", "item"]);
    expect(foldCounts([]).tools).toBe(0);
  });
});

function steer(text: string): ChatItem {
  seq += 1;
  return {
    type: "user",
    id: `s${seq}`,
    ts: seq,
    text,
    steer: true,
    pending: false,
  };
}

describe("foldCompletedTurns (round-3 R1: order, steer, units)", () => {
  it("quiet runs on either side of a failure fold separately, in event order", () => {
    const items: ChatItem[] = [
      user("go"),
      tool("read_skill"),
      tool("save_skill"),
      tool("run_shelxl", "error"),
      tool("read_skill"),
      tool("save_skill"),
      agent("reply"),
      turnDone(),
    ];
    const blocks = foldCompletedTurns(foldWorkRuns(toBlocks(items), true));
    expect(blocks.map((b) => b.kind)).toEqual([
      "item",
      "turnfold",
      "item",
      "turnfold",
      "item",
      "item",
    ]);
    // every item keeps its original order once the folds are flattened
    const flat = blocks.flatMap((b) =>
      b.kind === "turnfold" ? b.blocks : [b],
    );
    const ids = flat.map((b) => (b.kind === "item" ? b.item.id : b.kind));
    const orig = items.map((it) => it.id);
    expect(ids.filter((id) => orig.includes(id))).toEqual(orig);
  });

  it("a steer bubble stays inside the turn, unfolded, and does not end the segment", () => {
    const items: ChatItem[] = [
      user("go"),
      tool("read_skill"),
      tool("save_skill"),
      steer("孔里应该有客体"),
      tool("read_skill"),
      tool("save_skill"),
      agent("reply"),
      turnDone(),
    ];
    const blocks = foldCompletedTurns(foldWorkRuns(toBlocks(items), true));
    const kinds = blocks.map((b) => b.kind);
    expect(kinds).toEqual([
      "item",
      "turnfold",
      "item",
      "turnfold",
      "item",
      "item",
    ]);
    const mid = blocks[2];
    expect(
      mid.kind === "item" && mid.item.type === "user" && mid.item.steer,
    ).toBe(true);
  });

  it("fold durations treat event timestamps as seconds", () => {
    expect(spanMs(1000, 1000 + 2904)).toBe(2_904_000);
    expect(spanMs(1_700_000_000_000, 1_700_000_000_000 + 2904)).toBe(2904);
    expect(spanMs(5, 5)).toBe(0);
    expect(spanMs(Infinity, -Infinity)).toBe(0);
    const counts = foldCounts(
      foldWorkRuns(toBlocks([tool("inspect_model"), tool("edit_atoms")]), true),
    );
    expect(counts.ms).toBe(1000);
  });
});
