"use client";

/**
 * Event detail + the "import an interview from the calendar" flow (spec §46).
 *
 * An imported event can be classified, linked to an existing application, or
 * turned into a brand-new application. Nothing happens automatically — the
 * detection score is shown as evidence, and the user decides.
 */

import { ExternalLink, Link2, Plus, Sparkles, Video } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";

import { PersonAvatar, StageBadge } from "@/components/shared/badges";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/overlays";
import {
  Alert,
  Button,
  Field,
  Input,
  NativeSelect,
  Skeleton,
} from "@/components/ui/primitives";
import {
  LinkTargetPicker,
  type LinkTarget,
} from "@/components/applications/link-target-picker";
import { JourneyStrip } from "@/components/interviews/journey-strip";
import { ReadOnlyNote } from "@/components/shared/read-only";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  CLASSIFICATION_LABELS,
  formatDate,
  formatTime,
} from "@/lib/format";
import {
  useApplication,
  useCalendarEvent,
  useClassifyEvent,
  useCreateApplicationFromEvent,
  useInterviewTypes,
  useLinkEvent,
} from "@/lib/queries";
import { timezoneShort } from "@/lib/timezones";
import type { CalendarFeedEvent } from "@/lib/types";
import { EVENT_CLASSIFICATIONS } from "@/lib/types";

