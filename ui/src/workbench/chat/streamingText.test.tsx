import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { nextFadeState, rehypeStreamFade } from "./streamingText";

const start = { text: "", streaming: false, enabled: true, arrivals: [] };
const render = (text: string, previous = "") => {
  const state = nextFadeState({ ...start, text: previous }, text, true, true, 1000);
  return renderToStaticMarkup(<ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[[rehypeStreamFade, state]]}>{text}</ReactMarkdown>);
};

describe("streaming text arrivals", () => {
  it("fades append ranges only and never replays settled prose", () => {
    const first = nextFadeState(start, "已有文字", true, true, 0);
    const next = nextFadeState(first, "已有文字，新增结果", true, true, 500);
    expect(next.arrivals).toEqual([{ from: 4, to: 9, at: 500 }]);
    expect(next.text).toBe("已有文字，新增结果");
    expect(first.arrivals).toEqual([{ from: 0, to: 4, at: 0 }]);
  });

  it("shows authoritative corrections immediately, including interrupted text", () => {
    const live = nextFadeState(start, "R1 = 0.1", true, true, 100);
    const final = nextFadeState(live, "R1 = 0.0412", false, true, 110);
    expect(final.text).toBe("R1 = 0.0412");
    expect(final.arrivals).toEqual([]);
    const stopped = nextFadeState(live, live.text, false, true, 110);
    expect(stopped.text).toBe(live.text);
    expect(stopped.arrivals).toEqual(live.arrivals);
  });

  it("renders history and hidden/reduced-motion updates without replay", () => {
    expect(nextFadeState(start, "完成的历史", false, true, 0).arrivals).toEqual([]);
    const hidden = nextFadeState(start, "后台新增", true, false, 0);
    expect(hidden.arrivals).toEqual([]);
    expect(nextFadeState(hidden, hidden.text, true, true, 10).arrivals).toEqual([]);
  });
});

describe("Markdown leaf decoration", () => {
  it("keeps formatting and table semantics, with no animated raw markup", () => {
    const text = "已完成。\n\n**精修**，见 [报告](https://example.com)。\n\n| R1 | wR2 |\n| --- | --- |\n| 0.04 | 0.10 |";
    const html = render(text, "已完成。\n\n");
    expect(html).toContain("<p>已完成。</p>");
    expect(html).toMatch(/<strong><span[^>]*>精修<\/span><\/strong>/);
    expect(html).toMatch(/<a href="https:\/\/example.com"><span[^>]*>报告<\/span><\/a>/);
    expect(html).toContain("<table>");
    expect(html).toMatch(/<td><span[^>]*>0.04<\/span><\/td>/);
  });

  it("does not alter code, question JSON, escapes or entities", () => {
    const text = '文字 &amp; \\*星号\\*。\n\n`R1 = 0.04`\n\n```ask\n{"question":"已知化学式？"}\n```';
    expect(render(text)).toBe(renderToStaticMarkup(<ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>));
  });

  it("preserves graphemes even when a later delta completes one", () => {
    const html = render("已完成 é 👩‍🔬", "已完成 e");
    expect(html).toContain("é");
    expect(html).toContain("👩‍🔬");
    expect(html).not.toMatch(/e<\/span>/);
  });

  it("bounds animation wrappers for a large burst and leaves the settled prefix native", () => {
    const prefix = "旧内容。".repeat(5000);
    const html = render(prefix + "新增结果。".repeat(1000), prefix);
    expect((html.match(/data-stream-at/g) ?? []).length).toBeLessThanOrEqual(32);
    expect(html).toContain(`<p>${prefix}<span`);
  });
});
