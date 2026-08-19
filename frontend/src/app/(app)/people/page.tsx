"use client";

import { Archive, MoreHorizontal, Plus, Users } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { PersonAvatar } from "@/components/shared/badges";
import { PageHeader } from "@/components/shared/page-header";
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
  EmptyState,
  Field,
  Input,
  NativeSelect,
  Skeleton,
} from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  useCreatePerson,
  usePeople,
  usePersonArchive,
  usePersonColors,
  useSettings,
  useUpdatePerson,
} from "@/lib/queries";
import {
  DEFAULT_TIMEZONE,
  timezoneOptions,
  timezoneShort,
} from "@/lib/timezones";
import type { PersonWithStats } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function PeoplePage() {
  const [includeArchived, setIncludeArchived] = React.useState(false);
  const { data: people, isLoading } = usePeople(includeArchived);
  // Profiles are workspace-level: names and colours affect every view, so
  // creating and editing them is an administrator's job even for a user who
  // looks after that person's applications.
  const { isAdmin } = useAuth();
  const archive = usePersonArchive();

  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<PersonWithStats | null>(null);

  return (
    <div>
      <PageHeader
        title="People"
        description="Everyone whose job search this workspace tracks."
        actions={
          <>
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={includeArchived}
                onChange={(event) => setIncludeArchived(event.target.checked)}
                className="size-3.5 accent-[var(--primary)]"
              />
              Show archived
            </label>
            {isAdmin ? (
              <Button
                size="sm"
                variant="primary"
                onClick={() => {
                  setEditing(null);
                  setDialogOpen(true);
                }}
              >
                <Plus />
                Add person
              </Button>
            ) : null}
          </>
        }
      />

      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-40" />
          ))}
        </div>
      ) : (people?.length ?? 0) === 0 ? (
        <Card>
          <EmptyState
            icon={Users}
            title="No people yet"
            description={
              isAdmin
                ? "Add the first person. Applications, interviews and follow-ups all belong to someone."
                : "An administrator needs to add the first person before there is anything to track."
            }
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
                  Add person
                </Button>
              ) : null
            }
          />
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {people?.map((person) => (
            <Card
              key={person.id}
              className={cn(
                "relative overflow-hidden p-4",
                person.archived_at && "opacity-70",
              )}
            >
              <span
                aria-hidden
                className="absolute inset-x-0 top-0 h-1"
                style={{ backgroundColor: person.color }}
              />

              <div className="flex items-start gap-3">
                <PersonAvatar
                  color={person.color}
                  initials={person.initials}
                  size="lg"
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-foreground">
                    {person.display_name}
                    {person.archived_at ? (
                      <span className="ml-1.5 text-[11px] text-subtle-foreground">
                        archived
                      </span>
                    ) : null}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    {person.email ?? person.name}
                  </p>
                  <p className="text-[11px] text-subtle-foreground">
                    {timezoneShort(person.timezone)}
                  </p>
                </div>

                {isAdmin ? (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button size="icon-sm" variant="ghost" aria-label="Actions">
                      <MoreHorizontal />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent>
                    <DropdownMenuItem
                      onSelect={() => {
                        setEditing(person);
                        setDialogOpen(true);
                      }}
                    >
                      Edit
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onSelect={async () => {
                        try {
                          await archive.mutateAsync({
                            id: person.id,
                            restore: Boolean(person.archived_at),
                          });
                          toast.success(
                            person.archived_at
                              ? `${person.display_name} restored`
                              : `${person.display_name} archived`,
                          );
                        } catch (error) {
                          toast.error(
                            error instanceof ApiError
                              ? error.message
                              : "Could not update that person.",
                          );
                        }
                      }}
                    >
                      <Archive />
                      {person.archived_at ? "Restore" : "Archive"}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
                ) : null}
              </div>

              <dl className="mt-3 grid grid-cols-2 gap-2 border-t border-border pt-3 text-xs">
                <Stat label="Applications" value={person.application_count} />
                <Stat label="Active" value={person.active_application_count} />
                <Stat
                  label="Upcoming interviews"
                  value={person.upcoming_interview_count}
                />
                <Stat
                  label="Open follow-ups"
                  value={person.open_follow_up_count}
                />
              </dl>

              <p className="mt-2 text-[11px] text-subtle-foreground">
                {person.calendar_connection_count > 0
                  ? `${person.calendar_connection_count} calendar connected`
                  : "No calendar connected"}
              </p>
            </Card>
          ))}
        </div>
      )}

      <PersonDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        person={editing}
      />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className="tabular text-sm font-medium text-foreground">{value}</dd>
    </div>
  );
}

