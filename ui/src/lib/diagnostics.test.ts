import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  diagnosticContext,
  formatDiagnostic,
  recentDiagnostics,
  reportUiDiagnostic,
  setDiagnosticContext,
} from "./diagnostics";

describe("reportUiDiagnostic", () => {
  const calls: Array<{ url: string; body: unknown }> = [];
  beforeEach(() => {
    calls.length = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        calls.push({ url, body: JSON.parse(String(init?.body)) });
        return Promise.resolve(new Response(null, { status: 204 }));
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("ships the error with the current context and keeps a local copy", () => {
    setDiagnosticContext({ threadId: "t1", cursor: 42, node: "n0116" });
    const r = reportUiDiagnostic(
      "chat",
      new TypeError("x is null"),
      "  at Foo\n  at Bar",
    );
    expect(r.message).toBe("TypeError: x is null");
    expect(r.context).toEqual(
      expect.objectContaining({ threadId: "t1", cursor: 42, node: "n0116" }),
    );
    expect(diagnosticContext().cursor).toBe(42);
    expect(calls[0]?.url).toBe("/api/ui/diagnostics");
    expect((calls[0]?.body as { area: string }).area).toBe("chat");
    expect(recentDiagnostics().at(-1)?.message).toBe("TypeError: x is null");
    const text = formatDiagnostic(r);
    expect(text).toContain("chat: TypeError: x is null");
    expect(text).toContain("at Foo");
  });

  it("copes with non-Error values and never throws when fetch fails", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => {
        throw new Error("offline");
      }),
    );
    expect(() =>
      reportUiDiagnostic("window.error", "plain string"),
    ).not.toThrow();
    expect(reportUiDiagnostic("x", null).message).toBe("null");
  });

  it("rate-limits a burst so a render loop cannot flood the server", () => {
    for (let i = 0; i < 30; i += 1)
      reportUiDiagnostic("loop", new Error(`e${i}`));
    expect(calls.length).toBeLessThanOrEqual(8);
    expect(recentDiagnostics().length).toBeLessThanOrEqual(20);
  });
});
