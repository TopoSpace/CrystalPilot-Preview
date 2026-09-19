import { createContext, useContext, useLayoutEffect, useRef, useState } from "react";
import { useMotionPreference } from "../../lib/motion";

export const PLAYBACK_RATE = 60; // Unicode graphemes per second, independent of packets.
export const PREBUFFER_MS = 200;
const REFILL_MS = 120;
const segmenter = new Intl.Segmenter(undefined, { granularity: "grapheme" });

export interface PlaybackSnapshot { source: string; shown: number }
export const PlaybackCacheContext = createContext<Map<string, PlaybackSnapshot> | null>(null);
export const PlaybackReportContext = createContext<(id: string, pending: boolean) => void>(() => {});

/** A clock-driven reservoir. Network arrivals can extend it, but cannot
 * advance the playhead or accumulate catch-up credit during starvation. */
export class TextPlayback {
  source = "";
  shown = 0;
  private ends: number[] = [];
  private readyAt = 0;
  private lastAt = 0;
  private credit = 0;

  constructor(source: string, animate: boolean, now: number, saved?: PlaybackSnapshot) {
    this.receive(source, animate, now);
    if (saved) this.shown = Math.min(saved.shown, this.ends.length);
  }

  get offset() { return this.ends[this.shown - 1] ?? 0; }
  get text() { return this.source.slice(0, this.offset); }
  get pending() { return this.shown < this.ends.length; }
  snapshot(): PlaybackSnapshot { return { source: this.source, shown: this.shown }; }

  receive(source: string, animate: boolean, now: number) {
    const wasPending = this.pending;
    if (source !== this.source) {
      // Re-segment only the previous final grapheme plus the new suffix.
      // This also handles emoji/combining marks split across network deltas.
      const append = source.startsWith(this.source);
      const from = append ? this.ends.at(-2) ?? 0 : 0;
      const prefix = append ? this.ends.slice(0, -1) : [];
      this.ends = prefix.concat([...segmenter.segment(source.slice(from))].map(s => from + s.index + s.segment.length));
      this.source = source;
      this.shown = Math.min(this.shown, this.ends.length);
    }
    if (!animate) this.shown = this.ends.length;
    if (!wasPending && this.pending) {
      this.readyAt = now + (this.shown === 0 ? PREBUFFER_MS : REFILL_MS);
      this.lastAt = this.readyAt;
      this.credit = 0;
    }
    if (!this.pending) { this.lastAt = now; this.credit = 0; }
  }

  advance(now: number): boolean {
    if (!this.pending || now < this.readyAt) return false;
    // After a blocked frame, continue smoothly instead of dumping a burst.
    const elapsed = Math.max(0, Math.min(64, now - this.lastAt));
    this.lastAt = now;
    this.credit += elapsed * PLAYBACK_RATE / 1000;
    const count = Math.min(Math.floor(this.credit + 1e-9), this.ends.length - this.shown);
    if (count === 0) return false;
    this.shown += count;
    this.credit = this.pending ? Math.max(0, this.credit - count) : 0;
    return true;
  }
}

/** Persists across source-id promotion/paging, but never outside this open
 * transcript. History mounts directly; live completion drains at the same rate. */
export function useTextPlayback(source: string, live: boolean, renderId?: string) {
  const { animationsEnabled } = useMotionPreference();
  const cache = useContext(PlaybackCacheContext);
  const playerRef = useRef<TextPlayback | null>(null);
  if (playerRef.current === null) playerRef.current = new TextPlayback(
    source, animationsEnabled && (live || Boolean(renderId)), performance.now(),
    renderId ? cache?.get(renderId) : undefined,
  );
  const player = playerRef.current;
  const [view, setView] = useState(() => ({ text: player.text, pending: player.pending }));
  const frameRef = useRef(0);

  useLayoutEffect(() => {
    const publish = () => {
      if (renderId) cache?.set(renderId, player.snapshot());
      setView(previous => previous.text === player.text && previous.pending === player.pending
        ? previous : { text: player.text, pending: player.pending });
    };
    // A completion is not a flush. Only reduced motion/background viewing
    // bypasses playback; server state and approvals remain immediate.
    player.receive(source, animationsEnabled && (live || Boolean(renderId) || player.pending), performance.now());
    publish();
    const tick = (now: number) => {
      if (player.advance(now)) publish();
      frameRef.current = player.pending ? requestAnimationFrame(tick) : 0;
    };
    if (player.pending) frameRef.current = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frameRef.current);
      frameRef.current = 0;
      if (renderId) cache?.set(renderId, player.snapshot());
    };
  }, [source, live, animationsEnabled, player, cache, renderId]);
  return view;
}
