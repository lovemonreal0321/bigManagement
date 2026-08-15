"use client";

/**
 * Calendar views: Month, Week, Day, Agenda (spec §9), each supporting both
 * Overlay and Side-by-Side layouts for multiple people (spec §10).
 */

import * as React from "react";

import { EventChip, EventLine } from "@/components/calendar/event-chip";
import { PersonAvatar } from "@/components/shared/badges";
import { EmptyState } from "@/components/ui/primitives";
import { formatDayLabel, formatTime, isoDayIn } from "@/lib/format";
import {
  addDays,
  daysBetween,
  eventsForPerson,
  formatHourLabel,
  groupByDay,
  layoutDay,
  visibleHourRange,
} from "@/lib/calendar";
import type { CalendarFeedEvent, PersonWithStats } from "@/lib/types";
import { cn } from "@/lib/utils";

const HOUR_HEIGHT = 48; // px per hour in the time grids

interface ViewProps {
  events: CalendarFeedEvent[];
  tz?: string;
  onSelect?: (event: CalendarFeedEvent) => void;
}

// --------------------------------------------------------------------------
// Time grid (shared by Day and Week)
// --------------------------------------------------------------------------

function TimeGutter({
  startHour,
  endHour,
}: {
  startHour: number;
  endHour: number;
}) {
  const hours = Array.from(
    { length: endHour - startHour },
    (_, index) => startHour + index,
  );
  return (
    <div className="w-12 shrink-0 select-none border-r border-border">
      <div className="h-7 border-b border-border" />
      {hours.map((hour) => (
        <div
          key={hour}
          className="relative border-b border-border/60"
          style={{ height: HOUR_HEIGHT }}
        >
          <span className="absolute -top-2 right-1.5 text-[10px] tabular text-subtle-foreground">
            {formatHourLabel(hour)}
          </span>
        </div>
      ))}
    </div>
  );
}

