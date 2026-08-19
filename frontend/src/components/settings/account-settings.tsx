"use client";

/** Your own account: who you are, what you can edit, and your password. */

import { KeyRound, ShieldCheck, UserCog } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { PersonAvatar } from "@/components/shared/badges";
import {
  Alert,
  Button,
  Card,
  CardBody,
  CardHeader,
  Field,
  Input,
} from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useChangeOwnPassword, usePeople } from "@/lib/queries";

const MIN_PASSWORD_LENGTH = 6;

export function AccountSettings() {
  const { user, isAdmin } = useAuth();
  const { data: people } = usePeople();

  if (!user) return null;

  const assigned = (people ?? []).filter((person) =>
    user.assigned_person_ids.includes(person.id),
  );

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="Your account"
          description="Signed in as this user."
        />
        <CardBody className="space-y-3">
          <div className="flex items-center gap-2">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-surface-muted text-muted-foreground">
              {isAdmin ? (
                <ShieldCheck className="size-4" />
              ) : (
                <UserCog className="size-4" />
              )}
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-foreground">
                {user.display_name}
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {user.username} ·{" "}
                {isAdmin ? "Administrator" : "General user"}
              </p>
            </div>
          </div>

          {isAdmin ? (
            <p className="text-sm text-muted-foreground">
              You can change anything in this workspace.
            </p>
          ) : (
            <div>
              <p className="text-sm text-muted-foreground">
                You can see everything in the workspace.{" "}
                {assigned.length
                  ? "You can make changes to these profiles:"
                  : "You do not have any profiles assigned yet, so your access is view-only. An administrator can assign some."}
              </p>
              {assigned.length ? (
                <div className="mt-2 flex flex-wrap gap-1.5">
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
                </div>
              ) : null}
            </div>
          )}
        </CardBody>
      </Card>

      <ChangePasswordCard
        mustChange={user.must_change_password}
        key={String(user.must_change_password)}
      />
    </div>
  );
}

function ChangePasswordCard({ mustChange }: { mustChange: boolean }) {
  const changePassword = useChangeOwnPassword();
  const [current, setCurrent] = React.useState("");
  const [next, setNext] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  const tooShort = next.length > 0 && next.length < MIN_PASSWORD_LENGTH;
  const mismatch = confirm.length > 0 && confirm !== next;
  const canSubmit =
    current.length > 0 && next.length >= MIN_PASSWORD_LENGTH && confirm === next;

  return (
    <Card>
      <CardHeader
        title="Change your password"
        description="Only you will know the new one."
      />
      <CardBody>
        {mustChange ? (
          <Alert tone="warn" className="mb-3" title="Choose your own password">
            Your password was set by an administrator. Replace it with one only
            you know.
          </Alert>
        ) : null}

        <form
          className="max-w-sm space-y-3"
          onSubmit={async (event) => {
            event.preventDefault();
            setError(null);
            try {
              await changePassword.mutateAsync({
                current_password: current,
                new_password: next,
              });
              toast.success("Password changed");
              setCurrent("");
              setNext("");
              setConfirm("");
            } catch (err) {
              setError(
                err instanceof ApiError
                  ? err.message
                  : "Could not change your password.",
              );
            }
          }}
        >
          <Field label="Current password" htmlFor="current-password">
            <Input
              id="current-password"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
            />
          </Field>

          <Field
            label="New password"
            hint={`at least ${MIN_PASSWORD_LENGTH} characters`}
            htmlFor="next-password"
            error={tooShort ? "That password is too short." : null}
          >
            <Input
              id="next-password"
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(event) => setNext(event.target.value)}
            />
          </Field>

          <Field
            label="Confirm new password"
            htmlFor="confirm-password"
            error={mismatch ? "These two do not match." : null}
          >
            <Input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
            />
          </Field>

          {error ? (
            <Alert tone="danger" title="Could not change your password">
              {error}
            </Alert>
          ) : null}

          <Button type="submit" disabled={!canSubmit || changePassword.isPending}>
            <KeyRound />
            Change password
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}
