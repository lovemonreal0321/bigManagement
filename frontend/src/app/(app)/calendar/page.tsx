"use client";

import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Columns3,
  Filter,
  Layers,
  Link2Off,
  RefreshCw,
} from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import {
  AgendaView,
  DayView,
  MonthView,
  SideBySideDayView,
  SideBySideWeekView,
  WeekView,
} from "@/components/calendar/views";
import { EventDetailDialog } from "@/components/calendar/event-detail-dialog";
import { PageHeader } from "@/components/shared/page-header";
import { PersonAvatar } from "@/components/shared/badges";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
  Tabs,
  TabsList,
  TabsTrigger,
} from "@/components/ui/overlays";
import {
  Alert,
  Button,
  Card,
  ErrorState,
  Skeleton,
} from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { stepLegend } from "@/lib/event-color";
import {
  addDays,
  rangeForView,
  rangeToInstants,
  startOfMonth,
  startOfWeek,
  type CalendarLayoutMode,
  type CalendarViewMode,
} from "@/lib/calendar";
import { useMediaQuery } from "@/lib/browser-hooks";
import { formatMonthYear, isoDayIn } from "@/lib/format";
import { usePersonFilter } from "@/lib/person-filter";
import {
  useCalendarFeed,
  useInterviewTypes,
  useSettings,
  useSyncAllCalendars,
} from "@/lib/queries";
import type { CalendarFeedEvent } from "@/lib/types";

