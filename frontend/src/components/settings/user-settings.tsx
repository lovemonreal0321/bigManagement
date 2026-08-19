"use client";

/**
 * Users and profile assignment (Settings → Users). Administrators only.
 *
 * The model in one line: an administrator can do anything; everyone else reads
 * the whole workspace but writes only to the profiles assigned to them. That
 * sentence is on screen too, because "why can't I edit this?" is otherwise a
 * confusing thing to hit.
 */

import {
  KeyRound,
  Plus,
  ShieldCheck,
  Trash2,
  UserCog,
  Users as UsersIcon,
} from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { PersonAvatar } from "@/components/shared/badges";
import {
  Checkbox,
  Dialog,
  DialogContent,
  DialogFooter,
} from "@/components/ui/overlays";
import {
  Alert,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  Field,
  Input,
  NativeSelect,
  Skeleton,
} from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  useAssignPeople,
  useCreateUser,
  useDeleteUser,
  usePeople,
  useSetUserPassword,
  useUpdateUser,
  useUsers,
} from "@/lib/queries";
import type { AuthUser, PersonWithStats, UserRole } from "@/lib/types";

const MIN_PASSWORD_LENGTH = 6;

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export function UserSettings() {
  const { user: me } = useAuth();
  const { data: users, isLoading } = useUsers();
  const { data: people } = usePeople();
  const [creating, setCreating] = React.useState(false);

  const peopleById = React.useMemo(
    () => new Map((people ?? []).map((person) => [person.id, person])),
    [people],
  );

  return (
    <div className="space-y-4">
      <Alert tone="info" title="How access works">
        Administrators can change anything in the workspace. Everyone else can
        see all of it — the shared calendar, the pipeline, the analytics — but
        can only edit the profiles assigned to them below.
      </Alert>

      <Card>
        <CardHeader
          title="Users"
          description="Who can sign in, and which profiles they look after."
          action={
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus />
              Add user
            </Button>
          }
        />

        {isLoading ? (
          <CardBody className="space-y-2">
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
          </CardBody>
        ) : !users?.length ? (
          <CardBody>
            <EmptyState
              icon={UsersIcon}
              title="No users yet"
              description="Add someone to give them their own sign-in."
            />
          </CardBody>
        ) : (
          <ul className="divide-y divide-border">
            {users.map((user) => (
              <UserRow
                key={user.id}
                user={user}
                isMe={user.id === me?.id}
                people={people ?? []}
                peopleById={peopleById}
              />
            ))}
          </ul>
        )}
      </Card>

      <CreateUserDialog
        open={creating}
        onOpenChange={setCreating}
        people={people ?? []}
      />
    </div>
  );
}

// --------------------------------------------------------------------------
// One user
// --------------------------------------------------------------------------

function UserRow({
  user,
  isMe,
  people,
  peopleById,
}: {
  user: AuthUser;
  isMe: boolean;
  people: PersonWithStats[];
  peopleById: Map<string, PersonWithStats>;
}) {
  const updateUser = useUpdateUser();
  const deleteUser = useDeleteUser();
  const [assigning, setAssigning] = React.useState(false);
  const [resetting, setResetting] = React.useState(false);

  const isAdmin = user.role === "admin";
  const assigned = user.assigned_person_ids
    .map((id) => peopleById.get(id))
    .filter((person): person is PersonWithStats => Boolean(person));

  async function change(body: Parameters<typeof updateUser.mutateAsync>[0]["body"]) {
    try {
      await updateUser.mutateAsync({ id: user.id, body });
      toast.success("User updated");
    } catch (error) {
      toast.error(errorMessage(error, "Could not update that user."));
    }
  }

  return (
    <li className="p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-surface-muted text-muted-foreground">
          {isAdmin ? (
            <ShieldCheck className="size-4" />
          ) : (
            <UserCog className="size-4" />
          )}
        </span>

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground">
            {user.display_name}
            {isMe ? (
              <span className="ml-1.5 text-xs font-normal text-subtle-foreground">
                (you)
              </span>
            ) : null}
          </p>
          <p className="truncate text-xs text-muted-foreground">
            {user.username}
            {user.must_change_password
              ? " · must set a new password at next sign-in"
              : ""}
            {!user.is_active ? " · disabled" : ""}
          </p>
        </div>

        <NativeSelect
          className="w-auto"
          aria-label={`Role for ${user.display_name}`}
          value={user.role}
          onChange={(event) =>
            change({ role: event.target.value as UserRole })
          }
        >
          <option value="user">General user</option>
          <option value="admin">Administrator</option>
        </NativeSelect>

        <Button size="xs" variant="ghost" onClick={() => setResetting(true)}>
          <KeyRound />
          Password
        </Button>
        {/* Disabling yourself, or the last administrator, is refused by the
            server; the button stays visible so the reason is shown. */}
        <Button
          size="xs"
          variant="ghost"
          onClick={() => change({ is_active: !user.is_active })}
        >
          {user.is_active ? "Disable" : "Enable"}
        </Button>
        {!isMe ? (
          <Button
            size="xs"
            variant="ghost"
            onClick={async () => {
              try {
                await deleteUser.mutateAsync(user.id);
                toast.success("User removed");
              } catch (error) {
                toast.error(errorMessage(error, "Could not remove that user."));
              }
            }}
          >
            <Trash2 />
            Remove
          </Button>
        ) : null}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5 pl-10">
        {isAdmin ? (
          <span className="text-xs text-muted-foreground">
            Can edit every profile.
          </span>
        ) : assigned.length ? (
          <>
            {assigned.map((person) => (
              <span
                key={person.id}
                className="inline-flex items-center gap-1 rounded-full border border-border py-0.5 pl-0.5 pr-2 text-xs text-foreground"
              >
                <PersonAvatar
                  color={person.color}
                  initials={person.initials}
                  size="sm"
                />
                {person.display_name}
              </span>
            ))}
          </>
        ) : (
          <span className="text-xs text-muted-foreground">
            View-only — no profiles assigned yet.
          </span>
        )}
        {!isAdmin ? (
          <Button size="xs" variant="ghost" onClick={() => setAssigning(true)}>
            Assign profiles
          </Button>
        ) : null}
      </div>

      <AssignDialog
        open={assigning}
        onOpenChange={setAssigning}
        user={user}
        people={people}
      />
      <ResetPasswordDialog
        open={resetting}
        onOpenChange={setResetting}
        user={user}
      />
    </li>
  );
}

