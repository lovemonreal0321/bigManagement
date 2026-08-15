"use client";

import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  Link2,
  RefreshCw,
  Settings as SettingsIcon,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { EmailSettings } from "@/components/settings/email-settings";
import { PageHeader } from "@/components/shared/page-header";
import { PersonAvatar } from "@/components/shared/badges";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
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
import { formatCountdown } from "@/lib/format";
import {
  useCalendarConnections,
  useCalendarProviders,
  useDisconnectCalendar,
  usePeople,
  useSettings,
  useStartOAuth,
  useSyncConnection,
  useTimezones,
  useUpdateCalendarSelection,
  useUpdateSettings,
} from "@/lib/queries";

export default function SettingsPage() {
  const searchParams = useSearchParams();
  // Landing back from a Gmail OAuth round-trip should open the Email tab, so
  // the initial value is derived from the query string rather than set later.
  const [tab, setTab] = React.useState(() =>
    searchParams.get("email_connected") || searchParams.get("email_error")
      ? "email"
      : "calendars",
  );

  // The OAuth callback bounces back here with a result in the query string.
  React.useEffect(() => {
    const connected = searchParams.get("calendar_connected");
    const error = searchParams.get("calendar_error");
    const emailConnected = searchParams.get("email_connected");
    const emailError = searchParams.get("email_error");
    if (connected) toast.success(`${connected} calendar connected`);
    if (emailConnected) toast.success(`${emailConnected} mailbox connected`);
    if (emailError) {
      toast.error(
        `Could not connect the mailbox (${emailError.replace(/_/g, " ")}).`,
      );
    }
    if (error) {
      toast.error(
        error === "provider_not_configured"
          ? "That provider is not configured on the server yet."
          : `Could not connect the calendar (${error.replace(/_/g, " ")}).`,
      );
    }
    if (connected || error || emailConnected || emailError) {
      window.history.replaceState({}, "", "/settings");
    }
  }, [searchParams]);

  return (
    <div>
      <PageHeader
        title="Settings"
        description="Calendar connections, timezones and automation thresholds."
      />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="mb-4">
          <TabsTrigger value="calendars">
            <CalendarDays className="mr-1 inline size-3.5" />
            Calendars
          </TabsTrigger>
          <TabsTrigger value="email">
            <Sparkles className="mr-1 inline size-3.5" />
            Email &amp; AI
          </TabsTrigger>
          <TabsTrigger value="workspace">
            <SettingsIcon className="mr-1 inline size-3.5" />
            Workspace
          </TabsTrigger>
        </TabsList>

        <TabsContent value="calendars">
          <CalendarSettings />
        </TabsContent>
        <TabsContent value="email">
          <EmailSettings />
        </TabsContent>
        <TabsContent value="workspace">
          <WorkspaceSettings />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// --------------------------------------------------------------------------
// Calendars (spec §45)
// --------------------------------------------------------------------------

function CalendarSettings() {
  const { data: providers } = useCalendarProviders();
  const { data: connections, isLoading } = useCalendarConnections();
  const { data: people } = usePeople();
  const startOAuth = useStartOAuth();
  const syncConnection = useSyncConnection();
  const disconnect = useDisconnectCalendar();
  const updateSelection = useUpdateCalendarSelection();

  async function connect(provider: string, personId: string) {
    try {
      const result = await startOAuth.mutateAsync({ provider, personId });
      window.location.assign(result.authorization_url);
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : "Could not start the connection.",
      );
    }
  }

  return (
    <div className="space-y-4">
      {/* Provider configuration status (spec §69) */}
      <Card>
        <CardHeader
          title="Providers"
          description="Calendar sync needs OAuth credentials on the server. Everything else in the app works without them."
        />
        <CardBody className="space-y-2">
          {(providers ?? []).map((provider) => (
            <div
              key={provider.key}
              className="flex flex-wrap items-center gap-2 rounded-md border border-border p-3"
            >
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-1.5 text-sm font-medium text-foreground">
                  {provider.display_name}
                  {provider.is_configured ? (
                    <CheckCircle2 className="size-3.5 text-status-success" />
                  ) : (
                    <AlertTriangle className="size-3.5 text-status-warn" />
                  )}
                </p>
                <p className="text-xs text-muted-foreground">
                  {provider.is_configured
                    ? "Configured and ready to connect."
                    : provider.setup_hint}
                </p>
              </div>
            </div>
          ))}
        </CardBody>
      </Card>

      {/* Per-person connections */}
      <Card>
        <CardHeader
          title="Connected accounts"
          description="Each person can connect their own calendar."
        />
        {isLoading ? (
          <CardBody>
            <Skeleton className="h-24" />
          </CardBody>
        ) : (connections?.length ?? 0) === 0 ? (
          <EmptyState
            icon={Link2}
            title="No calendars connected"
            description="Connect an account below to import interviews automatically."
          />
        ) : (
          <ul className="divide-y divide-border">
            {connections?.map((connection) => (
              <li key={connection.id} className="p-4">
                <div className="flex flex-wrap items-start gap-3">
                  <PersonAvatar
                    color={connection.person_color}
                    initials={connection.person_initials}
                    size="lg"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-foreground">
                      {connection.person_name} ·{" "}
                      {connection.provider_display_name}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {connection.account_email ?? connection.account_name}
                    </p>
                    <p className="text-[11px] text-subtle-foreground">
                      {connection.last_sync_at
                        ? `Last synced ${formatCountdown(connection.last_sync_at)}`
                        : "Never synced"}
                    </p>
                  </div>

                  <div className="flex shrink-0 gap-1">
                    <Button
                      size="xs"
                      variant="secondary"
                      loading={
                        syncConnection.isPending &&
                        syncConnection.variables === connection.id
                      }
                      onClick={async () => {
                        try {
                          const result = await syncConnection.mutateAsync(
                            connection.id,
                          );
                          if (result.error) toast.error(result.error);
                          else
                            toast.success(
                              `${result.events_created} new, ${result.events_updated} updated`,
                            );
                        } catch (error) {
                          toast.error(
                            error instanceof ApiError
                              ? error.message
                              : "Sync failed.",
                          );
                        }
                      }}
                    >
                      <RefreshCw />
                      Sync now
                    </Button>
                    <Button
                      size="xs"
                      variant="ghost"
                      onClick={async () => {
                        await disconnect.mutateAsync(connection.id);
                        toast.success("Calendar disconnected");
                      }}
                    >
                      <Trash2 />
                      Disconnect
                    </Button>
                  </div>
                </div>

                {connection.status !== "connected" ? (
                  <Alert
                    tone="danger"
                    className="mt-2"
                    title="Calendar connection expired"
                    action={
                      <Button
                        size="xs"
                        variant="primary"
                        onClick={() =>
                          connect(connection.provider, connection.person_id)
                        }
                      >
                        Reconnect
                      </Button>
                    }
                  >
                    {connection.last_sync_error ??
                      "Reconnect the account to resume syncing."}
                  </Alert>
                ) : null}

                {connection.calendars.length > 0 ? (
                  <div className="mt-3 border-t border-border pt-3">
                    <p className="mb-1.5 text-[11px] font-medium text-muted-foreground">
                      Calendars to sync
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {connection.calendars.map((calendar) => (
                        <label
                          key={calendar.id}
                          className="flex cursor-pointer items-center gap-1.5 rounded border border-border px-2 py-1 text-xs"
                        >
                          <input
                            type="checkbox"
                            checked={calendar.is_selected}
                            onChange={(event) => {
                              const selected = connection.calendars
                                .filter((item) =>
                                  item.id === calendar.id
                                    ? event.target.checked
                                    : item.is_selected,
                                )
                                .map((item) => item.id);
                              updateSelection.mutate({
                                connectionId: connection.id,
                                selectedCalendarIds: selected,
                              });
                            }}
                            className="size-3.5 accent-[var(--primary)]"
                          />
                          {calendar.name}
                          {calendar.is_primary ? (
                            <span className="text-[10px] text-subtle-foreground">
                              primary
                            </span>
                          ) : null}
                        </label>
                      ))}
                    </div>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Connect a new account */}
      <Card>
        <CardHeader title="Connect a calendar" />
        <CardBody className="space-y-2">
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
              {(providers ?? []).map((provider) => (
                <Button
                  key={provider.key}
                  size="xs"
                  variant="secondary"
                  disabled={!provider.is_configured}
                  title={
                    provider.is_configured
                      ? undefined
                      : (provider.setup_hint ?? undefined)
                  }
                  onClick={() => connect(provider.key, person.id)}
                >
                  Connect {provider.display_name}
                </Button>
              ))}
            </div>
          ))}
        </CardBody>
      </Card>
    </div>
  );
}

// --------------------------------------------------------------------------
// Workspace
// --------------------------------------------------------------------------

function WorkspaceSettings() {
  const { data: settings, isLoading } = useSettings();
  const { data: timezones } = useTimezones();
  const updateSettings = useUpdateSettings();

  if (isLoading || !settings) return <Skeleton className="h-96" />;

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body: Record<string, unknown> = {
      name: form.get("name"),
      default_timezone: form.get("default_timezone"),
      week_starts_on: Number(form.get("week_starts_on")),
      display_timezone_mode: form.get("display_timezone_mode"),
      sync_window_past_days: Number(form.get("sync_window_past_days")),
      sync_window_future_days: Number(form.get("sync_window_future_days")),
      auto_detect_interviews: form.get("auto_detect_interviews") === "on",
      followup_after_interview_business_days: Number(
        form.get("followup_after_interview_business_days"),
      ),
      followup_chain_business_days: Number(
        form.get("followup_chain_business_days"),
      ),
      waiting_for_feedback_threshold_days: Number(
        form.get("waiting_for_feedback_threshold_days"),
      ),
      no_activity_ghosted_threshold_days: Number(
        form.get("no_activity_ghosted_threshold_days"),
      ),
    };

    try {
      await updateSettings.mutateAsync(body);
      toast.success("Settings saved");
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "Could not save settings.",
      );
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <Card>
        <CardHeader title="Workspace" />
        <CardBody className="grid gap-3 sm:grid-cols-2">
          <Field label="Name" htmlFor="ws-name">
            <Input id="ws-name" name="name" defaultValue={settings.name} />
          </Field>
          <Field label="Default timezone" htmlFor="ws-tz">
            <NativeSelect
              id="ws-tz"
              name="default_timezone"
              defaultValue={settings.default_timezone}
            >
              {(timezones ?? []).map((zone) => (
                <option key={zone} value={zone}>
                  {zone}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field label="Week starts on" htmlFor="ws-week">
            <NativeSelect
              id="ws-week"
              name="week_starts_on"
              defaultValue={String(settings.week_starts_on)}
            >
              <option value="0">Monday</option>
              <option value="6">Sunday</option>
            </NativeSelect>
          </Field>
          <Field
            label="Show times in"
            htmlFor="ws-tzmode"
            hint="(workspace or each person's own zone)"
          >
            <NativeSelect
              id="ws-tzmode"
              name="display_timezone_mode"
              defaultValue={settings.display_timezone_mode}
            >
              <option value="workspace">Workspace timezone</option>
              <option value="person">Each person&apos;s timezone</option>
            </NativeSelect>
          </Field>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Calendar sync"
          description="How far either side of today to import events."
        />
        <CardBody className="grid gap-3 sm:grid-cols-2">
          <Field label="Days in the past" htmlFor="ws-past">
            <Input
              id="ws-past"
              name="sync_window_past_days"
              type="number"
              min={1}
              max={3650}
              defaultValue={settings.sync_window_past_days}
            />
          </Field>
          <Field label="Days ahead" htmlFor="ws-future">
            <Input
              id="ws-future"
              name="sync_window_future_days"
              type="number"
              min={1}
              max={3650}
              defaultValue={settings.sync_window_future_days}
            />
          </Field>
          <label className="flex items-center gap-2 text-xs text-foreground sm:col-span-2">
            <input
              type="checkbox"
              name="auto_detect_interviews"
              defaultChecked={settings.auto_detect_interviews}
              className="size-3.5 accent-[var(--primary)]"
            />
            Suggest which imported events look like interviews
            <span className="text-subtle-foreground">
              (suggestions only — nothing is created automatically)
            </span>
          </label>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Follow-up automation"
          description="Thresholds used for suggestions and the Needs Attention panel."
        />
        <CardBody className="grid gap-3 sm:grid-cols-2">
          <Field
            label="Follow up after an interview"
            htmlFor="ws-fu1"
            hint="(business days)"
          >
            <Input
              id="ws-fu1"
              name="followup_after_interview_business_days"
              type="number"
              min={0}
              max={60}
              defaultValue={settings.followup_after_interview_business_days}
            />
          </Field>
          <Field
            label="Chain the next follow-up after"
            htmlFor="ws-fu2"
            hint="(business days)"
          >
            <Input
              id="ws-fu2"
              name="followup_chain_business_days"
              type="number"
              min={0}
              max={60}
              defaultValue={settings.followup_chain_business_days}
            />
          </Field>
          <Field
            label="Flag 'waiting for feedback' after"
            htmlFor="ws-wait"
            hint="(days)"
          >
            <Input
              id="ws-wait"
              name="waiting_for_feedback_threshold_days"
              type="number"
              min={1}
              max={365}
              defaultValue={settings.waiting_for_feedback_threshold_days}
            />
          </Field>
          <Field
            label="Suggest 'ghosted' after no activity for"
            htmlFor="ws-ghost"
            hint="(days)"
          >
            <Input
              id="ws-ghost"
              name="no_activity_ghosted_threshold_days"
              type="number"
              min={1}
              max={365}
              defaultValue={settings.no_activity_ghosted_threshold_days}
            />
          </Field>
        </CardBody>
      </Card>

      <div className="flex justify-end">
        <Button
          type="submit"
          variant="primary"
          size="sm"
          loading={updateSettings.isPending}
        >
          Save settings
        </Button>
      </div>
    </form>
  );
}
