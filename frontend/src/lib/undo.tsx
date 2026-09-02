"use client";

/**
 * A session-scoped undo stack for the sheet.
 *
 * Each entry carries the *inverse* of what was done rather than a snapshot, so
 * undoing a pasted block is one delete of known ids instead of diffing the
 * grid. That also keeps a paste as a single step: fifty rows arrived together
 * and they leave together.
 *
 * Deliberately not persisted. An undo that survives a reload would be
 * offering to reverse something the user can no longer see, and a stale id is
 * worse than no history.
 */

import * as React from "react";

export interface UndoEntry {
  /** Shown in the toast and the button's title: "pasted 12 applications". */
  label: string;
  /** Reverses the action. Throwing surfaces as a toast; the entry is dropped. */
  undo: () => Promise<void>;
}

interface UndoState {
  entries: UndoEntry[];
  push: (entry: UndoEntry) => void;
  undoLast: () => Promise<UndoEntry | null>;
  clear: () => void;
  canUndo: boolean;
  lastLabel: string | null;
  isUndoing: boolean;
}

const UndoContext = React.createContext<UndoState | null>(null);

/** Enough steps to cover a run of edits, small enough to stay comprehensible. */
const MAX_ENTRIES = 25;

export function UndoProvider({ children }: { children: React.ReactNode }) {
  const [entries, setEntries] = React.useState<UndoEntry[]>([]);
  const [isUndoing, setIsUndoing] = React.useState(false);

  const push = React.useCallback((entry: UndoEntry) => {
    setEntries((current) => [entry, ...current].slice(0, MAX_ENTRIES));
  }, []);

  const clear = React.useCallback(() => setEntries([]), []);

  const undoLast = React.useCallback(async () => {
    const [entry, ...rest] = entries;
    if (!entry) return null;

    setIsUndoing(true);
    try {
      await entry.undo();
      setEntries(rest);
      return entry;
    } finally {
      setIsUndoing(false);
    }
  }, [entries]);

  const value = React.useMemo<UndoState>(
    () => ({
      entries,
      push,
      undoLast,
      clear,
      canUndo: entries.length > 0 && !isUndoing,
      lastLabel: entries[0]?.label ?? null,
      isUndoing,
    }),
    [entries, push, undoLast, clear, isUndoing],
  );

  return <UndoContext.Provider value={value}>{children}</UndoContext.Provider>;
}

export function useUndo(): UndoState {
  const context = React.useContext(UndoContext);
  if (!context) throw new Error("useUndo must be used inside UndoProvider");
  return context;
}

/**
 * Ctrl+Z / Cmd+Z, ignored while the user is typing.
 *
 * A spreadsheet cell mid-edit has its own undo — the browser's — and stealing
 * it would be worse than not offering the shortcut at all.
 */
export function useUndoShortcut(onUndo: () => void, enabled = true) {
  React.useEffect(() => {
    if (!enabled) return;

    function handle(event: KeyboardEvent) {
      if (event.key !== "z" && event.key !== "Z") return;
      if (!(event.metaKey || event.ctrlKey) || event.shiftKey || event.altKey) {
        return;
      }
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) {
        return;
      }
      event.preventDefault();
      onUndo();
    }

    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, [onUndo, enabled]);
}
