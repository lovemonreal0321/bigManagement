"use client";

import {
  ArrowLeft,
  Archive,
  Bell,
  ExternalLink,
  MoreHorizontal,
  Plus,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { FollowUpDialog } from "@/components/followups/follow-up-dialog";
import { JourneyTimeline } from "@/components/interviews/journey-timeline";
import { OutcomeDialog } from "@/components/interviews/outcome-dialog";
import { StageDialog } from "@/components/interviews/stage-dialog";
import {
  FollowUpBadge,
  PersonChip,
  PriorityBadge,
  StatusBadge,
} from "@/components/shared/badges";
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
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  NativeSelect,
  Skeleton,
  Textarea,
} from "@/components/ui/primitives";
import { ReadOnlyNote } from "@/components/shared/read-only";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  APPLICATION_STATUS_LABELS,
  EMPLOYMENT_TYPE_LABELS,
  formatCountdown,
  formatDateOnly,
  formatSalary,
  WORK_MODE_LABELS,
} from "@/lib/format";
import {
  useAddNote,
  useApplication,
  useArchiveApplication,
  useCalendarConnections,
  useChangeApplicationStatus,
  useDeleteStage,
  useFollowUpAction,
  useFollowUpBoard,
  useSettings,
} from "@/lib/queries";
import { APPLICATION_STATUSES, type InterviewStage } from "@/lib/types";

