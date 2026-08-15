"use client";

/**
 * Create or edit an interview stage (spec §47).
 *
 * A stage can hold several time blocks, which is how a final loop is
 * represented (spec §16) — "Add another slot" appends to the same stage rather
 * than creating a second one.
 */

import { CalendarPlus, Plus, Trash2 } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

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
  INTERVIEW_STATUS_LABELS,
  OUTCOME_LABELS,
} from "@/lib/format";
import {
  useCreateStage,
  useInterviewTypes,
  useUpdateStage,
} from "@/lib/queries";
import {
  INTERVIEW_OUTCOMES,
  INTERVIEW_STATUSES,
  type InterviewStage,
} from "@/lib/types";

interface SlotDraft {
  key: string;
  title: string;
  typeKey: string;
  date: string;
  time: string;
  minutes: number;
  meetingUrl: string;
}

function emptySlot(index: number): SlotDraft {
  return {
    key: `slot-${index}-${Math.random().toString(36).slice(2, 8)}`,
    title: "",
    typeKey: "",
    date: "",
    time: "10:00",
    minutes: 60,
    meetingUrl: "",
  };
}

/** Combine a local date + time into an ISO instant in the browser's zone. */
function toInstant(date: string, time: string): string | null {
  if (!date) return null;
  const value = new Date(`${date}T${time || "09:00"}:00`);
  if (Number.isNaN(value.getTime())) return null;
  return value.toISOString();
}

export function StageDialog({
  open,
  onOpenChange,
  applicationId,
  stage,
  hasCalendarConnection,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  applicationId: string;
  stage?: InterviewStage | null;
  hasCalendarConnection?: boolean;
}) {
  const editing = Boolean(stage);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        // Keyed so switching between "add" and a specific stage remounts the
        // form with the right initial values instead of resetting in an effect.
        key={stage?.id ?? "new"}
        title={editing ? "Edit interview" : "Add interview"}
        description={
          editing
            ? undefined
            : "One stage can hold several time blocks — that is how a final loop is recorded."
        }
        size="lg"
      >
        <StageForm
          applicationId={applicationId}
          stage={stage}
          hasCalendarConnection={hasCalendarConnection}
          onDone={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  );
}

