/** Question cards (round-3 R6).
 *
 * When the agent is missing ONE fact that would change its next step it
 * writes a fenced block tagged `ask` and ends its turn:
 *
 *     ```ask
 *     {"settled": "...", "dispute": "...", "question": "...",
 *      "options": ["有", "没有", "不知道"], "fallback": "..."}
 *     ```
 *
 * The transcript renders the fence as a static card; the composer dock
 * shows the latest UNANSWERED one with its options. A click sends the
 * answer back as a `[prior]` message - the AGENTS template tells the agent
 * a `[prior]` line is a user-declared fact to verify against the data,
 * never data evidence. Pure functions here so the parsing and the "is it
 * still open" rule can be asserted without the DOM.
 */

export interface AskBlock {
  /** what the agent considers established (with its evidence) */
  settled: string | null;
  /** the disagreement and the evidence on each side */
  dispute: string | null;
  /** the one question */
  question: string;
  /** short answers offered as buttons (at most four) */
  options: string[];
  /** the conservative path taken when the user does not know */
  fallback: string | null;
  /** the fence body as written */
  raw: string;
}

/** ```ask ... ``` fences (the info string may carry trailing spaces). */
export const ASK_FENCE_RE = /```ask[ \t]*\r?\n([\s\S]*?)```/g;

const MAX_OPTIONS = 4;

function str(j: Record<string, unknown>, key: string): string | null {
  const v = j[key];
  return typeof v === "string" && v.trim() !== "" ? v.trim() : null;
}

/** One fence body -> card. Not JSON (the model wrote prose inside the
 * fence) degrades to a question-only card instead of vanishing. */
export function parseAskBody(body: string): AskBlock {
  const raw = body.trim();
  try {
    const parsed: unknown = JSON.parse(raw);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("not an object");
    }
    const j = parsed as Record<string, unknown>;
    const options = Array.isArray(j.options)
      ? j.options
          .map((o) => String(o).trim())
          .filter((o) => o !== "")
          .slice(0, MAX_OPTIONS)
      : [];
    return {
      settled: str(j, "settled"),
      dispute: str(j, "dispute"),
      question: str(j, "question") ?? raw,
      options,
      fallback: str(j, "fallback"),
      raw,
    };
  } catch {
    return { settled: null, dispute: null, question: raw, options: [], fallback: null, raw };
  }
}

export function parseAskBlocks(text: string): AskBlock[] {
  const out: AskBlock[] = [];
  for (const m of text.matchAll(ASK_FENCE_RE)) {
    const body = m[1].trim();
    if (body === "") continue;
    out.push(parseAskBody(body));
  }
  return out;
}

/** First token of a reply that answers a card; the template keys on it. */
export const PRIOR_PREFIX = "[prior]";

/** The message sent back for an answer: the question is repeated so the
 * agent (and a reader of the transcript) sees what was answered. */
export function priorReply(ask: AskBlock, answer: string): string {
  const a = answer.trim();
  return `${PRIOR_PREFIX} 问题：${ask.question}\n回答：${a}`;
}

export function isPriorReply(text: string): boolean {
  return text.trimStart().startsWith(PRIOR_PREFIX);
}

/** The subset of a thread item the open-question rule needs. */
export interface AskItemLike {
  type: string;
  id: string;
  text?: string;
  streaming?: boolean;
}

export interface OpenAsk {
  itemId: string;
  ask: AskBlock;
}

/** The latest question still waiting for the user: the last agent
 * message carries a card, it has finished streaming, and no user message
 * (answer or otherwise) and no later agent message follow it. An agent
 * that keeps talking after its card has moved on (taken its fallback), so
 * the card is closed too. */
export function latestOpenAsk(items: readonly AskItemLike[]): OpenAsk | null {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const it = items[i];
    if (it.type === "user") return null;
    if (it.type !== "agent") continue;
    if (it.streaming) return null;
    const blocks = parseAskBlocks(it.text ?? "");
    if (blocks.length === 0) return null;
    return { itemId: it.id, ask: blocks[blocks.length - 1] };
  }
  return null;
}
