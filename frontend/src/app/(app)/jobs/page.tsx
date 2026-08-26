"use client";

/**
 * Jobs — what the search is actually for.
 *
 * An application is an opportunity being pursued; a job is income being earned.
 * This page answers three questions: what is anyone earning, when is the next
 * payday, and what has been offered but not settled.
 */

import {
  Banknote,
  CalendarClock,
  Briefcase as BriefcaseIcon,
  Pencil,
  Plus,
  Lock,
  Square,
  Trash2,
  Wallet,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";

import { JobDialog } from "@/components/jobs/job-dialog";
import { PersonAvatar } from "@/components/shared/badges";
import { PageHeader } from "@/components/shared/page-header";
import { ReadOnlyNote } from "@/components/shared/read-only";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/overlays";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  Field,
  Input,
  NativeSelect,
  Skeleton,
  Textarea,
} from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  formatDateOnly,
  formatMoney,
  formatTenure,
  JOB_END_REASON_LABELS,
  JOB_STATUS_LABELS,
  JOB_TYPE_LABELS,
  PAY_PERIOD_LABELS,
} from "@/lib/format";
import { usePersonFilter } from "@/lib/person-filter";
import { useDeleteJob, useEndJob, useJobs, useJobSummary } from "@/lib/queries";
import { JOB_END_REASONS, type Job } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_TONES: Record<string, string> = {
  active: "bg-status-success-bg text-status-success",
  accepted: "bg-status-info-bg text-status-info",
  offered: "bg-status-warn-bg text-status-warn",
  ended: "bg-surface-muted text-muted-foreground",
  declined: "bg-surface-muted text-muted-foreground",
};

export default function JobsPage() {
  const { queryIds, people } = usePersonFilter();
  // Only an administrator manages jobs; a granted account reads its assigned
  // profiles and nothing else. The server enforces both.
  const { isAdmin, canViewJobs } = useAuth();
  const [includeEnded, setIncludeEnded] = React.useState(true);
  const jobs = useJobs(queryIds, includeEnded, canViewJobs);
  const summary = useJobSummary(queryIds, canViewJobs);

  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<Job | null>(null);
  const [ending, setEnding] = React.useState<Job | null>(null);

  // Reachable by typing the URL even with the nav item hidden.
  if (!canViewJobs) {
    return (
      <div className="space-y-4">
        <PageHeader title="Jobs" />
        <Card>
          <EmptyState
            icon={Lock}
            title="Job records are not shared with your account"
            description="Jobs carry salary details, so they are only visible to administrators and to accounts granted access. An administrator can grant it in Settings → Users."
          />
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Jobs"
        description={
          isAdmin
            ? "Offers, employment and payday — the outcome the rest of the app is working towards."
            : "Read-only. You are seeing the profiles assigned to you."
        }
        actions={
          isAdmin ? (
            <Button
              size="sm"
              variant="primary"
              onClick={() => {
                setEditing(null);
                setDialogOpen(true);
              }}
            >
              <Plus />
              Add job
            </Button>
          ) : null
        }
      />

      <JobSummaryCards summary={summary.data} loading={summary.isLoading} />

      <Card>
        <CardHeader
          title="All jobs"
          description="Live roles first, then history."
          action={
            <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={includeEnded}
                onChange={(event) => setIncludeEnded(event.target.checked)}
                className="size-3.5 accent-[var(--primary)]"
              />
              Show ended
            </label>
          }
        />

        {jobs.isLoading ? (
          <CardBody className="space-y-2">
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
          </CardBody>
        ) : jobs.isError ? (
          <CardBody>
            <ErrorState
              message={
                jobs.error instanceof ApiError ? jobs.error.message : undefined
              }
              onRetry={() => jobs.refetch()}
            />
          </CardBody>
        ) : (jobs.data?.length ?? 0) === 0 ? (
          <EmptyState
            icon={Wallet}
            title="No jobs recorded yet"
            description="Add one when an offer lands — it can be linked to the application that won it."
            action={
              isAdmin ? (
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() => {
                    setEditing(null);
                    setDialogOpen(true);
                  }}
                >
                  Add job
                </Button>
              ) : null
            }
          />
        ) : (
          <ul className="divide-y divide-border">
            {(jobs.data ?? []).map((job) => (
              <JobRow
                key={job.id}
                job={job}
                canEdit={isAdmin}
                onEdit={() => {
                  setEditing(job);
                  setDialogOpen(true);
                }}
                onEnd={() => setEnding(job)}
              />
            ))}
          </ul>
        )}
      </Card>

      <JobDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        job={editing}
        people={people}
      />
      <EndJobDialog job={ending} onClose={() => setEnding(null)} />
    </div>
  );
}

