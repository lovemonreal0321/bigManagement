"use client";

/**
 * The person tab bar, shared by every Applications view.
 *
 * Spreadsheet tabs, but they drive the list and the pipeline too, so switching
 * view keeps whoever you were looking at. Kept at the top of the content rather
 * than the bottom, spreadsheet-style, because a long list would otherwise put
 * the tabs a scroll away.
 *
 * The set of tabs follows the global person filter in the header: narrow that
 * and the bar narrows with it.
 */

import { Users } from "lucide-react";
import * as React from "react";

import { PersonAvatar } from "@/components/shared/badges";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import type { PersonWithStats } from "@/lib/types";

/** `null` is the "everyone" tab. */
export type ActivePerson = string | null;

export function PersonTabs({
  people,
  active,
  onChange,
  allowAll = true,
  counts,
  className,
}: {
  people: PersonWithStats[];
  active: ActivePerson;
  onChange: (id: ActivePerson) => void;
  /**
   * The sheet omits this: a spreadsheet tab is one person by definition, so
   * there is nothing sensible for "everyone" to show.
   */
  allowAll?: boolean;
  /** Per-person totals, when the view knows better than `application_count`. */
  counts?: Record<string, number>;
  className?: string;
}) {
  const { canEdit } = useAuth();

  if (people.length === 0) return null;

  const total = people.reduce(
    (sum, person) => sum + (counts?.[person.id] ?? person.application_count),
    0,
  );

  return (
    <div
      role="tablist"
      aria-label="Person"
      className={cn(
        "flex items-stretch gap-1 overflow-x-auto rounded-lg border border-border bg-surface-muted/50 px-1.5 py-1",
        className,
      )}
    >
      {allowAll ? (
        <TabButton
          active={active === null}
          onClick={() => onChange(null)}
          color="var(--muted-foreground)"
          label="Everyone"
          count={total}
          icon={<Users className="size-3.5 text-muted-foreground" />}
        />
      ) : null}

      {people.map((person) => (
        <TabButton
          key={person.id}
          active={active === person.id}
          onClick={() => onChange(person.id)}
          color={person.color}
          label={person.display_name}
          count={counts?.[person.id] ?? person.application_count}
          readOnly={!canEdit(person.id)}
          icon={
            <PersonAvatar
              color={person.color}
              initials={person.initials}
              size="sm"
            />
          }
        />
      ))}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  color,
  label,
  count,
  icon,
  readOnly,
}: {
  active: boolean;
  onClick: () => void;
  color: string;
  label: string;
  count: number;
  icon: React.ReactNode;
  readOnly?: boolean;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-md border-b-2 px-2.5 py-1 text-xs font-medium transition-colors",
        active
          ? "bg-surface text-foreground shadow-sm"
          : "border-b-transparent text-muted-foreground hover:bg-surface/60 hover:text-foreground",
      )}
      style={active ? { borderBottomColor: color } : undefined}
    >
      {icon}
      {label}
      <span className="tabular-nums text-subtle-foreground">{count}</span>
      {readOnly ? <span className="sr-only">(view only)</span> : null}
    </button>
  );
}
