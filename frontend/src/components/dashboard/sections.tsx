"use client";

import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  Inbox,
  Link2,
  Link2Off,
  Video,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";

import {
  Badge,
  PersonAvatar,
  PersonChip,
  StageBadge,
} from "@/components/shared/badges";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  Skeleton,
} from "@/components/ui/primitives";
import { Tooltip } from "@/components/ui/overlays";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  formatCountdown,
  formatDate,
  formatDayLabel,
  formatPercent,
  formatTime,
} from "@/lib/format";
import {
  useDismissSuggestion,
  useFollowUpAction,
  useCreateFollowUp,
} from "@/lib/queries";
import type {
  Activity,
  AttentionItem,
  FollowUpSuggestion,
  InterviewSuggestion,
  MetricCard,
  PersonComparisonRow,
  PipelineColumn,
  UpcomingInterview,
} from "@/lib/types";
import { cn } from "@/lib/utils";

// --------------------------------------------------------------------------
// Metric tiles (spec §23)
// --------------------------------------------------------------------------

export function MetricTiles({
  metrics,
  loading,
}: {
  metrics: MetricCard[];
  loading?: boolean;
}) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-7">
        {Array.from({ length: 7 }).map((_, index) => (
          <Skeleton key={index} className="h-20" />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-7">
      {metrics.map((metric) => {
        const tile = (
          <div
            className={cn(
              "flex h-full flex-col justify-between rounded-lg border border-border bg-surface p-3 transition-colors",
              metric.href && "hover:border-border-strong hover:bg-surface-hover",
            )}
          >
            <p className="text-[11px] font-medium leading-tight text-muted-foreground">
              {metric.label}
            </p>
            <p className="tabular mt-2 text-2xl font-semibold leading-none text-foreground">
              {metric.value}
            </p>
          </div>
        );
        return metric.href ? (
          <Link key={metric.key} href={metric.href} className="block">
            {tile}
          </Link>
        ) : (
          <div key={metric.key}>{tile}</div>
        );
      })}
    </div>
  );
}

// --------------------------------------------------------------------------
// Upcoming interviews (spec §24)
// --------------------------------------------------------------------------

export function UpcomingInterviewsCard({
  interviews,
  loading,
  onMarkComplete,
}: {
  interviews: UpcomingInterview[];
  loading?: boolean;
  onMarkComplete: (interview: UpcomingInterview) => void;
}) {
  const { canEdit } = useAuth();
  return (
    <Card>
      <CardHeader
        title="Upcoming interviews"
        action={
          <Button asChild variant="ghost" size="xs">
            <Link href="/calendar">
              Calendar
              <ChevronRight />
            </Link>
          </Button>
        }
      />
      {loading ? (
        <CardBody className="space-y-2">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-14" />
          ))}
        </CardBody>
      ) : interviews.length === 0 ? (
        <EmptyState
          icon={CalendarDays}
          title="No interviews scheduled"
          description="Add an interview from an application, or connect a calendar to import them."
          action={
            <Button asChild size="sm" variant="secondary">
              <Link href="/applications">Open applications</Link>
            </Button>
          }
        />
      ) : (
        <ul className="divide-y divide-border">
          {interviews.map((interview) => (
            <li
              key={`${interview.stage_id}:${interview.event_id ?? "stage"}`}
              className="relative flex items-center gap-3 px-4 py-2.5"
            >
              <span
                aria-hidden
                className="absolute inset-y-0 left-0 w-0.5"
                style={{ backgroundColor: interview.person_color }}
              />
              <PersonAvatar
                color={interview.person_color}
                initials={interview.person_initials}
                title={interview.person_name}
                size="md"
              />

              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="truncate text-sm font-medium text-foreground">
                    {interview.company_name}
                  </span>
                  <StageBadge badge={interview.stage_badge} />
                </div>
                <p className="truncate text-xs text-muted-foreground">
                  {interview.job_title}
                </p>
              </div>

              <div className="shrink-0 text-right">
                <p className="text-xs font-medium text-foreground">
                  {formatDayLabel(interview.starts_at, interview.timezone ?? undefined)}
                </p>
                <p className="tabular text-xs text-muted-foreground">
                  {formatTime(interview.starts_at, interview.timezone ?? undefined)}
                  <span className="ml-1 text-subtle-foreground">
                    {formatCountdown(interview.starts_at)}
                  </span>
                </p>
              </div>

              <div className="flex shrink-0 items-center gap-1">
                {interview.meeting_url ? (
                  <Tooltip content="Join meeting">
                    <a
                      href={interview.meeting_url}
                      target="_blank"
                      rel="noreferrer"
                      className="rounded p-1.5 text-muted-foreground hover:bg-surface-hover hover:text-foreground"
                    >
                      <Video className="size-3.5" />
                    </a>
                  </Tooltip>
                ) : null}
                {canEdit(interview.person_id) ? (
                  <Tooltip content="Record the result">
                    <button
                      type="button"
                      onClick={() => onMarkComplete(interview)}
                      className="rounded p-1.5 text-muted-foreground hover:bg-surface-hover hover:text-foreground"
                    >
                      <CheckCircle2 className="size-3.5" />
                    </button>
                  </Tooltip>
                ) : null}
                <Tooltip content="Open application">
                  <Link
                    href={`/applications/${interview.application_id}`}
                    className="rounded p-1.5 text-muted-foreground hover:bg-surface-hover hover:text-foreground"
                  >
                    <ArrowRight className="size-3.5" />
                  </Link>
                </Tooltip>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// --------------------------------------------------------------------------
// Awaiting outcome (spec §49)
// --------------------------------------------------------------------------

export function AwaitingOutcomeCard({
  interviews,
  onRecord,
}: {
  interviews: UpcomingInterview[];
  onRecord: (interview: UpcomingInterview) => void;
}) {
  const { canEdit } = useAuth();
  if (interviews.length === 0) return null;

  return (
    <Card className="border-status-warn/30">
      <CardHeader
        title="How did these go?"
        description="These interviews have passed and still need a result."
      />
      <ul className="divide-y divide-border">
        {interviews.map((interview) => (
          <li
            key={interview.stage_id}
            className="flex flex-wrap items-center gap-2 px-4 py-2.5"
          >
            <PersonAvatar
              color={interview.person_color}
              initials={interview.person_initials}
              title={interview.person_name}
            />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="truncate text-sm font-medium text-foreground">
                  {interview.company_name}
                </span>
                <StageBadge badge={interview.stage_badge} />
              </div>
              <p className="text-xs text-muted-foreground">
                {formatDate(interview.starts_at, interview.timezone ?? undefined)} ·{" "}
                {formatCountdown(interview.starts_at)}
              </p>
            </div>
            {canEdit(interview.person_id) ? (
              <Button
                size="xs"
                variant="primary"
                onClick={() => onRecord(interview)}
              >
                Record result
              </Button>
            ) : null}
          </li>
        ))}
      </ul>
    </Card>
  );
}

// --------------------------------------------------------------------------
// Needs attention (spec §22)
// --------------------------------------------------------------------------

const SEVERITY_STYLES = {
  high: "border-l-status-danger",
  medium: "border-l-status-warn",
  low: "border-l-status-info",
} as const;

export function NeedsAttentionCard({
  items,
  loading,
  onAction,
}: {
  items: AttentionItem[];
  loading?: boolean;
  onAction: (action: string, item: AttentionItem) => void;
}) {
  const { canEdit } = useAuth();
  const ACTION_LABELS: Record<string, string> = {
    complete: "Mark done",
    snooze: "Snooze",
    change_date: "Change date",
    open_application: "Open",
    mark_ghosted: "Mark ghosted",
    set_outcome: "Record result",
    create_follow_up: "Add follow-up",
    reschedule: "Reschedule",
    open_calendar: "Open calendar",
  };

  return (
    <Card>
      <CardHeader
        title="Needs attention"
        description="Everything waiting on you, most urgent first."
      />
      {loading ? (
        <CardBody className="space-y-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-16" />
          ))}
        </CardBody>
      ) : items.length === 0 ? (
        <EmptyState
          icon={CheckCircle2}
          title="Nothing needs attention"
          description="No overdue follow-ups, no results outstanding, no conflicts."
        />
      ) : (
        <ul className="divide-y divide-border">
          {items.map((item) => (
            <li
              key={item.id}
              className={cn(
                "border-l-2 px-4 py-2.5",
                SEVERITY_STYLES[item.severity],
              )}
            >
              <div className="flex flex-wrap items-start gap-2">
                <PersonAvatar
                  color={item.person_color}
                  initials={item.person_initials || "?"}
                  title={item.person_name}
                  className="mt-0.5"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="truncate text-sm font-medium text-foreground">
                      {item.company_name}
                    </span>
                    {item.stage_badge ? (
                      <StageBadge badge={item.stage_badge} />
                    ) : null}
                    {item.kind === "scheduling_conflict" ? (
                      <Badge tone="danger">
                        <AlertTriangle className="size-3" />
                        Conflict
                      </Badge>
                    ) : null}
                  </div>
                  <p className="truncate text-xs text-foreground/90">
                    {item.headline}
                  </p>
                  <p className="text-xs text-muted-foreground">{item.detail}</p>
                </div>
              </div>

              <div className="mt-2 flex flex-wrap gap-1 pl-8">
                {item.actions.map((action) =>
                  action === "open_application" && item.application_id ? (
                    <Button key={action} asChild size="xs" variant="ghost">
                      <Link href={`/applications/${item.application_id}`}>
                        Open
                      </Link>
                    </Button>
                  ) : action === "open_calendar" ? (
                    <Button key={action} asChild size="xs" variant="ghost">
                      <Link href="/calendar">Open calendar</Link>
                    </Button>
                  ) : !canEdit(item.person_id) ? null : (
                    <Button
                      key={action}
                      size="xs"
                      variant="ghost"
                      onClick={() => onAction(action, item)}
                    >
                      {ACTION_LABELS[action] ?? action}
                    </Button>
                  ),
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// --------------------------------------------------------------------------
// Pipeline summary (spec §23)
// --------------------------------------------------------------------------

export function PipelineSummaryCard({
  columns,
  loading,
}: {
  columns: PipelineColumn[];
  loading?: boolean;
}) {
  const total = columns.reduce((sum, column) => sum + column.count, 0);

  return (
    <Card>
      <CardHeader
        title="Pipeline"
        action={
          <Button asChild variant="ghost" size="xs">
            <Link href="/applications?view=pipeline">
              Open board
              <ChevronRight />
            </Link>
          </Button>
        }
      />
      <CardBody>
        {loading ? (
          <Skeleton className="h-16" />
        ) : total === 0 ? (
          <p className="py-4 text-center text-xs text-muted-foreground">
            No applications yet.
          </p>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
              {columns.map((column) => (
                <Link
                  key={column.key}
                  href={`/applications?column=${column.key}`}
                  className="rounded-md border border-border px-2 py-2 text-center transition-colors hover:bg-surface-hover"
                >
                  <p className="tabular text-lg font-semibold leading-none text-foreground">
                    {column.count}
                  </p>
                  <p className="mt-1 text-[11px] leading-tight text-muted-foreground">
                    {column.label}
                  </p>
                </Link>
              ))}
            </div>
            <div
              className="mt-3 flex h-1.5 overflow-hidden rounded-full bg-surface-muted"
              role="img"
              aria-label="Pipeline distribution"
            >
              {columns.map((column) =>
                column.count > 0 ? (
                  <div
                    key={column.key}
                    className="h-full"
                    style={{
                      width: `${(column.count / total) * 100}%`,
                      backgroundColor: PIPELINE_BAR_COLORS[column.key] ?? "var(--status-neutral)",
                    }}
                    title={`${column.label}: ${column.count}`}
                  />
                ) : null,
              )}
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}

const PIPELINE_BAR_COLORS: Record<string, string> = {
  applied: "var(--status-neutral)",
  screening: "var(--status-info)",
  interviewing: "var(--status-info)",
  final: "var(--status-offer)",
  offer: "var(--status-success)",
  closed: "var(--border-strong)",
};

// --------------------------------------------------------------------------
// Performance (spec §23, §28)
// --------------------------------------------------------------------------

export function PerformanceCard({
  rows,
  loading,
}: {
  rows: PersonComparisonRow[];
  loading?: boolean;
}) {
  return (
    <Card>
      <CardHeader
        title="Performance"
        description="Informational, not a scoreboard."
        action={
          <Button asChild variant="ghost" size="xs">
            <Link href="/analytics">
              Analytics
              <ChevronRight />
            </Link>
          </Button>
        }
      />
      {loading ? (
        <CardBody>
          <Skeleton className="h-24" />
        </CardBody>
      ) : rows.length === 0 ? (
        <EmptyState title="No data for this period" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-subtle-foreground">
                <th className="px-4 py-2 font-medium">Person</th>
                <th className="px-2 py-2 text-right font-medium">Apps</th>
                <th className="px-2 py-2 text-right font-medium">Interviews</th>
                <th className="px-2 py-2 text-right font-medium">Pass rate</th>
                <th className="px-2 py-2 text-right font-medium">Finals</th>
                <th className="px-4 py-2 text-right font-medium">Offers</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((row) => (
                <tr key={row.person_id}>
                  <td className="px-4 py-2">
                    <PersonChip
                      name={row.person_name}
                      color={row.person_color}
                      initials={row.person_initials}
                    />
                  </td>
                  <td className="tabular px-2 py-2 text-right">
                    {row.applications}
                  </td>
                  <td className="tabular px-2 py-2 text-right">
                    {row.interviews_held}
                  </td>
                  <td className="tabular px-2 py-2 text-right">
                    <Tooltip
                      content={`${row.pass_rate.numerator} of ${row.pass_rate.denominator} decided interviews passed`}
                    >
                      <span
                        className={cn(
                          !row.pass_rate.is_meaningful &&
                            "text-muted-foreground",
                        )}
                      >
                        {formatPercent(row.pass_rate.percent)}
                      </span>
                    </Tooltip>
                  </td>
                  <td className="tabular px-2 py-2 text-right">
                    {row.final_rounds}
                  </td>
                  <td className="tabular px-4 py-2 text-right font-medium">
                    {row.offers}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// --------------------------------------------------------------------------
// Suggestions (spec §8, §20)
// --------------------------------------------------------------------------

export function SuggestionsCard({
  interviewSuggestions,
  followUpSuggestions,
  onLinkEvent,
}: {
  interviewSuggestions: InterviewSuggestion[];
  followUpSuggestions: FollowUpSuggestion[];
  onLinkEvent: (suggestion: InterviewSuggestion) => void;
}) {
  const { canEdit } = useAuth();
  const dismiss = useDismissSuggestion();
  const createFollowUp = useCreateFollowUp();

  if (interviewSuggestions.length === 0 && followUpSuggestions.length === 0) {
    return null;
  }

  async function acceptFollowUp(suggestion: FollowUpSuggestion) {
    try {
      await createFollowUp.mutateAsync({
        application_id: suggestion.application_id,
        interview_stage_id: suggestion.interview_stage_id,
        title: suggestion.title,
        reason: suggestion.reason,
        due_date: suggestion.suggested_due_date,
      });
      toast.success("Follow-up created");
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : "Could not create the follow-up.",
      );
    }
  }

  return (
    <Card className="border-primary/30">
      <CardHeader
        title="Suggestions"
        description={
          interviewSuggestions.length > 0
            ? "Interviews on the calendar with no application behind them, and follow-ups worth booking. Nothing here is created until you accept it."
            : "Nothing here is created until you accept it."
        }
      />
      <ul className="divide-y divide-border">
        {interviewSuggestions.map((suggestion) => (
          <li key={suggestion.event_id} className="px-4 py-2.5">
            <div className="flex items-start gap-2">
              <Link2Off className="mt-0.5 size-4 shrink-0 text-status-warn" />
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-foreground">
                  Which application is this interview for?
                </p>
                <p className="truncate text-sm text-foreground">
                  {suggestion.title}
                </p>
                <p className="text-xs text-muted-foreground">
                  {suggestion.person_name} ·{" "}
                  {formatDate(suggestion.starts_at)}{" "}
                  {formatTime(suggestion.starts_at)}
                  {suggestion.reasons[0] ? ` · ${suggestion.reasons[0]}` : ""}
                </p>
              </div>
            </div>
            {canEdit(suggestion.person_id) ? (
              <div className="mt-2 flex flex-wrap gap-1 pl-6">
                <Button
                  size="xs"
                  variant="primary"
                  onClick={() => onLinkEvent(suggestion)}
                >
                  <Link2 />
                  Connect
                </Button>
                <Button
                  size="xs"
                  variant="ghost"
                  onClick={() => dismiss.mutate(suggestion.event_id)}
                  title="Stop asking about this event. It still counts as an interview."
                >
                  Not now
                </Button>
              </div>
            ) : null}
          </li>
        ))}

        {followUpSuggestions.map((suggestion) => (
          <li
            key={`${suggestion.rule_key}:${suggestion.interview_stage_id ?? suggestion.application_id}`}
            className="px-4 py-2.5"
          >
            <div className="flex items-start gap-2">
              <CalendarClock className="mt-0.5 size-4 shrink-0 text-status-warn" />
              <div className="min-w-0 flex-1">
                <p className="text-sm text-foreground">{suggestion.title}</p>
                <p className="text-xs text-muted-foreground">
                  {suggestion.reason} Suggested for{" "}
                  {formatDate(`${suggestion.suggested_due_date}T12:00:00Z`)}.
                </p>
              </div>
            </div>
            <div className="mt-2 flex flex-wrap gap-1 pl-6">
              {canEdit(suggestion.person_id) ? (
                <Button
                  size="xs"
                  variant="primary"
                  loading={createFollowUp.isPending}
                  onClick={() => void acceptFollowUp(suggestion)}
                >
                  Create follow-up
                </Button>
              ) : null}
              <Button asChild size="xs" variant="ghost">
                <Link href={`/applications/${suggestion.application_id}`}>
                  Open application
                </Link>
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

// --------------------------------------------------------------------------
// Recent activity (spec §33)
// --------------------------------------------------------------------------

export function RecentActivityCard({
  activity,
  loading,
}: {
  activity: Activity[];
  loading?: boolean;
}) {
  return (
    <Card>
      <CardHeader title="Recent activity" />
      {loading ? (
        <CardBody className="space-y-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-8" />
          ))}
        </CardBody>
      ) : activity.length === 0 ? (
        <EmptyState icon={Inbox} title="Nothing has happened yet" />
      ) : (
        <ul className="divide-y divide-border">
          {activity.map((entry) => (
            <li key={entry.id} className="flex items-start gap-2 px-4 py-2">
              {entry.person_color ? (
                <span
                  className="mt-1.5 size-1.5 shrink-0 rounded-full"
                  style={{ backgroundColor: entry.person_color }}
                  aria-hidden
                />
              ) : (
                <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-border-strong" />
              )}
              <div className="min-w-0 flex-1">
                <p className="text-xs leading-snug text-foreground">
                  {entry.message}
                </p>
                <p className="text-[11px] text-subtle-foreground">
                  {formatCountdown(entry.created_at)}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// --------------------------------------------------------------------------
// Follow-up quick actions used by the attention panel
// --------------------------------------------------------------------------

export function useAttentionActions() {
  const followUpAction = useFollowUpAction();

  return React.useCallback(
    async (action: string, item: AttentionItem) => {
      try {
        if (action === "complete" && item.follow_up_id) {
          await followUpAction.mutateAsync({
            id: item.follow_up_id,
            action: "complete",
          });
          toast.success("Follow-up completed");
        } else if (action === "snooze" && item.follow_up_id) {
          await followUpAction.mutateAsync({
            id: item.follow_up_id,
            action: "snooze",
            body: { days: 3 },
          });
          toast.success("Snoozed for 3 days");
        }
      } catch (error) {
        toast.error(
          error instanceof ApiError ? error.message : "Could not update that.",
        );
      }
    },
    [followUpAction],
  );
}
