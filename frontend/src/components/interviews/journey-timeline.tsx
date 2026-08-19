"use client";

/**
 * Interview Journey timeline (spec §17, §18).
 *
 * A vertical spine from "Applied" through every recorded stage. Each node is
 * clickable, carries its step tag, date, type, result and notes, and is
 * coloured by outcome: passed green, failed red, waiting amber, scheduled
 * blue, cancelled grey.
 */

import {
  Check,
  CircleDashed,
  Clock,
  MoreHorizontal,
  Video,
  X,
} from "lucide-react";
import * as React from "react";

import { OutcomeBadge, StageBadge } from "@/components/shared/badges";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/overlays";
import { Button } from "@/components/ui/primitives";
import {
  formatDate,
  formatDateOnly,
  formatTime,
  INTERVIEW_STATUS_LABELS,
} from "@/lib/format";
import type { InterviewStage } from "@/lib/types";
import { cn } from "@/lib/utils";

type NodeTone = "success" | "danger" | "warn" | "info" | "neutral";

function toneForStage(stage: InterviewStage): NodeTone {
  switch (stage.outcome) {
    case "passed":
      return "success";
    case "failed":
      return "danger";
    case "waiting":
      return "warn";
    case "cancelled":
    case "withdrawn":
      return "neutral";
    default:
      return stage.status === "scheduled" ? "info" : "neutral";
  }
}

const NODE_STYLES: Record<NodeTone, string> = {
  success: "border-status-success bg-status-success text-white",
  danger: "border-status-danger bg-status-danger text-white",
  warn: "border-status-warn bg-status-warn text-white",
  info: "border-status-info bg-status-info text-white",
  neutral: "border-border-strong bg-surface text-muted-foreground",
};

const RAIL_STYLES: Record<NodeTone, string> = {
  success: "bg-status-success/40",
  danger: "bg-status-danger/40",
  warn: "bg-status-warn/40",
  info: "bg-status-info/40",
  neutral: "bg-border",
};

function NodeIcon({ tone }: { tone: NodeTone }) {
  switch (tone) {
    case "success":
      return <Check className="size-3" strokeWidth={3} />;
    case "danger":
      return <X className="size-3" strokeWidth={3} />;
    case "warn":
      return <Clock className="size-3" strokeWidth={2.5} />;
    case "info":
      return <span className="size-1.5 rounded-full bg-white" />;
    default:
      return <CircleDashed className="size-3" />;
  }
}

export function JourneyTimeline({
  appliedDate,
  stages,
  tz,
  onEdit,
  onRecordOutcome,
  onDelete,
}: {
  appliedDate: string | null;
  stages: InterviewStage[];
  tz?: string;
  /**
   * Omit the callbacks to render a read-only journey — the actions menu
   * disappears with them, rather than offering something that would be
   * refused.
   */
  onEdit?: (stage: InterviewStage) => void;
  onRecordOutcome?: (stage: InterviewStage) => void;
  onDelete?: (stage: InterviewStage) => void;
}) {
  const readOnly = !onEdit && !onRecordOutcome && !onDelete;
  return (
    <ol className="relative">
      {/* "Applied" is always the first node of the journey. */}
      <li className="relative flex gap-3 pb-5">
        <span
          aria-hidden
          className={cn(
            "absolute left-[11px] top-6 h-full w-px",
            stages.length > 0 ? "bg-status-success/40" : "bg-transparent",
          )}
        />
        <span className="z-10 flex size-6 shrink-0 items-center justify-center rounded-full border-2 border-status-success bg-status-success text-white">
          <Check className="size-3" strokeWidth={3} />
        </span>
        <div className="min-w-0 flex-1 pt-0.5">
          <p className="text-sm font-medium text-foreground">Applied</p>
          <p className="text-xs text-muted-foreground">
            {appliedDate ? formatDateOnly(appliedDate) : "Date not recorded"}
          </p>
        </div>
      </li>

      {stages.map((stage, index) => {
        const tone = toneForStage(stage);
        const isLast = index === stages.length - 1;

        return (
          <li key={stage.id} className="relative flex gap-3 pb-5 last:pb-0">
            {!isLast ? (
              <span
                aria-hidden
                className={cn(
                  "absolute left-[11px] top-6 h-full w-px",
                  RAIL_STYLES[tone],
                )}
              />
            ) : null}

            <span
              className={cn(
                "z-10 flex size-6 shrink-0 items-center justify-center rounded-full border-2",
                NODE_STYLES[tone],
              )}
            >
              <NodeIcon tone={tone} />
            </span>

            <div className="min-w-0 flex-1 rounded-md border border-border bg-surface p-2.5">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="truncate text-sm font-medium text-foreground">
                      {stage.name}
                    </span>
                    <StageBadge badge={stage.stage_badge} />
                  </div>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {stage.scheduled_start
                      ? `${formatDate(stage.scheduled_start, tz)} · ${formatTime(
                          stage.scheduled_start,
                          tz,
                        )}`
                      : "Not scheduled yet"}
                    {stage.result_date
                      ? ` · result ${formatDateOnly(stage.result_date)}`
                      : ""}
                  </p>
                </div>

                <div className="flex shrink-0 items-center gap-1">
                  <OutcomeBadge outcome={stage.outcome} />
                  {stage.outcome === "pending" ? (
                    <span className="rounded bg-status-info-bg px-1.5 py-0.5 text-[11px] font-medium text-status-info">
                      {INTERVIEW_STATUS_LABELS[stage.status]}
                    </span>
                  ) : null}

                  {readOnly ? null : (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          size="icon-sm"
                          variant="ghost"
                          aria-label="Actions"
                        >
                          <MoreHorizontal />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent>
                        {onRecordOutcome ? (
                          <DropdownMenuItem
                            onSelect={() => onRecordOutcome(stage)}
                          >
                            Record result
                          </DropdownMenuItem>
                        ) : null}
                        {onEdit ? (
                          <DropdownMenuItem onSelect={() => onEdit(stage)}>
                            Edit interview
                          </DropdownMenuItem>
                        ) : null}
                        {onDelete ? (
                          <DropdownMenuItem
                            destructive
                            onSelect={() => onDelete(stage)}
                          >
                            Delete
                          </DropdownMenuItem>
                        ) : null}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  )}
                </div>
              </div>

              {/* Multi-slot stages list their blocks (spec §16). */}
              {stage.events.length > 1 ? (
                <ul className="mt-2 space-y-1 border-t border-border pt-2">
                  {stage.events.map((event) => (
                    <li
                      key={event.id}
                      className="flex items-center gap-2 text-xs"
                    >
                      <span className="tabular w-16 shrink-0 text-muted-foreground">
                        {formatTime(event.starts_at, event.timezone ?? tz)}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-foreground">
                        {event.title}
                      </span>
                      {event.type_short_label ? (
                        <StageBadge badge={event.type_short_label} />
                      ) : null}
                      {event.meeting_url ? (
                        <a
                          href={event.meeting_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-muted-foreground hover:text-foreground"
                          aria-label="Join meeting"
                        >
                          <Video className="size-3.5" />
                        </a>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : null}

              {stage.notes ? (
                <p className="mt-2 whitespace-pre-wrap border-t border-border pt-2 text-xs text-muted-foreground">
                  {stage.notes}
                </p>
              ) : null}

              {stage.events.some((event) => event.sync_error) ? (
                <p className="mt-2 text-[11px] text-status-warn">
                  {stage.events.find((event) => event.sync_error)?.sync_error}
                </p>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
