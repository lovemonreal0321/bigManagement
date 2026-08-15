"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { AiReviewFeed } from "@/components/ai/review-feed";
import { EventDetailDialog } from "@/components/calendar/event-detail-dialog";
import { WeekView } from "@/components/calendar/views";
import {
  AwaitingOutcomeCard,
  MetricTiles,
  NeedsAttentionCard,
  PerformanceCard,
  PipelineSummaryCard,
  RecentActivityCard,
  SuggestionsCard,
  UpcomingInterviewsCard,
  useAttentionActions,
} from "@/components/dashboard/sections";
import { OutcomeDialog } from "@/components/interviews/outcome-dialog";
import { PageHeader, PeriodSelect } from "@/components/shared/page-header";
import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Skeleton,
} from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { addDays, rangeToInstants, startOfWeek } from "@/lib/calendar";
import { isoDayIn } from "@/lib/format";
import { usePersonFilter } from "@/lib/person-filter";
import { useCalendarFeed, useDashboard, useSettings } from "@/lib/queries";
import type {
  CalendarFeedEvent,
  InterviewSuggestion,
  UpcomingInterview,
} from "@/lib/types";

export default function DashboardPage() {
  const { queryIds, people, selectedPeople } = usePersonFilter();
  const { data: settings } = useSettings();
  const [period, setPeriod] = React.useState("last_30_days");

  const dashboard = useDashboard(queryIds, period);
  const handleAttentionAction = useAttentionActions();

  const tz = settings?.default_timezone;
  const weekStartsOn = settings?.week_starts_on ?? 0;

  // Shared calendar preview: the current week.
  const weekStart = React.useMemo(
    () => startOfWeek(isoDayIn(new Date(), tz), weekStartsOn),
    [tz, weekStartsOn],
  );
  const weekRange = React.useMemo(
    () => rangeToInstants(weekStart, addDays(weekStart, 6)),
    [weekStart],
  );
  const weekFeed = useCalendarFeed(
    queryIds,
    weekRange.start,
    weekRange.end,
    { show_non_interview: false },
  );

  const [outcomeTarget, setOutcomeTarget] =
    React.useState<UpcomingInterview | null>(null);
  const [selectedEvent, setSelectedEvent] =
    React.useState<CalendarFeedEvent | null>(null);

  function reviewSuggestion(suggestion: InterviewSuggestion) {
    // Reuse the calendar's event dialog, which owns the link/create flow.
    setSelectedEvent({
      id: `calendar:${suggestion.event_id}`,
      kind: "external",
      person_id: suggestion.person_id,
      person_name: suggestion.person_name,
      person_color: suggestion.person_color,
      person_initials: "",
      title: suggestion.title,
      starts_at: suggestion.starts_at,
      ends_at: suggestion.ends_at,
      timezone: null,
      is_all_day: false,
      location: null,
      meeting_url: suggestion.meeting_url,
      application_id: null,
      interview_stage_id: null,
      interview_event_id: null,
      calendar_event_id: suggestion.event_id,
      company_name: suggestion.suggested_company,
      job_title: null,
      stage_badge: null,
      type_key: suggestion.suggested_type,
      type_label: suggestion.suggested_type_label,
      type_short_label: null,
      round_number: suggestion.suggested_round,
      stage_status: null,
      stage_outcome: null,
      classification: "unclassified",
      detection_score: suggestion.score,
      is_suggestion: true,
    });
  }

  if (people.length === 0 && !dashboard.isLoading) {
    return (
      <div>
        <PageHeader title="Dashboard" />
        <Card>
          <EmptyState
            title="No people yet"
            description="Add the people whose job search you are tracking. Everything in the app is organised around them."
            action={
              <Button asChild variant="primary" size="sm">
                <Link href="/people">Add a person</Link>
              </Button>
            }
          />
        </Card>
      </div>
    );
  }

  if (dashboard.isError) {
    return (
      <div>
        <PageHeader title="Dashboard" />
        <Card>
          <ErrorState
            message={
              dashboard.error instanceof ApiError
                ? dashboard.error.message
                : "Could not load the dashboard."
            }
            onRetry={() => dashboard.refetch()}
          />
        </Card>
      </div>
    );
  }

  const data = dashboard.data;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Dashboard"
        description={
          selectedPeople.length === people.length
            ? "Everyone in the workspace"
            : selectedPeople.map((person) => person.display_name).join(", ")
        }
        actions={<PeriodSelect value={period} onChange={setPeriod} />}
      />

      <MetricTiles
        metrics={data?.metrics ?? []}
        loading={dashboard.isLoading}
      />

      {data ? (
        <AwaitingOutcomeCard
          interviews={data.awaiting_outcome}
          onRecord={setOutcomeTarget}
        />
      ) : null}

      {data ? (
        <SuggestionsCard
          interviewSuggestions={data.interview_suggestions}
          followUpSuggestions={data.follow_up_suggestions}
          onLinkEvent={reviewSuggestion}
        />
      ) : null}

      <AiReviewFeed limit={5} />

      <div className="grid gap-4 xl:grid-cols-2">
        <UpcomingInterviewsCard
          interviews={data?.upcoming_interviews ?? []}
          loading={dashboard.isLoading}
          onMarkComplete={setOutcomeTarget}
        />
        <NeedsAttentionCard
          items={data?.needs_attention ?? []}
          loading={dashboard.isLoading}
          onAction={handleAttentionAction}
        />
      </div>

      {/* Shared calendar (spec §23) */}
      <Card>
        <CardHeader
          title="Shared calendar"
          description="This week's interviews across the selected people."
          action={
            <Button asChild variant="ghost" size="xs">
              <Link href="/calendar">
                Full calendar
                <ChevronRight />
              </Link>
            </Button>
          }
        />
        <div className="p-2">
          {weekFeed.isLoading ? (
            <Skeleton className="h-64" />
          ) : (weekFeed.data?.events.length ?? 0) === 0 ? (
            <EmptyState
              title="No interviews this week"
              description="Nothing is scheduled between now and the end of the week."
            />
          ) : (
            <WeekView
              events={weekFeed.data?.events ?? []}
              tz={tz}
              startDay={weekStart}
              onSelect={setSelectedEvent}
            />
          )}
        </div>
      </Card>

      <PipelineSummaryCard
        columns={data?.pipeline ?? []}
        loading={dashboard.isLoading}
      />

      <div className="grid gap-4 xl:grid-cols-2">
        <PerformanceCard
          rows={data?.performance ?? []}
          loading={dashboard.isLoading}
        />
        <RecentActivityCard
          activity={data?.recent_activity ?? []}
          loading={dashboard.isLoading}
        />
      </div>

      <OutcomeDialog
        open={outcomeTarget !== null}
        onOpenChange={(open) => !open && setOutcomeTarget(null)}
        stageId={outcomeTarget?.stage_id ?? null}
        stageName={outcomeTarget?.stage_name}
        companyName={outcomeTarget?.company_name}
        followUpBusinessDays={
          settings?.followup_after_interview_business_days ?? 3
        }
      />

      <EventDetailDialog
        event={selectedEvent}
        onOpenChange={(open) => !open && setSelectedEvent(null)}
        tz={tz}
      />
    </div>
  );
}
