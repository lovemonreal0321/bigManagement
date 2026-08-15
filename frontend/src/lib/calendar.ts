/**
 * Calendar geometry and grouping helpers.
 *
 * Pure functions over ISO instants plus a display timezone. Nothing here
 * touches the DOM or React, so the overlap maths can be reasoned about (and
 * tested) on its own.
 */

import { isoDayIn } from "./format";
import type { CalendarFeedEvent } from "./types";

export type CalendarViewMode = "month" | "week" | "day" | "agenda";
export type CalendarLayoutMode = "overlay" | "side_by_side";

export const DAY_MS = 86_400_000;

/** Wall-clock minutes since midnight for an instant, in a display timezone. */
export function minutesIntoDay(iso: string, tz?: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: tz,
  }).formatToParts(new Date(iso));
  const hour = Number(parts.find((p) => p.type === "hour")?.value ?? 0);
  const minute = Number(parts.find((p) => p.type === "minute")?.value ?? 0);
  // Intl renders midnight as "24" in some locales/zones.
  return (hour % 24) * 60 + minute;
}

/** `YYYY-MM-DD` for N days after an ISO day string. */
export function addDays(isoDay: string, days: number): string {
  const date = new Date(`${isoDay}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function startOfWeek(isoDay: string, weekStartsOn = 0): string {
  const date = new Date(`${isoDay}T12:00:00Z`);
  const weekday = date.getUTCDay(); // 0 = Sunday
  const mondayBased = (weekday + 6) % 7; // 0 = Monday
  const offset = weekStartsOn === 0 ? mondayBased : weekday;
  return addDays(isoDay, -offset);
}

export function startOfMonth(isoDay: string): string {
  return `${isoDay.slice(0, 7)}-01`;
}

export function endOfMonth(isoDay: string): string {
  const [year, month] = isoDay.split("-").map(Number);
  const date = new Date(Date.UTC(year, month, 0));
  return date.toISOString().slice(0, 10);
}

export function daysBetween(startDay: string, endDay: string): string[] {
  const days: string[] = [];
  let cursor = startDay;
  let guard = 0;
  while (cursor <= endDay && guard < 400) {
    days.push(cursor);
    cursor = addDays(cursor, 1);
    guard += 1;
  }
  return days;
}

/** Inclusive day range covered by a view, used to fetch the feed. */
export function rangeForView(
  mode: CalendarViewMode,
  anchorDay: string,
  weekStartsOn = 0,
): { startDay: string; endDay: string } {
  switch (mode) {
    case "day":
      return { startDay: anchorDay, endDay: anchorDay };
    case "week": {
      const start = startOfWeek(anchorDay, weekStartsOn);
      return { startDay: start, endDay: addDays(start, 6) };
    }
    case "agenda":
      return { startDay: anchorDay, endDay: addDays(anchorDay, 29) };
    case "month":
    default: {
      // Month grids show the trailing and leading days of adjacent months.
      const gridStart = startOfWeek(startOfMonth(anchorDay), weekStartsOn);
      const gridEnd = addDays(startOfWeek(endOfMonth(anchorDay), weekStartsOn), 6);
      return { startDay: gridStart, endDay: gridEnd };
    }
  }
}

/** UTC instants covering [startDay, endDay] in the display timezone. */
export function rangeToInstants(
  startDay: string,
  endDay: string,
): { start: string; end: string } {
  // A generous margin either side means an event is never clipped out of the
  // fetch because of a timezone offset.
  return {
    start: new Date(`${startDay}T00:00:00Z`).toISOString(),
    end: new Date(
      new Date(`${endDay}T00:00:00Z`).getTime() + DAY_MS,
    ).toISOString(),
  };
}

/** Group events by the local day they start on. */
export function groupByDay(
  events: CalendarFeedEvent[],
  tz?: string,
): Map<string, CalendarFeedEvent[]> {
  const map = new Map<string, CalendarFeedEvent[]>();
  for (const event of events) {
    const day = isoDayIn(event.starts_at, tz);
    const bucket = map.get(day);
    if (bucket) bucket.push(event);
    else map.set(day, [event]);
  }
  for (const bucket of map.values()) {
    bucket.sort(
      (a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime(),
    );
  }
  return map;
}

export interface PositionedEvent {
  event: CalendarFeedEvent;
  /** Minutes from midnight. */
  startMinutes: number;
  endMinutes: number;
  /** Column index and total columns, for overlapping events. */
  lane: number;
  lanes: number;
}

/**
 * Lay out one day's events into side-by-side lanes.
 *
 * Overlapping events are split into columns so neither is hidden. Events that
 * merely touch (one ends as the next begins) stay full width — that is a
 * normal back-to-back schedule, not a clash.
 */
export function layoutDay(
  events: CalendarFeedEvent[],
  tz?: string,
  minimumMinutes = 30,
): PositionedEvent[] {
  const positioned = events
    .filter((event) => !event.is_all_day)
    .map((event) => {
      const startMinutes = minutesIntoDay(event.starts_at, tz);
      let endMinutes = minutesIntoDay(event.ends_at, tz);
      // An event running past midnight wraps to a smaller number; clamp it to
      // the end of the day rather than rendering a negative height.
      if (endMinutes <= startMinutes) endMinutes = 24 * 60;
      return {
        event,
        startMinutes,
        endMinutes: Math.max(endMinutes, startMinutes + minimumMinutes),
        lane: 0,
        lanes: 1,
      };
    })
    .sort(
      (a, b) => a.startMinutes - b.startMinutes || a.endMinutes - b.endMinutes,
    );

  // Sweep through, collecting clusters of mutually overlapping events.
  let cluster: PositionedEvent[] = [];
  let clusterEnd = -1;

  const flush = () => {
    if (cluster.length === 0) return;
    const laneEnds: number[] = [];
    for (const item of cluster) {
      let lane = laneEnds.findIndex((end) => end <= item.startMinutes);
      if (lane === -1) {
        lane = laneEnds.length;
        laneEnds.push(item.endMinutes);
      } else {
        laneEnds[lane] = item.endMinutes;
      }
      item.lane = lane;
    }
    for (const item of cluster) item.lanes = laneEnds.length;
    cluster = [];
  };

  for (const item of positioned) {
    if (cluster.length > 0 && item.startMinutes >= clusterEnd) {
      flush();
      clusterEnd = -1;
    }
    cluster.push(item);
    clusterEnd = Math.max(clusterEnd, item.endMinutes);
  }
  flush();

  return positioned;
}

/** The hour window to render, widened to fit anything outside business hours. */
export function visibleHourRange(
  events: CalendarFeedEvent[],
  tz?: string,
  defaultStart = 7,
  defaultEnd = 21,
): { startHour: number; endHour: number } {
  let startHour = defaultStart;
  let endHour = defaultEnd;
  for (const event of events) {
    if (event.is_all_day) continue;
    const start = Math.floor(minutesIntoDay(event.starts_at, tz) / 60);
    const rawEnd = minutesIntoDay(event.ends_at, tz);
    const end = Math.ceil((rawEnd === 0 ? 24 * 60 : rawEnd) / 60);
    if (start < startHour) startHour = Math.max(0, start);
    if (end > endHour) endHour = Math.min(24, end);
  }
  if (endHour <= startHour) endHour = Math.min(24, startHour + 1);
  return { startHour, endHour };
}

export function formatHourLabel(hour: number): string {
  if (hour === 0 || hour === 24) return "12 AM";
  if (hour === 12) return "12 PM";
  return hour < 12 ? `${hour} AM` : `${hour - 12} PM`;
}

/** Filter a feed down to one person, for side-by-side columns. */
export function eventsForPerson(
  events: CalendarFeedEvent[],
  personId: string,
): CalendarFeedEvent[] {
  return events.filter((event) => event.person_id === personId);
}
