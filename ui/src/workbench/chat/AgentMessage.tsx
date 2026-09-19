/** Agent message: plain markdown text on the page background (no bubble),
 * with a Codex-style hover action row (copy) underneath. A fenced block
 * tagged `ask` (round-3 R6) renders as the question card instead of code. */
import { createContext, createElement, memo, useContext, useLayoutEffect, useMemo, type HTMLAttributes } from "react";
import ReactMarkdown, { type Components, type ExtraProps } from "react-markdown";
import remarkGfm from "remark-gfm";
import { parseAskBody } from "../../lib/askCard";
import { MdLink, mdUrlTransform } from "../../lib/mdLink";
import type { AgentItem } from "../../state/threadReducer";
import { AskCardStatic } from "./AskCard";
import { CopyAction } from "./MonoBlock";
import { clipSourceValue, rehypePlaybackLeaves, StreamTextLeaf, StreamViewportContext, useStreamingFade } from "./streamingText";
import { PlaybackReportContext, useTextPlayback } from "./textPlayback";

export const FinalRepliesContext = createContext<ReadonlySet<string>>(new Set());

function isAskClass(v: unknown): boolean {
  if (typeof v === "string") return /(^|\s)language-ask(\s|$)/.test(v);
  if (Array.isArray(v)) return v.some((x) => x === "language-ask");
  return false;
}

/** The `<pre>` around an ask fence would wrap the card in a code box. */
function firstChildIsAsk(node: unknown): boolean {
  const n = node as { children?: { type?: string; properties?: { className?: unknown } }[] } | undefined;
  const first = n?.children?.[0];
  return first?.type === "element" && isAskClass(first.properties?.className);
}

function streamedElement(tag: string) {
  return function Element({ node, children, ...props }: HTMLAttributes<HTMLElement> & ExtraProps) {
    const { offset } = useContext(StreamViewportContext);
    if ((node?.position?.start.offset ?? -1) >= offset) return null;
    return createElement(tag, props, children);
  };
}

const components: Components = {
  p: streamedElement("p"), h1: streamedElement("h1"), h2: streamedElement("h2"), h3: streamedElement("h3"),
  h4: streamedElement("h4"), h5: streamedElement("h5"), h6: streamedElement("h6"),
  ul: streamedElement("ul"), ol: streamedElement("ol"), li: streamedElement("li"), blockquote: streamedElement("blockquote"),
  table: streamedElement("table"), thead: streamedElement("thead"), tbody: streamedElement("tbody"), tr: streamedElement("tr"),
  th: streamedElement("th"), td: streamedElement("td"), hr: streamedElement("hr"), br: streamedElement("br"),
  strong: streamedElement("strong"), em: streamedElement("em"), del: streamedElement("del"),
  a: ({ node, ...props }) => {
    const { offset } = useContext(StreamViewportContext);
    if ((node?.position?.start.offset ?? -1) >= offset) return null;
    return <MdLink {...props} />;
  },
  img: ({ node, ...props }) => {
    const { offset } = useContext(StreamViewportContext);
    return (node?.position?.end.offset ?? 0) > offset ? null : <img {...props} />;
  },
  span: ({ node, children, ...props }) => {
    const from = node?.properties.dataStreamFrom, to = node?.properties.dataStreamTo;
    return typeof from === "number" && typeof to === "number"
      ? <StreamTextLeaf value={String(children ?? "")} from={from} to={to} />
      : <span {...props}>{children}</span>;
  },
  pre: ({ children, node }) => {
    const { offset } = useContext(StreamViewportContext);
    if ((node?.position?.start.offset ?? -1) >= offset) return null;
    if (firstChildIsAsk(node)) return (node?.position?.end.offset ?? 0) > offset ? null : <>{children}</>;
    return <pre>{children}</pre>;
  },
  code: ({ className, children, node, ...rest }) => {
    const { source, offset } = useContext(StreamViewportContext);
    if (isAskClass(className)) {
      return <AskCardStatic ask={parseAskBody(String(children ?? ""))} />;
    }
    const value = String(children ?? "");
    const from = node?.position?.start.offset ?? 0, to = node?.position?.end.offset ?? source.length;
    const exact = source.indexOf(value.trimEnd(), from);
    const shown = exact >= from && exact < to
      ? clipSourceValue(value, exact, exact + value.length, offset, source)
      : clipSourceValue(value, from, to, offset, source);
    if (!shown) return null;
    return (
      <code className={className} {...rest}>
        {shown}
      </code>
    );
  },
};

const MarkdownBody = memo(function MarkdownBody({ text }: { text: string }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypePlaybackLeaves]} components={components} urlTransform={mdUrlTransform}>{text}</ReactMarkdown>;
});

export const AgentMessage = memo(function AgentMessage({
  item,
}: {
  item: AgentItem;
}) {
  const finalReply = useContext(FinalRepliesContext).has(item.id);
  const playback = useTextPlayback(item.text, item.streaming, item.renderId);
  const presenting = item.streaming || playback.pending;
  const fade = useStreamingFade(playback.text, presenting);
  const reportPlayback = useContext(PlaybackReportContext);
  const unsettled = presenting || fade.arrivals.length > 0;
  useLayoutEffect(() => {
    reportPlayback(item.renderId ?? item.id, unsettled);
  }, [reportPlayback, item.renderId, item.id, unsettled]);
  const viewport = useMemo(() => ({ source: item.text, offset: playback.text.length, arrivals: fade.arrivals }), [item.text, playback.text, fade.arrivals]);
  return (
    <div className="group agent-message" data-testid="agent-message" data-streaming={item.streaming ? "true" : "false"} data-presenting={playback.pending ? "true" : "false"} data-visible-length={playback.text.length} data-source-length={item.text.length} data-final={finalReply ? "true" : "false"}>
      <div className="md max-w-none">
        <StreamViewportContext.Provider value={viewport}><MarkdownBody text={item.text} /></StreamViewportContext.Provider>
      </div>
      {!presenting && finalReply && (
        <div className="message-actions" data-testid="assistant-copy">
          <CopyAction text={item.text} />
        </div>
      )}
    </div>
  );
});
