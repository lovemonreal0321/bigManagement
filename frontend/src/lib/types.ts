/**
 * Types mirroring the FastAPI schemas in `backend/app/schemas/`.
 *
 * Kept hand-written rather than generated: the surface is small enough that
 * the extra build step would cost more than it saves, and these carry comments
 * the generator could not.
 */

// --------------------------------------------------------------------------
// Enums (values match the backend string enums exactly)
// --------------------------------------------------------------------------

export const APPLICATION_STATUSES = [
  "saved",
  "applied",
  "recruiter_contacted",
  "screening",
  "interviewing",
  "waiting_for_feedback",
  "scheduling_next_round",
  "final_round",
  "offer",
  "negotiating",
  "accepted",
  "rejected",
  "withdrawn",
  "on_hold",
  "ghosted",
  "archived",
] as const;
export type ApplicationStatus = (typeof APPLICATION_STATUSES)[number];

export const PIPELINE_COLUMNS = [
  "applied",
  "screening",
  "interviewing",
  "final",
  "offer",
  "closed",
] as const;
export type PipelineColumnKey = (typeof PIPELINE_COLUMNS)[number];

export const WORK_MODES = ["remote", "hybrid", "onsite", "unknown"] as const;
export type WorkMode = (typeof WORK_MODES)[number];

export const EMPLOYMENT_TYPES = [
  "full_time",
  "contract",
  "part_time",
  "internship",
  "unknown",
] as const;
export type EmploymentType = (typeof EMPLOYMENT_TYPES)[number];

export const PRIORITIES = ["low", "medium", "high", "urgent"] as const;
export type Priority = (typeof PRIORITIES)[number];

export const INTERVIEW_STATUSES = [
  "planned",
  "scheduled",
  "completed",
  "cancelled",
  "rescheduled",
  "no_show",
] as const;
export type InterviewStatus = (typeof INTERVIEW_STATUSES)[number];

export const INTERVIEW_OUTCOMES = [
  "pending",
  "waiting",
  "passed",
  "failed",
  "cancelled",
  "withdrawn",
  "unknown",
] as const;
export type InterviewOutcome = (typeof INTERVIEW_OUTCOMES)[number];

export const EVENT_CLASSIFICATIONS = [
  "unclassified",
  "normal_meeting",
  "interview",
  "recruiter_call",
  "assessment",
  "personal",
  "ignored",
] as const;
export type EventClassification = (typeof EVENT_CLASSIFICATIONS)[number];

export type FollowUpStatus = "open" | "completed" | "snoozed" | "cancelled";
export type FollowUpComputedStatus =
  | "open"
  | "due_today"
  | "overdue"
  | "completed"
  | "snoozed"
  | "cancelled";

// --------------------------------------------------------------------------
// Core entities
// --------------------------------------------------------------------------

export interface Person {
  id: string;
  name: string;
  display_name: string;
  initials: string;
  color: string;
  avatar_url: string | null;
  email: string | null;
  timezone: string;
  is_active: boolean;
  archived_at: string | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface PersonWithStats extends Person {
  application_count: number;
  active_application_count: number;
  upcoming_interview_count: number;
  open_follow_up_count: number;
  calendar_connection_count: number;
}

export interface NextInterviewSummary {
  stage_id: string;
  stage_name: string;
  stage_badge: string;
  type_key: string;
  type_short_label: string;
  round_number: number | null;
  starts_at: string;
  status: string;
}

export interface Application {
  id: string;
  person_id: string;
  company_name: string;
  job_title: string;
  job_url: string | null;
  location: string | null;
  work_mode: WorkMode;
  employment_type: EmploymentType;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string;
  hourly_rate: number | null;
  source: string | null;
  applied_date: string | null;
  status: ApplicationStatus;
  priority: Priority;
  notes: string | null;
  resume_version_id: string | null;
  last_activity_at: string;
  archived_at: string | null;
  created_at: string;
  updated_at: string;

