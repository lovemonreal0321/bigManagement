"use client";

/**
 * The marker shown where edit controls would be, for a person this user does
 * not look after.
 *
 * Saying so beats hiding everything silently: without it, a general user sees
 * a page that looks subtly broken rather than one that is deliberately
 * read-only.
 */

import { Eye } from "lucide-react";

import { Tooltip } from "@/components/ui/overlays";
import { useAuth } from "@/lib/auth";

export function ReadOnlyNote({ className }: { className?: string }) {
  return (
    <Tooltip content="Only an administrator or an assigned user can change this person's records.">
      <span
        className={
          "inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground " +
          (className ?? "")
        }
      >
        <Eye className="size-3" />
        View only
      </span>
    </Tooltip>
  );
}

/**
 * `canEdit` for a single person, as a hook — the common case, and shorter than
 * destructuring `useAuth()` at every call site.
 */
export function useCanEdit(personId: string | null | undefined): boolean {
  return useAuth().canEdit(personId);
}
