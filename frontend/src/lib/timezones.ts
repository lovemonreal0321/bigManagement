/**
 * The timezones this app offers.
 *
 * Deliberately just the three US zones. The IANA identifier is what gets
 * stored, never the literal abbreviation: `America/Los_Angeles` follows
 * daylight saving, whereas a fixed `PST` would be an hour wrong from March to
 * November. The abbreviation is only ever a label.
 */

export interface TimezoneOption {
  /** IANA identifier — what is stored and what `Intl` formats with. */
  value: string;
  /** Short form shown in dense UI. */
  short: string;
  /** Full form for pickers. */
  label: string;
}

export const TIMEZONES: TimezoneOption[] = [
  { value: "America/Los_Angeles", short: "PST", label: "PST — Pacific" },
  { value: "America/Chicago", short: "CST", label: "CST — Central" },
  { value: "America/New_York", short: "EST", label: "EST — Eastern" },
];

export const DEFAULT_TIMEZONE = "America/New_York";

const BY_VALUE = new Map(TIMEZONES.map((zone) => [zone.value, zone]));

/**
 * Short label for a stored timezone.
 *
 * Values outside the three are still rendered rather than hidden — calendar
 * events arrive with whatever zone the provider used, and showing
 * "Europe/Berlin" is more honest than mislabelling it or dropping it.
 */
export function timezoneShort(value: string | null | undefined): string {
  if (!value) return "";
  return BY_VALUE.get(value)?.short ?? value;
}

export function timezoneLabel(value: string | null | undefined): string {
  if (!value) return "";
  return BY_VALUE.get(value)?.label ?? value;
}

export function isSupportedTimezone(value: string | null | undefined): boolean {
  return Boolean(value && BY_VALUE.has(value));
}

/**
 * Options for a picker, including the current value when it is not one of the
 * three.
 *
 * Without this, editing a record that predates the restriction would silently
 * rewrite its timezone to whichever option happened to render first.
 */
export function timezoneOptions(current?: string | null): TimezoneOption[] {
  if (!current || BY_VALUE.has(current)) return TIMEZONES;
  return [
    ...TIMEZONES,
    { value: current, short: current, label: `${current} (current)` },
  ];
}