export default function CalendarPage() {
  const { queryIds, selectedPeople } = usePersonFilter();
  const { data: settings } = useSettings();
  const { data: types } = useInterviewTypes();
  const syncCalendar = useSyncAllCalendars();

  const tz = settings?.default_timezone;
  const weekStartsOn = settings?.week_starts_on ?? 0;

  // Agenda on a narrow viewport rather than squeezing a week grid onto a phone
  // (spec §40). Derived, so it needs no effect and no hydration mismatch: the
  // media query reports false on the server and corrects itself on mount.
  const isNarrow = useMediaQuery("(max-width: 640px)");
  const [chosenView, setChosenView] = React.useState<CalendarViewMode | null>(
    null,
  );
  const viewMode: CalendarViewMode =
    chosenView ?? (isNarrow ? "agenda" : "week");
  const setViewMode = setChosenView;
  const [layoutMode, setLayoutMode] =
    React.useState<CalendarLayoutMode>("overlay");
  const [anchorDay, setAnchorDay] = React.useState(() => isoDayIn(new Date()));
  const [selected, setSelected] = React.useState<CalendarFeedEvent | null>(null);
  const [typeFilter, setTypeFilter] = React.useState<string[]>([]);
  const [showNonInterview, setShowNonInterview] = React.useState(true);

  const { startDay, endDay } = React.useMemo(
    () => rangeForView(viewMode, anchorDay, weekStartsOn),
    [viewMode, anchorDay, weekStartsOn],
  );
  const { start, end } = React.useMemo(
    () => rangeToInstants(startDay, endDay),
    [startDay, endDay],
  );

  const feed = useCalendarFeed(queryIds, start, end, {
    type_key: typeFilter.length ? typeFilter : undefined,
    show_non_interview: showNonInterview,
  });

  const events = React.useMemo(() => feed.data?.events ?? [], [feed.data]);
  const conflicts = feed.data?.conflicts ?? [];
  // Only the steps actually on screen, so the legend stays short.
  const legend = React.useMemo(() => stepLegend(events), [events]);
  const unconnected = events.filter((event) => event.needs_application);

  function step(direction: -1 | 1) {
    setAnchorDay((current) => {
      switch (viewMode) {
        case "day":
          return addDays(current, direction);
        case "week":
          return addDays(current, direction * 7);
        case "agenda":
          return addDays(current, direction * 30);
        case "month":
        default: {
          const [year, month] = current.split("-").map(Number);
          const next = new Date(Date.UTC(year, month - 1 + direction, 1));
          return next.toISOString().slice(0, 10);
        }
      }
    });
  }

  const rangeLabel = React.useMemo(() => {
    if (viewMode === "month") {
      return formatMonthYear(new Date(`${startOfMonth(anchorDay)}T12:00:00Z`));
    }
    if (viewMode === "day") {
      return new Intl.DateTimeFormat("en-US", {
        weekday: "long",
        month: "long",
        day: "numeric",
      }).format(new Date(`${anchorDay}T12:00:00Z`));
    }
    const weekStart = startOfWeek(anchorDay, weekStartsOn);
    const weekEnd = addDays(weekStart, 6);
    const fmt = (day: string) =>
      new Intl.DateTimeFormat("en-US", {
        month: "short",
        day: "numeric",
      }).format(new Date(`${day}T12:00:00Z`));
    return viewMode === "agenda"
      ? `${fmt(startDay)} – ${fmt(endDay)}`
      : `${fmt(weekStart)} – ${fmt(weekEnd)}`;
  }, [viewMode, anchorDay, weekStartsOn, startDay, endDay]);

  const canSideBySide =
    (viewMode === "day" || viewMode === "week") && selectedPeople.length > 1;

  async function handleSync() {
    try {
      const summary = await syncCalendar.mutateAsync();
      if (summary.errors.length > 0) {
        toast.error(summary.errors[0]);
      } else if (summary.results.length === 0) {
        toast.info("No calendars are connected yet.");
      } else {
        toast.success(`Synced ${summary.total_events} events`);
      }
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Could not sync calendars.",
      );
    }
  }

  return (
    <div>
      <PageHeader
        title="Calendar"
        description="Interviews and imported events for the selected people."
        actions={
          <Button
            size="sm"
            variant="secondary"
            onClick={handleSync}
            loading={syncCalendar.isPending}
          >
            <RefreshCw />
            Sync
          </Button>
        }
      />

      {/* Toolbar */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          <Button
            size="icon-sm"
            variant="secondary"
            onClick={() => step(-1)}
            aria-label="Previous"
          >
            <ChevronLeft />
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setAnchorDay(isoDayIn(new Date()))}
          >
            Today
          </Button>
          <Button
            size="icon-sm"
            variant="secondary"
            onClick={() => step(1)}
            aria-label="Next"
          >
            <ChevronRight />
          </Button>
        </div>

        <p className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
          {rangeLabel}
        </p>

        <Tabs
          value={viewMode}
          onValueChange={(value) => setViewMode(value as CalendarViewMode)}
        >
          <TabsList>
            <TabsTrigger value="month">Month</TabsTrigger>
            <TabsTrigger value="week">Week</TabsTrigger>
            <TabsTrigger value="day">Day</TabsTrigger>
            <TabsTrigger value="agenda">Agenda</TabsTrigger>
          </TabsList>
        </Tabs>

        {canSideBySide ? (
          <Button
            size="sm"
            variant={layoutMode === "side_by_side" ? "primary" : "secondary"}
            onClick={() =>
              setLayoutMode((mode) =>
                mode === "overlay" ? "side_by_side" : "overlay",
              )
            }
            title="Toggle side-by-side columns per person"
          >
            {layoutMode === "side_by_side" ? <Columns3 /> : <Layers />}
            <span className="hidden sm:inline">
              {layoutMode === "side_by_side" ? "Side by side" : "Overlay"}
            </span>
          </Button>
        ) : null}

        <Popover>
          <PopoverTrigger asChild>
            <Button size="sm" variant="secondary">
              <Filter />
              <span className="hidden sm:inline">Filters</span>
              {typeFilter.length > 0 ? (
                <span className="ml-0.5 rounded bg-primary px-1 text-[10px] text-primary-foreground">
                  {typeFilter.length}
                </span>
              ) : null}
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-60">
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-subtle-foreground">
              Interview type
            </p>
            <div className="max-h-56 space-y-0.5 overflow-y-auto">
              {(types ?? []).map((type) => (
                <label
                  key={type.key}
                  className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-xs hover:bg-surface-hover"
                >
                  <input
                    type="checkbox"
                    checked={typeFilter.includes(type.key)}
                    onChange={() =>
                      setTypeFilter((current) =>
                        current.includes(type.key)
                          ? current.filter((key) => key !== type.key)
                          : [...current, type.key],
                      )
                    }
                    className="size-3.5 accent-[var(--primary)]"
                  />
                  {type.label}
                </label>
              ))}
            </div>
            <label className="mt-2 flex cursor-pointer items-center gap-2 border-t border-border pt-2 text-xs">
              <input
                type="checkbox"
                checked={showNonInterview}
                onChange={(event) => setShowNonInterview(event.target.checked)}
                className="size-3.5 accent-[var(--primary)]"
              />
              Show personal and non-interview events
            </label>
            {typeFilter.length > 0 ? (
              <Button
                size="xs"
                variant="ghost"
                className="mt-2 w-full"
                onClick={() => setTypeFilter([])}
              >
                Clear type filters
              </Button>
            ) : null}
          </PopoverContent>
        </Popover>
      </div>

      {/* Conflicts (spec §43) */}
      {conflicts.length > 0 ? (
        <div className="mb-3 space-y-1.5">
          {conflicts.slice(0, 3).map((conflict, index) => (
            <Alert
              key={`${conflict.person_id}:${index}`}
              tone="danger"
              title={
                <span className="flex items-center gap-1.5">
                  <AlertTriangle className="size-3.5" />
                  Scheduling conflict — {conflict.person_name}
                </span>
              }
            >
              {conflict.first_title} overlaps {conflict.second_title} by{" "}
              {conflict.overlap_minutes} minutes.
            </Alert>
          ))}
        </div>
      ) : null}

      {/* Interviews with nothing behind them (spec §8) */}
      {unconnected.length > 0 ? (
        <Alert
          tone="warn"
          className="mb-3"
          title={
            <span className="flex items-center gap-1.5">
              <Link2Off className="size-3.5" />
              {unconnected.length} interview
              {unconnected.length === 1 ? " has" : "s have"} no application
            </span>
          }
        >
          {unconnected.length === 1
            ? `"${unconnected[0].title}" counts as an interview but is not `
            : "They count as interviews but are not "}
          connected to an application, so they are missing from the funnel and
          every rate on the dashboard. Open one to connect it — or mark it
          personal or not an interview to stop it counting.
        </Alert>
      ) : null}

      {/* Legend */}
      {selectedPeople.length > 1 || legend.length > 0 ? (
        <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
          {selectedPeople.length > 1
            ? selectedPeople.map((person) => (
                <span
                  key={person.id}
                  className="flex items-center gap-1.5 text-[11px] text-muted-foreground"
                >
                  <PersonAvatar
                    color={person.color}
                    initials={person.initials}
                    size="xs"
                  />
                  {person.display_name}
                </span>
              ))
            : null}
          {selectedPeople.length > 1 && legend.length > 0 ? (
            <span aria-hidden className="h-3 w-px bg-border" />
          ) : null}
          {legend.map((entry) => (
            <span
              key={entry.label}
              className="flex items-center gap-1.5 text-[11px] text-muted-foreground"
            >
              <span
                aria-hidden
                className="h-3 w-1 rounded-full"
                style={{ backgroundColor: entry.color }}
              />
              {entry.label}
            </span>
          ))}
        </div>
      ) : null}

      {/* Grid */}
      {feed.isLoading ? (
        <Skeleton className="h-[32rem]" />
      ) : feed.isError ? (
        <Card>
          <ErrorState
            message={
              feed.error instanceof ApiError
                ? feed.error.message
                : "Could not load the calendar."
            }
            onRetry={() => feed.refetch()}
          />
        </Card>
      ) : viewMode === "agenda" ? (
        <AgendaView events={events} tz={tz} onSelect={setSelected} />
      ) : viewMode === "month" ? (
        <MonthView
          events={events}
          tz={tz}
          onSelect={setSelected}
          gridStart={startDay}
          gridEnd={endDay}
          anchorMonth={anchorDay.slice(0, 7)}
        />
      ) : viewMode === "day" ? (
        layoutMode === "side_by_side" && canSideBySide ? (
          <SideBySideDayView
            events={events}
            tz={tz}
            onSelect={setSelected}
            day={anchorDay}
            people={selectedPeople}
          />
        ) : (
          <DayView
            events={events}
            tz={tz}
            onSelect={setSelected}
            day={anchorDay}
          />
        )
      ) : layoutMode === "side_by_side" && canSideBySide ? (
        <SideBySideWeekView
          events={events}
          tz={tz}
          onSelect={setSelected}
          startDay={startDay}
          people={selectedPeople}
        />
      ) : (
        <WeekView
          events={events}
          tz={tz}
          onSelect={setSelected}
          startDay={startDay}
        />
      )}

      <EventDetailDialog
        event={selected}
        onOpenChange={(open) => !open && setSelected(null)}
        tz={tz}
      />
    </div>
  );
}
