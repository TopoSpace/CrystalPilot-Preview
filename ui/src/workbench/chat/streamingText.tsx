import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { Element, Root, RootContent, Text } from "hast";
import { useMotionPreference } from "../../lib/motion";

const FADE_MS = 220;
const STAGGER_MS = 100;
const SETTLE_MS = FADE_MS + STAGGER_MS;
const graphemes = new Intl.Segmenter(undefined, { granularity: "grapheme" });

export interface Arrival { from: number; to: number; at: number }
interface FadeState {
  text: string;
  streaming: boolean;
  enabled: boolean;
  arrivals: Arrival[];
}

/** Fade arrivals follow the local playhead, not the upstream packet timing. */
export function nextFadeState(previous: FadeState, text: string, streaming: boolean, enabled: boolean, now: number): FadeState {
  const appended = text.startsWith(previous.text);
  const arrivals = enabled && previous.enabled && appended
    ? previous.arrivals.filter(range => now - range.at < SETTLE_MS)
    : [];
  if (enabled && (streaming || previous.streaming) && appended && text.length > previous.text.length) {
    arrivals.push({ from: previous.text.length, to: text.length, at: now });
  }
  // Corrections/reconnect replacements are displayed exactly as received.
  return { text, streaming, enabled, arrivals };
}

export function useStreamingFade(text: string, streaming: boolean) {
  const { animationsEnabled } = useMotionPreference();
  const [state, setState] = useState<FadeState>(() => nextFadeState(
    { text: "", streaming: false, enabled: animationsEnabled, arrivals: [] },
    text, streaming, animationsEnabled, performance.now(),
  ));
  let current = state;
  // Derive before paint, so a new fragment never flashes at full opacity
  // before fading. React discards this render and commits the fresh state.
  if (state.text !== text || state.streaming !== streaming || state.enabled !== animationsEnabled) {
    current = nextFadeState(state, text, streaming, animationsEnabled, performance.now());
    setState(current);
  }
  const arrivals = current.arrivals;
  useEffect(() => {
    if (arrivals.length === 0) return;
    const timer = window.setTimeout(() => {
      setState(value => ({ ...value, arrivals: [] }));
    }, Math.max(0, arrivals.at(-1)!.at + SETTLE_MS - performance.now()) + 20);
    return () => window.clearTimeout(timer);
  }, [arrivals]);
  return { text, arrivals };
}

/** One mount-relative delay per arrival. Reconciliation or Markdown
 * reparenting resumes its original age instead of replaying old words. */
export function StreamFadeSpan({ at, children }: { at: number; children: ReactNode }) {
  const [delay] = useState(() => at - performance.now());
  return <span className="stream-fragment" style={{ animationDelay: `${delay}ms` }}>{children}</span>;
}

function fadeText(node: Text, text: string, arrivals: Arrival[]): RootContent[] {
  const from = node.position?.start.offset;
  const to = node.position?.end.offset;
  // Escapes/entities and synthetic Markdown nodes do not have a 1:1 source
  // mapping. Leave those native, preserving exact Markdown semantics.
  if (from === undefined || to === undefined || text.slice(from, to) !== node.value) return [node];
  const relevant = arrivals.filter(range => range.to > from && range.from < to);
  if (relevant.length === 0) return [node];
  const pieces: { value: string; key: string; at?: number }[] = [];
  const first = graphemes.segment(node.value).containing(Math.max(0, relevant[0].from - from))?.index ?? 0;
  if (first > 0) pieces.push({ value: node.value.slice(0, first), key: "settled" });
  const newestFirst = [...relevant].reverse();
  for (const { segment, index } of graphemes.segment(node.value.slice(first))) {
    const start = from + first + index, end = start + segment.length;
    // The newest arrival wins when a delta completes a combining character
    // or emoji. Never split a grapheme between independently fading spans.
    const range = newestFirst.find(r => end > r.from && start < r.to);
    const width = range ? Math.max(8, Math.ceil((range.to - range.from) / 32)) : 1;
    const bucket = range ? Math.floor(Math.max(0, start - range.from) / width) : 0;
    const key = range ? `${range.at}:${range.from}:${bucket}` : "settled";
    const last = pieces.at(-1);
    if (last?.key === key) last.value += segment;
    else pieces.push({ value: segment, key, at: range
      ? range.at + STAGGER_MS * bucket * width / (range.to - range.from)
      : undefined });
  }
  return pieces.map(piece => piece.at === undefined || !piece.value.trim()
    ? { type: "text", value: piece.value }
    : { type: "element", tagName: "span", properties: { dataStreamAt: piece.at }, children: [{ type: "text", value: piece.value }] });
}

