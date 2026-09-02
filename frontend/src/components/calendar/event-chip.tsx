"use client";

/**
 * A calendar event block.
 *
 * Every interview chip shows, in priority order: person colour, company, the
 * step tag ("R2 · Technical"), and the time. Job title appears only when there
 * is room (spec §9).
 */

import { Link2Off, Video } from "lucide-react";
import * as React from "react";

import { PersonAvatar, StageBadge } from "@/components/shared/badges";
import { stepColor } from "@/lib/event-color";
import { formatTime } from "@/lib/format";
import type { CalendarFeedEvent } from "@/lib/types";
import { cn, personBorder, personTint } from "@/lib/utils";

export function EventChip({
  event,
  tz,
  size = "md",
  showPerson = true,
  onSelect,
  className,
  style,
}: {
  event: CalendarFeedEvent;
  tz?: string;
  size?: "xs" | "sm" | "md";
  showPerson?: boolean;
  onSelect?: (event: CalendarFeedEvent) => void;
  className?: string;
  style?: React.CSSProperties;
}) {
  const isInterview = event.kind === "interview";
  const cancelled = event.stage_status === "cancelled";
  const color = event.person_color;
  // Person colour still says *who*; the step colour says *which round*.
  const step = stepColor(event);
  const counts = event.counts_as_interview;

  const label = isInterview
    ? (event.company_name ?? event.title)
    : event.title;

  return (
    <button
      type="button"
      onClick={() => onSelect?.(event)}
      title={[
        label,
        event.stage_badge ?? step?.label,
        formatTime(event.starts_at, tz),
        event.needs_application ? "no application connected" : null,
      ]
        .filter(Boolean)
        .join(" · ")}
      className={cn(
        "group relative flex w-full min-w-0 flex-col overflow-hidden rounded border text-left transition-colors",
        size === "xs" ? "gap-0 px-1 py-0.5" : "gap-0.5 px-1.5 py-1",
        cancelled && "opacity-55 line-through",
        onSelect && "hover:brightness-105",
        className,
      )}
      style={{
        // Person colour identifies *who*; it is never used for status.
        backgroundColor: counts ? personTint(color, 16) : "var(--surface-muted)",
        borderColor: counts ? personBorder(color, 45) : "var(--border)",
        ...style,
      }}
    >
      {/* The spine carries the step. Person identity is already on the avatar
          and the tint, so this is the one place a round can have a colour of
          its own without two schemes fighting. */}
      <span
        aria-hidden
        className="absolute inset-y-0 left-0 w-1"
        style={{ backgroundColor: step?.color ?? "var(--border-strong)" }}
      />

      <span className="flex min-w-0 items-center gap-1 pl-1">
        {showPerson ? (
          <PersonAvatar
            color={color}
            initials={event.person_initials}
            size="xs"
            title={event.person_name}
          />
        ) : null}
        <span
          className={cn(
            "min-w-0 flex-1 truncate font-medium text-foreground",
            size === "xs" ? "text-[10px] leading-tight" : "text-[11px] leading-tight",
          )}
        >
          {label}
        </span>
        {event.needs_application ? (
          <Link2Off
            className="size-3 shrink-0 text-status-warn"
            aria-label="No application connected"
          />
        ) : null}
        {event.meeting_url && size !== "xs" ? (
          <Video className="size-3 shrink-0 text-muted-foreground" aria-hidden />
        ) : null}
      </span>

      {size !== "xs" ? (
        <span className="flex min-w-0 items-center gap-1 pl-1">
          {event.stage_badge ? (
            <StageBadge
              badge={event.stage_badge}
              variant="onColor"
              className="px-1 py-0 text-[10px] leading-4"
            />
          ) : null}
          <span className="tabular truncate text-[10px] leading-4 text-muted-foreground">
            {formatTime(event.starts_at, tz)}
          </span>
        </span>
      ) : null}

      {size === "md" && isInterview && event.job_title ? (
        <span className="hidden truncate pl-1 text-[10px] leading-4 text-muted-foreground @[9rem]:block">
          {event.job_title}
        </span>
      ) : null}
    </button>
  );
}

/** Single-line variant for month cells and dense lists. */
export function EventLine({
  event,
  tz,
  onSelect,
}: {
  event: CalendarFeedEvent;
  tz?: string;
  onSelect?: (event: CalendarFeedEvent) => void;
}) {
  const isInterview = event.kind === "interview";
  const step = stepColor(event);
  return (
    <button
      type="button"
      onClick={() => onSelect?.(event)}
      title={[
        event.company_name ?? event.title,
        step?.label,
        formatTime(event.starts_at, tz),
        event.needs_application ? "no application connected" : null,
      ]
        .filter(Boolean)
        .join(" · ")}
      className={cn(
        "flex w-full min-w-0 items-center gap-1 rounded px-1 py-0.5 text-left transition-colors hover:bg-surface-hover",
        event.stage_status === "cancelled" && "opacity-55 line-through",
      )}
    >
      <span
        className="size-1.5 shrink-0 rounded-full"
        style={{ backgroundColor: step?.color ?? "var(--border-strong)" }}
        aria-hidden
      />
      <span className="tabular shrink-0 text-[10px] text-muted-foreground">
        {formatTime(event.starts_at, tz).replace(":00", "")}
      </span>
      <span className="min-w-0 flex-1 truncate text-[11px] text-foreground">
        {isInterview ? (event.company_name ?? event.title) : event.title}
      </span>
      {event.stage_badge ? (
        <span className="hidden shrink-0 text-[10px] text-muted-foreground sm:inline">
          {event.stage_badge}
        </span>
      ) : null}
    </button>
  );
}
