"use client";

import * as React from "react";
import { toast } from "sonner";

import { Dialog, DialogContent, DialogFooter } from "@/components/ui/overlays";
import {
  Button,
  Field,
  Input,
  NativeSelect,
  Textarea,
} from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { addDaysIso, PRIORITY_LABELS, todayIso } from "@/lib/format";
import { useCreateFollowUp, useUpdateFollowUp } from "@/lib/queries";
import { PRIORITIES, type FollowUp, type InterviewStage } from "@/lib/types";

export function FollowUpDialog({
  open,
  onOpenChange,
  applicationId,
  stages = [],
  followUp,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  applicationId?: string;
  stages?: InterviewStage[];
  followUp?: FollowUp | null;
}) {
  const create = useCreateFollowUp();
  const update = useUpdateFollowUp();
  const editing = Boolean(followUp);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body = {
      title: String(form.get("title") ?? "").trim(),
      reason: form.get("reason") || undefined,
      due_date: form.get("due_date"),
      priority: form.get("priority") || "medium",
      interview_stage_id: form.get("interview_stage_id") || null,
      notes: form.get("notes") || undefined,
    };

    try {
      if (editing && followUp) {
        await update.mutateAsync({ id: followUp.id, body });
        toast.success("Follow-up updated");
      } else {
        await create.mutateAsync({ ...body, application_id: applicationId });
        toast.success("Follow-up created");
      }
      onOpenChange(false);
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : "Could not save the follow-up.",
      );
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={editing ? "Edit follow-up" : "New follow-up"}
        size="sm"
      >
        <form onSubmit={handleSubmit}>
          <div className="space-y-3 p-4">
            <Field label="What needs doing?" htmlFor="fu-title">
              <Input
                id="fu-title"
                name="title"
                required
                autoFocus
                defaultValue={followUp?.title ?? ""}
                placeholder="Chase the interview result"
              />
            </Field>

            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Due date" htmlFor="fu-date">
                <Input
                  id="fu-date"
                  name="due_date"
                  type="date"
                  required
                  defaultValue={followUp?.due_date ?? addDaysIso(todayIso(), 3)}
                  min={editing ? undefined : undefined}
                />
              </Field>
              <Field label="Priority" htmlFor="fu-priority">
                <NativeSelect
                  id="fu-priority"
                  name="priority"
                  defaultValue={followUp?.priority ?? "medium"}
                >
                  {PRIORITIES.map((priority) => (
                    <option key={priority} value={priority}>
                      {PRIORITY_LABELS[priority]}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
            </div>

            {stages.length > 0 ? (
              <Field
                label="Related interview"
                htmlFor="fu-stage"
                hint="(optional)"
              >
                <NativeSelect
                  id="fu-stage"
                  name="interview_stage_id"
                  defaultValue={followUp?.interview_stage_id ?? ""}
                >
                  <option value="">None</option>
                  {stages.map((stage) => (
                    <option key={stage.id} value={stage.id}>
                      {stage.name}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
            ) : null}

            <Field label="Why" htmlFor="fu-reason" hint="(optional)">
              <Textarea
                id="fu-reason"
                name="reason"
                rows={2}
                defaultValue={followUp?.reason ?? ""}
                placeholder="Recruiter said they would reply this week."
              />
            </Field>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              loading={create.isPending || update.isPending}
            >
              {editing ? "Save" : "Create follow-up"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