// --------------------------------------------------------------------------

function JobSummaryCards({
  summary,
  loading,
}: {
  summary: ReturnType<typeof useJobSummary>["data"];
  loading?: boolean;
}) {
  if (loading) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-20" />
        ))}
      </div>
    );
  }
  if (!summary) return null;

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Tile
        icon={<Banknote className="size-4" />}
        label="Annual, live jobs"
        value={formatMoney(summary.total_annual, summary.currency, {
          compact: true,
        })}
        hint={
          summary.offered_count > 0
            ? `${summary.offered_count} offer${summary.offered_count === 1 ? "" : "s"} not counted`
            : "Offers and ended jobs excluded"
        }
      />
      <Tile
        icon={<BriefcaseIcon className="size-4" />}
        label="Live jobs"
        value={String(summary.live_count)}
        hint={`${summary.ended_count} ended`}
      />
      <Tile
        icon={<CalendarClock className="size-4" />}
        label="Next payday"
        value={
          summary.next_pay_date ? formatDateOnly(summary.next_pay_date) : "—"
        }
        hint={
          summary.next_pay_amount
            ? `${formatMoney(summary.next_pay_amount, summary.currency)} gross`
            : "No pay schedule set"
        }
      />
      <Tile
        icon={<Wallet className="size-4" />}
        label="People earning"
        value={String(
          summary.by_person.filter((person) => person.live_count > 0).length,
        )}
        hint={`of ${summary.by_person.length} shown`}
      />
    </div>
  );
}

function Tile({
  icon,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <Card className="p-3">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {icon}
        {label}
      </div>
      <p className="mt-1 text-xl font-semibold tracking-tight text-foreground">
        {value}
      </p>
      {hint ? (
        <p className="mt-0.5 text-[11px] text-subtle-foreground">{hint}</p>
      ) : null}
    </Card>
  );
}