export function EventDetailDialog({
  event,
  onOpenChange,
  tz,
}: {
  event: CalendarFeedEvent | null;
  onOpenChange: (open: boolean) => void;
  tz?: string;
}) {
  const open = event !== null;
  const isExternal = event?.kind === "external";
  const calendarEventId = event?.calendar_event_id ?? null;

  const { data: detail, isLoading } = useCalendarEvent(
    isExternal ? calendarEventId : null,
  );
  const { canEdit } = useAuth();
  // Classifying and linking author records against the event's person.
  const editable = canEdit(event?.person_id);
  const classify = useClassifyEvent();
  // The whole path this meeting belongs to, so the calendar answers "where are
  // we with this company?" rather than just "what is this meeting?".
  const journey = useApplication(event?.application_id ?? "", {
    enabled: Boolean(event?.application_id),
  });
  // Keyed by event id below, so switching events resets the flow without an
  // effect.
  const [mode, setMode] = React.useState<"none" | "link" | "create">("none");

  if (!event) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        key={event.id}
        title={event.company_name ?? event.title}
        description={`${formatDate(event.starts_at, tz)} · ${formatTime(
          event.starts_at,
          tz,
        )} – ${formatTime(event.ends_at, tz)}`}
      >
        <div className="space-y-4 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <PersonAvatar
              color={event.person_color}
              initials={event.person_initials}
              title={event.person_name}
              size="lg"
            />
            <div className="min-w-0">
              <p className="text-sm font-medium text-foreground">
                {event.person_name}
              </p>
              <p className="text-xs text-muted-foreground">
                {timezoneShort(event.timezone ?? tz) || "Workspace time"}
              </p>
            </div>
            <div className="flex-1" />
            {event.stage_badge ? <StageBadge badge={event.stage_badge} /> : null}
          </div>

          {event.kind === "interview" ? (
            <div className="space-y-2 rounded-md border border-border bg-surface-muted/40 p-3">
              <p className="text-sm font-medium text-foreground">
                {event.title}
              </p>
              {event.job_title ? (
                <p className="text-xs text-muted-foreground">
                  {event.job_title}
                </p>
              ) : null}

              {journey.data ? (
                <div className="pt-1">
                  <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-subtle-foreground">
                    The path so far
                  </p>
                  <JourneyStrip
                    appliedDate={journey.data.applied_date}
                    stages={journey.data.stages}
                    highlightStageId={event.interview_stage_id}
                  />
                </div>
              ) : null}

              <div className="flex flex-wrap gap-2 pt-1">
                {event.application_id ? (
                  <Button asChild size="xs" variant="primary">
                    <Link href={`/applications/${event.application_id}`}>
                      Open application
                    </Link>
                  </Button>
                ) : null}
                {event.meeting_url ? (
                  <Button asChild size="xs" variant="secondary">
                    <a href={event.meeting_url} target="_blank" rel="noreferrer">
                      <Video />
                      Join
                    </a>
                  </Button>
                ) : null}
              </div>
            </div>
          ) : null}

          {isExternal ? (
            isLoading ? (
              <Skeleton className="h-24" />
            ) : (
              <>
                {detail?.detection_score && detail.detection_score >= 0.5 ? (
                  <Alert
                    tone="info"
                    title={
                      <span className="flex items-center gap-1.5">
                        <Sparkles className="size-3.5" />
                        Possible interview detected
                      </span>
                    }
                  >
                    <ul className="mt-1 list-disc space-y-0.5 pl-4">
                      {(detail.detection_reasons ?? []).map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                    <p className="mt-1.5 opacity-80">
                      Nothing is created from this on its own — link it or
                      ignore it.
                    </p>
                  </Alert>
                ) : null}

                {detail?.description ? (
                  <p className="max-h-32 overflow-y-auto whitespace-pre-wrap rounded-md border border-border bg-surface-muted/40 p-2 text-xs text-muted-foreground">
                    {detail.description}
                  </p>
                ) : null}

                {editable ? (
                <Field label="Classification">
                  <div className="flex flex-wrap gap-1.5">
                    {EVENT_CLASSIFICATIONS.filter(
                      (value) => value !== "unclassified",
                    ).map((value) => {
                      const active = detail?.classification === value;
                      return (
                        <Button
                          key={value}
                          size="xs"
                          variant={active ? "primary" : "secondary"}
                          loading={
                            classify.isPending &&
                            classify.variables?.classification === value
                          }
                          onClick={() =>
                            calendarEventId &&
                            classify.mutate(
                              {
                                eventId: calendarEventId,
                                classification: value,
                              },
                              {
                                onSuccess: () =>
                                  toast.success(
                                    `Marked as ${CLASSIFICATION_LABELS[value].toLowerCase()}`,
                                  ),
                                onError: (error) =>
                                  toast.error(
                                    error instanceof ApiError
                                      ? error.message
                                      : "Could not update the event.",
                                  ),
                              },
                            )
                          }
                        >
                          {CLASSIFICATION_LABELS[value]}
                        </Button>
                      );
                    })}
                  </div>
                </Field>
                ) : (
                  <ReadOnlyNote />
                )}

                {detail?.interview_stage_id ? (
                  <Alert tone="success" title="Linked to an interview">
                    {detail.company_name} — {detail.stage_badge}
                  </Alert>
                ) : !editable ? null : mode === "none" ? (
                  <div className="flex flex-wrap gap-2 border-t border-border pt-3">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => setMode("link")}
                    >
                      <Link2 />
                      Link existing application
                    </Button>
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() => setMode("create")}
                    >
                      <Plus />
                      Create new application
                    </Button>
                  </div>
                ) : mode === "link" ? (
                  <LinkExistingForm
                    eventId={calendarEventId!}
                    personId={event.person_id}
                    personName={event.person_name}
                    onDone={() => onOpenChange(false)}
                    onCancel={() => setMode("none")}
                  />
                ) : (
                  <CreateApplicationForm
                    eventId={calendarEventId!}
                    suggestedCompany={detail?.company_name ?? null}
                    onDone={() => onOpenChange(false)}
                    onCancel={() => setMode("none")}
                  />
                )}
              </>
            )
          ) : null}
        </div>

        <DialogFooter>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => onOpenChange(false)}
          >
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function LinkExistingForm({
  eventId,
  personId,
  personName,
  onDone,
  onCancel,
}: {
  eventId: string;
  personId: string;
  personName?: string;
  onDone: () => void;
  onCancel: () => void;
}) {
  const { data: types } = useInterviewTypes();
  const link = useLinkEvent();
  const [target, setTarget] = React.useState<LinkTarget | null>(null);
  // "next" creates a new round; "existing" hangs this meeting off the round
  // that was picked — one round can span several sittings (spec §16).
  const [mode, setMode] = React.useState<"next" | "existing">("next");

  // The journey so far, so the round being added has visible context.
  const journey = useApplication(target?.applicationId ?? "", {
    enabled: Boolean(target?.applicationId),
  });

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!target) return;
    const form = new FormData(event.currentTarget);
    const attachToStage = mode === "existing" && target.stage;

    try {
      await link.mutateAsync({
        eventId,
        body: {
          application_id: target.applicationId,
          interview_stage_id: attachToStage ? target.stage!.stage_id : undefined,
          type_key: attachToStage ? undefined : form.get("type_key") || undefined,
          round_number: attachToStage
            ? undefined
            : form.get("round_number")
              ? Number(form.get("round_number"))
              : undefined,
        },
      });
      toast.success(
        attachToStage
          ? `Added to ${target.stage!.stage_badge}`
          : "Event linked to the application",
      );
      onDone();
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Could not link the event.",
      );
    }
  }

  return (
    <form
      onSubmit={submit}
      className="space-y-3 rounded-md border border-border p-3"
    >
      <Field label="Application or interview">
        <LinkTargetPicker
          personId={personId}
          personName={personName}
          value={target}
          onChange={(next) => {
            setTarget(next);
            // Picking an interview usually means "this follows on from that",
            // so default to a new round either way.
            setMode("next");
          }}
          autoFocus
        />
      </Field>

      {target ? (
        <>
          {journey.data ? (
            <div className="rounded-md border border-border bg-surface-muted/40 p-2.5">
              <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-subtle-foreground">
                Where this sits
              </p>
              <JourneyStrip
                appliedDate={journey.data.applied_date}
                stages={journey.data.stages}
                highlightStageId={
                  mode === "existing" ? target.stage?.stage_id : null
                }
              />
            </div>
          ) : null}

          <Field label="This meeting is">
            <div className="space-y-1.5">
              <label className="flex cursor-pointer items-start gap-2 rounded-md border border-border p-2 text-sm hover:bg-surface-hover">
                <input
                  type="radio"
                  name="link-mode"
                  checked={mode === "next"}
                  onChange={() => setMode("next")}
                  className="mt-0.5 accent-[var(--primary)]"
                />
                <span>
                  <span className="text-foreground">
                    the next round (R{target.nextRoundNumber})
                  </span>
                  <span className="block text-xs text-muted-foreground">
                    Adds a new step to this application&apos;s journey.
                  </span>
                </span>
              </label>

              {target.stage ? (
                <label className="flex cursor-pointer items-start gap-2 rounded-md border border-border p-2 text-sm hover:bg-surface-hover">
                  <input
                    type="radio"
                    name="link-mode"
                    checked={mode === "existing"}
                    onChange={() => setMode("existing")}
                    className="mt-0.5 accent-[var(--primary)]"
                  />
                  <span>
                    <span className="text-foreground">
                      part of {target.stage.stage_badge}
                    </span>
                    <span className="block text-xs text-muted-foreground">
                      Another sitting of a round that already exists — a loop
                      split over two days, say.
                    </span>
                  </span>
                </label>
              ) : null}
            </div>
          </Field>

          {mode === "next" ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Interview type" htmlFor="link-type">
                <NativeSelect id="link-type" name="type_key" defaultValue="">
                  <option value="">Detect automatically</option>
                  {(types ?? []).map((type) => (
                    <option key={type.key} value={type.key}>
                      {type.label}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
              <Field label="Round" htmlFor="link-round">
                <Input
                  id="link-round"
                  name="round_number"
                  type="number"
                  min={1}
                  max={20}
                  defaultValue={target.nextRoundNumber}
                />
              </Field>
            </div>
          ) : null}
        </>
      ) : null}

      <div className="flex justify-end gap-2">
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Back
        </Button>
        <Button
          type="submit"
          size="sm"
          variant="primary"
          loading={link.isPending}
          disabled={!target}
        >
          Link event
        </Button>
      </div>
    </form>
  );
}

function CreateApplicationForm({
  eventId,
  suggestedCompany,
  onDone,
  onCancel,
}: {
  eventId: string;
  suggestedCompany: string | null;
  onDone: () => void;
  onCancel: () => void;
}) {
  const { data: types } = useInterviewTypes();
  const create = useCreateApplicationFromEvent();

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await create.mutateAsync({
        eventId,
        body: {
          company_name: String(form.get("company_name") ?? "").trim(),
          job_title: String(form.get("job_title") ?? "").trim(),
          type_key: form.get("type_key") || "other",
          round_number: form.get("round_number")
            ? Number(form.get("round_number"))
            : undefined,
        },
      });
      toast.success("Application created and linked");
      onDone();
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : "Could not create the application.",
      );
    }
  }

  return (
    <form
      onSubmit={submit}
      className="space-y-3 rounded-md border border-border p-3"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Company" htmlFor="create-company">
          <Input
            id="create-company"
            name="company_name"
            required
            defaultValue={suggestedCompany ?? ""}
            placeholder="Amazon"
          />
        </Field>
        <Field label="Job title" htmlFor="create-title">
          <Input
            id="create-title"
            name="job_title"
            required
            placeholder="Senior AI Engineer"
          />
        </Field>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Interview type" htmlFor="create-type">
          <NativeSelect id="create-type" name="type_key" defaultValue="technical">
            {(types ?? []).map((type) => (
              <option key={type.key} value={type.key}>
                {type.label}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field label="Round" htmlFor="create-round" hint="(optional)">
          <Input
            id="create-round"
            name="round_number"
            type="number"
            min={1}
            max={20}
            placeholder="1"
          />
        </Field>
      </div>

      <div className="flex justify-end gap-2">
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Back
        </Button>
        <Button
          type="submit"
          size="sm"
          variant="primary"
          loading={create.isPending}
        >
          Create and link
        </Button>
      </div>
    </form>
  );
}

export function ExternalEventLink({ url }: { url: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
    >
      Open <ExternalLink className="size-3" />
    </a>
  );
}
