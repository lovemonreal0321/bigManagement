import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Turn a person's hex colour into a translucent surface.
 *
 * Person colours come from the database and are applied inline, so they cannot
 * be Tailwind classes. `color-mix` keeps a single source of truth for the hue
 * while adapting the tint to light and dark backgrounds.
 */
export function personTint(color: string, percent = 12): string {
  return `color-mix(in srgb, ${color} ${percent}%, transparent)`;
}

export function personBorder(color: string, percent = 40): string {
  return `color-mix(in srgb, ${color} ${percent}%, transparent)`;
}

/** Deterministic key for React lists built from composite values. */
export function keyOf(...parts: (string | number | null | undefined)[]): string {
  return parts.filter((p) => p !== null && p !== undefined).join(":");
}