function JobRow({
  job,
  canEdit,
  onEdit,
  onEnd,
}: {
  job: Job;
  canEdit: boolean;
  onEdit: () => void;
  onEnd: () => void;
}) {
  const remove = useDeleteJob();

  return (
    <li className={cn("p-3", !job.is_live && "opacity-70")}>
      <div className="flex flex-wrap items-start gap-2">
        <PersonAvatar
          color={job.person_color}
          initials={job.person_initials}
          title={job.person_name}
          size="md"
        />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <p className="truncate text-sm font-medium text-foreground">
              {job.company_name}
            </p>
            <span
              className={cn(
                "rounded px-1.5 py-0.5 text-[11px] font-medium",
                STATUS_TONES[job.status],
              )}
            >
              {JOB_STATUS_LABELS[job.status]}
            </span>
            <span className="rounded bg-surface-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
              {JOB_TYPE_LABELS[job.job_type]}
            </span>
          </div>
          <p className="truncate text-xs text-muted-foreground">
            {job.title}
            {job.location ? ` · ${job.location}` : ""}
            {job.start_date ? ` · from ${formatDateOnly(job.start_date)}` : ""}
            {job.tenure_days !== null ? ` · ${formatTenure(job.tenure_days)}` : ""}
          </p>

          {job.end_date ? (
            <p className="mt-0.5 text-xs text-muted-foreground">
              Ended {formatDateOnly(job.end_date)}
              {job.end_reason ? ` · ${JOB_END_REASON_LABELS[job.end_reason]}` : ""}
              {job.end_note ? ` — ${job.end_note}` : ""}
            </p>
          ) : null}

          {job.application_id ? (
            <Link
              href={`/applications/${job.application_id}`}
              className="mt-0.5 inline-block text-xs text-primary hover:underline"
            >
              From the {job.application_company} application →
            </Link>
          ) : null}
        </div>

        <div className="text-right">
          <p className="text-sm font-semibold tabular-nums text-foreground">
            {formatMoney(job.annual_amount, job.currency, { compact: true })}
            <span className="text-xs font-normal text-muted-foreground">/yr</span>
          </p>
          {job.hourly_amount ? (
            <p className="text-[11px] tabular-nums text-subtle-foreground">
              {formatMoney(job.hourly_amount, job.currency)}/h ·{" "}
              {job.hours_per_week}h week
            </p>
          ) : null}
        </div>

        {canEdit ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="icon-sm" variant="ghost" aria-label={`Actions for ${job.company_name}`}>
                <Pencil className="size-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuItem onSelect={onEdit}>Edit</DropdownMenuItem>
              {job.is_live ? (
                <DropdownMenuItem onSelect={onEnd}>
                  <Square />
                  End this job
                </DropdownMenuItem>
              ) : null}
              <DropdownMenuItem
                destructive
                onSelect={async () => {
                  try {
                    await remove.mutateAsync(job.id);
                    toast.success("Job removed");
                  } catch (error) {
                    toast.error(
                      error instanceof ApiError
                        ? error.message
                        : "Could not remove the job.",
                    );
                  }
                }}
              >
                <Trash2 />
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : (
          <ReadOnlyNote />
        )}
      </div>

      {/* Upcoming paydays — only a live job with a schedule has any. */}
      {job.upcoming_pay_dates.length > 0 ? (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 pl-10">
          <span className="text-[11px] text-subtle-foreground">
            {PAY_PERIOD_LABELS[job.pay_period]} ·
          </span>
          {job.upcoming_pay_dates.slice(0, 4).map((pay) => (
            <span
              key={pay.date}
              className={cn(
                "rounded-full border px-2 py-0.5 text-[11px] tabular-nums",
                pay.is_next
                  ? "border-primary bg-primary/10 text-foreground"
                  : "border-border text-muted-foreground",
              )}
            >
              {formatDateOnly(pay.date)}
              {pay.amount ? ` · ${formatMoney(pay.amount, job.currency)}` : ""}
            </span>
          ))}
        </div>
      ) : null}
    </li>
  );
}

function EndJobDialog({ job, onClose }: { job: Job | null; onClose: () => void }) {
  const endJob = useEndJob();
  const [error, setError] = React.useState<string | null>(null);

  return (
    <Dialog open={Boolean(job)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent title={job ? `End the job at ${job.company_name}` : "End job"}>
        {job ? (
          <form
            className="space-y-3 p-4"
            onSubmit={async (event) => {
              event.preventDefault();
              setError(null);
              const form = new FormData(event.currentTarget);
              try {
                await endJob.mutateAsync({
                  id: job.id,
                  body: {
                    end_date: form.get("end_date") || null,
                    reason: form.get("reason") || null,
                    note: form.get("note") || null,
                  },
                });
                toast.success("Job marked as ended");
                onClose();
              } catch (err) {
                setError(
                  err instanceof ApiError ? err.message : "Could not end the job.",
                );
              }
            }}
          >
            <p className="text-sm text-muted-foreground">
              The job stays on record — ending it stops the pay projection and
              takes it out of the earning total.
            </p>

            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Last day" htmlFor="end-date">
                <Input id="end-date" name="end_date" type="date" />
              </Field>
              <Field label="Reason" htmlFor="end-reason">
                <NativeSelect id="end-reason" name="reason" defaultValue="">
                  <option value="">Not recorded</option>
                  {JOB_END_REASONS.map((value) => (
                    <option key={value} value={value}>
                      {JOB_END_REASON_LABELS[value]}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
            </div>

            <Field label="Note" htmlFor="end-note" hint="optional">
              <Textarea id="end-note" name="note" rows={2} />
            </Field>

            {error ? (
              <div className="text-xs text-status-danger">{error}</div>
            ) : null}

            <DialogFooter>
              <Button type="button" variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" loading={endJob.isPending}>
                End job
              </Button>
            </DialogFooter>
          </form>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
