"use client";

import { createContext, useCallback, useContext, useMemo } from "react";

import { readStoredValue, useStoredValue, writeStoredValue } from "./browser-hooks";
import { useAuth } from "./auth";
import { usePeople } from "./queries";
import type { PersonWithStats } from "./types";

/**
 * The global person selector (spec §4).
 *
 * Semantics deliberately mirror the backend's `PersonScope`:
 *
 *   selectedIds = []  ->  "everyone", and the API is called with no
 *                         `person_ids` parameter at all.
 *   selectedIds = [x] ->  only that person.
 *
 * Representing "everyone" as an empty array rather than "all the ids" means a
 * newly added person is included automatically instead of being invisible
 * until the user re-selects.
 *
 * The selection persists to localStorage (spec §4) and is read through
 * `useSyncExternalStore`, so there is no read-then-setState round trip. Ids
 * belonging to people who no longer exist are filtered out at read time rather
 * than by rewriting storage, which keeps this a pure derivation.
 */

const STORAGE_KEY = "jscc.selectedPeople";

interface PersonFilterState {
  people: PersonWithStats[];
  selectedIds: string[];
  /** Ids to send to the API — `undefined` when everyone is selected. */
  queryIds: string[] | undefined;
  selectedPeople: PersonWithStats[];
  isAllSelected: boolean;
  isLoading: boolean;
  toggle: (personId: string) => void;
  selectOnly: (personId: string) => void;
  selectAll: () => void;
  clear: () => void;
  isSelected: (personId: string) => boolean;
}

const PersonFilterContext = createContext<PersonFilterState | null>(null);

function parseIds(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((value): value is string => typeof value === "string")
      : [];
  } catch {
    return [];
  }
}

export function PersonFilterProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const { status } = useAuth();
  // The roster is fetched here rather than pushed in from the shell, so no
  // component has to copy query data into context via an effect.
  const { data: people, isLoading } = usePeople(false, {
    enabled: status === "authenticated",
  });

  const storedRaw = useStoredValue(STORAGE_KEY);

  const value = useMemo<PersonFilterState>(() => {
    const roster = people ?? [];
    const alive = new Set(roster.map((person) => person.id));
    // Drop ids for people archived or deleted since the last visit.
    const selectedIds = parseIds(storedRaw).filter((id) => alive.has(id));
    const isAllSelected = selectedIds.length === 0;
    const selectedSet = new Set(selectedIds);

    return {
      people: roster,
      selectedIds,
      queryIds: isAllSelected ? undefined : selectedIds,
      selectedPeople: isAllSelected
        ? roster
        : roster.filter((person) => selectedSet.has(person.id)),
      isAllSelected,
      isLoading,
      isSelected: (personId: string) =>
        isAllSelected || selectedSet.has(personId),
      toggle: () => {},
      selectOnly: () => {},
      selectAll: () => {},
      clear: () => {},
    };
  }, [people, storedRaw, isLoading]);

  const write = useCallback((ids: string[]) => {
    writeStoredValue(STORAGE_KEY, JSON.stringify(ids));
  }, []);

  const toggle = useCallback(
    (personId: string) => {
      const current = parseIds(readStoredValue(STORAGE_KEY));
      write(
        current.includes(personId)
          ? current.filter((id) => id !== personId)
          : [...current, personId],
      );
    },
    [write],
  );

  const selectOnly = useCallback(
    (personId: string) => write([personId]),
    [write],
  );
  const selectAll = useCallback(() => write([]), [write]);

  const contextValue = useMemo<PersonFilterState>(
    () => ({ ...value, toggle, selectOnly, selectAll, clear: selectAll }),
    [value, toggle, selectOnly, selectAll],
  );

  return (
    <PersonFilterContext.Provider value={contextValue}>
      {children}
    </PersonFilterContext.Provider>
  );
}

export function usePersonFilter(): PersonFilterState {
  const context = useContext(PersonFilterContext);
  if (!context) {
    throw new Error("usePersonFilter must be used inside PersonFilterProvider");
  }
  return context;
}