function PersonDialog({
  open,
  onOpenChange,
  person,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  person: PersonWithStats | null;
}) {
  const { data: colors } = usePersonColors();
  const { data: settings } = useSettings();
  const createPerson = useCreatePerson();
  const updatePerson = useUpdatePerson();
  const editing = Boolean(person);
  // The dialog content is keyed by person below, so this initialises fresh
  // each time it opens rather than being reset in an effect.
  const [color, setColor] = React.useState<string | null>(person?.color ?? null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body: Record<string, unknown> = {
      name: String(form.get("name") ?? "").trim(),
      display_name: form.get("display_name") || undefined,
      initials: form.get("initials") || undefined,
      email: form.get("email") || undefined,
      timezone: form.get("timezone") || undefined,
    };
    if (color) body.color = color;

    try {
      if (editing && person) {
        await updatePerson.mutateAsync({ id: person.id, body });
        toast.success("Person updated");
      } else {
        await createPerson.mutateAsync(body);
        toast.success("Person added");
      }
      onOpenChange(false);
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Could not save the person.",
      );
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        key={person?.id ?? "new"}
        title={editing ? "Edit person" : "Add person"}
        description="Each person gets a colour used consistently across the whole app."
        size="sm"
      >
        <form onSubmit={handleSubmit}>
          <div className="space-y-3 p-4">
            <Field label="Full name" htmlFor="person-name">
              <Input
                id="person-name"
                name="name"
                required
                autoFocus
                defaultValue={person?.name ?? ""}
                placeholder="John Carter"
              />
            </Field>

            <div className="grid gap-3 sm:grid-cols-2">
              <Field
                label="Display name"
                htmlFor="person-display"
                hint="(optional)"
              >
                <Input
                  id="person-display"
                  name="display_name"
                  defaultValue={person?.display_name ?? ""}
                  placeholder="John"
                />
              </Field>
              <Field label="Initials" htmlFor="person-initials" hint="(optional)">
                <Input
                  id="person-initials"
                  name="initials"
                  maxLength={4}
                  defaultValue={person?.initials ?? ""}
                  placeholder="JC"
                />
              </Field>
            </div>

            <Field label="Email" htmlFor="person-email" hint="(optional)">
              <Input
                id="person-email"
                name="email"
                type="email"
                defaultValue={person?.email ?? ""}
              />
            </Field>

            <Field label="Timezone" htmlFor="person-tz">
              <NativeSelect
                id="person-tz"
                name="timezone"
                defaultValue={
                  person?.timezone ?? settings?.default_timezone ?? DEFAULT_TIMEZONE
                }
              >
                {timezoneOptions(person?.timezone).map((zone) => (
                  <option key={zone.value} value={zone.value}>
                    {zone.label}
                  </option>
                ))}
              </NativeSelect>
            </Field>

            <Field
              label="Colour"
              hint="(used on the calendar, cards and charts)"
            >
              <div className="flex flex-wrap gap-1.5">
                {(colors ?? []).map((value) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setColor(value)}
                    aria-label={`Colour ${value}`}
                    aria-pressed={color === value}
                    className={cn(
                      "size-7 rounded-full border-2 transition-transform",
                      color === value
                        ? "scale-110 border-foreground"
                        : "border-transparent hover:scale-105",
                    )}
                    style={{ backgroundColor: value }}
                  />
                ))}
              </div>
              {!editing ? (
                <p className="mt-1.5 text-[11px] text-subtle-foreground">
                  Leave unselected to get the next free colour automatically.
                </p>
              ) : null}
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
              loading={createPerson.isPending || updatePerson.isPending}
            >
              {editing ? "Save changes" : "Add person"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