// --------------------------------------------------------------------------
// Dialogs
//
// Each renders nothing while closed, so its state resets on every open rather
// than being cleared by hand.
// --------------------------------------------------------------------------

function CreateUserDialog({
  open,
  onOpenChange,
  people,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  people: PersonWithStats[];
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Add a user">
        {open ? (
          <CreateUserForm people={people} onDone={() => onOpenChange(false)} />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function CreateUserForm({
  people,
  onDone,
}: {
  people: PersonWithStats[];
  onDone: () => void;
}) {
  const createUser = useCreateUser();
  const [username, setUsername] = React.useState("");
  const [displayName, setDisplayName] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [role, setRole] = React.useState<UserRole>("user");
  const [selected, setSelected] = React.useState<string[]>([]);
  const [error, setError] = React.useState<string | null>(null);

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD_LENGTH;
  const canSubmit =
    username.trim().length > 0 && password.length >= MIN_PASSWORD_LENGTH;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await createUser.mutateAsync({
        username: username.trim().toLowerCase(),
        password,
        display_name: displayName.trim() || undefined,
        role,
        person_ids: role === "admin" ? [] : selected,
      });
      toast.success(`${username.trim().toLowerCase()} can now sign in`);
      onDone();
    } catch (err) {
      setError(errorMessage(err, "Could not create that user."));
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label="Username" htmlFor="new-username">
        <Input
          id="new-username"
          value={username}
          autoComplete="off"
          placeholder="casey"
          onChange={(event) => setUsername(event.target.value)}
        />
      </Field>

      <Field label="Display name" hint="optional" htmlFor="new-display-name">
        <Input
          id="new-display-name"
          value={displayName}
          placeholder="Casey Rivera"
          onChange={(event) => setDisplayName(event.target.value)}
        />
      </Field>

      <Field
        label="Temporary password"
        hint={`at least ${MIN_PASSWORD_LENGTH} characters`}
        htmlFor="new-password"
        error={tooShort ? "That password is too short." : null}
      >
        <Input
          id="new-password"
          type="password"
          value={password}
          autoComplete="new-password"
          onChange={(event) => setPassword(event.target.value)}
        />
      </Field>
      <p className="-mt-1 text-xs text-muted-foreground">
        They will be asked to choose their own password after signing in.
      </p>

      <Field label="Role" htmlFor="new-role">
        <NativeSelect
          id="new-role"
          value={role}
          onChange={(event) => setRole(event.target.value as UserRole)}
        >
          <option value="user">General user — edits assigned profiles only</option>
          <option value="admin">Administrator — full access</option>
        </NativeSelect>
      </Field>

      {role === "user" ? (
        <Field label="Profiles they can edit" hint="pick any number">
          <PersonPicker
            people={people}
            selected={selected}
            onChange={setSelected}
          />
        </Field>
      ) : null}

      {error ? (
        <Alert tone="danger" title="Could not add the user">
          {error}
        </Alert>
      ) : null}

      <DialogFooter>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={!canSubmit || createUser.isPending}>
          Add user
        </Button>
      </DialogFooter>
    </form>
  );
}

function AssignDialog({
  open,
  onOpenChange,
  user,
  people,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  user: AuthUser;
  people: PersonWithStats[];
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={`Profiles ${user.display_name} can edit`}>
        {open ? (
          <AssignForm
            user={user}
            people={people}
            onDone={() => onOpenChange(false)}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function AssignForm({
  user,
  people,
  onDone,
}: {
  user: AuthUser;
  people: PersonWithStats[];
  onDone: () => void;
}) {
  const assign = useAssignPeople();
  const [selected, setSelected] = React.useState<string[]>(
    user.assigned_person_ids,
  );
  const [error, setError] = React.useState<string | null>(null);

  return (
    <form
      className="space-y-3"
      onSubmit={async (event) => {
        event.preventDefault();
        setError(null);
        try {
          await assign.mutateAsync({ id: user.id, personIds: selected });
          toast.success("Assignments saved");
          onDone();
        } catch (err) {
          setError(errorMessage(err, "Could not save those assignments."));
        }
      }}
    >
      <p className="text-sm text-muted-foreground">
        {user.display_name} can already see everyone. Ticking a profile lets
        them add and change that person&apos;s applications, interviews and
        follow-ups.
      </p>

      <PersonPicker people={people} selected={selected} onChange={setSelected} />

      {error ? (
        <Alert tone="danger" title="Could not save">
          {error}
        </Alert>
      ) : null}

      <DialogFooter>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={assign.isPending}>
          Save
        </Button>
      </DialogFooter>
    </form>
  );
}

function ResetPasswordDialog({
  open,
  onOpenChange,
  user,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  user: AuthUser;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={`Set a password for ${user.display_name}`}>
        {open ? (
          <ResetPasswordForm user={user} onDone={() => onOpenChange(false)} />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function ResetPasswordForm({
  user,
  onDone,
}: {
  user: AuthUser;
  onDone: () => void;
}) {
  const setPassword = useSetUserPassword();
  const [value, setValue] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const tooShort = value.length > 0 && value.length < MIN_PASSWORD_LENGTH;

  return (
    <form
      className="space-y-3"
      onSubmit={async (event) => {
        event.preventDefault();
        setError(null);
        try {
          await setPassword.mutateAsync({ id: user.id, password: value });
          toast.success(`Password set for ${user.username}`);
          onDone();
        } catch (err) {
          setError(errorMessage(err, "Could not set that password."));
        }
      }}
    >
      <Field
        label="New password"
        hint={`at least ${MIN_PASSWORD_LENGTH} characters`}
        htmlFor="reset-password"
        error={tooShort ? "That password is too short." : null}
      >
        <Input
          id="reset-password"
          type="password"
          value={value}
          autoComplete="new-password"
          onChange={(event) => setValue(event.target.value)}
        />
      </Field>
      <p className="-mt-1 text-xs text-muted-foreground">
        They will be asked to choose their own the next time they sign in.
      </p>

      {error ? (
        <Alert tone="danger" title="Could not set the password">
          {error}
        </Alert>
      ) : null}

      <DialogFooter>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button
          type="submit"
          disabled={value.length < MIN_PASSWORD_LENGTH || setPassword.isPending}
        >
          Set password
        </Button>
      </DialogFooter>
    </form>
  );
}

// --------------------------------------------------------------------------

function PersonPicker({
  people,
  selected,
  onChange,
}: {
  people: PersonWithStats[];
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  if (!people.length) {
    return (
      <p className="text-sm text-muted-foreground">
        There are no profiles yet. Add one on the People page first.
      </p>
    );
  }

  return (
    <div className="max-h-56 space-y-1 overflow-y-auto rounded-md border border-border p-1.5">
      {people.map((person) => {
        const checked = selected.includes(person.id);
        return (
          <label
            key={person.id}
            className="flex cursor-pointer items-center gap-2 rounded p-1.5 hover:bg-surface-muted"
          >
            <Checkbox
              checked={checked}
              onCheckedChange={(next) =>
                onChange(
                  next === true
                    ? [...selected, person.id]
                    : selected.filter((id) => id !== person.id),
                )
              }
            />
            <PersonAvatar
              color={person.color}
              initials={person.initials}
              size="sm"
            />
            <span className="text-sm text-foreground">
              {person.display_name}
            </span>
          </label>
        );
      })}
    </div>
  );
}
