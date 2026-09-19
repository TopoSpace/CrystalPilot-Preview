/** Tiny cross-pane bridge: the crystal pane (and node tree) push snippet
 * requests here; the mounted Composer appends them to its local draft text.
 * A seq counter makes repeated identical inserts observable.
 *
 * Files travel the same way. The viewer can hand the agent the frame the
 * user is actually looking at instead of a description of it - the render
 * carries orientation, which overlays are on and what the density looks
 * like there, none of which survives being turned into a sentence. */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

export interface DraftInsert {
  seq: number;
  text: string;
}

export interface DraftFiles {
  seq: number;
  files: File[];
}

interface ComposerDraftValue {
  pending: DraftInsert | null;
  pendingFiles: DraftFiles | null;
  /** Ask the composer to append `text` to its draft. */
  insert: (text: string) => void;
  /** Ask the composer to attach `files` (same path as the + menu: eager
   * upload, thumbnail chip, per-item retry). */
  attach: (files: File[]) => void;
  /** Composer acknowledges it consumed the pending insert. */
  consume: () => void;
  consumeFiles: () => void;
}

const ComposerDraftContext = createContext<ComposerDraftValue>({
  pending: null,
  pendingFiles: null,
  insert: () => undefined,
  attach: () => undefined,
  consume: () => undefined,
  consumeFiles: () => undefined,
});

export function useComposerDraft(): ComposerDraftValue {
  return useContext(ComposerDraftContext);
}

export function ComposerDraftProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<DraftInsert | null>(null);
  const [pendingFiles, setPendingFiles] = useState<DraftFiles | null>(null);
  const seqRef = useRef(0);

  const insert = useCallback((text: string) => {
    seqRef.current += 1;
    setPending({ seq: seqRef.current, text });
  }, []);

  const attach = useCallback((files: File[]) => {
    if (files.length === 0) return;
    seqRef.current += 1;
    setPendingFiles({ seq: seqRef.current, files });
  }, []);

  const consume = useCallback(() => setPending(null), []);
  const consumeFiles = useCallback(() => setPendingFiles(null), []);

  const value = useMemo(
    () => ({ pending, pendingFiles, insert, attach, consume, consumeFiles }),
    [pending, pendingFiles, insert, attach, consume, consumeFiles],
  );

  return (
    <ComposerDraftContext.Provider value={value}>
      {children}
    </ComposerDraftContext.Provider>
  );
}
