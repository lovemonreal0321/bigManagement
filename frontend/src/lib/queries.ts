"use client";

/** TanStack Query hooks. One place that knows how the API is shaped. */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";

import { api, type QueryValue } from "./api";
import type {
  Activity,
  AiExtraction,
  AiModels,
  ApplicationSheet,
  BulkApplicationResult,
  BulkApplicationRow,
  AuthUser,
  AiStatus,
  Analytics,
  Application,
  ApplicationDetail,
  CalendarConnection,
  CalendarEventDetail,
  CalendarFeed,
  Dashboard,
  EmailAccount,
  EmailProviderInfo,
  EnrichSummary,
  FollowUp,
  FollowUpBoard,
  FollowUpSuggestion,
  InterviewSearchResult,
  InterviewStage,
  ImapHostSuggestion,
  InterviewSuggestion,
  InterviewType,
  Job,
  JobSummary,
  Page,
  PersonWithStats,
  Pipeline,
  ProviderInfo,
  SyncResult,
  SyncSummary,
  UpcomingInterview,
  UserCreatePayload,
  UserUpdatePayload,
  Workload,
  WorkspaceSettings,
} from "./types";

type PersonIds = string[] | undefined;

/** Scope key so every person-filtered query refetches when the filter moves. */
const scope = (personIds: PersonIds) => personIds?.slice().sort().join(",") ?? "all";

const personParams = (personIds: PersonIds): Record<string, QueryValue> =>
  personIds ? { person_ids: personIds } : {};

export const queryKeys = {
  people: ["people"] as const,
  settings: ["settings"] as const,
  interviewTypes: ["interview-types"] as const,
  providers: ["calendar", "providers"] as const,
  connections: ["calendar", "connections"] as const,
  dashboard: (personIds: PersonIds, period: string) =>
    ["dashboard", scope(personIds), period] as const,
  applications: (personIds: PersonIds, filters: unknown) =>
    ["applications", scope(personIds), filters] as const,
  application: (id: string) => ["application", id] as const,
  pipeline: (personIds: PersonIds, search: string) =>
    ["pipeline", scope(personIds), search] as const,
  followUpBoard: (personIds: PersonIds) =>
    ["follow-ups", "board", scope(personIds)] as const,
  followUpSuggestions: (personIds: PersonIds) =>
    ["follow-ups", "suggestions", scope(personIds)] as const,
  analytics: (personIds: PersonIds, period: string, range: string) =>
    ["analytics", scope(personIds), period, range] as const,
  workload: (personIds: PersonIds, start: string, end: string) =>
    ["workload", scope(personIds), start, end] as const,
  calendarFeed: (personIds: PersonIds, start: string, end: string, filters: unknown) =>
    ["calendar", "feed", scope(personIds), start, end, filters] as const,
  calendarSuggestions: (personIds: PersonIds) =>
    ["calendar", "suggestions", scope(personIds)] as const,
  calendarEvent: (id: string) => ["calendar", "event", id] as const,
  upcoming: (personIds: PersonIds) => ["upcoming", scope(personIds)] as const,
  activity: (personIds: PersonIds, applicationId?: string) =>
    ["activity", scope(personIds), applicationId ?? "all"] as const,
  users: ["users"] as const,
  jobs: (personIds: PersonIds, includeEnded: boolean) =>
    ["jobs", scope(personIds), includeEnded] as const,
  jobSummary: (personIds: PersonIds) => ["jobs", "summary", scope(personIds)] as const,
  interviewSearch: (personIds: PersonIds, search: string) =>
    ["interviews", "search", scope(personIds), search] as const,
  sheet: (
    personIds: PersonIds,
    personId: string | null,
    search: string,
    archived: boolean,
    day: string | null,
  ) =>
    [
      "applications",
      "sheet",
      scope(personIds),
      personId ?? "first",
      search,
      archived,
      day ?? "all",
    ] as const,
};

/** Invalidate everything that can be affected by a write. */
export function useInvalidateAll() {
  const client = useQueryClient();
  return () => {
    for (const key of [
      "dashboard",
      "applications",
      "application",
      "pipeline",
      "follow-ups",
      "analytics",
      "workload",
      "calendar",
      "upcoming",
      "activity",
      "people",
    ]) {
      client.invalidateQueries({ queryKey: [key] });
    }
  };
}

