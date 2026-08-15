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
  offers: number;
  accepted: number;
  rejected: number;
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

export interface Analytics {
  period: { key: string; label: string; start: string | null; end: string | null };
  person_ids: string[];
  volume: VolumeCounts;
  conversions: ConversionMetrics;
  by_type: TypePerformance[];
  funnel: FunnelStep[];
  comparison: PersonComparisonRow[];
  trend: TimeSeriesPoint[];
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

export interface AuthUser {
  id: string;
  username: string;
  display_name: string;
  email: string | null;
  workspace_id: string;
}

// --------------------------------------------------------------------------
// Email + AI
// --------------------------------------------------------------------------

export type EmailProviderKey = "gmail" | "imap";

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
