"use client";

/**
 * The path so far, in one line: applied → R1 → R2 → …
 *
 * The application detail page has a full vertical timeline. This is the
 * compact version, for places where the journey is context rather than the
 * subject — chiefly a calendar event, where the question is "where does this
 * meeting sit in the process?".
 */

import { Check, Circle, Clock, X } from "lucide-react";
import * as React from "react";

import { formatDate, formatDateOnly } from "@/lib/format";
import type { InterviewStage } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Outcome first — a decided result is what you want to see at a glance. */
function stageTone(stage: InterviewStage) {
  if (stage.outcome === "passed") return "passed";
  if (stage.outcome === "failed") return "failed";
  if (stage.status === "cancelled") return "cancelled";
  if (stage.status === "completed" || stage.outcome === "waiting") return "waiting";
  return "upcoming";
}

const TONE_STYLES: Record<string, string> = {
  passed: "border-status-success text-status-success",
  failed: "border-status-danger text-status-danger",
  cancelled: "border-border text-subtle-foreground line-through",
  waiting: "border-status-warn text-status-warn",
  upcoming: "border-border text-muted-foreground",
};

const TONE_ICONS: Record<string, React.ReactNode> = {
  passed: <Check className="size-3" />,
  failed: <X className="size-3" />,
  cancelled: <X className="size-3" />,
  waiting: <Clock className="size-3" />,
  upcoming: <Circle className="size-3" />,
};

export function JourneyStrip({
  appliedDate,
  stages,
  highlightStageId,
  className,
}: {
  appliedDate: string | null;
  stages: InterviewStage[];
  /** The round this view is about, if any — drawn with a ring. */
  highlightStageId?: string | null;
  className?: string;
}) {
  const ordered = React.useMemo(
    () => [...stages].sort((a, b) => a.sequence - b.sequence),
    [stages],
  );

  return (
    <ol
      className={cn("flex flex-wrap items-center gap-1 text-xs", className)}
      aria-label="Interview journey"
    >
      <li className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-muted-foreground">
        Applied
        {appliedDate ? (
          <span className="text-subtle-foreground">
            {formatDateOnly(appliedDate)}
          </span>
        ) : null}
      </li>

      {ordered.length === 0 ? (
        <li className="text-subtle-foreground">· no interviews recorded yet</li>
      ) : null}

      {ordered.map((stage) => {
        const tone = stageTone(stage);
        return (
          <React.Fragment key={stage.id}>
            <li aria-hidden className="text-subtle-foreground">
              →
            </li>
            <li
              className={cn(
                "inline-flex items-center gap-1 rounded-full border px-2 py-0.5",
                TONE_STYLES[tone],
                stage.id === highlightStageId &&
                  "ring-2 ring-primary ring-offset-1 ring-offset-surface",
              )}
              title={`${stage.name} · ${stage.status}${
                stage.outcome !== "pending" ? ` · ${stage.outcome}` : ""
              }`}
            >
              {TONE_ICONS[tone]}
              {stage.stage_badge ?? stage.name}
              {stage.scheduled_start ? (
                <span className="text-subtle-foreground">
                  {formatDate(stage.scheduled_start)}
                </span>
              ) : null}
              {/* One round can span several sittings (spec §16). */}
              {stage.event_count > 1 ? (
                <span className="text-subtle-foreground">
                  ·{stage.event_count} slots
                </span>
              ) : null}
            </li>
          </React.Fragment>
        );
      })}
    </ol>
  );
}