// --------------------------------------------------------------------------
// People
// --------------------------------------------------------------------------

export function usePeople(
  includeArchived = false,
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: [...queryKeys.people, includeArchived],
    queryFn: () =>
      api.get<PersonWithStats[]>("/people", {
        include_archived: includeArchived,
      }),
    staleTime: 30_000,
    ...options,
  });
}

export function usePersonColors() {
  return useQuery({
    queryKey: ["people", "colors"],
    queryFn: () => api.get<string[]>("/people/colors"),
    staleTime: Infinity,
  });
}

// --------------------------------------------------------------------------
// Dashboard
// --------------------------------------------------------------------------

export function useDashboard(personIds: PersonIds, period = "last_30_days") {
  return useQuery({
    queryKey: queryKeys.dashboard(personIds, period),
    queryFn: () =>
      api.get<Dashboard>("/dashboard", { ...personParams(personIds), period }),
  });
}

// --------------------------------------------------------------------------
// Applications
// --------------------------------------------------------------------------

export interface ApplicationFilterInput {
  status?: string[];
  column?: string[];
  type_key?: string[];
  outcome?: string[];
  work_mode?: string[];
  source?: string[];
  company?: string;
  q?: string;
  applied_from?: string;
  applied_to?: string;
  has_upcoming_interview?: boolean;
  has_overdue_follow_up?: boolean;
  include_archived?: boolean;
  sort?: string;
  limit?: number;
  offset?: number;
}

export function useApplications(
  personIds: PersonIds,
  filters: ApplicationFilterInput = {},
) {
  return useQuery({
    queryKey: queryKeys.applications(personIds, filters),
    queryFn: () =>
      api.get<Page<Application>>("/applications", {
        ...personParams(personIds),
        ...(filters as Record<string, QueryValue>),
      }),
  });
}

export function useApplication(
  id: string,
  options?: Partial<UseQueryOptions<ApplicationDetail>>,
) {
  return useQuery({
    queryKey: queryKeys.application(id),
    queryFn: () => api.get<ApplicationDetail>(`/applications/${id}`),
    ...options,
  });
}

export function usePipeline(personIds: PersonIds, search = "") {
  return useQuery({
    queryKey: queryKeys.pipeline(personIds, search),
    queryFn: () =>
      api.get<Pipeline>("/applications/pipeline", {
        ...personParams(personIds),
        q: search || undefined,
      }),
  });
}

export function useSheet(
  personIds: PersonIds,
  personId: string | null,
  search = "",
  includeArchived = false,
  day: string | null = null,
) {
  return useQuery({
    queryKey: queryKeys.sheet(personIds, personId, search, includeArchived, day),
    queryFn: () =>
      api.get<ApplicationSheet>("/applications/sheet", {
        person_ids: personIds,
        person_id: personId ?? undefined,
        q: search || undefined,
        include_archived: includeArchived || undefined,
        day: day ?? undefined,
      }),
    // Keep the previous grid on screen while a keystroke re-queries, so the
    // sheet does not blank out on every letter typed.
    placeholderData: (previous) => previous,
  });
}

/** Past interviews, to hang a later round off one of them. */
export function useInterviewSearch(personIds: PersonIds, search = "") {
  return useQuery({
    queryKey: queryKeys.interviewSearch(personIds, search),
    queryFn: () =>
      api.get<InterviewSearchResult[]>("/interviews/search", {
        ...personParams(personIds),
        q: search || undefined,
        limit: 25,
      }),
    placeholderData: (previous) => previous,
  });
}

// --------------------------------------------------------------------------
// Jobs
// --------------------------------------------------------------------------

/** `enabled` is off for accounts without job access, so no pointless 403. */
export function useJobs(personIds: PersonIds, includeEnded = true, enabled = true) {
  return useQuery({
    queryKey: queryKeys.jobs(personIds, includeEnded),
    queryFn: () =>
      api.get<Job[]>("/jobs", {
        ...personParams(personIds),
        include_ended: includeEnded,
      }),
    enabled,
  });
}

export function useJobSummary(personIds: PersonIds, enabled = true) {
  return useQuery({
    queryKey: queryKeys.jobSummary(personIds),
    queryFn: () => api.get<JobSummary>("/jobs/summary", personParams(personIds)),
    enabled,
  });
}