  person: Person | null;
  pipeline_column: PipelineColumnKey;
  days_since_activity: number;
  stage_count: number;
  next_interview: NextInterviewSummary | null;
  current_stage_badge: string | null;
  open_follow_up_count: number;
  has_overdue_follow_up: boolean;
}

export interface InterviewEvent {
  id: string;
  interview_stage_id: string;
  calendar_event_id: string | null;
  title: string;
  type_key: string | null;
  type_label: string | null;
  type_short_label: string | null;
  starts_at: string;
  ends_at: string;
  timezone: string | null;
  location: string | null;
  meeting_url: string | null;
  interviewer_names: string | null;
  sequence: number;
  source: string;
  sync_state: string;
  sync_error: string | null;
}

export interface InterviewStage {
  id: string;
  application_id: string;
  round_number: number | null;
  sequence: number;
  name: string;
  type_key: string;
  type_label: string | null;
  type_short_label: string | null;
  /** Pre-rendered "R2 · Technical" tag — shown wherever the stage appears. */
  stage_badge: string | null;
  status: InterviewStatus;
  outcome: InterviewOutcome;
  scheduled_start: string | null;
  scheduled_end: string | null;
  result_date: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  events: InterviewEvent[];
  event_count: number;
}

export interface ApplicationNote {
  id: string;
  application_id: string;
  body: string;
  created_at: string;
  updated_at: string;
}

export interface ApplicationDetail extends Application {
  stages: InterviewStage[];
  notes_log: ApplicationNote[];
}

export interface InterviewType {
  id: string;
  key: string;
  label: string;
  short_label: string;
  is_builtin: boolean;
  is_active: boolean;
  sort_order: number;
  counts_as_technical: boolean;
  counts_as_final: boolean;
  counts_as_screening: boolean;
}

export interface UpcomingInterview {
  stage_id: string;
  event_id: string | null;
  application_id: string;
  person_id: string;
  person_name: string;
  person_color: string;
  person_initials: string;
  company_name: string;
  job_title: string;
  stage_name: string;
  type_key: string;
  type_label: string;
  type_short_label: string;
  round_number: number | null;
  stage_badge: string;
  status: InterviewStatus;
  outcome: InterviewOutcome;
  starts_at: string;
  ends_at: string;
  timezone: string | null;
  meeting_url: string | null;
  location: string | null;
}

// --------------------------------------------------------------------------
// Pipeline
// --------------------------------------------------------------------------

export interface PipelineCard {
  id: string;
  person_id: string;
  person_name: string;
  person_color: string;
  person_initials: string;
  company_name: string;
  job_title: string;
  status: ApplicationStatus;
  priority: Priority;
  current_stage_badge: string | null;
  next_interview: NextInterviewSummary | null;
  days_since_activity: number;
  open_follow_up_count: number;
  has_overdue_follow_up: boolean;
}

export interface PipelineColumn {
  key: PipelineColumnKey;
  label: string;
  count: number;
  cards: PipelineCard[];
}

export interface Pipeline {
  columns: PipelineColumn[];
  total: number;
}

// --------------------------------------------------------------------------
// Follow-ups
// --------------------------------------------------------------------------

export interface FollowUp {
  id: string;
  person_id: string;
  application_id: string;
  interview_stage_id: string | null;
  title: string;
  reason: string | null;
  due_date: string;
  due_time: string | null;
  status: FollowUpStatus;
  priority: Priority;
  completed_at: string | null;
  snoozed_until: string | null;
  notes: string | null;
  auto_generated: boolean;
  rule_key: string;
  created_at: string;
  updated_at: string;

