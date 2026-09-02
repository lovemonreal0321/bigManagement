/**
 * What colour a calendar block gets, and why.
 *
 * Person colour answers *who*, and it keeps doing that — it stays on the avatar
 * and the chip's tint. This file answers *which step*: a recruiter screen and a
 * final round should not look alike on a month grid where the text is too small
 * to read.
 *
 * The hues run roughly early → late through the process, so a calendar reads as
 * progress rather than as a set of unrelated labels. They are fixed hex values
 * rather than theme tokens because they need to stay distinguishable from each
 * other, which a semantic palette of five statuses cannot do; they are only ever
 * used as a spine or a dot, never behind text, so contrast is not at stake.
 */

import { CLASSIFICATION_LABELS } from "@/lib/format";
import type { CalendarFeedEvent } from "@/lib/types";

export interface StepColor {
  /** The colour itself. */
  color: string;
  /** What the colour means, for tooltips and the legend. */
  label: string;
}

const NEUTRAL = "var(--border-strong)";

/** Built-in interview types, early in the process first. */
const TYPE_COLORS: Record<string, string> = {
  recruiter_screen: "#0ea5e9", // sky — first contact
  hr_screen: "#06b6d4", // cyan
  hiring_manager: "#6366f1", // indigo
  technical: "#8b5cf6", // violet
  coding: "#a855f7", // purple
  machine_learning: "#c026d3", // fuchsia
  system_design: "#7c3aed", // deep violet
  behavioral: "#f59e0b", // amber
  culture_fit: "#f97316", // orange
  panel: "#ec4899", // pink
  final: "#10b981", // emerald — nearly there
  online_assessment: "#14b8a6", // teal
  take_home: "#0d9488", // deep teal
  other: "#64748b", // slate
};

/**
 * Fallback for a custom type the palette has never heard of. Hashing the key
 * keeps it stable across reloads, which matters more than the exact hue: a type
 * that changed colour every render would be worse than no colour at all.
 */
const FALLBACK_HUES = [
  "#0ea5e9",
  "#6366f1",
  "#8b5cf6",
  "#f59e0b",
  "#ec4899",
  "#10b981",
  "#14b8a6",
  "#f97316",
];

function hashedColor(key: string): string {
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) {
    hash = (hash * 31 + key.charCodeAt(i)) | 0;
  }
  return FALLBACK_HUES[Math.abs(hash) % FALLBACK_HUES.length];
}

/** Colour for an interview type key. */
export function typeColor(typeKey: string | null | undefined): string {
  if (!typeKey) return NEUTRAL;
  return TYPE_COLORS[typeKey] ?? hashedColor(typeKey);
}

/**
 * Imported events that have no stage behind them yet. They still count as
 * interviews, so they get a colour — a muted one, because nobody has said which
 * step it is.
 */
const CLASSIFICATION_COLORS: Record<string, string> = {
  unclassified: "#64748b", // slate — counts, but unsorted
  interview: "#6366f1",
  recruiter_call: "#0ea5e9",
  assessment: "#14b8a6",
};

/**
 * The step colour for any block on the feed.
 *
 * A linked interview is coloured by its type. An imported event is coloured by
 * what it has been filed as. An event that does not count as an interview gets
 * no colour at all — that absence is the point, and it is what makes a personal
 * appointment recede on a busy week.
 */
export function stepColor(event: CalendarFeedEvent): StepColor | null {
  if (!event.counts_as_interview) return null;

  if (event.type_key) {
    return {
      color: typeColor(event.type_key),
      label: event.type_label ?? event.type_key,
    };
  }

  const classification = event.classification ?? "unclassified";
  const color = CLASSIFICATION_COLORS[classification];
  if (!color) return null;
  return { color, label: CLASSIFICATION_LABELS[classification] ?? "Interview" };
}

/** The legend under the calendar: only the types actually on screen. */
export function stepLegend(
  events: CalendarFeedEvent[],
): { color: string; label: string }[] {
  const seen = new Map<string, string>();
  for (const event of events) {
    const step = stepColor(event);
    if (step) seen.set(step.label, step.color);
  }
  return [...seen].map(([label, color]) => ({ label, color }));
}