function useJobMutation<TVars>(fn: (vars: TVars) => Promise<unknown>) {
  const client = useQueryClient();
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["jobs"] });
      invalidate();
    },
  });
}

export function useCreateJob() {
  return useJobMutation((body: Record<string, unknown>) =>
    api.post<Job>("/jobs", body),
  );
}

export function useUpdateJob() {
  return useJobMutation(
    ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api.patch<Job>(`/jobs/${id}`, body),
  );
}

export function useEndJob() {
  return useJobMutation(
    ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api.post<Job>(`/jobs/${id}/end`, body),
  );
}

export function useDeleteJob() {
  return useJobMutation((id: string) => api.del(`/jobs/${id}`));
}

export function useFilterOptions() {
  return useQuery({
    queryKey: ["applications", "filter-options"],
    queryFn: () =>
      api.get<{ sources: string[]; companies: string[]; outcomes: string[] }>(
        "/applications/filter-options",
      ),
    staleTime: 60_000,
  });
}

export function useCreateApplication() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post<Application>("/applications", body),
    onSuccess: invalidate,
  });
}

/** Paste a block of rows out of a spreadsheet. One request, one transaction. */
export function useBulkCreateApplications() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: (body: { person_id: string; rows: BulkApplicationRow[] }) =>
      api.post<BulkApplicationResult>("/applications/bulk", body),
    onSuccess: invalidate,
  });
}

export function useUpdateApplication() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api.patch<Application>(`/applications/${id}`, body),
    onSuccess: invalidate,
  });
}

export function useChangeApplicationStatus() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({
      id,
      status,
      column,
    }: {
      id: string;
      status?: string;
      column?: string;
    }) => api.post<Application>(`/applications/${id}/status`, { status, column }),
    onSuccess: invalidate,
  });
}

export function useArchiveApplication() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({ id, restore }: { id: string; restore?: boolean }) =>
      api.post<Application>(
        `/applications/${id}/${restore ? "restore" : "archive"}`,
      ),
    onSuccess: invalidate,
  });
}

export function useAddNote() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: string }) =>
      api.post(`/applications/${id}/notes`, { body }),
    onSuccess: invalidate,
  });
}

// --------------------------------------------------------------------------
// Interviews
// --------------------------------------------------------------------------

export function useInterviewTypes() {
  return useQuery({
    queryKey: queryKeys.interviewTypes,
    queryFn: () => api.get<InterviewType[]>("/interview-types"),
    staleTime: 300_000,
  });
}

export function useUpcomingInterviews(personIds: PersonIds, limit = 25) {
  return useQuery({
    queryKey: queryKeys.upcoming(personIds),
    queryFn: () =>
      api.get<UpcomingInterview[]>("/interviews/upcoming", {
        ...personParams(personIds),
        limit,
      }),
  });
}

export function useCreateStage() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({
      applicationId,
      body,
    }: {
      applicationId: string;
      body: Record<string, unknown>;
    }) => api.post<InterviewStage>(`/applications/${applicationId}/stages`, body),
    onSuccess: invalidate,
  });
}

export function useUpdateStage() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api.patch<InterviewStage>(`/interview-stages/${id}`, body),
    onSuccess: invalidate,
  });
}

export function useSetOutcome() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api.post<InterviewStage>(`/interview-stages/${id}/outcome`, body),
    onSuccess: invalidate,
  });
}

export function useDeleteStage() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: (id: string) => api.del(`/interview-stages/${id}`),
    onSuccess: invalidate,
  });
}

export function useAddInterviewEvent() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({
      stageId,
      body,
    }: {
      stageId: string;
      body: Record<string, unknown>;
    }) => api.post(`/interview-stages/${stageId}/events`, body),
    onSuccess: invalidate,
  });
}

export function useUpdateInterviewEvent() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api.patch(`/interview-events/${id}`, body),
    onSuccess: invalidate,
  });
}

export function useDeleteInterviewEvent() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: (id: string) => api.del(`/interview-events/${id}`),
    onSuccess: invalidate,
  });
}

// --------------------------------------------------------------------------
// Follow-ups
// --------------------------------------------------------------------------

export function useFollowUpBoard(personIds: PersonIds) {
  return useQuery({
    queryKey: queryKeys.followUpBoard(personIds),
    queryFn: () =>
      api.get<FollowUpBoard>("/follow-ups/board", personParams(personIds)),
  });
}