  computed_status: FollowUpComputedStatus;
  days_overdue: number | null;
  days_until_due: number | null;
  due_description: string;
  person_name: string;
  person_color: string;
  person_initials: string;
  company_name: string;
  job_title: string;
  stage_badge: string | null;
}

export interface FollowUpBoard {
  overdue: FollowUp[];
  due_today: FollowUp[];
  upcoming: FollowUp[];
  snoozed: FollowUp[];
  completed: FollowUp[];
  counts: Record<string, number>;
}

export interface FollowUpSuggestion {
  rule_key: string;
  application_id: string;
  interview_stage_id: string | null;
  person_id: string;
  title: string;
  reason: string;
  suggested_due_date: string;
}

// --------------------------------------------------------------------------
// Calendar
// --------------------------------------------------------------------------

export interface CalendarFeedEvent {
  id: string;
  kind: "interview" | "external";
  person_id: string;
  person_name: string;
  person_color: string;
  person_initials: string;
  title: string;
  starts_at: string;
  ends_at: string;
  timezone: string | null;
  is_all_day: boolean;
  location: string | null;
  meeting_url: string | null;
  application_id: string | null;
  interview_stage_id: string | null;
  interview_event_id: string | null;
  calendar_event_id: string | null;
  company_name: string | null;
  job_title: string | null;
  stage_badge: string | null;
  type_key: string | null;
  type_label: string | null;
  type_short_label: string | null;
  round_number: number | null;
  stage_status: InterviewStatus | null;
  stage_outcome: InterviewOutcome | null;
  classification: EventClassification | null;
  detection_score: number;
  is_suggestion: boolean;
  /** Whether this block feeds the interview numbers. */
  counts_as_interview: boolean;
  /** Counts as an interview but has no application behind it. */
  needs_application: boolean;
}

export interface ScheduleConflict {
  person_id: string;
  person_name: string;
  person_color: string;
  first_title: string;
  first_start: string;
  first_end: string;
  second_title: string;
  second_start: string;
  second_end: string;
  overlap_minutes: number;
}

export interface CalendarFeed {
  start: string;
  end: string;
  events: CalendarFeedEvent[];
  conflicts: ScheduleConflict[];
  person_ids: string[];
}

export interface ExternalCalendar {
  id: string;
  connection_id: string;
  provider_calendar_id: string;
  name: string;
  description: string | null;
  timezone: string | null;
  color: string | null;
  is_primary: boolean;
  is_selected: boolean;
  can_write: boolean;
  last_synced_at: string | null;
}

export interface CalendarConnection {
  id: string;
  person_id: string;
  provider: "google" | "microsoft";
  provider_display_name: string;
  account_email: string | null;
  account_name: string | null;
  status: "connected" | "expired" | "error" | "disconnected";
  last_sync_at: string | null;
  last_sync_error: string | null;
  last_sync_error_at: string | null;
  sync_window_past_days: number | null;
  sync_window_future_days: number | null;
  created_at: string;
  calendars: ExternalCalendar[];
  person_name: string;
  person_color: string;
  person_initials: string;
}

export interface ProviderInfo {
  key: string;
  display_name: string;
  is_configured: boolean;
  missing_settings: string[];
  setup_hint: string | null;
}

export interface SyncResult {
  connection_id: string;
  provider: string;
  calendars_synced: number;
  events_created: number;
  events_updated: number;
  events_deleted: number;
  duplicates_skipped: number;
  interviews_rescheduled: number;
  interviews_cancelled: number;
  suggestions_found: number;
  started_at: string;
  finished_at: string;
  error: string | null;
}

export interface SyncSummary {
  results: SyncResult[];
  total_events: number;
  errors: string[];
}

export interface InterviewSuggestion {
  event_id: string;
  person_id: string;
  person_name: string;
  person_color: string;
  title: string;
  starts_at: string;
  ends_at: string;
  score: number;
  reasons: string[];
  suggested_company: string | null;
  suggested_type: string | null;
  suggested_type_label: string | null;
  suggested_round: number | null;
  meeting_url: string | null;
}

export interface CalendarEventDetail {
  id: string;
  person_id: string;
  external_calendar_id: string | null;
  provider: string | null;
  provider_event_id: string | null;
  title: string;
  description: string | null;
  location: string | null;
  meeting_url: string | null;
  organizer_email: string | null;
  organizer_name: string | null;
  starts_at: string;
  ends_at: string;
  start_timezone: string | null;
  is_all_day: boolean;
  status: string;
  classification: EventClassification;
  classification_locked: boolean;
  source: string;
  detection_score: number;
  detection_reasons: string[] | null;
  detection_dismissed: boolean;
  person_name: string;
  person_color: string;
  person_initials: string;
  calendar_name: string | null;
  interview_stage_id: string | null;
  application_id: string | null;
  company_name: string | null;
  job_title: string | null;
  stage_badge: string | null;
  stage_status: string | null;
  stage_outcome: string | null;
  round_number: number | null;
  type_key: string | null;
  type_label: string | null;
}

// --------------------------------------------------------------------------
// Analytics
// --------------------------------------------------------------------------

export interface Rate {
  numerator: number;
  denominator: number;
  value: number | null;
  percent: number | null;
  is_meaningful: boolean;
}

export interface VolumeCounts {
  applications: number;
  applications_with_interview: number;
  interview_stages: number;
  interviews_held: number;
  passed: number;
  failed: number;
  waiting: number;
  scheduled: number;
  cancelled: number;
  final_rounds: number;
  /** Offers from applications submitted in this period (cohort-anchored). */
  offers: number;
  accepted: number;
  rejected: number;
  /** Offers received during this period, whenever the application was sent. */
  offers_received: number;
  /** Interviews on a connected calendar during this period. */
  calendar_interviews: number;
  /** How many of those have no application behind them. */
  calendar_interviews_unlinked: number;
}

export interface ConversionMetrics {
  application_to_interview: Rate;
  first_to_next_round: Rate;
  interview_pass_rate: Rate;
  technical_pass_rate: Rate;
  final_to_offer: Rate;
  application_to_offer: Rate;
  offer_acceptance: Rate;
}

export interface TypePerformance {
  type_key: string;
  label: string;
  short_label: string;
  passed: number;
  failed: number;
  total_decided: number;
  scheduled: number;
  waiting: number;
  rate: Rate;
}

export interface FunnelStep {
  key: string;
  label: string;
  count: number;
  conversion_from_previous: Rate | null;
  conversion_from_start: Rate | null;
}

export interface PersonComparisonRow {
  person_id: string;
  person_name: string;
  person_color: string;
  person_initials: string;
  applications: number;
  interviews_held: number;
  interview_stages: number;
  pass_rate: Rate;
  final_rounds: number;
  offers: number;
  accepted: number;
}

export interface TimeSeriesPoint {
  bucket: string;
  applications: number;
  interviews: number;
  offers: number;
}

export interface JobOutcome {
  jobs_started: number;
  jobs_ended: number;
  offers_open: number;
  live_jobs: number;
  /** Live jobs only, gross. An offer is not income. */
  total_annual: number;
  currency: string;
}

export interface Analytics {
  period: { key: string; label: string; start: string | null; end: string | null };
  person_ids: string[];
  volume: VolumeCounts;
  conversions: ConversionMetrics;
  by_type: TypePerformance[];
  funnel: FunnelStep[];
  comparison: PersonComparisonRow[];
  trend: TimeSeriesPoint[];
  jobs: JobOutcome | null;
  notes: Record<string, string>;
}

export interface WorkloadPerson {
  person_id: string;
  person_name: string;
  person_color: string;
  person_initials: string;
  interview_count: number;
  busiest_day: string | null;
  busiest_day_count: number;
}

export interface WorkloadDay {
  day: string;
  person_id: string;
  person_name: string;
  person_color: string;
  count: number;
  is_heavy: boolean;
}

export interface Workload {
  start: string;
  end: string;
  per_person: WorkloadPerson[];
  heavy_days: WorkloadDay[];
  conflicts: ScheduleConflict[];
  heavy_day_threshold: number;
}

// --------------------------------------------------------------------------
// Dashboard + activity
// --------------------------------------------------------------------------

export interface MetricCard {
  key: string;
  label: string;
  value: number;
  hint: string | null;
  href: string | null;
}

export interface AttentionItem {
  id: string;
  kind:
    | "overdue_follow_up"
    | "awaiting_result"
    | "upcoming_interview"
    | "waiting_too_long"
    | "no_activity"
    | "scheduling_conflict";
  severity: "high" | "medium" | "low";
  person_id: string;
  person_name: string;
  person_color: string;
  person_initials: string;
  company_name: string;
  job_title: string | null;
  headline: string;
  detail: string;
  application_id: string | null;
  interview_stage_id: string | null;
  follow_up_id: string | null;
  stage_badge: string | null;
  due_date: string | null;
  happens_at: string | null;
  actions: string[];
}

export interface Activity {
  id: string;
  type: string;
  message: string;
  meta: Record<string, unknown> | null;
  person_id: string | null;
  application_id: string | null;
  interview_stage_id: string | null;
  follow_up_id: string | null;
  created_at: string;
  person_name: string;
  person_color: string;
  person_initials: string;
}

export interface Dashboard {
  person_ids: string[];
  period_key: string;
  metrics: MetricCard[];
  upcoming_interviews: UpcomingInterview[];
  needs_attention: AttentionItem[];
  pipeline: PipelineColumn[];
  performance: PersonComparisonRow[];
  recent_activity: Activity[];
  follow_up_suggestions: FollowUpSuggestion[];
  interview_suggestions: InterviewSuggestion[];
  awaiting_outcome: UpcomingInterview[];
}

// --------------------------------------------------------------------------
// Settings + misc
// --------------------------------------------------------------------------

export interface WorkspaceSettings {
  id: string;
  name: string;
  default_timezone: string;
  week_starts_on: number;
  display_timezone_mode: "workspace" | "person";
  sync_window_past_days: number;
  sync_window_future_days: number;
  auto_detect_interviews: boolean;
  followup_after_interview_business_days: number;
  followup_chain_business_days: number;
  waiting_for_feedback_threshold_days: number;
  no_activity_ghosted_threshold_days: number;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export type UserRole = "admin" | "user";

export interface AuthUser {
  id: string;
  username: string;
  display_name: string;
  email: string | null;
  workspace_id: string;
  role: UserRole;
  is_active: boolean;
  must_change_password: boolean;
  /** Jobs carry salary, so they are hidden unless an admin grants this. */
  can_view_jobs: boolean;
  last_login_at: string | null;
  /**
   * Profiles this user may edit. Always empty for an admin, who may edit
   * everyone — check the role before reading this as "nothing".
   */
  assigned_person_ids: string[];
}

export interface UserCreatePayload {
  username: string;
  password: string;
  display_name?: string;
  email?: string | null;
  role?: UserRole;
  person_ids?: string[];
  can_view_jobs?: boolean;
}

export interface UserUpdatePayload {
  display_name?: string;
  email?: string | null;
  role?: UserRole;
  is_active?: boolean;
  can_view_jobs?: boolean;
}

// --------------------------------------------------------------------------
// Email + AI
// --------------------------------------------------------------------------

export type EmailProviderKey = "gmail" | "microsoft" | "imap";

export interface EmailAccount {
  id: string;
  person_id: string;
  provider: EmailProviderKey;
  provider_display_name: string;
  address: string;
  display_name: string | null;
  status: "connected" | "expired" | "error" | "disconnected";
  last_used_at: string | null;
  last_error: string | null;
  last_error_at: string | null;
  imap_host: string | null;
  imap_folders: string[] | null;
  created_at: string;
  person_name: string;
  person_color: string;
  person_initials: string;
}

export interface EmailProviderInfo {
  key: EmailProviderKey;
  display_name: string;
  is_configured: boolean;
  requires_app_password: boolean;
  missing_settings: string[];
  setup_hint: string | null;
}

export interface ImapHostSuggestion {
  host: string | null;
  port: number;
  folders: string[];
  known_provider: boolean;
  hint: string | null;
}

export interface EmailMessagePreview {
  id: string;
  subject: string | null;
  from_address: string | null;
  from_name: string | null;
  sent_at: string | null;
  match_score: number;
  match_reasons: string[] | null;
  body_excerpt: string | null;
}

export type ExtractionStatus =
  | "pending"
  | "no_matches"
  | "extracted"
  | "applied"
  | "suggested"
  | "undone"
  | "failed";

export interface AiExtraction {
  id: string;
  person_id: string | null;
  calendar_event_id: string | null;
  status: ExtractionStatus;
  confidence: number;
  result: Record<string, unknown> | null;
  reasoning: string | null;
  error: string | null;
  model: string | null;
  tokens_used: number;
  message_count: number;
  created_application_id: string | null;
  created_stage_id: string | null;
  linked_existing_application: boolean;
  undone_at: string | null;
  created_at: string;
  person_name: string;
  person_color: string;
  person_initials: string;
  event_title: string | null;
  event_starts_at: string | null;
  company_name: string | null;
  job_title: string | null;
  stage_badge: string | null;
  is_undoable: boolean;
  messages: EmailMessagePreview[];
}

export interface EnrichSummary {
  processed: number;
  applied: number;
  suggested: number;
  skipped: number;
  failed: number;
  tokens_used: number;
  extractions: AiExtraction[];
  errors: string[];
}

export interface AiStatus {
  enabled: boolean;
  configured: boolean;
  model: string;
  base_url: string;
  auto_create_confidence: number;
  email_accounts: number;
  setup_hint: string | null;
}

export interface AiModels {
  models: string[];
  current: string;
  /** False when `current` is not in `models` — the cause of "model not found". */
  current_is_available: boolean;
}

// --------------------------------------------------------------------------
// Sheet view
// --------------------------------------------------------------------------

export interface SheetRow {
  id: string;
  person_id: string;
  applied_date: string | null;
  company_name: string;
  job_title: string;
  job_url: string | null;
  status: ApplicationStatus;
  is_archived: boolean;
  /** Other rows on this sheet pointing at the same posting. */
  duplicate_of: string[];
  duplicate_note: string | null;
}

export interface SheetDay {
  /** `null` is the "no date recorded" bucket, pinned to the bottom. */
  date: string | null;
  label: string;
  count: number;
  rows: SheetRow[];
}

export interface SheetTab {
  person_id: string;
  name: string;
  initials: string;
  color: string;
  total: number;
  can_edit: boolean;
}

export interface ApplicationSheet {
  tabs: SheetTab[];
  person_id: string | null;
  can_edit: boolean;
  days: SheetDay[];
  /** Rows after the search; `total` ignores it, so the tabs hold still. */
  matched: number;
  total: number;
  busiest_day: string | null;
  busiest_day_count: number;
  /** The single day being shown, or `null` for every day. */
  day: string | null;
  /** A day was asked for but the search overrode it and looked everywhere. */
  search_ignored_day: boolean;
}

/** One pasted row. Only the company is required. */
export interface BulkApplicationRow {
  company_name: string;
  job_title?: string | null;
  job_url?: string | null;
  applied_date?: string | null;
}

export interface BulkApplicationResult {
  created: number;
  application_ids: string[];
}

// --------------------------------------------------------------------------
// Interview search — finding a past round to hang a later one off
// --------------------------------------------------------------------------

export interface InterviewSearchResult {
  stage_id: string;
  application_id: string;
  person_id: string;
  company_name: string;
  job_title: string;
  stage_name: string;
  stage_badge: string;
  type_key: string;
  round_number: number | null;
  sequence: number;
  status: InterviewStatus;
  outcome: InterviewOutcome;
  scheduled_start: string | null;
  result_date: string | null;
  event_count: number;
  /** The round a following interview would take on this application. */
  next_round_number: number;
}

// --------------------------------------------------------------------------
// Jobs
// --------------------------------------------------------------------------

export const JOB_STATUSES = [
  "offered",
  "accepted",
  "active",
  "ended",
  "declined",
] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];

export const JOB_TYPES = [
  "full_time",
  "part_time",
  "contract",
  "freelance",
  "internship",
  "temporary",
] as const;
export type JobType = (typeof JOB_TYPES)[number];

export const JOB_END_REASONS = [
  "resigned",
  "laid_off",
  "contract_ended",
  "terminated",
  "other",
] as const;
export type JobEndReason = (typeof JOB_END_REASONS)[number];

export const SALARY_TYPES = ["annual", "hourly"] as const;
export type SalaryType = (typeof SALARY_TYPES)[number];

export const PAY_PERIODS = [
  "weekly",
  "biweekly",
  "semimonthly",
  "monthly",
] as const;
export type PayPeriod = (typeof PAY_PERIODS)[number];

export interface PayDate {
  date: string;
  amount: number | null;
  is_next: boolean;
}

export interface Job {
  id: string;
  person_id: string;
  workspace_id: string;
  company_name: string;
  title: string;
  job_type: JobType;
  status: JobStatus;
  location: string | null;

