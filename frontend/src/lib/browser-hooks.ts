"use client";

/**
 * Bridges to browser state that React does not own.
 *
 * All of these use `useSyncExternalStore` rather than "read in an effect, then
 * setState". That avoids the cascading extra render, and — more importantly —
 * gives an explicit server snapshot, so the SSR pass and the first client
 * render agree instead of producing a hydration mismatch.
 */

import { useCallback, useSyncExternalStore } from "react";

// --------------------------------------------------------------------------
// localStorage
// --------------------------------------------------------------------------

const listeners = new Set<() => void>();

function notify() {
  for (const listener of listeners) listener();
}

function subscribeToStorage(listener: () => void) {
  listeners.add(listener);
  // Also react to writes from another tab.
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

/** Write a value and wake every subscriber in this tab. */
export function writeStoredValue(key: string, value: string | null) {
  if (typeof window === "undefined") return;
  if (value === null) window.localStorage.removeItem(key);
  else window.localStorage.setItem(key, value);
  notify();
}

export function readStoredValue(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    // Private-mode or blocked storage: behave as if nothing was saved.
    return null;
  }
}

/** Subscribe to a raw localStorage string. `null` on the server. */
export function useStoredValue(key: string): string | null {
  return useSyncExternalStore(
    subscribeToStorage,
    useCallback(() => readStoredValue(key), [key]),
    () => null,
  );
}

/**
 * False during SSR and the hydrating render, true afterwards.
 *
 * This matters for anything that reads browser storage: before hydration
 * completes `useStoredValue` necessarily returns its server snapshot (`null`),
 * which is indistinguishable from "the value is genuinely absent". Callers that
 * act on absence — redirecting a signed-out user, for instance — must wait for
 * this to be true first, or they will bounce every direct page load.
 */
export function useIsHydrated(): boolean {
  return useSyncExternalStore(
    subscribeToStorage,
    () => true,
    () => false,
  );
}

// --------------------------------------------------------------------------
// Media queries
// --------------------------------------------------------------------------

/**
 * `false` on the server and during the first client render, so markup matches;
 * it flips as soon as the real match is known.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (listener: () => void) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", listener);
      return () => list.removeEventListener("change", listener);
    },
    [query],
  );

  return useSyncExternalStore(
    subscribe,
    useCallback(() => window.matchMedia(query).matches, [query]),
    () => false,
  );
}