export function useFollowUpSuggestions(personIds: PersonIds) {
  return useQuery({
    queryKey: queryKeys.followUpSuggestions(personIds),
    queryFn: () =>
      api.get<FollowUpSuggestion[]>(
        "/follow-ups/suggestions",
        personParams(personIds),
      ),
  });
}

export function useCreateFollowUp() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post<FollowUp>("/follow-ups", body),
    onSuccess: invalidate,
  });
}

export function useUpdateFollowUp() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api.patch<FollowUp>(`/follow-ups/${id}`, body),
    onSuccess: invalidate,
  });
}

export function useFollowUpAction() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({
      id,
      action,
      body,
    }: {
      id: string;
      action: "complete" | "snooze" | "cancel";
      body?: Record<string, unknown>;
    }) => api.post<FollowUp>(`/follow-ups/${id}/${action}`, body ?? {}),
    onSuccess: invalidate,
  });
}

export function useDeleteFollowUp() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: (id: string) => api.del(`/follow-ups/${id}`),
    onSuccess: invalidate,
  });
}

// --------------------------------------------------------------------------
// Calendar
// --------------------------------------------------------------------------

export interface CalendarFilterInput {
  type_key?: string[];
  stage_status?: string[];
  external_calendar_id?: string[];
  classification?: string[];
  show_non_interview?: boolean;
}

export function useCalendarFeed(
  personIds: PersonIds,
  start: string,
  end: string,
  filters: CalendarFilterInput = {},
) {
  return useQuery({
    queryKey: queryKeys.calendarFeed(personIds, start, end, filters),
    queryFn: () =>
      api.get<CalendarFeed>("/calendar/feed", {
        ...personParams(personIds),
        start,
        end,
        ...(filters as Record<string, QueryValue>),
      }),
  });
}

export function useCalendarSuggestions(personIds: PersonIds) {
  return useQuery({
    queryKey: queryKeys.calendarSuggestions(personIds),
    queryFn: () =>
      api.get<InterviewSuggestion[]>(
        "/calendar/suggestions",
        personParams(personIds),
      ),
  });
}

export function useCalendarEvent(id: string | null) {
  return useQuery({
    queryKey: queryKeys.calendarEvent(id ?? ""),
    queryFn: () => api.get<CalendarEventDetail>(`/calendar/events/${id}`),
    enabled: Boolean(id),
  });
}

export function useCalendarProviders() {
  return useQuery({
    queryKey: queryKeys.providers,
    queryFn: () => api.get<ProviderInfo[]>("/calendar/providers"),
    staleTime: 300_000,
  });
}

export function useCalendarConnections() {
  return useQuery({
    queryKey: queryKeys.connections,
    queryFn: () => api.get<CalendarConnection[]>("/calendar/connections/all"),
  });
}

export function useStartOAuth() {
  return useMutation({
    mutationFn: ({ provider, personId }: { provider: string; personId: string }) =>
      api.post<{ authorization_url: string }>(
        `/calendar/oauth/${provider}/start`,
        undefined,
        { person_id: personId },
      ),
  });
}

/** Sync every connected calendar. Returns a per-connection summary. */
export function useSyncAllCalendars() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: () => api.post<SyncSummary>("/calendar/sync"),
    onSuccess: invalidate,
  });
}

/** Sync one connection, for the per-account "Sync now" button in Settings. */
export function useSyncConnection() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: (connectionId: string) =>
      api.post<SyncResult>(`/calendar/connections/${connectionId}/sync`),
    onSuccess: invalidate,
  });
}

export function useDisconnectCalendar() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: (connectionId: string) =>
      api.del(`/calendar/connections/${connectionId}`),
    onSuccess: invalidate,
  });
}

export function useUpdateCalendarSelection() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({
      connectionId,
      selectedCalendarIds,
    }: {
      connectionId: string;
      selectedCalendarIds: string[];
    }) =>
      api.post<CalendarConnection>(
        `/calendar/connections/${connectionId}/calendars`,
        { selected_calendar_ids: selectedCalendarIds },
      ),
    onSuccess: invalidate,
  });
}

export function useClassifyEvent() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({
      eventId,
      classification,
    }: {
      eventId: string;
      classification: string;
    }) => api.post(`/calendar/events/${eventId}/classify`, { classification }),
    onSuccess: invalidate,
  });
}

