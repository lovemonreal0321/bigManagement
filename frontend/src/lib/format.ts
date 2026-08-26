/**
 * Display formatting.
 *
 * Every date helper takes an explicit timezone. Nothing here falls back to the
 * browser's zone silently, because a workspace can span several (spec §44) and
 * "10:00" means nothing without saying whose 10:00 it is.
 */

import type {
  ApplicationStatus,
  FollowUpComputedStatus,
  InterviewOutcome,
  InterviewStatus,
  Priority,
  WorkMode,
} from "./types";

export type Tone =
  | "neutral"
  | "info"
  | "warn"
  | "success"
  | "danger"
  | "offer";

// --------------------------------------------------------------------------
// Dates and times
// --------------------------------------------------------------------------

function fmt(iso: string, tz: string | undefined, options: Intl.DateTimeFormatOptions) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-US", { ...options, timeZone: tz }).format(date);
}

export function formatTime(iso: string, tz?: string) {
  return fmt(iso, tz, { hour: "numeric", minute: "2-digit" });
}

export function formatDate(iso: string, tz?: string) {
  return fmt(iso, tz, { month: "short", day: "numeric" });
}

export function formatLongDate(iso: string, tz?: string) {
  return fmt(iso, tz, { weekday: "short", month: "short", day: "numeric" });
}

export function formatFullDate(iso: string, tz?: string) {
  return fmt(iso, tz, { year: "numeric", month: "short", day: "numeric" });
}

export function formatDateTime(iso: string, tz?: string) {
  return `${formatDate(iso, tz)}, ${formatTime(iso, tz)}`;
}

export function formatMonthYear(date: Date, tz?: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    year: "numeric",
    timeZone: tz,
  }).format(date);
}

/** Calendar date in a given timezone, as `YYYY-MM-DD`. */
export function isoDayIn(value: Date | string, tz?: string): string {
  const date = typeof value === "string" ? new Date(value) : value;
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: tz,
  }).format(date);
}

/** "Today", "Tomorrow", "Yesterday", or a short date. */
export function formatDayLabel(iso: string, tz?: string): string {
  const target = isoDayIn(iso, tz);
  const now = new Date();
  const today = isoDayIn(now, tz);
  const tomorrow = isoDayIn(new Date(now.getTime() + 86400000), tz);
  const yesterday = isoDayIn(new Date(now.getTime() - 86400000), tz);

  if (target === today) return "Today";
  if (target === tomorrow) return "Tomorrow";
  if (target === yesterday) return "Yesterday";
  return formatLongDate(iso, tz);
}

/** Short countdown for upcoming interviews: "in 2h", "in 3d", "now". */
export function formatCountdown(iso: string): string {
  const diffMs = new Date(iso).getTime() - Date.now();
  if (Number.isNaN(diffMs)) return "";
  const past = diffMs < 0;
  const minutes = Math.round(Math.abs(diffMs) / 60000);

  if (minutes < 1) return "now";
  if (minutes < 60) return past ? `${minutes}m ago` : `in ${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return past ? `${hours}h ago` : `in ${hours}h`;
  const days = Math.round(hours / 24);
  if (days < 30) return past ? `${days}d ago` : `in ${days}d`;
  const months = Math.round(days / 30);
  return past ? `${months}mo ago` : `in ${months}mo`;
}

export function formatDaysAgo(days: number): string {
  if (days <= 0) return "today";
  if (days === 1) return "1 day ago";
  return `${days} days ago`;
}

/** Local date string (`YYYY-MM-DD`) usable as a date-input value. */
export function todayIso(tz?: string): string {
  return isoDayIn(new Date(), tz);
}

export function addDaysIso(iso: string, days: number): string {
  const date = new Date(`${iso}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/** Renders a `YYYY-MM-DD` value without shifting it across a timezone. */
/**
 * `Aug 17` from a date-only string, read as-is rather than shifted into the
 * viewer's zone.
 *
 * Tolerates a full ISO datetime by taking its date part: a formatter that
 * throws takes the whole page down with it, which is a wildly disproportionate
 * outcome for a bad string.
 */
export function formatDateOnly(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  if (!year || !month || !day) return iso;
  const value = new Date(Date.UTC(year, month - 1, day));
  if (Number.isNaN(value.getTime())) return iso;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  }).format(value);
}

