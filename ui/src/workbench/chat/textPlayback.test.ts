import { describe, expect, it } from "vitest";
import { TextPlayback, PLAYBACK_RATE } from "./textPlayback";

function play(player: TextPlayback, from: number, to: number) {
  for (let now = from; now <= to; now += 10) player.advance(now);
}

describe("fixed-rate local playback", () => {
  it("starts before upstream completion and absorbs uneven packets at the same speed", () => {
    const player = new TextPlayback("晶".repeat(80), true, 0);
    play(player, 0, 200);
    expect(player.shown).toBe(0);
    play(player, 210, 700);
    expect(player.shown).toBeCloseTo(PLAYBACK_RATE / 2, 0);
    player.receive("晶".repeat(200), true, 700);
    expect(player.shown).toBe(30); // a packet cannot move the playhead
    play(player, 710, 1200);
    expect(player.shown).toBe(60);
    expect(player.pending).toBe(true);
  });

  it("keeps draining at the same rate after completion and interruption", () => {
    const player = new TextPlayback("结果".repeat(30), true, 0);
    play(player, 0, 400);
    const shown = player.shown;
    player.receive(player.source, true, 400); // server completion is not a flush
    expect(player.shown).toBe(shown);
    play(player, 410, 1400);
    expect(player.text).toBe(player.source);
    expect(player.pending).toBe(false);
  });

  it("does not bank empty time or dump delayed frames", () => {
    const player = new TextPlayback("短句", true, 0);
    play(player, 0, 1000);
    player.receive("短句" + "新".repeat(100), true, 5000);
    expect(player.advance(5100)).toBe(false);
    player.advance(9000);
    expect(player.shown).toBeLessThanOrEqual(6);
  });

  it("preserves Unicode, corrections and a cached playhead", () => {
    const player = new TextPlayback("e", true, 0);
    player.receive("é👩‍🔬晶体", true, 100);
    play(player, 200, 240);
    expect(player.text).toBe("é👩‍🔬");
    const restored = new TextPlayback(player.source, true, 300, player.snapshot());
    expect(restored.text).toBe(player.text);
    restored.receive("正确结果", true, 310);
    expect(restored.text).toBe("正确");
    play(restored, 400, 800);
    expect(restored.text).toBe("正确结果");
  });

  it("shows history and reduced-motion/background updates immediately", () => {
    const player = new TextPlayback("历史完整内容", false, 0);
    expect(player.text).toBe(player.source);
    player.receive(player.source + "新增", false, 10);
    expect(player.pending).toBe(false);
  });
});
