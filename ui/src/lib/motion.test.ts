import { afterEach, describe, expect, it, vi } from "vitest";
import {
  animateView,
  motionDuration,
  motionEnabled,
  motionScrollBehavior,
  REDUCED_MOTION_QUERY,
} from "./motion";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("cancellable centering", () => {
  it("moves instantly without scheduling frames under reduced motion", () => {
    const frame = vi.fn();
    vi.stubGlobal("requestAnimationFrame", frame);
    const apply = vi.fn();
    animateView([0, 0], [10, 20], motionDuration(300, true), apply);
    expect(apply).toHaveBeenCalledWith([10, 20]);
    expect(frame).not.toHaveBeenCalled();
  });
  it("cancels queued movement on hide/unmount and does not replay it", () => {
    let callback: FrameRequestCallback = () => {};
    vi.spyOn(performance, "now").mockReturnValue(100);
    const request = vi.fn((cb: FrameRequestCallback) => { callback = cb; return 7; });
    const cancel = vi.fn();
    vi.stubGlobal("requestAnimationFrame", request);
    vi.stubGlobal("cancelAnimationFrame", cancel);
    const apply = vi.fn();
    const stop = animateView([0, 10], [10, 30], 300, apply);
    callback(250);
    expect(apply).toHaveBeenLastCalledWith([5, 20]);
    expect(request).toHaveBeenCalledTimes(2);
    stop();
    expect(cancel).toHaveBeenCalledWith(7);
    callback(400);
    expect(apply).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledTimes(2);
  });
  it("finishes at the target and stops scheduling", () => {
    let callback: FrameRequestCallback = () => {};
    vi.spyOn(performance, "now").mockReturnValue(0);
    const request = vi.fn((cb: FrameRequestCallback) => { callback = cb; return 1; });
    vi.stubGlobal("requestAnimationFrame", request);
    const apply = vi.fn();
    animateView([0], [5], 300, apply);
    callback(450);
    expect(apply).toHaveBeenLastCalledWith([5]);
    expect(request).toHaveBeenCalledTimes(1);
  });
});

describe("motion policy", () => {
  it("uses the system reduced-motion media query", () => {
    expect(REDUCED_MOTION_QUERY).toBe("(prefers-reduced-motion: reduce)");
  });

  it("removes JS movement when reduced motion is requested", () => {
    expect(motionDuration(300, true)).toBe(0);
    expect(motionScrollBehavior(true)).toBe("auto");
    expect(motionDuration(300, false)).toBe(300);
    expect(motionScrollBehavior(false)).toBe("smooth");
  });

  it("runs animation loops only while visible and motion is allowed", () => {
    expect(motionEnabled(false, true)).toBe(true);
    expect(motionEnabled(true, true)).toBe(false);
    expect(motionEnabled(false, false)).toBe(false);
  });
});