  offered_date: string | null;
  start_date: string | null;
  end_date: string | null;
  end_reason: JobEndReason | null;
  end_note: string | null;

  salary_type: SalaryType;
  annual_amount: number | null;
  hourly_amount: number | null;
  currency: string;
  hours_per_week: number;
  weeks_per_year: number;

  pay_period: PayPeriod;
  first_pay_date: string | null;

  application_id: string | null;
  interview_stage_id: string | null;
  notes: string | null;
  created_at: string | null;

  person_name: string;
  person_color: string;
  person_initials: string;
  /** One cheque, gross. Net would need a tax position this app does not know. */
  gross_per_paycheck: number | null;
  upcoming_pay_dates: PayDate[];
  next_pay_date: string | null;
  tenure_days: number | null;
  is_live: boolean;
  application_company: string | null;
  stage_badge: string | null;
}

export interface JobPersonSummary {
  person_id: string;
  person_name: string;
  person_color: string;
  person_initials: string;
  live_count: number;
  total_annual: number;
  next_pay_date: string | null;
}

/** An application that reached an offer with no job recorded against it. */
export interface PendingOffer {
  application_id: string;
  person_id: string;
  person_name: string;
  person_color: string;
  person_initials: string;
  company_name: string;
  job_title: string;
  status: string;
  offered_date: string | null;
  interview_stage_id: string | null;
}

export interface JobSummary {
  live_count: number;
  offered_count: number;
  ended_count: number;
  /** Live jobs only — an offer is not income, and an ended job is not either. */
  total_annual: number;
  currency: string;
  next_pay_date: string | null;
  next_pay_amount: number | null;
  next_pay_job_id: string | null;
  by_person: JobPersonSummary[];
}
