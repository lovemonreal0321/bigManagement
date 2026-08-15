"use client";

/**
 * The two colour systems, kept apart on purpose (spec §42).
 *
 *   `PersonAvatar` / `PersonChip` use the person's own colour — identity.
 *   `StatusBadge` / `OutcomeBadge` use the semantic palette — state.
 *   `StageBadge` is the interview step tag ("R2 · Technical") and is neutral,
 *      so it never competes with either system.
 */

import * as React from "react";

import {
  APPLICATION_STATUS_LABELS,
  APPLICATION_STATUS_TONES,
  FOLLOW_UP_LABELS,
  FOLLOW_UP_TONES,
  INTERVIEW_STATUS_LABELS,
  INTERVIEW_STATUS_TONES,
  OUTCOME_LABELS,
  OUTCOME_TONES,
  PRIORITY_LABELS,
  PRIORITY_TONES,
  TONE_CLASSES,
  TONE_DOT_CLASSES,
  type Tone,
} from "@/lib/format";
import type {
  ApplicationStatus,
  FollowUpComputedStatus,
  InterviewOutcome,
  InterviewStatus,
  Priority,
} from "@/lib/types";
import { cn, personBorder, personTint } from "@/lib/utils";

// --------------------------------------------------------------------------
// Person identity
// --------------------------------------------------------------------------

export function PersonAvatar({
  color,
  initials,
  size = "md",
  className,
  title,
}: {
  color: string;
  initials: string;
  size?: "xs" | "sm" | "md" | "lg";
  className?: string;
  title?: string;
}) {
  const sizes = {
    xs: "size-4 text-[8px]",
    sm: "size-5 text-[9px]",
    md: "size-6 text-[10px]",
    lg: "size-9 text-xs",
  } as const;

  return (
    <span
      title={title}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full font-semibold uppercase leading-none text-white",
        sizes[size],
        className,
      )}
      style={{ backgroundColor: color }}
      aria-hidden={!title}
    >
      {initials}
    </span>
  );
}

export function PersonChip({
  name,
  color,
  initials,
  className,
  showName = true,
  size = "sm",
}: {
  name: string;
  color: string;
  initials: string;
  className?: string;
  showName?: boolean;
  size?: "xs" | "sm" | "md";
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border py-0.5 pl-0.5 pr-2 text-xs font-medium",
        !showName && "pr-0.5",
        className,
      )}
      style={{
        backgroundColor: personTint(color, 10),
        borderColor: personBorder(color, 35),
        color: "var(--foreground)",
      }}
    >
      <PersonAvatar color={color} initials={initials} size={size} />
      {showName ? <span className="truncate">{name}</span> : null}
    </span>
  );
}

/** Left colour rail used on cards and calendar chips. */
export function PersonRail({ color }: { color: string }) {
  return (
    <span
      aria-hidden
      className="absolute inset-y-0 left-0 w-1 rounded-l"
      style={{ backgroundColor: color }}
    />
  );
}

// --------------------------------------------------------------------------
// Semantic state
// --------------------------------------------------------------------------

export function Badge({
  tone = "neutral",
  children,
  className,
  dot,
}: {
  tone?: Tone;
  children: React.ReactNode;
  className?: string;
  dot?: boolean;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] font-medium leading-4",
        TONE_CLASSES[tone],
        className,
      )}
    >
      {dot ? (
        <span
          className={cn("size-1.5 rounded-full", TONE_DOT_CLASSES[tone])}
          aria-hidden
        />
      ) : null}
      {children}
    </span>
  );
}

export function StatusBadge({
  status,
  className,
}: {
  status: ApplicationStatus;
  className?: string;
}) {
  return (
    <Badge tone={APPLICATION_STATUS_TONES[status] ?? "neutral"} className={className} dot>
      {APPLICATION_STATUS_LABELS[status] ?? status}
    </Badge>
  );
}

export function InterviewStatusBadge({
  status,
  className,
}: {
  status: InterviewStatus;
  className?: string;
}) {
  return (
    <Badge tone={INTERVIEW_STATUS_TONES[status] ?? "neutral"} className={className}>
      {INTERVIEW_STATUS_LABELS[status] ?? status}
    </Badge>
  );
}

export function OutcomeBadge({
  outcome,
  className,
}: {
  outcome: InterviewOutcome;
  className?: string;
}) {
  // "Pending" adds nothing next to a Scheduled status, so it is not rendered.
  if (outcome === "pending") return null;
  return (
    <Badge tone={OUTCOME_TONES[outcome] ?? "neutral"} className={className}>
      {OUTCOME_LABELS[outcome] ?? outcome}
    </Badge>
  );
}

export function FollowUpBadge({
  status,
  className,
}: {
  status: FollowUpComputedStatus;
  className?: string;
}) {
  return (
    <Badge tone={FOLLOW_UP_TONES[status] ?? "neutral"} className={className}>
      {FOLLOW_UP_LABELS[status] ?? status}
    </Badge>
  );
}

export function PriorityBadge({
  priority,
  className,
}: {
  priority: Priority;
  className?: string;
}) {
  // Medium is the default and carries no information worth the pixels.
  if (priority === "medium" || priority === "low") return null;
  return (
    <Badge tone={PRIORITY_TONES[priority]} className={className}>
      {PRIORITY_LABELS[priority]}
    </Badge>
  );
}

// --------------------------------------------------------------------------
// Interview step tag
// --------------------------------------------------------------------------

/**
 * The per-step tag: "R2 · Technical".
 *
 * Rendered wherever a stage appears — calendar chips, pipeline cards, the
 * journey timeline, upcoming lists — so a step is always identifiable at a
 * glance.
 */
export function StageBadge({
  badge,
  className,
  variant = "default",
}: {
  badge: string | null | undefined;
  className?: string;
  variant?: "default" | "outline" | "onColor";
}) {
  if (!badge) return null;

  const variants = {
    default: "bg-surface-muted text-muted-foreground",
    outline: "border border-border text-muted-foreground",
    onColor: "bg-black/10 text-current dark:bg-white/15",
  } as const;

  return (
    <span
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] font-medium leading-4",
        variants[variant],
        className,
      )}
    >
      {badge}
    </span>
  );
}