export function formatDurationMinutes(startIso: string, endIso: string): string {
  const minutes = Math.round(
    (new Date(endIso).getTime() - new Date(startIso).getTime()) / 60000,
  );
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

// --------------------------------------------------------------------------
// Numbers
// --------------------------------------------------------------------------

export function formatPercent(value: number | null): string {
  // `null` means "no data", which is not the same as 0% (spec §54).
  if (value === null || value === undefined) return "—";
  return `${value}%`;
}

export function formatSalary(
  min: number | null,
  max: number | null,
  currency = "USD",
): string | null {
  if (min === null && max === null) return null;
  const compact = (value: number) =>
    new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      notation: value >= 10000 ? "compact" : "standard",
      maximumFractionDigits: 0,
    }).format(value);

  if (min !== null && max !== null) return `${compact(min)} – ${compact(max)}`;
  return compact((min ?? max) as number);
}

// --------------------------------------------------------------------------
// Labels
// --------------------------------------------------------------------------

export function humanise(value: string | null | undefined): string {
  if (!value) return "—";
  return value
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export const APPLICATION_STATUS_LABELS: Record<ApplicationStatus, string> = {
  saved: "Saved",
  applied: "Applied",
  recruiter_contacted: "Recruiter Contacted",
  screening: "Screening",
  interviewing: "Interviewing",
  waiting_for_feedback: "Waiting for Feedback",
  scheduling_next_round: "Scheduling Next Round",
  final_round: "Final Round",
  offer: "Offer",
  negotiating: "Negotiating",
  accepted: "Accepted",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
  on_hold: "On Hold",
  ghosted: "Ghosted",
  archived: "Archived",
};

/**
 * Status -> semantic tone (spec §42). This is the *state* colour system and is
 * kept strictly separate from person colours.
 */
export const APPLICATION_STATUS_TONES: Record<ApplicationStatus, Tone> = {
  saved: "neutral",
  applied: "neutral",
  recruiter_contacted: "info",
  screening: "info",
  interviewing: "info",
  waiting_for_feedback: "warn",
  scheduling_next_round: "warn",
  final_round: "offer",
  offer: "success",
  negotiating: "success",
  accepted: "success",
  rejected: "danger",
  withdrawn: "neutral",
  on_hold: "warn",
  ghosted: "neutral",
  archived: "neutral",
};

export const INTERVIEW_STATUS_LABELS: Record<InterviewStatus, string> = {
  planned: "Planned",
  scheduled: "Scheduled",
  completed: "Completed",
  cancelled: "Cancelled",
  rescheduled: "Rescheduled",
  no_show: "No Show",
};

export const INTERVIEW_STATUS_TONES: Record<InterviewStatus, Tone> = {
  planned: "neutral",
  scheduled: "info",
  completed: "neutral",
  cancelled: "neutral",
  rescheduled: "warn",
  no_show: "danger",
};

export const OUTCOME_LABELS: Record<InterviewOutcome, string> = {
  pending: "Pending",
  waiting: "Waiting",
  passed: "Passed",
  failed: "Failed",
  cancelled: "Cancelled",
  withdrawn: "Withdrawn",
  unknown: "Unknown",
};

/** Spec §18: passed green, failed red, waiting amber, cancelled grey. */
export const OUTCOME_TONES: Record<InterviewOutcome, Tone> = {
  pending: "neutral",
  waiting: "warn",
  passed: "success",
  failed: "danger",
  cancelled: "neutral",
  withdrawn: "neutral",
  unknown: "neutral",
};

export const FOLLOW_UP_TONES: Record<FollowUpComputedStatus, Tone> = {
  open: "info",
  due_today: "warn",
  overdue: "danger",
  completed: "success",
  snoozed: "neutral",
  cancelled: "neutral",
};

export const FOLLOW_UP_LABELS: Record<FollowUpComputedStatus, string> = {
  open: "Upcoming",
  due_today: "Due today",
  overdue: "Overdue",
  completed: "Completed",
  snoozed: "Snoozed",
  cancelled: "Cancelled",
};

export const PRIORITY_LABELS: Record<Priority, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  urgent: "Urgent",
};

