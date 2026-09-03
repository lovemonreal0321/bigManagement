"use client";

/**
 * Adding or editing a job.
 *
 * The salary block is the part worth care: whichever figure you type, the other
 * is worked out live, and either can be overridden. The basis (hours a week,
 * weeks a year) is on screen rather than assumed, because 40 x 52 is only right
 * for a full-time year.
 */

import * as React from "react";
import { toast } from "sonner";

import { ApplicationPicker } from "@/components/applications/application-picker";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/overlays";
import {
  Alert,
  Button,
  Field,
  Input,
  NativeSelect,
  Textarea,
} from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import {
  formatMoney,
  JOB_STATUS_LABELS,
  JOB_TYPE_LABELS,
  PAY_PERIOD_LABELS,
  PAY_PERIODS_PER_YEAR,
} from "@/lib/format";
import { useCreateJob, useUpdateJob } from "@/lib/queries";
import {
  JOB_STATUSES,
  JOB_TYPES,
  PAY_PERIODS,
  type Job,
  type PersonWithStats,
} from "@/lib/types";

/**
 * What is already known when a job is recorded from an offer.
 *
 * Everything the application can answer, so the form opens with the company,
 * the role and the link already filled in and only the terms left to type.
 */
export interface JobPrefill {
  person_id: string;
  company_name: string;
  title: string;
  application_id: string;
  interview_stage_id: string | null;
  offered_date: string | null;
}

