"use client";

/**
 * Analytics charts.
 *
 * Conventions applied throughout (see the dataviz method):
 *   - Colour is assigned by job. Person series use each person's own colour
 *     (identity); magnitude charts use ONE hue and vary length, not hue.
 *   - One axis per chart. Never two y-scales.
 *   - Every rate is shown with its numerator/denominator, never a bare
 *     percentage (spec §27).
 *   - Grid and axes are recessive; marks are thin with rounded data-ends.
 *   - Legend for two or more series, plus a table view for the comparison.
 */

import * as React from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatPercent } from "@/lib/format";
import type {
  FunnelStep,
  PersonComparisonRow,
  Rate,
  TimeSeriesPoint,
  TypePerformance,
} from "@/lib/types";

const AXIS_STYLE = {
  fontSize: 11,
  fill: "var(--muted-foreground)",
} as const;

const GRID_STROKE = "var(--border)";

/** Shared tooltip shell so every chart reads the same. */
function TooltipCard({
  title,
  rows,
}: {
  title: string;
  rows: { label: string; value: string; color?: string }[];
}) {
  return (
    <div className="rounded-md border border-border bg-surface px-2.5 py-2 shadow-lg">
      <p className="mb-1 text-xs font-medium text-foreground">{title}</p>
      <ul className="space-y-0.5">
        {rows.map((row) => (
          <li
            key={row.label}
            className="flex items-center gap-2 text-[11px] text-muted-foreground"
          >
            {row.color ? (
              <span
                className="size-2 shrink-0 rounded-full"
                style={{ backgroundColor: row.color }}
                aria-hidden
              />
            ) : null}
            <span className="flex-1">{row.label}</span>
            <span className="tabular font-medium text-foreground">
              {row.value}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// --------------------------------------------------------------------------
// Funnel (spec §29)
// --------------------------------------------------------------------------

/**
 * A funnel is a magnitude comparison, so it uses one hue and varies length.
 * Rendered as plain bars rather than a chart library: at five steps the CSS
 * version is lighter, keeps the conversion labels exactly where they belong,
 * and cannot mis-scale.
 */
export function FunnelChart({ steps }: { steps: FunnelStep[] }) {
  const max = Math.max(...steps.map((step) => step.count), 1);

  return (
    <ol className="space-y-2.5">
      {steps.map((step, index) => {
        const width = (step.count / max) * 100;
        return (
          <li key={step.key}>
            <div className="mb-1 flex items-baseline justify-between gap-2">
              <span className="text-xs font-medium text-foreground">
                {step.label}
              </span>
              <span className="flex items-baseline gap-2">
                <span className="tabular text-sm font-semibold text-foreground">
                  {step.count}
                </span>
                {step.conversion_from_previous ? (
                  <span className="tabular text-[11px] text-muted-foreground">
                    {formatPercent(step.conversion_from_previous.percent)} of
                    previous
                  </span>
                ) : null}
              </span>
            </div>
            <div
              className="h-2.5 w-full overflow-hidden rounded-full bg-surface-muted"
              role="img"
              aria-label={`${step.label}: ${step.count}`}
            >
              <div
                className="h-full rounded-full transition-[width]"
                style={{
                  width: `${Math.max(width, step.count > 0 ? 2 : 0)}%`,
                  // One hue, stepped darker as the funnel narrows.
                  backgroundColor: `color-mix(in srgb, var(--primary) ${
                    100 - index * 12
                  }%, var(--border-strong))`,
                }}
              />
            </div>
          </li>
        );
      })}
    </ol>
  );
}

// --------------------------------------------------------------------------
// Pass rate by interview type (spec §27)
// --------------------------------------------------------------------------

export function TypePerformanceChart({ rows }: { rows: TypePerformance[] }) {
  // Only types with a decided outcome can have a rate at all.
  const data = rows.filter((row) => row.total_decided > 0);
  if (data.length === 0) {
    return (
      <p className="py-6 text-center text-xs text-muted-foreground">
        No decided interview outcomes in this period yet.
      </p>
    );
  }

  return (
    <div>
      <div style={{ height: Math.max(140, data.length * 34) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            layout="vertical"
            margin={{ top: 4, right: 44, bottom: 4, left: 4 }}
            barCategoryGap={6}
          >
            <CartesianGrid
              horizontal={false}
              stroke={GRID_STROKE}
              strokeDasharray="2 2"
            />
            <XAxis
              type="number"
              domain={[0, 100]}
              tickFormatter={(value) => `${value}%`}
              tick={AXIS_STYLE}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              type="category"
              dataKey="short_label"
              width={82}
              tick={AXIS_STYLE}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              cursor={{ fill: "var(--surface-hover)" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const row = payload[0].payload as TypePerformance;
                return (
                  <TooltipCard
                    title={row.label}
                    rows={[
                      {
                        label: "Pass rate",
                        value: formatPercent(row.rate.percent),
                      },
                      {
                        label: "Passed",
                        value: `${row.passed} of ${row.total_decided}`,
                      },
                      { label: "Awaiting result", value: String(row.waiting) },
                      { label: "Scheduled", value: String(row.scheduled) },
                    ]}
                  />
                );
              }}
            />
            <Bar
              dataKey={(row: TypePerformance) => row.rate.percent ?? 0}
              radius={[0, 4, 4, 0]}
              barSize={14}
              // Magnitude, so one hue; low-evidence bars are muted rather than
              // recoloured, so the eye is not drawn to an unreliable number.
              label={{
                position: "right",
                fontSize: 11,
                fill: "var(--muted-foreground)",
                formatter: (value: unknown) => `${value ?? 0}%`,
              }}
            >
              {data.map((row) => (
                <Cell
                  key={row.type_key}
                  fill={
                    row.rate.is_meaningful
                      ? "var(--primary)"
                      : "var(--border-strong)"
                  }
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* The fraction behind every percentage (spec §27). */}
      <ul className="mt-2 grid gap-x-4 gap-y-1 border-t border-border pt-2 sm:grid-cols-2">
        {data.map((row) => (
          <li
            key={row.type_key}
            className="flex items-baseline justify-between text-[11px]"
          >
            <span className="text-muted-foreground">{row.label}</span>
            <span className="tabular text-foreground">
              {row.passed} / {row.total_decided} passed
              {!row.rate.is_meaningful ? (
                <span className="ml-1 text-subtle-foreground">
                  (too few to read into)
                </span>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// --------------------------------------------------------------------------
// Person comparison (spec §28)
// --------------------------------------------------------------------------

type ComparisonMetric = "applications" | "interviews_held" | "offers";

const COMPARISON_METRICS: { key: ComparisonMetric; label: string }[] = [
  { key: "applications", label: "Applications" },
  { key: "interviews_held", label: "Interviews" },
  { key: "offers", label: "Offers" },
];

export function PersonComparisonChart({
  rows,
}: {
  rows: PersonComparisonRow[];
}) {
  const [metric, setMetric] = React.useState<ComparisonMetric>("applications");

  if (rows.length === 0) return null;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-1">
        {COMPARISON_METRICS.map((option) => (
          <button
            key={option.key}
            type="button"
            onClick={() => setMetric(option.key)}
            className={`rounded px-2 py-1 text-[11px] font-medium transition-colors ${
              metric === option.key
                ? "bg-surface-muted text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>

      <div style={{ height: Math.max(120, rows.length * 40) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={rows}
            layout="vertical"
            margin={{ top: 4, right: 36, bottom: 4, left: 4 }}
            barCategoryGap={8}
          >
            <CartesianGrid
              horizontal={false}
              stroke={GRID_STROKE}
              strokeDasharray="2 2"
            />
            <XAxis
              type="number"
              tick={AXIS_STYLE}
              tickLine={false}
              axisLine={false}
              allowDecimals={false}
            />
            <YAxis
              type="category"
              dataKey="person_name"
              width={72}
              tick={AXIS_STYLE}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              cursor={{ fill: "var(--surface-hover)" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const row = payload[0].payload as PersonComparisonRow;
                return (
                  <TooltipCard
                    title={row.person_name}
                    rows={[
                      {
                        label: "Applications",
                        value: String(row.applications),
                        color: row.person_color,
                      },
                      {
                        label: "Interviews held",
                        value: String(row.interviews_held),
                      },
                      {
                        label: "Pass rate",
                        value: `${formatPercent(row.pass_rate.percent)} (${
                          row.pass_rate.numerator
                        }/${row.pass_rate.denominator})`,
                      },
                      { label: "Offers", value: String(row.offers) },
                    ]}
                  />
                );
              }}
            />
            <Bar
              dataKey={metric}
              radius={[0, 4, 4, 0]}
              barSize={16}
              label={{
                position: "right",
                fontSize: 11,
                fill: "var(--muted-foreground)",
              }}
            >
              {/* Colour follows the person, never their rank. */}
              {rows.map((row) => (
                <Cell key={row.person_id} fill={row.person_color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/** The table view that accompanies the comparison chart. */
export function PersonComparisonTable({
  rows,
}: {
  rows: PersonComparisonRow[];
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-subtle-foreground">
            <th className="px-4 py-2 font-medium">Metric</th>
            {rows.map((row) => (
              <th key={row.person_id} className="px-3 py-2 text-right font-medium">
                <span className="inline-flex items-center gap-1.5">
                  <span
                    className="size-2 rounded-full"
                    style={{ backgroundColor: row.person_color }}
                    aria-hidden
                  />
                  {row.person_name}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {(
            [
              ["Applications", (r: PersonComparisonRow) => String(r.applications)],
              ["Interviews", (r: PersonComparisonRow) => String(r.interviews_held)],
              [
                "Pass rate",
                (r: PersonComparisonRow) =>
                  r.pass_rate.denominator === 0
                    ? "—"
                    : `${formatPercent(r.pass_rate.percent)} (${r.pass_rate.numerator}/${r.pass_rate.denominator})`,
              ],
              ["Final rounds", (r: PersonComparisonRow) => String(r.final_rounds)],
              ["Offers", (r: PersonComparisonRow) => String(r.offers)],
              ["Accepted", (r: PersonComparisonRow) => String(r.accepted)],
            ] as const
          ).map(([label, accessor]) => (
            <tr key={label}>
              <td className="px-4 py-2 text-muted-foreground">{label}</td>
              {rows.map((row) => (
                <td
                  key={row.person_id}
                  className="tabular px-3 py-2 text-right text-foreground"
                >
                  {accessor(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --------------------------------------------------------------------------
// Trend (spec §55)
// --------------------------------------------------------------------------

const TREND_SERIES = [
  { key: "applications", label: "Applications", color: "var(--status-info)" },
  { key: "interviews", label: "Interviews", color: "var(--status-offer)" },
  { key: "offers", label: "Offers", color: "var(--status-success)" },
] as const;

export function TrendChart({ points }: { points: TimeSeriesPoint[] }) {
  if (points.length < 2) {
    return (
      <p className="py-6 text-center text-xs text-muted-foreground">
        Not enough history in this period to plot a trend.
      </p>
    );
  }

  const data = points.map((point) => ({
    ...point,
    label: new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
    }).format(new Date(`${point.bucket}T12:00:00Z`)),
  }));

  return (
    <div style={{ height: 220 }}>
      <ResponsiveContainer width="100%" height="100%">
        {/* All three series are counts, so one shared axis is correct. */}
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: -18 }}>
          <CartesianGrid vertical={false} stroke={GRID_STROKE} strokeDasharray="2 2" />
          <XAxis
            dataKey="label"
            tick={AXIS_STYLE}
            tickLine={false}
            axisLine={false}
            minTickGap={24}
          />
          <YAxis
            tick={AXIS_STYLE}
            tickLine={false}
            axisLine={false}
            allowDecimals={false}
            width={38}
          />
          <Tooltip
            cursor={{ stroke: "var(--border-strong)", strokeWidth: 1 }}
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              return (
                <TooltipCard
                  title={String(label)}
                  rows={TREND_SERIES.map((series) => ({
                    label: series.label,
                    color: series.color,
                    value: String(
                      (payload[0].payload as Record<string, number>)[
                        series.key
                      ] ?? 0,
                    ),
                  }))}
                />
              );
            }}
          />
          <Legend
            verticalAlign="top"
            align="right"
            height={28}
            iconType="circle"
            iconSize={8}
            formatter={(value) => (
              <span className="text-[11px] text-muted-foreground">{value}</span>
            )}
          />
          {TREND_SERIES.map((series) => (
            <Line
              key={series.key}
              type="monotone"
              dataKey={series.key}
              name={series.label}
              stroke={series.color}
              strokeWidth={2}
              dot={{ r: 3, strokeWidth: 2 }}
              activeDot={{ r: 5 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// --------------------------------------------------------------------------
// Stat tiles — a number, not a chart (spec §26)
// --------------------------------------------------------------------------

export function RateTile({
  label,
  rate,
  hint,
}: {
  label: string;
  rate: Rate;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-surface p-3">
      <p className="text-[11px] font-medium leading-tight text-muted-foreground">
        {label}
      </p>
      <p className="tabular mt-1.5 text-2xl font-semibold leading-none text-foreground">
        {formatPercent(rate.percent)}
      </p>
      <p className="tabular mt-1.5 text-[11px] text-subtle-foreground">
        {rate.denominator === 0
          ? "No data yet"
          : `${rate.numerator} of ${rate.denominator}`}
        {!rate.is_meaningful && rate.denominator > 0 ? " · small sample" : ""}
      </p>
      {hint ? (
        <p className="mt-1 text-[10px] leading-snug text-subtle-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function CountTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: number;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-surface p-3">
      <p className="text-[11px] font-medium leading-tight text-muted-foreground">
        {label}
      </p>
      <p className="tabular mt-1.5 text-2xl font-semibold leading-none text-foreground">
        {value}
      </p>
      {hint ? (
        <p className="mt-1.5 text-[11px] text-subtle-foreground">{hint}</p>
      ) : null}
    </div>
  );
}
