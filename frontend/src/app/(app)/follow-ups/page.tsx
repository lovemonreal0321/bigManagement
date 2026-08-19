"use client";

import { CheckCircle2, Clock, MoreHorizontal, Plus } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";

import { FollowUpDialog } from "@/components/followups/follow-up-dialog";
import {
  FollowUpBadge,
  PersonAvatar,
  PriorityBadge,
  StageBadge,
} from "@/components/shared/badges";
import { PageHeader } from "@/components/shared/page-header";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/overlays";
import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Skeleton,
} from "@/components/ui/primitives";
import { ReadOnlyNote } from "@/components/shared/read-only";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateOnly } from "@/lib/format";
import { usePersonFilter } from "@/lib/person-filter";
import {
  useDeleteFollowUp,
  useFollowUpAction,
  useFollowUpBoard,
} from "@/lib/queries";
import type { FollowUp } from "@/lib/types";
import { cn } from "@/lib/utils";

const SECTIONS = [
  {
    key: "overdue",
    title: "Overdue",
    tone: "border-l-status-danger",
    empty: "Nothing is overdue.",
  },
  {
    key: "due_today",
    title: "Due today",
    tone: "border-l-status-warn",
    empty: "Nothing is due today.",
  },
  {
    key: "upcoming",
    title: "Upcoming",
    tone: "border-l-status-info",
    empty: "Nothing scheduled.",
  },
  {
    key: "snoozed",
    title: "Snoozed",
    tone: "border-l-border-strong",
    empty: "Nothing snoozed.",
  },
  {
    key: "completed",
    title: "Recently completed",
    tone: "border-l-status-success",
    empty: "Nothing completed yet.",
  },
] as const;

export default function FollowUpsPage() {
  const { queryIds } = usePersonFilter();
  const board = useFollowUpBoard(queryIds);
  const { canEdit } = useAuth();
  const action = useFollowUpAction();
  const remove = useDeleteFollowUp();

  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<FollowUp | null>(null);

  async function run(
    followUp: FollowUp,
    kind: "complete" | "snooze" | "cancel",
    body?: Record<string, unknown>,
  ) {
    try {
      await action.mutateAsync({ id: followUp.id, action: kind, body });
      toast.success(
        kind === "complete"
          ? "Follow-up completed"
          : kind === "snooze"
            ? "Snoozed"
            : "Cancelled",
      );
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : "Could not update the follow-up.",
      );
    }
  }

  const counts = board.data?.counts ?? {};
  const actionable = (counts.overdue ?? 0) + (counts.due_today ?? 0);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Follow-Ups"
        description={
          actionable > 0
            ? `${actionable} need${actionable === 1 ? "s" : ""} attention now`
            : "Nothing needs attention right now"
        }
        actions={
          <Button
            size="sm"
            variant="primary"
            onClick={() => {
              setEditing(null);
              setDialogOpen(true);
            }}
            disabled
            title="Open an application to add a follow-up to it"
          >
            <Plus />
            New follow-up
          </Button>
        }
      />

      {board.isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-40" />
          ))}
        </div>
      ) : board.isError ? (
        <Card>
          <ErrorState
            message={
              board.error instanceof ApiError ? board.error.message : undefined
            }
            onRetry={() => board.refetch()}
          />
        </Card>
      ) : (
        SECTIONS.map((section) => {
          const items = (board.data?.[section.key] ?? []) as FollowUp[];
          // Only the empty "overdue"/"due today" sections are worth showing,
          // as reassurance. The rest just add noise when empty.
          if (
            items.length === 0 &&
            !["overdue", "due_today"].includes(section.key)
          ) {
            return null;
          }

          return (
            <Card key={section.key}>
              <CardHeader
                title={section.title}
                action={
                  <span className="tabular rounded bg-surface-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                    {items.length}
                  </span>
                }
              />
              {items.length === 0 ? (
                <EmptyState icon={CheckCircle2} title={section.empty} />
              ) : (
                <ul className="divide-y divide-border">
                  {items.map((followUp) => (
                    <li
                      key={followUp.id}
                      className={cn("border-l-2 px-4 py-3", section.tone)}
                    >
                      <div className="flex flex-wrap items-start gap-3">
                        <PersonAvatar
                          color={followUp.person_color}
                          initials={followUp.person_initials}
                          title={followUp.person_name}
                          size="lg"
                        />

                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="truncate text-sm font-medium text-foreground">
                              {followUp.company_name}
                            </span>
                            {followUp.stage_badge ? (
                              <StageBadge badge={followUp.stage_badge} />
                            ) : null}
                            <FollowUpBadge status={followUp.computed_status} />
                            <PriorityBadge priority={followUp.priority} />
                            {followUp.auto_generated ? (
                              <span className="text-[10px] text-subtle-foreground">
                                auto
                              </span>
                            ) : null}
                          </div>

                          <p className="mt-0.5 text-sm text-foreground">
                            {followUp.title}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {followUp.job_title}
                            {followUp.reason ? ` · ${followUp.reason}` : ""}
                          </p>
                          <p className="mt-0.5 flex items-center gap-1 text-[11px] text-subtle-foreground">
                            <Clock className="size-3" />
                            {followUp.due_description} ·{" "}
                            {formatDateOnly(followUp.due_date)}
                          </p>
                        </div>

                        <div className="flex shrink-0 flex-wrap items-center gap-1">
                          {!canEdit(followUp.person_id) ? (
                            <ReadOnlyNote />
                          ) : (
                          <>
                          {followUp.computed_status !== "completed" ? (
                            <>
                              <Button
                                size="xs"
                                variant="secondary"
                                onClick={() => run(followUp, "complete")}
                              >
                                Complete
                              </Button>
                              <Button
                                size="xs"
                                variant="ghost"
                                onClick={() =>
                                  run(followUp, "snooze", { days: 1 })
                                }
                              >
                                Tomorrow
                              </Button>
                            </>
                          ) : null}

                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button
                                size="icon-sm"
                                variant="ghost"
                                aria-label="More actions"
                              >
                                <MoreHorizontal />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent>
                              <DropdownMenuItem asChild>
                                <Link
                                  href={`/applications/${followUp.application_id}`}
                                >
                                  Open application
                                </Link>
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onSelect={() => {
                                  setEditing(followUp);
                                  setDialogOpen(true);
                                }}
                              >
                                Edit
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onSelect={() =>
                                  run(followUp, "snooze", { days: 7 })
                                }
                              >
                                Snooze a week
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem
                                onSelect={() => run(followUp, "cancel")}
                              >
                                Cancel
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                destructive
                                onSelect={() => remove.mutate(followUp.id)}
                              >
                                Delete
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                          </>
                          )}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          );
        })
      )}

      <FollowUpDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        followUp={editing}
        applicationId={editing?.application_id}
      />
    </div>
  );
}