export const StreamViewportContext = createContext<{ source: string; offset: number; arrivals: Arrival[] }>(
  { source: "", offset: Infinity, arrivals: [] },
);

/** Decode/layout remain the Markdown parser's job. For escaped/entity text,
 * a proportional source mapping reveals decoded graphemes, never raw syntax. */
export function clipSourceValue(value: string, from: number, to: number, offset: number, source: string): string {
  if (offset >= to) return value;
  if (offset <= from) return "";
  if (source.slice(from, to) === value) return value.slice(0, offset - from);
  const clusters = [...graphemes.segment(value)];
  const count = Math.floor(clusters.length * (offset - from) / (to - from));
  return count === 0 ? "" : value.slice(0, clusters[count - 1].index + clusters[count - 1].segment.length);
}

export function StreamTextLeaf({ value, from, to }: { value: string; from: number; to: number }) {
  const { source, offset, arrivals } = useContext(StreamViewportContext);
  const visible = clipSourceValue(value, from, to, offset, source);
  if (!visible) return null;
  const end = Math.min(offset, to);
  const point = (offset: number) => ({ line: 1, column: 1, offset });
  const pieces = fadeText({ type: "text", value: visible, position: { start: point(from), end: point(end) } }, source, arrivals);
  return <>{pieces.map((piece, i) => piece.type === "text" ? piece.value
    : piece.type === "element" ? <StreamFadeSpan key={`${piece.properties.dataStreamAt}:${i}`} at={Number(piece.properties.dataStreamAt)}>{(piece.children[0] as Text).value}</StreamFadeSpan>
    : null)}</>;
}

/** Run only when source packets change. Cursor updates go directly to the
 * text consumers via context, avoiding a full Markdown parse every frame. */
export function rehypePlaybackLeaves() {
  return (tree: Root) => {
    const visit = (parent: Root | Element) => {
      if (parent.type === "element" && parent.tagName === "pre") {
        for (const child of parent.children) if (child.type === "element" && child.tagName === "code") child.position ??= parent.position;
      }
      if (parent.type === "element" && (parent.tagName === "pre" || parent.tagName === "code")) return;
      parent.children = parent.children.map(child => {
        if (child.type === "element") visit(child);
        const from = child.position?.start.offset, to = child.position?.end.offset;
        if (child.type !== "text" || from === undefined || to === undefined) return child;
        return { type: "element", tagName: "span", properties: { dataStreamFrom: from, dataStreamTo: to }, children: [child] };
      }) as typeof parent.children;
    };
    visit(tree);
  };
}

/** Decorate text leaves, not paragraphs: existing prose, links, lists and
 * tables keep their native layout. Code/ask fences remain untouched. */
export function rehypeStreamFade({ text, arrivals }: { text: string; arrivals: Arrival[] }) {
  return (tree: Root) => {
    if (arrivals.length === 0) return;
    const visit = (parent: Root | Element) => {
      if (parent.type === "element" && (parent.tagName === "pre" || parent.tagName === "code")) return;
      parent.children = parent.children.flatMap(child => {
        if (child.type === "element") visit(child);
        return child.type === "text" ? fadeText(child, text, arrivals) : [child];
      }) as typeof parent.children;
    };
    visit(tree);
  };
}