export function JobDialog({
  open,
  onOpenChange,
  job,
  people,
  defaultPersonId,
  prefill,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  job?: Job | null;
  people: PersonWithStats[];
  defaultPersonId?: string | null;
  prefill?: JobPrefill | null;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={
          job
            ? "Edit job"
            : prefill
              ? `Record the offer from ${prefill.company_name}`
              : "Add a job"
        }
        size="lg"
      >
        {/* Unmounted while closed, so the form resets without an effect. */}
        {open ? (
          <JobForm
            job={job ?? null}
            prefill={job ? null : (prefill ?? null)}
            people={people}
            defaultPersonId={defaultPersonId ?? null}
            onDone={() => onOpenChange(false)}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function JobForm({
  job,
  prefill,
  people,
  defaultPersonId,
  onDone,
}: {
  job: Job | null;
  prefill: JobPrefill | null;
  people: PersonWithStats[];
  defaultPersonId: string | null;
  onDone: () => void;
}) {
  const createJob = useCreateJob();
  const updateJob = useUpdateJob();
  const [error, setError] = React.useState<string | null>(null);

  const [personId, setPersonId] = React.useState(
    job?.person_id ?? prefill?.person_id ?? defaultPersonId ?? people[0]?.id ?? "",
  );
  const [salaryType, setSalaryType] = React.useState(job?.salary_type ?? "annual");
  const [annual, setAnnual] = React.useState(
    job?.annual_amount != null ? String(job.annual_amount) : "",
  );
  const [hourly, setHourly] = React.useState(
    job?.hourly_amount != null ? String(job.hourly_amount) : "",
  );
  const [hoursPerWeek, setHoursPerWeek] = React.useState(
    String(job?.hours_per_week ?? 40),
  );
  const [weeksPerYear, setWeeksPerYear] = React.useState(
    String(job?.weeks_per_year ?? 52),
  );
  const [payPeriod, setPayPeriod] = React.useState(job?.pay_period ?? "biweekly");
  const [status, setStatus] = React.useState(job?.status ?? "offered");
  const [applicationId, setApplicationId] = React.useState(
    job?.application_id ?? prefill?.application_id ?? "",
  );

  const basis =
    (Number(hoursPerWeek) || 0) * (Number(weeksPerYear) || 0);

  /** Typing in one box fills the other, live. */
  function onAnnualChange(value: string) {
    setAnnual(value);
    const amount = Number(value);
    if (value && Number.isFinite(amount) && basis > 0) {
      setHourly((amount / basis).toFixed(2));
    }
  }
  function onHourlyChange(value: string) {
    setHourly(value);
    const rate = Number(value);
    if (value && Number.isFinite(rate)) {
      setAnnual(String(Math.round(rate * basis)));
    }
  }

  /**
   * Changing the basis has to move the derived figure too, or the two stop
   * agreeing: setting 32 hours a week while the annual still reads a 40-hour
   * year is simply wrong on screen.
   */
  function rebase(nextHours: string, nextWeeks: string) {
    const nextBasis = (Number(nextHours) || 0) * (Number(nextWeeks) || 0);
    if (nextBasis <= 0) return;
    if (salaryType === "hourly") {
      const rate = Number(hourly);
      if (hourly && Number.isFinite(rate)) {
        setAnnual(String(Math.round(rate * nextBasis)));
      }
    } else {
      const amount = Number(annual);
      if (annual && Number.isFinite(amount)) {
        setHourly((amount / nextBasis).toFixed(2));
      }
    }
  }

  function onHoursChange(value: string) {
    setHoursPerWeek(value);
    rebase(value, weeksPerYear);
  }
  function onWeeksChange(value: string) {
    setWeeksPerYear(value);
    rebase(hoursPerWeek, value);
  }

  const perCheque =
    Number(annual) > 0 && PAY_PERIODS_PER_YEAR[payPeriod]
      ? Number(annual) / PAY_PERIODS_PER_YEAR[payPeriod]
      : null;

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);

    const body: Record<string, unknown> = {
      company_name: String(form.get("company_name") ?? "").trim(),
      title: String(form.get("title") ?? "").trim(),
      job_type: form.get("job_type"),
      status,
      location: form.get("location") || null,
      start_date: form.get("start_date") || null,
      salary_type: salaryType,
      annual_amount: annual ? Number(annual) : null,
      hourly_amount: hourly ? Number(hourly) : null,
      currency: form.get("currency") || "USD",
      hours_per_week: Number(hoursPerWeek) || 40,
      weeks_per_year: Number(weeksPerYear) || 52,
      pay_period: payPeriod,
      first_pay_date: form.get("first_pay_date") || null,
      application_id: applicationId || null,
      notes: form.get("notes") || null,
    };

    // Carried through from the offer rather than shown as fields: the day it
    // landed is already recorded, and the interview it came from is a link,
    // not something to retype.
    if (prefill) {
      body.offered_date = prefill.offered_date;
      body.interview_stage_id = prefill.interview_stage_id;
    }

    try {
      if (job) {
        await updateJob.mutateAsync({ id: job.id, body });
        toast.success("Job updated");
      } else {
        await createJob.mutateAsync({ ...body, person_id: personId });
        toast.success(`${body.company_name} added`);
      }
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the job.");
    }
  }

  const pending = createJob.isPending || updateJob.isPending;

  return (
    <form onSubmit={submit} className="max-h-[70vh] space-y-3 overflow-y-auto p-4">
      {!job ? (
        <Field label="Person" htmlFor="job-person">
          <NativeSelect
            id="job-person"
            value={personId}
            onChange={(event) => setPersonId(event.target.value)}
          >
            {people.map((person) => (
              <option key={person.id} value={person.id}>
                {person.display_name}
              </option>
            ))}
          </NativeSelect>
        </Field>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Company" htmlFor="job-company">
          <Input
            id="job-company"
            name="company_name"
            required
            defaultValue={job?.company_name ?? prefill?.company_name ?? ""}
            placeholder="Anthropic"
          />
        </Field>
        <Field label="Job title" htmlFor="job-title">
          <Input
            id="job-title"
            name="title"
            required
            defaultValue={job?.title ?? prefill?.title ?? ""}
            placeholder="Senior AI Engineer"
          />
        </Field>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Status" htmlFor="job-status">
          <NativeSelect
            id="job-status"
            value={status}
            onChange={(event) => setStatus(event.target.value as Job["status"])}
          >
            {JOB_STATUSES.map((value) => (
              <option key={value} value={value}>
                {JOB_STATUS_LABELS[value]}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field label="Type" htmlFor="job-type">
          <NativeSelect
            id="job-type"
            name="job_type"
            defaultValue={job?.job_type ?? "full_time"}
          >
            {JOB_TYPES.map((value) => (
              <option key={value} value={value}>
                {JOB_TYPE_LABELS[value]}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field label="Start date" htmlFor="job-start">
          <Input
            id="job-start"
            name="start_date"
            type="date"
            defaultValue={job?.start_date ?? ""}
          />
        </Field>
      </div>

      {/* --- money ------------------------------------------------------- */}
      <fieldset className="space-y-3 rounded-md border border-border p-3">
        <legend className="px-1 text-xs font-medium text-muted-foreground">
          Pay
        </legend>

        <Field label="Quoted as">
          <div className="flex gap-2">
            {(["annual", "hourly"] as const).map((value) => (
              <label
                key={value}
                className="inline-flex cursor-pointer items-center gap-1.5 text-sm text-foreground"
              >
                <input
                  type="radio"
                  name="salary_type"
                  checked={salaryType === value}
                  onChange={() => setSalaryType(value)}
                  className="accent-[var(--primary)]"
                />
                {value === "annual" ? "Annual salary" : "Hourly rate"}
              </label>
            ))}
          </div>
        </Field>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label="Annual"
            htmlFor="job-annual"
            hint={salaryType === "hourly" ? "calculated" : undefined}
          >
            <Input
              id="job-annual"
              type="number"
              min={0}
              step="1"
              value={annual}
              onChange={(event) => onAnnualChange(event.target.value)}
              placeholder="180000"
            />
          </Field>
          <Field
            label="Hourly"
            htmlFor="job-hourly"
            hint={salaryType === "annual" ? "calculated" : undefined}
          >
            <Input
              id="job-hourly"
              type="number"
              min={0}
              step="0.01"
              value={hourly}
              onChange={(event) => onHourlyChange(event.target.value)}
              placeholder="85.00"
            />
          </Field>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Hours / week" htmlFor="job-hours">
            <Input
              id="job-hours"
              type="number"
              min={1}
              max={168}
              step="0.5"
              value={hoursPerWeek}
              onChange={(event) => onHoursChange(event.target.value)}
            />
          </Field>
          <Field label="Weeks / year" htmlFor="job-weeks">
            <Input
              id="job-weeks"
              type="number"
              min={1}
              max={53}
              step="1"
              value={weeksPerYear}
              onChange={(event) => onWeeksChange(event.target.value)}
            />
          </Field>
          <Field label="Currency" htmlFor="job-currency">
            <Input
              id="job-currency"
              name="currency"
              defaultValue={job?.currency ?? "USD"}
              maxLength={8}
            />
          </Field>
        </div>

        <p className="text-[11px] text-subtle-foreground">
          The conversion uses {hoursPerWeek || 0} hours a week over{" "}
          {weeksPerYear || 0} weeks. Change either and both figures update; type
          over a figure to override it.
        </p>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Pay period" htmlFor="job-period">
            <NativeSelect
              id="job-period"
              value={payPeriod}
              onChange={(event) =>
                setPayPeriod(event.target.value as Job["pay_period"])
              }
            >
              {PAY_PERIODS.map((value) => (
                <option key={value} value={value}>
                  {PAY_PERIOD_LABELS[value]}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field label="First pay date" htmlFor="job-first-pay">
            <Input
              id="job-first-pay"
              name="first_pay_date"
              type="date"
              defaultValue={job?.first_pay_date ?? ""}
            />
          </Field>
        </div>

        {perCheque ? (
          <p className="text-xs text-muted-foreground">
            About{" "}
            <span className="font-medium text-foreground">
              {formatMoney(perCheque)}
            </span>{" "}
            per cheque, gross — {PAY_PERIODS_PER_YEAR[payPeriod]} a year.
          </p>
        ) : null}
      </fieldset>

      <Field
        label="Came from this application"
        hint="optional"
      >
        {personId ? (
          <ApplicationPicker
            personId={personId}
            value={applicationId}
            onChange={(id) => setApplicationId(id)}
          />
        ) : null}
      </Field>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Location" htmlFor="job-location" hint="optional">
          <Input
            id="job-location"
            name="location"
            defaultValue={job?.location ?? ""}
            placeholder="Remote"
          />
        </Field>
      </div>

      <Field label="Notes" htmlFor="job-notes" hint="optional">
        <Textarea id="job-notes" name="notes" rows={2} defaultValue={job?.notes ?? ""} />
      </Field>

      {error ? (
        <Alert tone="danger" title="Could not save">
          {error}
        </Alert>
      ) : null}

      <DialogFooter>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" loading={pending}>
          {job ? "Save changes" : "Add job"}
        </Button>
      </DialogFooter>
    </form>
  );
}
