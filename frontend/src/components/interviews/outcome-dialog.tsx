"use client";

/**
 * "How did it go?" (spec §49).
 *
 * One tap records the result. If the answer is "still waiting", the suggested
 * follow-up date is offered right there — which is the moment the user
 * actually knows whether they want it (spec §20).
 */

import { Check, Clock, RotateCcw, X, XCircle } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { Dialog, DialogContent, DialogFooter } from "@/components/ui/overlays";
import {
  Button,
  Field,
  Input,
  Textarea,
} from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { addDaysIso, todayIso } from "@/lib/format";
import { useSetOutcome } from "@/lib/queries";
import type { InterviewOutcome } from "@/lib/types";
import { cn } from "@/lib/utils";

const CHOICES: {
  outcome: InterviewOutcome;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  classes: string;
}[] = [
  {
    outcome: "passed",
    label: "Passed",
    icon: Check,
    classes:
      "border-status-success/40 bg-status-success-bg text-status-success hover:border-status-success",
  },
  {
    outcome: "waiting",
    label: "Waiting",
    icon: Clock,
    classes:
      "border-status-warn/40 bg-status-warn-bg text-status-warn hover:border-status-warn",
  },
  {
    outcome: "failed",
    label: "Failed",
    icon: XCircle,
    classes:
      "border-status-danger/40 bg-status-danger-bg text-status-danger hover:border-status-danger",
  },
  {
    outcome: "cancelled",
    label: "Cancelled",
    icon: X,
    classes: "border-border bg-surface-muted text-muted-foreground",
  },
];

export function OutcomeDialog({
  open,
  onOpenChange,
  stageId,
  stageName,
  companyName,
  followUpBusinessDays = 3,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  stageId: string | null;
  stageName?: string;
  companyName?: string;
  followUpBusinessDays?: number;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="How did it go?"
        description={
          companyName
            ? `${companyName}${stageName ? ` — ${stageName}` : ""}`
            : undefined
        }
        size="sm"
      >
        {/*
          The body lives in its own component so closing the dialog unmounts it
          and the next open starts from clean state — no reset-in-an-effect.
        */}
        <OutcomeForm
          stageId={stageId}
          followUpBusinessDays={followUpBusinessDays}
          onDone={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  );
}

function OutcomeForm({
  stageId,
  followUpBusinessDays,
  onDone,
}: {
  stageId: string | null;
  followUpBusinessDays: number;
  onDone: () => void;
}) {
  const setOutcome = useSetOutcome();
  const [choice, setChoice] = React.useState<InterviewOutcome | null>(null);
  const [note, setNote] = React.useState("");
  const [createFollowUp, setCreateFollowUp] = React.useState(true);
  const [followUpDate, setFollowUpDate] = React.useState(() =>
    suggestBusinessDate(followUpBusinessDays),
  );

  async function submit(outcome: InterviewOutcome) {
    if (!stageId) return;
    // Only "waiting" leaves something outstanding to chase.
    const wantsFollowUp = outcome === "waiting" && createFollowUp;
    try {
      await setOutcome.mutateAsync({
        id: stageId,
        body: {
          outcome,
          note: note.trim() || undefined,
          create_follow_up: wantsFollowUp,
          follow_up_due_date: wantsFollowUp ? followUpDate : undefined,
        },
      });
      toast.success(
        wantsFollowUp
          ? "Result saved and follow-up scheduled"
          : "Result saved",
      );
      onDone();
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Could not save the result.",
      );
    }
  }

  const showFollowUp = choice === "waiting";

  return (
    <>
      <div className="space-y-4 p-4">
          <div className="grid grid-cols-2 gap-2">
            {CHOICES.map((option) => {
              const Icon = option.icon;
              const active = choice === option.outcome;
              return (
                <button
                  key={option.outcome}
                  type="button"
                  onClick={() => {
                    // "Waiting" needs a second step for the follow-up date;
                    // everything else can save immediately.
                    if (option.outcome === "waiting") setChoice("waiting");
                    else {
                      setChoice(option.outcome);
                      void submit(option.outcome);
                    }
                  }}
                  className={cn(
                    "flex items-center justify-center gap-2 rounded-md border px-3 py-3 text-sm font-medium transition-colors",
                    option.classes,
                    active && "ring-2 ring-ring",
                  )}
                >
                  <Icon className="size-4" />
                  {option.label}
                </button>
              );
            })}
          </div>

          <button
            type="button"
            onClick={() => {
              setChoice("unknown");
              void submit("unknown");
            }}
            className="flex w-full items-center justify-center gap-2 rounded-md border border-border px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-surface-hover"
          >
            <RotateCcw className="size-3.5" />
            Rescheduled or unknown
          </button>

          {showFollowUp ? (
            <div className="space-y-3 rounded-md border border-border bg-surface-muted/50 p-3">
              <label className="flex items-start gap-2 text-xs text-foreground">
                <input
                  type="checkbox"
                  checked={createFollowUp}
                  onChange={(event) => setCreateFollowUp(event.target.checked)}
                  className="mt-0.5 size-3.5 accent-[var(--primary)]"
                />
                <span>
                  Remind me to chase this result
                  <span className="block text-[11px] text-muted-foreground">
                    Suggested {followUpBusinessDays} business days from today.
                  </span>
                </span>
              </label>
              {createFollowUp ? (
                <Field label="Follow up on" htmlFor="outcome-followup-date">
                  <Input
                    id="outcome-followup-date"
                    type="date"
                    value={followUpDate}
                    min={todayIso()}
                    onChange={(event) => setFollowUpDate(event.target.value)}
                  />
                </Field>
              ) : null}
            </div>
          ) : null}

          <Field label="Note" htmlFor="outcome-note" hint="(optional)">
            <Textarea
              id="outcome-note"
              rows={2}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Two graph problems, went well."
            />
          </Field>
        </div>

      <DialogFooter>
        <Button variant="secondary" size="sm" onClick={onDone}>
          Cancel
        </Button>
        <Button
          variant="primary"
          size="sm"
          disabled={!showFollowUp}
          loading={setOutcome.isPending}
          onClick={() => void submit("waiting")}
        >
          Save
        </Button>
      </DialogFooter>
    </>
  );
}

/** Approximate the backend's business-day suggestion for the default value. */
function suggestBusinessDate(businessDays: number): string {
  let iso = todayIso();
  let remaining = businessDays;
  while (remaining > 0) {
    iso = addDaysIso(iso, 1);
    const weekday = new Date(`${iso}T12:00:00Z`).getUTCDay();
    if (weekday !== 0 && weekday !== 6) remaining -= 1;
  }
  return iso;
}