export const PRIORITY_TONES: Record<Priority, Tone> = {
  low: "neutral",
  medium: "neutral",
  high: "warn",
  urgent: "danger",
};

export const WORK_MODE_LABELS: Record<WorkMode, string> = {
  remote: "Remote",
  hybrid: "Hybrid",
  onsite: "On-site",
  unknown: "Not specified",
};

export const EMPLOYMENT_TYPE_LABELS: Record<string, string> = {
  full_time: "Full-time",
  contract: "Contract",
  part_time: "Part-time",
  internship: "Internship",
  unknown: "Not specified",
};

export const CLASSIFICATION_LABELS: Record<string, string> = {
  unclassified: "Not classified",
  normal_meeting: "Normal meeting",
  interview: "Interview",
  recruiter_call: "Recruiter call",
  assessment: "Assessment",
  personal: "Personal",
  ignored: "Ignored",
};

/** Tailwind classes for a semantic tone. */
export const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-status-neutral-bg text-status-neutral",
  info: "bg-status-info-bg text-status-info",
  warn: "bg-status-warn-bg text-status-warn",
  success: "bg-status-success-bg text-status-success",
  danger: "bg-status-danger-bg text-status-danger",
  offer: "bg-status-offer-bg text-status-offer",
};

export const TONE_DOT_CLASSES: Record<Tone, string> = {
  neutral: "bg-status-neutral",
  info: "bg-status-info",
  warn: "bg-status-warn",
  success: "bg-status-success",
  danger: "bg-status-danger",
  offer: "bg-status-offer",
};

/** `$176,800` — full precision, for figures the user typed themselves. */
export function formatMoney(
  value: number | null | undefined,
  currency = "USD",
  { compact = false }: { compact?: boolean } = {},
): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    notation: compact && Math.abs(value) >= 10_000 ? "compact" : "standard",
    maximumFractionDigits: Number.isInteger(value) ? 0 : 2,
  }).format(value);
}

/** "2 years, 3 months" — how long a job has run. */
export function formatTenure(days: number | null | undefined): string {
  if (days === null || days === undefined) return "—";
  if (days < 31) return `${days} day${days === 1 ? "" : "s"}`;
  const months = Math.floor(days / 30.44);
  if (months < 12) return `${months} month${months === 1 ? "" : "s"}`;
  const years = Math.floor(months / 12);
  const rest = months % 12;
  const yearPart = `${years} year${years === 1 ? "" : "s"}`;
  return rest ? `${yearPart}, ${rest} month${rest === 1 ? "" : "s"}` : yearPart;
}

export const JOB_STATUS_LABELS: Record<string, string> = {
  offered: "Offered",
  accepted: "Accepted",
  active: "Active",
  ended: "Ended",
  declined: "Declined",
};

export const JOB_TYPE_LABELS: Record<string, string> = {
  full_time: "Full time",
  part_time: "Part time",
  contract: "Contract",
  freelance: "Freelance",
  internship: "Internship",
  temporary: "Temporary",
};

export const JOB_END_REASON_LABELS: Record<string, string> = {
  resigned: "Resigned",
  laid_off: "Laid off",
  contract_ended: "Contract ended",
  terminated: "Terminated",
  other: "Other",
};

export const PAY_PERIOD_LABELS: Record<string, string> = {
  weekly: "Weekly",
  biweekly: "Every two weeks",
  semimonthly: "Twice a month",
  monthly: "Monthly",
};

/** Cheques per year. Twice-a-month is 24, not 26 — people notice on payday. */
export const PAY_PERIODS_PER_YEAR: Record<string, number> = {
  weekly: 52,
  biweekly: 26,
  semimonthly: 24,
  monthly: 12,
};
