"use client";

/**
 * Mailboxes + AI status (Settings → Email & AI).
 *
 * Gmail connects over OAuth (reusing the Google client already set up for
 * Calendar). Everything else — Yahoo especially — goes over IMAP with an
 * app-specific password, because Yahoo no longer grants OAuth to third-party
 * apps. The form explains that rather than leaving the user to discover it.
 */

import {
  AlertTriangle,
  CheckCircle2,
  Info,
  Mail,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
} from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { PersonAvatar } from "@/components/shared/badges";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/overlays";
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
import { formatCountdown } from "@/lib/format";
import {
  useAiModels,
  useAiStatus,
  useConnectImap,
  useDeleteEmailAccount,
  useEmailAccounts,
  useEmailProviders,
  useImapSuggestion,
  usePeople,
  useStartEmailOAuth,
  useVerifyEmailAccount,
} from "@/lib/queries";

export function EmailSettings() {
  const { data: providers } = useEmailProviders();
  const { data: accounts, isLoading } = useEmailAccounts();
  const { data: people } = usePeople();
  const { data: aiStatus } = useAiStatus();
  // Only asked for on demand: it is a live round-trip to the provider.
  const [checkModels, setCheckModels] = React.useState(false);
  const aiModels = useAiModels(checkModels);

  const startOAuth = useStartEmailOAuth();
  const verify = useVerifyEmailAccount();
  const remove = useDeleteEmailAccount();

  const [imapOpen, setImapOpen] = React.useState(false);
  const gmailProvider = providers?.find((p) => p.key === "gmail");
  const outlookProvider = providers?.find((p) => p.key === "microsoft");
  const imapProvider = providers?.find((p) => p.key === "imap");

  async function connect(provider: "gmail" | "microsoft", personId: string) {
    try {
      const result = await startOAuth.mutateAsync({ provider, personId });
      window.location.assign(result.authorization_url);
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : "Could not start the sign-in.",
      );
    }
  }

  return (
    <div className="space-y-4">
      {/* How it works — this is unusual enough to be worth stating. */}
      <Card>
        <CardHeader
          title="How AI enrichment works"
          description="The calendar is the trigger; email fills in the detail."
        />
        <CardBody>
          <ol className="space-y-1.5 text-xs text-muted-foreground">
            <li>
              <span className="font-medium text-foreground">1.</span> An
              interview-shaped event appears on a connected calendar.
            </li>
            <li>
              <span className="font-medium text-foreground">2.</span> The app
              finds the emails tied to <em>that event</em> — the people on the
              invite, around that date. Your mailbox is never scanned generally.
            </li>
            <li>
              <span className="font-medium text-foreground">3.</span> Kimi reads
              them and works out the company, role and which round it is.
            </li>
            <li>
              <span className="font-medium text-foreground">4.</span> Confident
              results fill in the application automatically; anything less
              certain waits for you. Everything can be undone.
            </li>
          </ol>
        </CardBody>
      </Card>

      {/* AI status */}
      <Card>
        <CardHeader
          title="AI model"
          action={
            aiStatus?.configured ? (
              <span className="flex items-center gap-1 text-xs text-status-success">
                <CheckCircle2 className="size-3.5" />
                Ready
              </span>
            ) : (
              <span className="flex items-center gap-1 text-xs text-status-warn">
                <AlertTriangle className="size-3.5" />
                Not configured
              </span>
            )
          }
        />
        <CardBody className="space-y-2">
          <dl className="grid gap-2 text-xs sm:grid-cols-3">
            <div>
              <dt className="text-muted-foreground">Model</dt>
              <dd className="font-medium text-foreground">
                {aiStatus?.model ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Endpoint</dt>
              <dd className="truncate font-medium text-foreground">
                {aiStatus?.base_url ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Auto-create above</dt>
              <dd className="font-medium text-foreground">
                {aiStatus
                  ? `${Math.round(aiStatus.auto_create_confidence * 100)}% confidence`
                  : "—"}
              </dd>
            </div>
          </dl>

          {aiStatus?.setup_hint ? (
            <Alert tone="info" title="Setup needed">
              {aiStatus.setup_hint}
            </Alert>
          ) : null}

          {/* Providers retire model names without notice, which otherwise
              surfaces only as an opaque "model not found" mid-enrichment. */}
          {aiStatus?.configured ? (
            <div className="rounded-md border border-border p-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-muted-foreground">
                  Model names change over time. Check what this key can use.
                </p>
                <Button
                  size="xs"
                  variant="secondary"
                  loading={aiModels.isFetching}
                  onClick={() => setCheckModels(true)}
                >
                  <RefreshCw />
                  Check models
                </Button>
              </div>

              {aiModels.isError ? (
                <Alert tone="danger" className="mt-2" title="Could not ask the provider">
                  {aiModels.error instanceof ApiError
                    ? aiModels.error.message
                    : "The model list could not be fetched."}
                </Alert>
              ) : aiModels.data ? (
                <div className="mt-2 space-y-1.5">
                  {aiModels.data.current_is_available ? (
                    <p className="flex items-center gap-1 text-xs text-status-success">
                      <CheckCircle2 className="size-3.5" />
                      {aiModels.data.current} is available.
                    </p>
                  ) : (
                    <Alert tone="danger" title="The configured model is not available">
                      <code>{aiModels.data.current}</code> is not one this key can
                      use — that is what causes &ldquo;Not found the model … or
                      Permission denied&rdquo;. Set <code>KIMI_MODEL</code> in{" "}
                      <code>backend/.env</code> to one below and restart the
                      backend.
                    </Alert>
                  )}
                  <ul className="flex flex-wrap gap-1">
                    {aiModels.data.models.map((model) => (
                      <li
                        key={model}
                        className={
                          "rounded border px-1.5 py-0.5 font-mono text-[11px] " +
                          (model === aiModels.data.current
                            ? "border-primary bg-primary/10 text-foreground"
                            : "border-border text-muted-foreground")
                        }
                      >
                        {model}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}

          <p className="flex items-start gap-1.5 text-[11px] leading-snug text-subtle-foreground">
            <Info className="mt-0.5 size-3 shrink-0" />
            Only the emails matched to an interview are sent to the model, and
            only the first few thousand characters of each. Nothing else in your
            mailbox leaves this machine.
          </p>
        </CardBody>
      </Card>

      {/* Connected mailboxes */}
      <Card>
        <CardHeader
          title="Mailboxes"
          description="Each person can connect their own."
          action={
            <Button size="xs" variant="secondary" onClick={() => setImapOpen(true)}>
              <Plus />
              Add IMAP / Yahoo
            </Button>
          }
        />
        {imapProvider?.setup_hint ? (
          <div className="border-b border-border px-4 py-2.5">
            <p className="flex items-start gap-1.5 text-[11px] leading-snug text-muted-foreground">
              <Info className="mt-0.5 size-3 shrink-0" />
              {imapProvider.setup_hint}
            </p>
          </div>
        ) : null}
        {isLoading ? (
          <CardBody>
            <Skeleton className="h-20" />
          </CardBody>
        ) : (accounts?.length ?? 0) === 0 ? (
          <EmptyState
            icon={Mail}
            title="No mailboxes connected"
            description="Connect one so the AI can read the emails behind an interview."
          />
        ) : (
          <ul className="divide-y divide-border">
            {accounts?.map((account) => (
              <li key={account.id} className="p-4">
                <div className="flex flex-wrap items-start gap-3">
                  <PersonAvatar
                    color={account.person_color}
                    initials={account.person_initials}
                    size="lg"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-foreground">
                      {account.person_name} · {account.provider_display_name}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {account.address}
                    </p>
                    <p className="text-[11px] text-subtle-foreground">
                      {account.last_used_at
                        ? `Last read ${formatCountdown(account.last_used_at)}`
                        : "Not used yet"}
                      {account.imap_host ? ` · ${account.imap_host}` : ""}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <Button
                      size="xs"
                      variant="secondary"
                      loading={verify.isPending && verify.variables === account.id}
                      onClick={async () => {
                        try {
                          await verify.mutateAsync(account.id);
                          toast.success("Connection is working");
                        } catch (error) {
                          toast.error(
                            error instanceof ApiError
                              ? error.message
                              : "Could not reach the mailbox.",
                          );
                        }
                      }}
                    >
                      <RefreshCw />
                      Test
                    </Button>
                    <Button
                      size="xs"
                      variant="ghost"
                      onClick={async () => {
                        await remove.mutateAsync(account.id);
                        toast.success("Mailbox disconnected");
                      }}
                    >
                      <Trash2 />
                      Remove
                    </Button>
                  </div>
                </div>

                {account.status !== "connected" && account.last_error ? (
                  <Alert tone="danger" className="mt-2" title="Mailbox problem">
                    {account.last_error}
                  </Alert>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Connect a mailbox over OAuth */}
      <Card>
        <CardHeader
          title="Connect with OAuth"
          description="Gmail and Outlook reuse the Google and Microsoft apps already set up for Calendar, with read-only mail access."
        />
        <CardBody className="space-y-2">
          {gmailProvider && !gmailProvider.is_configured ? (
            <Alert tone="warn" title="Google is not configured yet">
              {gmailProvider.setup_hint}
            </Alert>
          ) : null}
          {outlookProvider && !outlookProvider.is_configured ? (
            <Alert tone="warn" title="Microsoft is not configured yet">
              {outlookProvider.setup_hint}
            </Alert>
          ) : null}
          {(people ?? []).map((person) => (
            <div
              key={person.id}
              className="flex flex-wrap items-center gap-2 rounded-md border border-border p-2.5"
            >
              <PersonAvatar
                color={person.color}
                initials={person.initials}
                size="md"
              />
              <span className="min-w-0 flex-1 truncate text-sm text-foreground">
                {person.display_name}
              </span>
              <Button
                size="xs"
                variant="secondary"
                disabled={!gmailProvider?.is_configured}
                onClick={() => connect("gmail", person.id)}
              >
                Connect Gmail
              </Button>
              <Button
                size="xs"
                variant="secondary"
                disabled={!outlookProvider?.is_configured}
                title={
                  outlookProvider?.is_configured
                    ? undefined
                    : (outlookProvider?.setup_hint ?? undefined)
                }
                onClick={() => connect("microsoft", person.id)}
              >
                Connect Outlook
              </Button>
            </div>
          ))}
        </CardBody>
      </Card>

      <ImapDialog open={imapOpen} onOpenChange={setImapOpen} />
    </div>
  );
}

// --------------------------------------------------------------------------
// IMAP / Yahoo
// --------------------------------------------------------------------------

function ImapDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Connect a mailbox"
        description="Yahoo, iCloud, Outlook or any IMAP server."
      >
        <ImapForm onDone={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function ImapForm({ onDone }: { onDone: () => void }) {
  const { data: people } = usePeople();
  const connect = useConnectImap();

  // Null means "not chosen yet", which resolves to the first person once the
  // roster loads — derived rather than synced, so no effect is needed.
  const [chosenPerson, setChosenPerson] = React.useState<string | null>(null);
  const [address, setAddress] = React.useState("");
  const { data: suggestion } = useImapSuggestion(address);
  const [hostOverride, setHostOverride] = React.useState("");

  const personId = chosenPerson ?? people?.[0]?.id ?? "";
  const host = hostOverride || suggestion?.host || "";

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await connect.mutateAsync({
        person_id: personId,
        address: address.trim(),
        password: String(form.get("password") ?? ""),
        imap_host: host || undefined,
        imap_port: suggestion?.port ?? 993,
      });
      toast.success(`${address} connected`);
      onDone();
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Could not connect the mailbox.",
      );
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <div className="space-y-3 p-4">
        <Field label="Person" htmlFor="imap-person">
          <NativeSelect
            id="imap-person"
            value={personId}
            onChange={(event) => setChosenPerson(event.target.value)}
            required
          >
            {(people ?? []).map((person) => (
              <option key={person.id} value={person.id}>
                {person.display_name}
              </option>
            ))}
          </NativeSelect>
        </Field>

        <Field label="Email address" htmlFor="imap-address">
          <Input
            id="imap-address"
            type="email"
            value={address}
            onChange={(event) => setAddress(event.target.value)}
            placeholder="you@yahoo.com"
            required
            autoFocus
          />
        </Field>

        {suggestion?.hint ? (
          <Alert tone={suggestion.known_provider ? "info" : "warn"}>
            {suggestion.hint}
          </Alert>
        ) : null}

        <Field
          label="App password"
          htmlFor="imap-password"
          hint="(not your normal password)"
        >
          <Input
            id="imap-password"
            name="password"
            type="password"
            required
            placeholder="••••••••••••"
          />
        </Field>

        <Field
          label="IMAP server"
          htmlFor="imap-host"
          hint={suggestion?.known_provider ? "(detected)" : "(required)"}
        >
          <Input
            id="imap-host"
            value={host}
            onChange={(event) => setHostOverride(event.target.value)}
            placeholder="imap.mail.yahoo.com"
            required
          />
        </Field>

        <p className="flex items-start gap-1.5 text-[11px] leading-snug text-subtle-foreground">
          <Sparkles className="mt-0.5 size-3 shrink-0" />
          The password is encrypted before it is stored, and only used to read
          mail matching an interview on your calendar.
        </p>
      </div>

      <DialogFooter>
        <Button type="button" variant="secondary" size="sm" onClick={onDone}>
          Cancel
        </Button>
        <Button
          type="submit"
          variant="primary"
          size="sm"
          loading={connect.isPending}
          disabled={!personId || !address || !host}
        >
          Connect and test
        </Button>
      </DialogFooter>
    </form>
  );
}