export default function ApplicationDetailPage() {
  const params = useParams<{ id: string }>();
  const applicationId = params.id;

  const { data: application, isLoading, isError, error, refetch } =
    useApplication(applicationId);
  const { data: settings } = useSettings();
  const { data: connections } = useCalendarConnections();

  // A user who does not look after this person sees the whole record but
  // gets no edit controls, matching what the server would allow.
  const { canEdit: canEditPerson } = useAuth();
  const canEdit = canEditPerson(application?.person_id);

  const changeStatus = useChangeApplicationStatus();
  const archive = useArchiveApplication();
  const addNote = useAddNote();
  const deleteStage = useDeleteStage();
  const followUpAction = useFollowUpAction();

  const [stageDialogOpen, setStageDialogOpen] = React.useState(false);
  const [editingStage, setEditingStage] = React.useState<InterviewStage | null>(
    null,
  );
  const [outcomeStage, setOutcomeStage] = React.useState<InterviewStage | null>(
    null,
  );
  const [followUpOpen, setFollowUpOpen] = React.useState(false);
  const [noteBody, setNoteBody] = React.useState("");

  // Follow-ups for this application only.
  const board = useFollowUpBoard(
    application ? [application.person_id] : undefined,
  );
  const applicationFollowUps = React.useMemo(() => {
    if (!board.data || !application) return [];
    return [
      ...board.data.overdue,
      ...board.data.due_today,
      ...board.data.upcoming,
      ...board.data.snoozed,
    ].filter((item) => item.application_id === application.id);
  }, [board.data, application]);

  const hasConnection = React.useMemo(
    () =>
      Boolean(
        application &&
          connections?.some(
            (connection) =>
              connection.person_id === application.person_id &&
              connection.status === "connected",
          ),
      ),
    [connections, application],
  );

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-32" />
        <Skeleton className="h-96" />
      </div>
    );
  }

  if (isError || !application) {
    return (
      <Card>
        <ErrorState
          title="Application not found"
          message={
            error instanceof ApiError
              ? error.message
              : "That application could not be loaded."
          }
          onRetry={() => refetch()}
        />
        <div className="pb-6 text-center">
          <Button asChild size="sm" variant="secondary">
            <Link href="/applications">Back to applications</Link>
          </Button>
        </div>
      </Card>
    );
  }

  const salary = formatSalary(
    application.salary_min,
    application.salary_max,
    application.salary_currency,
  );

  async function handleAddNote(event: React.FormEvent) {
    event.preventDefault();
    // `application` is guaranteed non-null below the loading/error guards, but
    // the closure is defined before TypeScript can see that.
    if (!noteBody.trim() || !application) return;
    try {
      await addNote.mutateAsync({ id: application.id, body: noteBody });
      setNoteBody("");
      toast.success("Note added");
    } catch (err) {
      toast.error(
        err instanceof ApiError ? err.message : "Could not add the note.",
      );
    }
  }

  return (
    <div className="space-y-4">
      <Button asChild size="xs" variant="ghost" className="-ml-2">
        <Link href="/applications">
          <ArrowLeft />
          Applications
        </Link>
      </Button>

      {/* Header (spec §17) */}
      <Card>
        <CardBody>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-lg font-semibold tracking-tight text-foreground">
                  {application.company_name}
                </h1>
                <StatusBadge status={application.status} />
                <PriorityBadge priority={application.priority} />
              </div>
              <p className="mt-0.5 text-sm text-muted-foreground">
                {application.job_title}
              </p>

              <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
                {application.person ? (
                  <PersonChip
                    name={application.person.display_name}
                    color={application.person.color}
                    initials={application.person.initials}
                  />
                ) : null}
                {application.applied_date ? (
                  <span>
                    Applied {formatDateOnly(application.applied_date)}
                  </span>
                ) : null}
                {application.location ? <span>{application.location}</span> : null}
                <span>{WORK_MODE_LABELS[application.work_mode]}</span>
                <span>
                  {EMPLOYMENT_TYPE_LABELS[application.employment_type]}
                </span>
                {salary ? (
                  <span className="font-medium text-foreground">{salary}</span>
                ) : null}
                {application.source ? (
                  <span>via {application.source}</span>
                ) : null}
                {application.job_url ? (
                  <a
                    href={application.job_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-primary hover:underline"
                  >
                    Job posting
                    <ExternalLink className="size-3" />
                  </a>
                ) : null}
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-2">
              <NativeSelect
                value={application.status}
                aria-label="Application status"
                className="h-8 w-44 text-xs"
                disabled={!canEdit}
                onChange={async (event) => {
                  try {
                    await changeStatus.mutateAsync({
                      id: application.id,
                      status: event.target.value,
                    });
                    toast.success("Status updated");
                  } catch (err) {
                    toast.error(
                      err instanceof ApiError
                        ? err.message
                        : "Could not update the status.",
                    );
                  }
                }}
              >
                {APPLICATION_STATUSES.map((status) => (
                  <option key={status} value={status}>
                    {APPLICATION_STATUS_LABELS[status]}
                  </option>
                ))}
              </NativeSelect>

              {canEdit ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button size="icon-sm" variant="secondary" aria-label="More">
                    <MoreHorizontal />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                  <DropdownMenuItem onSelect={() => setFollowUpOpen(true)}>
                    <Bell />
                    Add follow-up
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onSelect={async () => {
                      await archive.mutateAsync({
                        id: application.id,
                        restore: Boolean(application.archived_at),
                      });
                      toast.success(
                        application.archived_at
                          ? "Application restored"
                          : "Application archived",
                      );
                    }}
                  >
                    <Archive />
                    {application.archived_at ? "Restore" : "Archive"}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              ) : (
                <ReadOnlyNote />
              )}
            </div>
          </div>
        </CardBody>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Journey */}
        <Card className="lg:col-span-2">
          <CardHeader
            title="Interview journey"
            description="Every step from application to outcome."
            action={
              canEdit ? (
                <Button
                  size="xs"
                  variant="primary"
                  onClick={() => {
                    setEditingStage(null);
                    setStageDialogOpen(true);
                  }}
                >
                  <Plus />
                  Add interview
                </Button>
              ) : null
            }
          />
          <CardBody>
            {application.stages.length === 0 ? (
              <EmptyState
                title="No interviews recorded yet"
                description="Add the first round — a recruiter screen, a technical, whatever happened."
                action={
                  canEdit ? (
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() => {
                        setEditingStage(null);
                        setStageDialogOpen(true);
                      }}
                    >
                      Add interview
                    </Button>
                  ) : null
                }
              />
            ) : (
              <JourneyTimeline
                appliedDate={application.applied_date}
                stages={application.stages}
                tz={settings?.default_timezone}
                onEdit={
                  canEdit
                    ? (stage) => {
                        setEditingStage(stage);
                        setStageDialogOpen(true);
                      }
                    : undefined
                }
                onRecordOutcome={canEdit ? setOutcomeStage : undefined}
                onDelete={!canEdit ? undefined : async (stage) => {
                  try {
                    await deleteStage.mutateAsync(stage.id);
                    toast.success("Interview removed");
                  } catch (err) {
                    toast.error(
                      err instanceof ApiError
                        ? err.message
                        : "Could not remove the interview.",
                    );
                  }
                }}
              />
            )}
          </CardBody>
        </Card>

        <div className="space-y-4">
          {/* Follow-ups */}
          <Card>
            <CardHeader
              title="Follow-ups"
              action={
                canEdit ? (
                  <Button
                    size="xs"
                    variant="ghost"
                    onClick={() => setFollowUpOpen(true)}
                  >
                    <Plus />
                    Add
                  </Button>
                ) : null
              }
            />
            {applicationFollowUps.length === 0 ? (
              <EmptyState
                title="No active follow-up"
                description="Record one when you are waiting on an answer."
              />
            ) : (
              <ul className="divide-y divide-border">
                {applicationFollowUps.map((followUp) => (
                  <li key={followUp.id} className="px-4 py-2.5">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm text-foreground">
                          {followUp.title}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {followUp.due_description}
                        </p>
                      </div>
                      <FollowUpBadge status={followUp.computed_status} />
                    </div>
                    {canEdit ? (
                    <div className="mt-1.5 flex gap-1">
                      <Button
                        size="xs"
                        variant="ghost"
                        onClick={() =>
                          followUpAction.mutate({
                            id: followUp.id,
                            action: "complete",
                          })
                        }
                      >
                        Complete
                      </Button>
                      <Button
                        size="xs"
                        variant="ghost"
                        onClick={() =>
                          followUpAction.mutate({
                            id: followUp.id,
                            action: "snooze",
                            body: { days: 3 },
                          })
                        }
                      >
                        Snooze 3d
                      </Button>
                    </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {/* Notes */}
          <Card>
            <CardHeader title="Notes" />
            <CardBody className="space-y-3">
              {application.notes ? (
                <p className="whitespace-pre-wrap rounded-md border border-border bg-surface-muted/40 p-2.5 text-xs text-foreground">
                  {application.notes}
                </p>
              ) : null}

              {canEdit ? (
              <form onSubmit={handleAddNote} className="space-y-2">
                <Textarea
                  rows={2}
                  value={noteBody}
                  onChange={(event) => setNoteBody(event.target.value)}
                  placeholder="Add a note…"
                />
                <Button
                  type="submit"
                  size="xs"
                  variant="secondary"
                  loading={addNote.isPending}
                  disabled={!noteBody.trim()}
                >
                  Add note
                </Button>
              </form>
              ) : null}

              {application.notes_log.length > 0 ? (
                <ul className="space-y-2 border-t border-border pt-2">
                  {application.notes_log.map((note) => (
                    <li key={note.id}>
                      <p className="whitespace-pre-wrap text-xs text-foreground">
                        {note.body}
                      </p>
                      <p className="mt-0.5 text-[11px] text-subtle-foreground">
                        {formatCountdown(note.created_at)}
                      </p>
                    </li>
                  ))}
                </ul>
              ) : null}
            </CardBody>
          </Card>
        </div>
      </div>

      <StageDialog
        open={stageDialogOpen}
        onOpenChange={setStageDialogOpen}
        applicationId={application.id}
        stage={editingStage}
        hasCalendarConnection={hasConnection}
      />

      <OutcomeDialog
        open={outcomeStage !== null}
        onOpenChange={(open) => !open && setOutcomeStage(null)}
        stageId={outcomeStage?.id ?? null}
        stageName={outcomeStage?.name}
        companyName={application.company_name}
        followUpBusinessDays={
          settings?.followup_after_interview_business_days ?? 3
        }
      />

      <FollowUpDialog
        open={followUpOpen}
        onOpenChange={setFollowUpOpen}
        applicationId={application.id}
        stages={application.stages}
      />
    </div>
  );
}