export function useDismissSuggestion() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: (eventId: string) =>
      api.post(`/calendar/events/${eventId}/dismiss`, { dismissed: true }),
    onSuccess: invalidate,
  });
}

export function useLinkEvent() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({
      eventId,
      body,
    }: {
      eventId: string;
      body: Record<string, unknown>;
    }) => api.post<InterviewStage>(`/calendar/events/${eventId}/link`, body),
    onSuccess: invalidate,
  });
}

export function useCreateApplicationFromEvent() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({
      eventId,
      body,
    }: {
      eventId: string;
      body: Record<string, unknown>;
    }) =>
      api.post<{ application_id: string }>(
        `/calendar/events/${eventId}/create-application`,
        body,
      ),
    onSuccess: invalidate,
  });
}

// --------------------------------------------------------------------------
// Analytics
// --------------------------------------------------------------------------

export function useAnalytics(
  personIds: PersonIds,
  period: string,
  range?: { start?: string; end?: string },
) {
  return useQuery({
    queryKey: queryKeys.analytics(
      personIds,
      period,
      `${range?.start ?? ""}:${range?.end ?? ""}`,
    ),
    queryFn: () =>
      api.get<Analytics>("/analytics", {
        ...personParams(personIds),
        period,
        start: range?.start,
        end: range?.end,
      }),
  });
}

export function useWorkload(personIds: PersonIds, start?: string, end?: string) {
  return useQuery({
    queryKey: queryKeys.workload(personIds, start ?? "", end ?? ""),
    queryFn: () =>
      api.get<Workload>("/analytics/workload", {
        ...personParams(personIds),
        start,
        end,
      }),
  });
}

// --------------------------------------------------------------------------
// Activity + settings
// --------------------------------------------------------------------------

export function useActivity(personIds: PersonIds, applicationId?: string) {
  return useQuery({
    queryKey: queryKeys.activity(personIds, applicationId),
    queryFn: () =>
      api.get<Page<Activity>>("/activity", {
        ...personParams(personIds),
        application_id: applicationId,
        limit: 50,
      }),
  });
}

export function useSettings() {
  return useQuery({
    queryKey: queryKeys.settings,
    queryFn: () => api.get<WorkspaceSettings>("/settings"),
  });
}

export function useUpdateSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.patch<WorkspaceSettings>("/settings", body),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: queryKeys.settings });
    },
  });
}

// --------------------------------------------------------------------------
// People mutations
// --------------------------------------------------------------------------

export function useCreatePerson() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post("/people", body),
    onSuccess: invalidate,
  });
}

export function useUpdatePerson() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api.patch(`/people/${id}`, body),
    onSuccess: invalidate,
  });
}

export function usePersonArchive() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({ id, restore }: { id: string; restore?: boolean }) =>
      api.post(`/people/${id}/${restore ? "restore" : "archive"}`),
    onSuccess: invalidate,
  });
}

// --------------------------------------------------------------------------
// Users and roles
//
// Every endpoint here is administrator-only on the server. The UI hides these
// controls rather than letting the user discover the 403.
// --------------------------------------------------------------------------

export function useUsers(enabled = true) {
  return useQuery({
    queryKey: queryKeys.users,
    queryFn: () => api.get<AuthUser[]>("/users"),
    enabled,
  });
}

/** Shared wrapper: every user mutation refreshes the same list. */
function useUserMutation<TVars>(fn: (vars: TVars) => Promise<unknown>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      client.invalidateQueries({ queryKey: queryKeys.users });
    },
  });
}

export function useCreateUser() {
  return useUserMutation((body: UserCreatePayload) =>
    api.post<AuthUser>("/users", body),
  );
}

export function useUpdateUser() {
  return useUserMutation(
    ({ id, body }: { id: string; body: UserUpdatePayload }) =>
      api.patch<AuthUser>(`/users/${id}`, body),
  );
}

export function useSetUserPassword() {
  return useUserMutation(({ id, password }: { id: string; password: string }) =>
    api.put<AuthUser>(`/users/${id}/password`, { password }),
  );
}

export function useAssignPeople() {
  return useUserMutation(
    ({ id, personIds }: { id: string; personIds: string[] }) =>
      api.put<AuthUser>(`/users/${id}/people`, { person_ids: personIds }),
  );
}

