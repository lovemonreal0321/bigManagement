"use client";

import { AlertTriangle, Info } from "lucide-react";
import * as React from "react";

import {
  CountTile,
  FunnelChart,
  PersonComparisonChart,
  PersonComparisonTable,
  RateTile,
  TrendChart,
  TypePerformanceChart,
} from "@/components/analytics/charts";
import { PageHeader, PeriodSelect } from "@/components/shared/page-header";
import { PersonAvatar } from "@/components/shared/badges";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/overlays";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  Input,
  Skeleton,
} from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { formatDateOnly, formatMoney } from "@/lib/format";
import { usePersonFilter } from "@/lib/person-filter";
import { useAnalytics, useWorkload } from "@/lib/queries";

export default function AnalyticsPage() {
  const { queryIds, selectedPeople } = usePersonFilter();
  const [period, setPeriod] = React.useState("last_30_days");
  const [customStart, setCustomStart] = React.useState("");
  const [customEnd, setCustomEnd] = React.useState("");

  const range =
    period === "custom" && customStart && customEnd
      ? { start: customStart, end: customEnd }
      : undefined;

  const analytics = useAnalytics(
    queryIds,
    period === "custom" && !range ? "last_30_days" : period,
    range,
  );
  const workload = useWorkload(queryIds);

  const data = analytics.data;

  if (analytics.isError) {
    return (
      <div>
        <PageHeader title="Analytics" />
        <Card>
          <ErrorState
            message={
              analytics.error instanceof ApiError
                ? analytics.error.message
                : "Could not load analytics."
            }
            onRetry={() => analytics.refetch()}
          />
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Analytics"
        description={
          selectedPeople.length === 1
            ? selectedPeople[0].display_name
            : `${selectedPeople.length} people`
        }
        actions={
          <>
            <PeriodSelect value={period} onChange={setPeriod} />
            <Popover>
              <PopoverTrigger asChild>
                <Button size="sm" variant="ghost" aria-label="How these are calculated">
                  <Info />
                  <span className="hidden sm:inline">How these are counted</span>
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-80">
                <p className="mb-2 text-xs font-semibold text-foreground">
                  How these numbers are counted
                </p>
                <div className="space-y-2 text-[11px] leading-snug text-muted-foreground">
                  {Object.entries(data?.notes ?? {}).map(([key, note]) => (
                    <p key={key}>{note}</p>
                  ))}
                </div>
              </PopoverContent>
            </Popover>
          </>
        }
      >
        {period === "custom" ? (
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label className="mb-1 block text-[11px] text-muted-foreground">
                From
              </label>
              <Input
                type="date"
                value={customStart}
                onChange={(event) => setCustomStart(event.target.value)}
                className="h-8 w-40 text-xs"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-muted-foreground">
                To
              </label>
              <Input
                type="date"
                value={customEnd}
                onChange={(event) => setCustomEnd(event.target.value)}
                className="h-8 w-40 text-xs"
              />
            </div>
          </div>
        ) : null}
      </PageHeader>

      {analytics.isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-24" />
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      ) : !data ? null : data.volume.applications === 0 &&
        data.volume.interview_stages === 0 ? (
        <Card>
          <EmptyState
            title="No data in this period"
            description="Try a wider period, or add applications and interviews first."
          />
        </Card>
      ) : (
        <>
          {/* Volume (spec §25) */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <CountTile label="Applications" value={data.volume.applications} />
            <CountTile
              label="Interviews held"
              value={data.volume.interviews_held}
              hint={`${data.volume.scheduled} scheduled`}
            />
            <CountTile label="Passed" value={data.volume.passed} />
            <CountTile label="Failed" value={data.volume.failed} />
            <CountTile
              label="Final rounds"
              value={data.volume.final_rounds}
            />
            <CountTile
              label="Offers"
              value={data.volume.offers}
              hint={`${data.volume.accepted} accepted`}
            />
          </div>

          {/* Conversion (spec §26) */}
          <Card>
            <CardHeader
              title="Conversion"
              description="Every rate shows the counts behind it."
            />
            <CardBody>
              <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
                <RateTile
                  label="Application → Interview"
                  rate={data.conversions.application_to_interview}
                />
                <RateTile
                  label="First → Next round"
                  rate={data.conversions.first_to_next_round}
                />
                <RateTile
                  label="Interview pass rate"
                  rate={data.conversions.interview_pass_rate}
                  hint="Passed ÷ (passed + failed)"
                />
                <RateTile
                  label="Technical pass rate"
                  rate={data.conversions.technical_pass_rate}
                />
                <RateTile
                  label="Final → Offer"
                  rate={data.conversions.final_to_offer}
                />
                <RateTile
                  label="Application → Offer"
                  rate={data.conversions.application_to_offer}
                />
                <RateTile
                  label="Offer acceptance"
                  rate={data.conversions.offer_acceptance}
                />
              </div>
            </CardBody>
          </Card>

          {/* Where the search actually got to. The funnel stops at "offer";
              this is the other end — offers that turned into work. */}
          {data.jobs ? (
            <Card>
              <CardHeader
                title="Jobs from this search"
                description="Counted by when a job started or ended. The pay figure is present-tense — what is being earned now, gross."
              />
              <CardBody>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                  <JobStat label="Started" value={String(data.jobs.jobs_started)} />
                  <JobStat label="Ended" value={String(data.jobs.jobs_ended)} />
                  <JobStat
                    label="Offers open"
                    value={String(data.jobs.offers_open)}
                  />
                  <JobStat label="Live jobs" value={String(data.jobs.live_jobs)} />
                  <JobStat
                    label="Annual, live"
                    value={formatMoney(data.jobs.total_annual, data.jobs.currency, {
                      compact: true,
                    })}
                  />
                </div>
                <p className="mt-2 text-[11px] text-subtle-foreground">
                  Offers and ended jobs are excluded from the pay figure — an
                  offer is not income, and an ended job has stopped being income.
                </p>
              </CardBody>
            </Card>
          ) : null}

          <div className="grid gap-4 lg:grid-cols-2">
            {/* Funnel (spec §29) */}
            <Card>
              <CardHeader
                title="Application funnel"
                description="Applications submitted in this period, and how far each got."
              />
              <CardBody>
                <FunnelChart steps={data.funnel} />
              </CardBody>
            </Card>

            {/* By type (spec §27) */}
            <Card>
              <CardHeader
                title="Performance by interview type"
                description="Only decided outcomes count toward a rate."
              />
              <CardBody>
                <TypePerformanceChart rows={data.by_type} />
              </CardBody>
            </Card>
          </div>

          {/* Trend */}
          <Card>
            <CardHeader
              title="Activity over time"
              description="Applications submitted and interviews held."
            />
            <CardBody>
              <TrendChart points={data.trend} />
            </CardBody>
          </Card>

          {/* Person comparison (spec §28) */}
          {data.comparison.length > 1 ? (
            <Card>
              <CardHeader
                title="By person"
                description="Different people, different searches — this is context, not a ranking."
              />
              <CardBody>
                <PersonComparisonChart rows={data.comparison} />
              </CardBody>
              <div className="border-t border-border">
                <PersonComparisonTable rows={data.comparison} />
              </div>
            </Card>
          ) : null}

          {/* Workload + conflicts (spec §30) */}
          <Card>
            <CardHeader
              title="This week's workload"
              description="Interview load per person, and any clashes."
            />
            <CardBody className="space-y-3">
              {workload.isLoading ? (
                <Skeleton className="h-20" />
              ) : (
                <>
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {(workload.data?.per_person ?? []).map((person) => (
                      <div
                        key={person.person_id}
                        className="flex items-center gap-2 rounded-md border border-border p-2.5"
                      >
                        <PersonAvatar
                          color={person.person_color}
                          initials={person.person_initials}
                          size="lg"
                        />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-xs font-medium text-foreground">
                            {person.person_name}
                          </p>
                          <p className="text-[11px] text-muted-foreground">
                            {person.interview_count} interview
                            {person.interview_count === 1 ? "" : "s"}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>

                  {(workload.data?.heavy_days ?? []).length > 0 ? (
                    <div className="rounded-md border border-status-warn/30 bg-status-warn-bg p-2.5">
                      <p className="text-xs font-medium text-status-warn">
                        Heavy days
                      </p>
                      <ul className="mt-1 space-y-0.5">
                        {workload.data?.heavy_days.map((day) => (
                          <li
                            key={`${day.person_id}:${day.day}`}
                            className="text-[11px] text-status-warn"
                          >
                            {day.person_name} has {day.count} interviews on{" "}
                            {formatDateOnly(day.day)}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  {(workload.data?.conflicts ?? []).length > 0 ? (
                    <div className="rounded-md border border-status-danger/30 bg-status-danger-bg p-2.5">
                      <p className="flex items-center gap-1.5 text-xs font-medium text-status-danger">
                        <AlertTriangle className="size-3.5" />
                        Scheduling conflicts
                      </p>
                      <ul className="mt-1 space-y-0.5">
                        {workload.data?.conflicts.map((conflict, index) => (
                          <li
                            key={`${conflict.person_id}:${index}`}
                            className="text-[11px] text-status-danger"
                          >
                            {conflict.person_name}: {conflict.first_title}{" "}
                            overlaps {conflict.second_title} by{" "}
                            {conflict.overlap_minutes} min
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : (
                    <p className="text-[11px] text-muted-foreground">
                      No scheduling conflicts this week.
                    </p>
                  )}
                </>
              )}
            </CardBody>
          </Card>
        </>
      )}
    </div>
  );
}

function JobStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border p-2.5">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums text-foreground">
        {value}
      </p>
    </div>
  );
}