function StageForm({
  applicationId,
  stage,
  hasCalendarConnection,
  onDone,
}: {
  applicationId: string;
  stage?: InterviewStage | null;
  hasCalendarConnection?: boolean;
  onDone: () => void;
}) {
  const { data: types } = useInterviewTypes();
  const createStage = useCreateStage();
  const updateStage = useUpdateStage();
  const editing = Boolean(stage);

  const [typeKey, setTypeKey] = React.useState(stage?.type_key ?? "technical");
  const [name, setName] = React.useState(stage?.name ?? "");
  const [round, setRound] = React.useState(
    stage?.round_number ? String(stage.round_number) : "",
  );
  const [status, setStatus] = React.useState<string>(stage?.status ?? "planned");
  const [outcome, setOutcome] = React.useState<string>(
    stage?.outcome ?? "pending",
  );
  const [notes, setNotes] = React.useState(stage?.notes ?? "");
  const [slots, setSlots] = React.useState<SlotDraft[]>(() =>
    stage ? [] : [emptySlot(0)],
  );
  const [addToCalendar, setAddToCalendar] = React.useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();

    const events = slots
      .map((slot) => {
        const startsAt = toInstant(slot.date, slot.time);
        if (!startsAt) return null;
        const endsAt = new Date(
          new Date(startsAt).getTime() + slot.minutes * 60_000,
        ).toISOString();
        return {
          title: slot.title || undefined,
          type_key: slot.typeKey || undefined,
          starts_at: startsAt,
          ends_at: endsAt,
          meeting_url: slot.meetingUrl || undefined,
          add_to_calendar: addToCalendar,
        };
      })
      .filter(Boolean);

    try {
      if (editing && stage) {
        await updateStage.mutateAsync({
          id: stage.id,
          body: {
            type_key: typeKey,
            name: name || undefined,
            round_number: round ? Number(round) : null,
            status,
            outcome,
            notes: notes || null,
          },
        });
        toast.success("Interview updated");
      } else {
        await createStage.mutateAsync({
          applicationId,
          body: {
            type_key: typeKey,
            name: name || undefined,
            round_number: round ? Number(round) : undefined,
            status: events.length > 0 ? "scheduled" : status,
            outcome,
            notes: notes || undefined,
            events,
          },
        });
        toast.success(
          events.length > 1
            ? `Interview added with ${events.length} slots`
            : "Interview added",
        );
      }
      onDone();
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : "Could not save the interview.",
      );
    }
  }

  return (
    <form onSubmit={handleSubmit}>
          <div className="space-y-4 p-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Interview type" htmlFor="stage-type" className="sm:col-span-2">
                <NativeSelect
                  id="stage-type"
                  value={typeKey}
                  onChange={(event) => setTypeKey(event.target.value)}
                >
                  {(types ?? []).map((type) => (
                    <option key={type.key} value={type.key}>
                      {type.label}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
              <Field label="Round" htmlFor="stage-round" hint="(optional)">
                <Input
                  id="stage-round"
                  type="number"
                  min={1}
                  max={20}
                  value={round}
                  onChange={(event) => setRound(event.target.value)}
                  placeholder="2"
                />
              </Field>
            </div>

            <Field
              label="Name"
              htmlFor="stage-name"
              hint="(defaults from the type and round)"
            >
              <Input
                id="stage-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Technical Interview"
              />
            </Field>

            {editing ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Status" htmlFor="stage-status">
                  <NativeSelect
                    id="stage-status"
                    value={status}
                    onChange={(event) => setStatus(event.target.value)}
                  >
                    {INTERVIEW_STATUSES.map((value) => (
                      <option key={value} value={value}>
                        {INTERVIEW_STATUS_LABELS[value]}
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
                <Field label="Outcome" htmlFor="stage-outcome">
                  <NativeSelect
                    id="stage-outcome"
                    value={outcome}
                    onChange={(event) => setOutcome(event.target.value)}
                  >
                    {INTERVIEW_OUTCOMES.map((value) => (
                      <option key={value} value={value}>
                        {OUTCOME_LABELS[value]}
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
              </div>
            ) : (
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-xs font-medium text-muted-foreground">
                    Time slots
                  </p>
                  <Button
                    type="button"
                    size="xs"
                    variant="ghost"
                    onClick={() =>
                      setSlots((current) => [
                        ...current,
                        emptySlot(current.length),
                      ])
                    }
                  >
                    <Plus />
                    Add another slot
                  </Button>
                </div>

                <div className="space-y-2">
                  {slots.map((slot, index) => (
                    <div
                      key={slot.key}
                      className="rounded-md border border-border p-2.5"
                    >
                      <div className="grid gap-2 sm:grid-cols-4">
                        <Field label="Date">
                          <Input
                            type="date"
                            value={slot.date}
                            onChange={(event) =>
                              setSlots((current) =>
                                current.map((item, i) =>
                                  i === index
                                    ? { ...item, date: event.target.value }
                                    : item,
                                ),
                              )
                            }
                          />
                        </Field>
                        <Field label="Start">
                          <Input
                            type="time"
                            value={slot.time}
                            onChange={(event) =>
                              setSlots((current) =>
                                current.map((item, i) =>
                                  i === index
                                    ? { ...item, time: event.target.value }
                                    : item,
                                ),
                              )
                            }
                          />
                        </Field>
                        <Field label="Minutes">
                          <Input
                            type="number"
                            min={15}
                            step={15}
                            value={slot.minutes}
                            onChange={(event) =>
                              setSlots((current) =>
                                current.map((item, i) =>
                                  i === index
                                    ? {
                                        ...item,
                                        minutes: Number(event.target.value),
                                      }
                                    : item,
                                ),
                              )
                            }
                          />
                        </Field>
                        <Field label="Slot type" hint="(optional)">
                          <NativeSelect
                            value={slot.typeKey}
                            onChange={(event) =>
                              setSlots((current) =>
                                current.map((item, i) =>
                                  i === index
                                    ? { ...item, typeKey: event.target.value }
                                    : item,
                                ),
                              )
                            }
                          >
                            <option value="">Same as stage</option>
                            {(types ?? []).map((type) => (
                              <option key={type.key} value={type.key}>
                                {type.label}
                              </option>
                            ))}
                          </NativeSelect>
                        </Field>
                      </div>

                      <div className="mt-2 flex items-end gap-2">
                        <Field label="Label" className="flex-1">
                          <Input
                            value={slot.title}
                            onChange={(event) =>
                              setSlots((current) =>
                                current.map((item, i) =>
                                  i === index
                                    ? { ...item, title: event.target.value }
                                    : item,
                                ),
                              )
                            }
                            placeholder="System Design"
                          />
                        </Field>
                        <Field label="Meeting link" className="flex-1">
                          <Input
                            value={slot.meetingUrl}
                            onChange={(event) =>
                              setSlots((current) =>
                                current.map((item, i) =>
                                  i === index
                                    ? {
                                        ...item,
                                        meetingUrl: event.target.value,
                                      }
                                    : item,
                                ),
                              )
                            }
                            placeholder="https://…"
                          />
                        </Field>
                        {slots.length > 1 ? (
                          <Button
                            type="button"
                            size="icon-sm"
                            variant="ghost"
                            aria-label="Remove slot"
                            onClick={() =>
                              setSlots((current) =>
                                current.filter((_, i) => i !== index),
                              )
                            }
                          >
                            <Trash2 />
                          </Button>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>

                {hasCalendarConnection ? (
                  <label className="mt-2 flex cursor-pointer items-center gap-2 text-xs text-foreground">
                    <input
                      type="checkbox"
                      checked={addToCalendar}
                      onChange={(event) => setAddToCalendar(event.target.checked)}
                      className="size-3.5 accent-[var(--primary)]"
                    />
                    <CalendarPlus className="size-3.5" />
                    Add to the connected calendar
                  </label>
                ) : (
                  <Alert tone="info" className="mt-2">
                    No calendar is connected for this person, so this interview
                    is stored here only. Connect one in Settings to push it out.
                  </Alert>
                )}
              </div>
            )}

            <Field label="Notes" htmlFor="stage-notes" hint="(optional)">
              <Textarea
                id="stage-notes"
                rows={2}
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
              />
            </Field>
          </div>

          <DialogFooter>
        <Button type="button" variant="secondary" size="sm" onClick={onDone}>
          Cancel
        </Button>
        <Button
          type="submit"
          variant="primary"
          size="sm"
          loading={createStage.isPending || updateStage.isPending}
        >
          {editing ? "Save changes" : "Add interview"}
        </Button>
      </DialogFooter>
    </form>
  );
}
