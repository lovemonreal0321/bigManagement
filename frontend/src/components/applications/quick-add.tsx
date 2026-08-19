"use client";

/**
 * Quick Add (spec §50).
 *
 * Three required fields — person, company, title — and nothing else in the
 * way. Everything optional sits behind "More details" so the common path is
 * type, type, Enter.
 */

import { Plus } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { PersonAvatar } from "@/components/shared/badges";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/overlays";
import {
  Button,
  Field,
  Input,
  NativeSelect,
  Textarea,
} from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { APPLICATION_STATUS_LABELS, todayIso } from "@/lib/format";
import { usePersonFilter } from "@/lib/person-filter";
import { useCreateApplication } from "@/lib/queries";
import { APPLICATION_STATUSES, WORK_MODES } from "@/lib/types";
import { WORK_MODE_LABELS } from "@/lib/format";

export function QuickAddDialog({
  open,
  onOpenChange,
  defaultPersonId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultPersonId?: string;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="New application"
        description="Person, company and role are all that is required."
      >
        {/* Unmounted while closed, so each open starts from a clean form. */}
        <QuickAddForm
          defaultPersonId={defaultPersonId}
          onDone={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  );
}

function QuickAddForm({
  defaultPersonId,
  onDone,
}: {
  defaultPersonId?: string;
  onDone: () => void;
}) {
  const { people: allPeople, selectedIds } = usePersonFilter();
  const { canEdit } = useAuth();
  // Only offer profiles this user may actually write to, so the form cannot
  // be filled in and then refused at the last step.
  const people = React.useMemo(
    () => allPeople.filter((person) => canEdit(person.id)),
    [allPeople, canEdit],
  );
  const createApplication = useCreateApplication();
  const [expanded, setExpanded] = React.useState(false);
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  // Defaults to the person the user is currently looking at, as long as they
  // may edit them.
  const [personId, setPersonId] = React.useState(() => {
    const preferred = [defaultPersonId, ...selectedIds].find(
      (id) => id && canEdit(id),
    );
    return preferred ?? people[0]?.id ?? "";
  });

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setErrors({});

    const body: Record<string, unknown> = {
      person_id: personId,
      company_name: String(form.get("company_name") ?? "").trim(),
      job_title: String(form.get("job_title") ?? "").trim(),
      status: form.get("status") || "applied",
      applied_date: form.get("applied_date") || undefined,
      job_url: form.get("job_url") || undefined,
      location: form.get("location") || undefined,
      work_mode: form.get("work_mode") || "unknown",
      source: form.get("source") || undefined,
      notes: form.get("notes") || undefined,
    };

    const salaryMin = form.get("salary_min");
    const salaryMax = form.get("salary_max");
    if (salaryMin) body.salary_min = Number(salaryMin);
    if (salaryMax) body.salary_max = Number(salaryMax);

    try {
      await createApplication.mutateAsync(body);
      toast.success(`${body.company_name} added`);
      onDone();
    } catch (error) {
      if (error instanceof ApiError) {
        setErrors(error.fieldErrors);
        toast.error(error.message);
      } else {
        toast.error("Could not save the application.");
      }
    }
  }

  return (
    <form onSubmit={handleSubmit}>
          <div className="space-y-4 p-4">
            <Field label="Person" htmlFor="qa-person" error={errors.person_id}>
              <div className="flex flex-wrap gap-1.5">
                {people.map((person) => (
                  <button
                    key={person.id}
                    type="button"
                    onClick={() => setPersonId(person.id)}
                    className={`inline-flex items-center gap-1.5 rounded-full border py-1 pl-1 pr-2.5 text-xs font-medium transition-colors ${
                      personId === person.id
                        ? "border-primary bg-primary/10 text-foreground"
                        : "border-border bg-surface text-muted-foreground hover:bg-surface-hover"
                    }`}
                  >
                    <PersonAvatar
                      color={person.color}
                      initials={person.initials}
                      size="sm"
                    />
                    {person.display_name}
                  </button>
                ))}
              </div>
              <input type="hidden" id="qa-person" value={personId} readOnly />
            </Field>

            <div className="grid gap-3 sm:grid-cols-2">
              <Field
                label="Company"
                htmlFor="qa-company"
                error={errors.company_name}
              >
                <Input
                  id="qa-company"
                  name="company_name"
                  required
                  autoFocus
                  placeholder="Amazon"
                  invalid={Boolean(errors.company_name)}
                />
              </Field>
              <Field
                label="Job title"
                htmlFor="qa-title"
                error={errors.job_title}
              >
                <Input
                  id="qa-title"
                  name="job_title"
                  required
                  placeholder="Senior AI Engineer"
                  invalid={Boolean(errors.job_title)}
                />
              </Field>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Applied date" htmlFor="qa-date">
                <Input
                  id="qa-date"
                  name="applied_date"
                  type="date"
                  defaultValue={todayIso()}
                />
              </Field>
              <Field label="Status" htmlFor="qa-status">
                <NativeSelect
                  id="qa-status"
                  name="status"
                  defaultValue="applied"
                >
                  {APPLICATION_STATUSES.map((status) => (
                    <option key={status} value={status}>
                      {APPLICATION_STATUS_LABELS[status]}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
            </div>

            {expanded ? (
              <div className="space-y-3 border-t border-border pt-3">
                <Field label="Job posting URL" htmlFor="qa-url">
                  <Input
                    id="qa-url"
                    name="job_url"
                    type="url"
                    placeholder="https://…"
                  />
                </Field>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Location" htmlFor="qa-location">
                    <Input
                      id="qa-location"
                      name="location"
                      placeholder="Seattle, WA"
                    />
                  </Field>
                  <Field label="Work mode" htmlFor="qa-mode">
                    <NativeSelect
                      id="qa-mode"
                      name="work_mode"
                      defaultValue="unknown"
                    >
                      {WORK_MODES.map((mode) => (
                        <option key={mode} value={mode}>
                          {WORK_MODE_LABELS[mode]}
                        </option>
                      ))}
                    </NativeSelect>
                  </Field>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <Field label="Salary min" htmlFor="qa-smin">
                    <Input
                      id="qa-smin"
                      name="salary_min"
                      type="number"
                      min={0}
                      placeholder="180000"
                    />
                  </Field>
                  <Field label="Salary max" htmlFor="qa-smax">
                    <Input
                      id="qa-smax"
                      name="salary_max"
                      type="number"
                      min={0}
                      placeholder="220000"
                    />
                  </Field>
                  <Field label="Source" htmlFor="qa-source">
                    <Input
                      id="qa-source"
                      name="source"
                      placeholder="LinkedIn"
                    />
                  </Field>
                </div>
                <Field label="Notes" htmlFor="qa-notes">
                  <Textarea id="qa-notes" name="notes" rows={3} />
                </Field>
              </div>
            ) : null}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setExpanded((value) => !value)}
            >
              {expanded ? "Fewer details" : "More details"}
            </Button>
            <div className="flex-1" />
        <Button type="button" variant="secondary" size="sm" onClick={onDone}>
          Cancel
        </Button>
        <Button
          type="submit"
          variant="primary"
          size="sm"
          loading={createApplication.isPending}
          disabled={!personId}
        >
          Add application
        </Button>
      </DialogFooter>
    </form>
  );
}

export function QuickAddButton() {
  const [open, setOpen] = React.useState(false);
  const { people } = usePersonFilter();
  const { canEdit } = useAuth();
  const editable = people.filter((person) => canEdit(person.id));

  return (
    <>
      <Button
        variant="primary"
        size="sm"
        disabled={editable.length === 0}
        onClick={() => setOpen(true)}
        title={
          people.length === 0
            ? "Add a person first"
            : editable.length === 0
              ? "You have no profiles assigned to you yet"
              : "Add an application"
        }
      >
        <Plus />
        <span className="hidden sm:inline">New</span>
      </Button>
      <QuickAddDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
