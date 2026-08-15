"use client";

/**
 * The global person filter (spec §4).
 *
 * On wide screens the people are shown as toggle chips so the current
 * selection is readable without opening anything. On narrow screens they
 * collapse into one button that opens the same list as checkboxes.
 *
 * "Everyone" is represented by an empty selection rather than every id, so a
 * newly added person is included automatically.
 */

import { Check, ChevronDown, Users } from "lucide-react";
import * as React from "react";

import { PersonAvatar } from "@/components/shared/badges";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/overlays";
import { Button } from "@/components/ui/primitives";
import { usePersonFilter } from "@/lib/person-filter";
import { cn, personBorder, personTint } from "@/lib/utils";

export function PersonSelector() {
  const {
    people,
    isAllSelected,
    isSelected,
    selectedIds,
    toggle,
    selectOnly,
    selectAll,
  } = usePersonFilter();

  if (people.length === 0) return null;

  const summary = isAllSelected
    ? "All people"
    : selectedIds.length === 1
      ? (people.find((p) => p.id === selectedIds[0])?.display_name ??
        "1 person")
      : `${selectedIds.length} people`;

  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="hidden shrink-0 text-xs font-medium text-muted-foreground lg:inline">
        People
      </span>

      {/* Wide screens: inline chips. */}
      <div className="hidden min-w-0 flex-wrap items-center gap-1.5 md:flex">
        {people.map((person) => {
          const active = isSelected(person.id);
          return (
            <button
              key={person.id}
              type="button"
              onClick={() => toggle(person.id)}
              onDoubleClick={() => selectOnly(person.id)}
              aria-pressed={active}
              title={`${person.display_name}${
                active ? " — selected" : ""
              } (double-click to show only them)`}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border py-0.5 pl-0.5 pr-2.5 text-xs font-medium transition-colors",
                active
                  ? "text-foreground"
                  : "border-border bg-surface text-subtle-foreground hover:text-muted-foreground",
              )}
              style={
                active
                  ? {
                      backgroundColor: personTint(person.color, 14),
                      borderColor: personBorder(person.color, 45),
                    }
                  : undefined
              }
            >
              <PersonAvatar
                color={active ? person.color : "var(--subtle-foreground)"}
                initials={person.initials}
                size="sm"
              />
              <span className="max-w-24 truncate">{person.display_name}</span>
              {active && !isAllSelected ? (
                <Check className="size-3" strokeWidth={3} aria-hidden />
              ) : null}
            </button>
          );
        })}
      </div>

      {/* Controls (and the whole selector on small screens). */}
      <Popover>
        <PopoverTrigger asChild>
          <Button size="sm" variant="secondary" className="shrink-0">
            <Users className="md:hidden" />
            <span className="md:hidden">{summary}</span>
            <span className="hidden md:inline">
              {isAllSelected ? "All" : summary}
            </span>
            <ChevronDown className="size-3.5 opacity-60" />
          </Button>
        </PopoverTrigger>

        <PopoverContent align="end" className="w-64 p-2">
          <div className="mb-2 flex items-center gap-1 border-b border-border pb-2">
            <Button
              size="xs"
              variant={isAllSelected ? "primary" : "ghost"}
              className="flex-1"
              onClick={selectAll}
            >
              Select all
            </Button>
            <Button
              size="xs"
              variant="ghost"
              className="flex-1"
              onClick={selectAll}
              disabled={isAllSelected}
            >
              Clear
            </Button>
          </div>

          <ul className="max-h-72 space-y-0.5 overflow-y-auto">
            {people.map((person) => {
              const active = isSelected(person.id);
              return (
                <li key={person.id}>
                  <div className="group flex items-center gap-2 rounded px-1.5 py-1 hover:bg-surface-hover">
                    <button
                      type="button"
                      onClick={() => toggle(person.id)}
                      className="flex min-w-0 flex-1 items-center gap-2 text-left"
                      aria-pressed={active}
                    >
                      <span
                        className={cn(
                          "flex size-4 shrink-0 items-center justify-center rounded border",
                          active
                            ? "border-transparent"
                            : "border-border-strong bg-surface",
                        )}
                        style={
                          active ? { backgroundColor: person.color } : undefined
                        }
                      >
                        {active ? (
                          <Check
                            className="size-3 text-white"
                            strokeWidth={3}
                            aria-hidden
                          />
                        ) : null}
                      </span>
                      <PersonAvatar
                        color={person.color}
                        initials={person.initials}
                        size="sm"
                      />
                      <span className="truncate text-xs text-foreground">
                        {person.display_name}
                      </span>
                    </button>

                    {/* "Current person" — jump straight to one person. */}
                    <button
                      type="button"
                      onClick={() => selectOnly(person.id)}
                      className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium text-subtle-foreground opacity-0 transition-opacity hover:bg-surface-muted hover:text-foreground group-hover:opacity-100 focus:opacity-100"
                    >
                      Only
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>

          <p className="mt-2 border-t border-border pt-2 text-[11px] leading-snug text-subtle-foreground">
            {isAllSelected
              ? "Showing everyone in the workspace."
              : `Showing ${selectedIds.length} of ${people.length} people. Every page respects this filter.`}
          </p>
        </PopoverContent>
      </Popover>
    </div>
  );
}