function DayColumn({
  day,
  events,
  tz,
  startHour,
  endHour,
  onSelect,
  showPerson = true,
  header,
  className,
}: {
  day: string;
  events: CalendarFeedEvent[];
  tz?: string;
  startHour: number;
  endHour: number;
  onSelect?: (event: CalendarFeedEvent) => void;
  showPerson?: boolean;
  header: React.ReactNode;
  className?: string;
}) {
  const positioned = React.useMemo(
    () => layoutDay(events, tz),
    [events, tz],
  );
  const allDay = events.filter((event) => event.is_all_day);
  const hours = endHour - startHour;
  const isToday = day === isoDayIn(new Date(), tz);

  return (
    <div className={cn("min-w-0 flex-1 border-r border-border", className)}>
      <div
        className={cn(
          "flex h-7 items-center justify-center gap-1 border-b border-border px-1 text-[11px] font-medium",
          isToday ? "bg-primary/5 text-primary" : "text-muted-foreground",
        )}
      >
        {header}
      </div>

      <div
        className="relative @container"
        style={{ height: hours * HOUR_HEIGHT }}
      >
        {/* Hour lines */}
        {Array.from({ length: hours }).map((_, index) => (
          <div
            key={index}
            className="absolute inset-x-0 border-b border-border/60"
            style={{ top: index * HOUR_HEIGHT, height: HOUR_HEIGHT }}
          />
        ))}

        {isToday ? <CurrentTimeLine startHour={startHour} tz={tz} /> : null}

        {allDay.length > 0 ? (
          <div className="absolute inset-x-0.5 top-0 z-20 space-y-0.5">
            {allDay.map((event) => (
              <EventLine
                key={event.id}
                event={event}
                tz={tz}
                onSelect={onSelect}
              />
            ))}
          </div>
        ) : null}

        {positioned.map((item) => {
          const top =
            ((item.startMinutes - startHour * 60) / 60) * HOUR_HEIGHT;
          const height = Math.max(
            18,
            ((item.endMinutes - item.startMinutes) / 60) * HOUR_HEIGHT - 2,
          );
          const width = 100 / item.lanes;
          return (
            <div
              key={item.event.id}
              className="absolute z-10 px-0.5"
              style={{
                top,
                height,
                left: `${item.lane * width}%`,
                width: `${width}%`,
              }}
            >
              <EventChip
                event={item.event}
                tz={tz}
                size={height < 34 ? "xs" : "sm"}
                showPerson={showPerson}
                onSelect={onSelect}
                className="h-full"
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CurrentTimeLine({
  startHour,
  tz,
}: {
  startHour: number;
  tz?: string;
}) {
  const [minutes, setMinutes] = React.useState<number | null>(null);

  React.useEffect(() => {
    // Rendered only on the client: the server has no "now".
    const update = () => {
      const parts = new Intl.DateTimeFormat("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
        timeZone: tz,
      }).formatToParts(new Date());
      const hour = Number(parts.find((p) => p.type === "hour")?.value ?? 0);
      const minute = Number(parts.find((p) => p.type === "minute")?.value ?? 0);
      setMinutes((hour % 24) * 60 + minute);
    };
    update();
    const timer = window.setInterval(update, 60_000);
    return () => window.clearInterval(timer);
  }, [tz]);

  if (minutes === null) return null;
  const top = ((minutes - startHour * 60) / 60) * HOUR_HEIGHT;
  if (top < 0) return null;

  return (
    <div
      className="pointer-events-none absolute inset-x-0 z-30 flex items-center"
      style={{ top }}
      aria-hidden
    >
      <span className="size-1.5 rounded-full bg-status-danger" />
      <span className="h-px flex-1 bg-status-danger" />
    </div>
  );
}

// --------------------------------------------------------------------------
// Week
// --------------------------------------------------------------------------

export function WeekView({
  events,
  tz,
  onSelect,
  startDay,
}: ViewProps & { startDay: string }) {
  const days = React.useMemo(
    () => daysBetween(startDay, addDays(startDay, 6)),
    [startDay],
  );
  const byDay = React.useMemo(() => groupByDay(events, tz), [events, tz]);
  const { startHour, endHour } = React.useMemo(
    () => visibleHourRange(events, tz),
    [events, tz],
  );

  return (
    <div className="flex overflow-x-auto rounded-lg border border-border bg-surface">
      <TimeGutter startHour={startHour} endHour={endHour} />
      <div className="flex min-w-[42rem] flex-1">
        {days.map((day) => (
          <DayColumn
            key={day}
            day={day}
            events={byDay.get(day) ?? []}
            tz={tz}
            startHour={startHour}
            endHour={endHour}
            onSelect={onSelect}
            header={<DayHeader day={day} />}
          />
        ))}
      </div>
    </div>
  );
}

function DayHeader({ day }: { day: string }) {
  const date = new Date(`${day}T12:00:00Z`);
  return (
    <>
      <span>
        {new Intl.DateTimeFormat("en-US", { weekday: "short" }).format(date)}
      </span>
      <span className="tabular">{date.getUTCDate()}</span>
    </>
  );
}

// --------------------------------------------------------------------------
// Day
// --------------------------------------------------------------------------

export function DayView({
  events,
  tz,
  onSelect,
  day,
}: ViewProps & { day: string }) {
  const byDay = React.useMemo(() => groupByDay(events, tz), [events, tz]);
  const dayEvents = React.useMemo(() => byDay.get(day) ?? [], [byDay, day]);
  const { startHour, endHour } = React.useMemo(
    () => visibleHourRange(dayEvents, tz),
    [dayEvents, tz],
  );

  return (
    <div className="flex overflow-hidden rounded-lg border border-border bg-surface">
      <TimeGutter startHour={startHour} endHour={endHour} />
      <DayColumn
        day={day}
        events={dayEvents}
        tz={tz}
        startHour={startHour}
        endHour={endHour}
        onSelect={onSelect}
        header={<span>{formatDayLabel(`${day}T12:00:00Z`, tz)}</span>}
        className="border-r-0"
      />
    </div>
  );
}

// --------------------------------------------------------------------------
// Side-by-side (spec §10)
// --------------------------------------------------------------------------

/**
 * One column per person for a single day — the layout in the spec's table.
 */
export function SideBySideDayView({
  events,
  tz,
  onSelect,
  day,
  people,
}: ViewProps & { day: string; people: PersonWithStats[] }) {
  const byDay = React.useMemo(() => groupByDay(events, tz), [events, tz]);
  const dayEvents = React.useMemo(() => byDay.get(day) ?? [], [byDay, day]);
  const { startHour, endHour } = React.useMemo(
    () => visibleHourRange(dayEvents, tz),
    [dayEvents, tz],
  );

  if (people.length === 0) return null;

  return (
    <div className="flex overflow-x-auto rounded-lg border border-border bg-surface">
      <TimeGutter startHour={startHour} endHour={endHour} />
      <div
        className="flex flex-1"
        style={{ minWidth: `${people.length * 9}rem` }}
      >
        {people.map((person) => (
          <DayColumn
            key={person.id}
            day={day}
            events={eventsForPerson(dayEvents, person.id)}
            tz={tz}
            startHour={startHour}
            endHour={endHour}
            onSelect={onSelect}
            showPerson={false}
            header={
              <span className="flex items-center gap-1.5">
                <PersonAvatar
                  color={person.color}
                  initials={person.initials}
                  size="xs"
                />
                <span className="truncate">{person.display_name}</span>
              </span>
            }
          />
        ))}
      </div>
    </div>
  );
}

/**
 * A full week grid per person, stacked. Keeps each person's week readable
 * instead of squeezing 21 columns onto one screen.
 */
export function SideBySideWeekView({
  events,
  tz,
  onSelect,
  startDay,
  people,
}: ViewProps & { startDay: string; people: PersonWithStats[] }) {
  return (
    <div className="space-y-3">
      {people.map((person) => {
        const personEvents = eventsForPerson(events, person.id);
        return (
          <div key={person.id}>
            <div className="mb-1.5 flex items-center gap-2">
              <PersonAvatar
                color={person.color}
                initials={person.initials}
                size="sm"
              />
              <span className="text-xs font-medium text-foreground">
                {person.display_name}
              </span>
              <span className="text-[11px] text-subtle-foreground">
                {personEvents.length} event
                {personEvents.length === 1 ? "" : "s"}
              </span>
            </div>
            <WeekView
              events={personEvents}
              tz={tz}
              onSelect={onSelect}
              startDay={startDay}
            />
          </div>
        );
      })}
    </div>
  );
}

// --------------------------------------------------------------------------
// Month
// --------------------------------------------------------------------------

export function MonthView({
  events,
  tz,
  onSelect,
  gridStart,
  gridEnd,
  anchorMonth,
}: ViewProps & {
  gridStart: string;
  gridEnd: string;
  anchorMonth: string;
}) {
  const days = React.useMemo(
    () => daysBetween(gridStart, gridEnd),
    [gridStart, gridEnd],
  );
  const byDay = React.useMemo(() => groupByDay(events, tz), [events, tz]);
  const today = isoDayIn(new Date(), tz);
  const [expandedDay, setExpandedDay] = React.useState<string | null>(null);

  const weekdayLabels = days.slice(0, 7).map((day) =>
    new Intl.DateTimeFormat("en-US", { weekday: "short" }).format(
      new Date(`${day}T12:00:00Z`),
    ),
  );

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      <div className="grid grid-cols-7 border-b border-border">
        {weekdayLabels.map((label) => (
          <div
            key={label}
            className="px-2 py-1.5 text-center text-[11px] font-medium text-muted-foreground"
          >
            {label}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-7">
        {days.map((day) => {
          const dayEvents = byDay.get(day) ?? [];
          const inMonth = day.slice(0, 7) === anchorMonth;
          const isToday = day === today;
          const expanded = expandedDay === day;
          const visible = expanded ? dayEvents : dayEvents.slice(0, 3);

          return (
            <div
              key={day}
              className={cn(
                "min-h-24 border-b border-r border-border p-1",
                !inMonth && "bg-surface-muted/40",
              )}
            >
              <div className="mb-1 flex items-center justify-between px-0.5">
                <span
                  className={cn(
                    "tabular text-[11px]",
                    isToday
                      ? "flex size-4.5 items-center justify-center rounded-full bg-primary px-1 font-semibold text-primary-foreground"
                      : inMonth
                        ? "text-foreground"
                        : "text-subtle-foreground",
                  )}
                >
                  {Number(day.slice(-2))}
                </span>
              </div>

              <div className="space-y-0.5">
                {visible.map((event) => (
                  <EventLine
                    key={event.id}
                    event={event}
                    tz={tz}
                    onSelect={onSelect}
                  />
                ))}
                {dayEvents.length > 3 ? (
                  <button
                    type="button"
                    onClick={() => setExpandedDay(expanded ? null : day)}
                    className="w-full rounded px-1 py-0.5 text-left text-[10px] text-muted-foreground hover:bg-surface-hover"
                  >
                    {expanded ? "Show less" : `+${dayEvents.length - 3} more`}
                  </button>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
// Agenda (also the mobile default — spec §40)
// --------------------------------------------------------------------------

export function AgendaView({ events, tz, onSelect }: ViewProps) {
  const byDay = React.useMemo(() => groupByDay(events, tz), [events, tz]);
  const days = React.useMemo(
    () => Array.from(byDay.keys()).sort(),
    [byDay],
  );

  if (days.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-surface">
        <EmptyState
          title="Nothing scheduled"
          description="No interviews or events in this range."
        />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {days.map((day) => (
        <div key={day} className="rounded-lg border border-border bg-surface">
          <div className="flex items-baseline justify-between border-b border-border px-3 py-2">
            <p className="text-xs font-semibold text-foreground">
              {formatDayLabel(`${day}T12:00:00Z`, tz)}
            </p>
            <p className="text-[11px] text-subtle-foreground">
              {byDay.get(day)?.length} event
              {byDay.get(day)?.length === 1 ? "" : "s"}
            </p>
          </div>
          <ul className="divide-y divide-border">
            {(byDay.get(day) ?? []).map((event) => (
              <li key={event.id} className="flex items-stretch gap-2 px-3 py-2">
                <div className="w-16 shrink-0 pt-0.5">
                  <p className="tabular text-xs font-medium text-foreground">
                    {event.is_all_day ? "All day" : formatTime(event.starts_at, tz)}
                  </p>
                  {!event.is_all_day ? (
                    <p className="tabular text-[10px] text-subtle-foreground">
                      {formatTime(event.ends_at, tz)}
                    </p>
                  ) : null}
                </div>
                <div className="min-w-0 flex-1">
                  <EventChip
                    event={event}
                    tz={tz}
                    onSelect={onSelect}
                    size="md"
                  />
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