export function useDeleteUser() {
  return useUserMutation((id: string) => api.del(`/users/${id}`));
}

export function useChangeOwnPassword() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      api.post<AuthUser>("/auth/password", body),
    onSuccess: () => {
      // `must_change_password` just flipped, so the cached session is stale.
      client.invalidateQueries({ queryKey: ["auth", "me"] });
    },
  });
}

// --------------------------------------------------------------------------
// Email accounts
// --------------------------------------------------------------------------

export function useEmailProviders() {
  return useQuery({
    queryKey: ["email", "providers"],
    queryFn: () => api.get<EmailProviderInfo[]>("/email/providers"),
    staleTime: 300_000,
  });
}

export function useEmailAccounts() {
  return useQuery({
    queryKey: ["email", "accounts"],
    queryFn: () => api.get<EmailAccount[]>("/email/accounts"),
  });
}

/** Prefills the IMAP form from an address (Yahoo, iCloud, Outlook, …). */
export function useImapSuggestion(address: string) {
  const trimmed = address.trim();
  return useQuery({
    queryKey: ["email", "imap-suggest", trimmed],
    queryFn: () =>
      api.get<ImapHostSuggestion>("/email/imap/suggest", { address: trimmed }),
    enabled: trimmed.includes("@") && trimmed.split("@")[1]?.includes("."),
    staleTime: Infinity,
  });
}

export function useConnectImap() {
  const invalidate = useInvalidateAll();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post<EmailAccount>("/email/accounts/imap", body),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["email"] });
      client.invalidateQueries({ queryKey: ["ai"] });
      invalidate();
    },
  });
}

/** Start the mail OAuth flow for Gmail or Outlook. */
export function useStartEmailOAuth() {
  return useMutation({
    mutationFn: ({
      provider,
      personId,
    }: {
      provider: "gmail" | "microsoft";
      personId: string;
    }) =>
      api.post<{ authorization_url: string }>(
        `/email/oauth/${provider === "gmail" ? "google" : "microsoft"}/start`,
        undefined,
        { person_id: personId },
      ),
  });
}

export function useVerifyEmailAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) =>
      api.post<EmailAccount>(`/email/accounts/${accountId}/verify`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["email"] }),
  });
}

export function useDeleteEmailAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) => api.del(`/email/accounts/${accountId}`),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["email"] });
      client.invalidateQueries({ queryKey: ["ai"] });
    },
  });
}

// --------------------------------------------------------------------------
// AI enrichment
// --------------------------------------------------------------------------

export function useAiStatus() {
  return useQuery({
    queryKey: ["ai", "status"],
    queryFn: () => api.get<AiStatus>("/ai/status"),
  });
}

/**
 * Which models the configured key may use. Only fetched when asked for, since
 * it is a live call out to the provider.
 */
export function useAiModels(enabled = false) {
  return useQuery({
    queryKey: ["ai", "models"],
    queryFn: () => api.get<AiModels>("/ai/models"),
    enabled,
    retry: false,
    staleTime: 5 * 60_000,
  });
}

export function useAiExtractions(personIds: PersonIds, limit = 25) {
  return useQuery({
    queryKey: ["ai", "extractions", scope(personIds), limit],
    queryFn: () =>
      api.get<AiExtraction[]>("/ai/extractions", {
        ...personParams(personIds),
        limit,
      }),
  });
}

export function useAiExtraction(id: string | null) {
  return useQuery({
    queryKey: ["ai", "extraction", id ?? ""],
    queryFn: () => api.get<AiExtraction>(`/ai/extractions/${id}`),
    enabled: Boolean(id),
  });
}

/** Read email for interview-shaped calendar events and fill in the details. */
export function useRunEnrichment(personIds: PersonIds) {
  const invalidate = useInvalidateAll();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown> = {}) =>
      api.post<EnrichSummary>("/ai/enrich", { limit: 10, ...body }, personParams(personIds)),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["ai"] });
      invalidate();
    },
  });
}

export function useUndoExtraction() {
  const invalidate = useInvalidateAll();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<AiExtraction>(`/ai/extractions/${id}/undo`),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["ai"] });
      invalidate();
    },
  });
}

export function useApplyExtraction() {
  const invalidate = useInvalidateAll();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<AiExtraction>(`/ai/extractions/${id}/apply`),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["ai"] });
      invalidate();
    },
  });
}
