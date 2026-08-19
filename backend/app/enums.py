"""Central enum definitions.

Everything is a `str` enum so values serialise directly to JSON and store as TEXT
in SQLite. Values are stable wire identifiers — never rename one without a
migration, because they are persisted.
"""

from __future__ import annotations

from enum import StrEnum

# --------------------------------------------------------------------------
# People
# --------------------------------------------------------------------------


class UserRole(StrEnum):
    """Who can change what.

    `ADMIN` may do anything in the workspace. `USER` may edit only the profiles
    assigned to them and reads everything else.
    """

    ADMIN = "admin"
    USER = "user"


class PersonStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------


class ApplicationStatus(StrEnum):
    SAVED = "saved"
    APPLIED = "applied"
    RECRUITER_CONTACTED = "recruiter_contacted"
    SCREENING = "screening"
    INTERVIEWING = "interviewing"
    WAITING_FOR_FEEDBACK = "waiting_for_feedback"
    SCHEDULING_NEXT_ROUND = "scheduling_next_round"
    FINAL_ROUND = "final_round"
    OFFER = "offer"
    NEGOTIATING = "negotiating"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    ON_HOLD = "on_hold"
    GHOSTED = "ghosted"
    ARCHIVED = "archived"


class PipelineColumn(StrEnum):
    """The six Kanban columns from the spec."""

    APPLIED = "applied"
    SCREENING = "screening"
    INTERVIEWING = "interviewing"
    FINAL = "final"
    OFFER = "offer"
    CLOSED = "closed"


#: Which pipeline column a given application status lives in.
STATUS_TO_COLUMN: dict[ApplicationStatus, PipelineColumn] = {
    ApplicationStatus.SAVED: PipelineColumn.APPLIED,
    ApplicationStatus.APPLIED: PipelineColumn.APPLIED,
    ApplicationStatus.RECRUITER_CONTACTED: PipelineColumn.APPLIED,
    ApplicationStatus.SCREENING: PipelineColumn.SCREENING,
    ApplicationStatus.INTERVIEWING: PipelineColumn.INTERVIEWING,
    ApplicationStatus.WAITING_FOR_FEEDBACK: PipelineColumn.INTERVIEWING,
    ApplicationStatus.SCHEDULING_NEXT_ROUND: PipelineColumn.INTERVIEWING,
    ApplicationStatus.FINAL_ROUND: PipelineColumn.FINAL,
    ApplicationStatus.OFFER: PipelineColumn.OFFER,
    ApplicationStatus.NEGOTIATING: PipelineColumn.OFFER,
    ApplicationStatus.ACCEPTED: PipelineColumn.OFFER,
    ApplicationStatus.REJECTED: PipelineColumn.CLOSED,
    ApplicationStatus.WITHDRAWN: PipelineColumn.CLOSED,
    ApplicationStatus.ON_HOLD: PipelineColumn.CLOSED,
    ApplicationStatus.GHOSTED: PipelineColumn.CLOSED,
    ApplicationStatus.ARCHIVED: PipelineColumn.CLOSED,
}

#: The status assigned when a card is dragged into a column. Dropping into a
#: column whose current status already maps there is a no-op (see service).
COLUMN_DEFAULT_STATUS: dict[PipelineColumn, ApplicationStatus] = {
    PipelineColumn.APPLIED: ApplicationStatus.APPLIED,
    PipelineColumn.SCREENING: ApplicationStatus.SCREENING,
    PipelineColumn.INTERVIEWING: ApplicationStatus.INTERVIEWING,
    PipelineColumn.FINAL: ApplicationStatus.FINAL_ROUND,
    PipelineColumn.OFFER: ApplicationStatus.OFFER,
    PipelineColumn.CLOSED: ApplicationStatus.REJECTED,
}

#: Statuses that mean the opportunity is over, one way or another.
TERMINAL_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.ACCEPTED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.GHOSTED,
        ApplicationStatus.ARCHIVED,
    }
)

#: Statuses that count as "active pipeline" on the dashboard metric card.
ACTIVE_STATUSES: frozenset[ApplicationStatus] = frozenset(
    set(ApplicationStatus) - TERMINAL_STATUSES - {ApplicationStatus.SAVED}
)

#: Statuses that represent a live offer.
OFFER_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.OFFER,
        ApplicationStatus.NEGOTIATING,
        ApplicationStatus.ACCEPTED,
    }
)


class WorkMode(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class EmploymentType(StrEnum):
    FULL_TIME = "full_time"
    CONTRACT = "contract"
    PART_TIME = "part_time"
    INTERNSHIP = "internship"
    UNKNOWN = "unknown"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


# --------------------------------------------------------------------------
# Interviews
# --------------------------------------------------------------------------


class InterviewStatus(StrEnum):
    """Where the stage is in its lifecycle. Answers "has it happened yet?"."""

    PLANNED = "planned"  # known to be part of the process, no date yet
    SCHEDULED = "scheduled"  # has a date/time
    COMPLETED = "completed"  # it happened
    CANCELLED = "cancelled"  # called off, will not happen
    RESCHEDULED = "rescheduled"  # moved; a replacement stage/event carries the new time
    NO_SHOW = "no_show"  # nobody showed up


class InterviewOutcome(StrEnum):
    """The verdict. Answers "what was the result?"."""

    PENDING = "pending"  # hasn't happened yet, so there is no verdict
    WAITING = "waiting"  # happened, awaiting the company's decision
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WITHDRAWN = "withdrawn"
    UNKNOWN = "unknown"


#: Only these outcomes are decided results, so only these form the denominator
#: of a pass rate. See `domains/analytics/formulas.py`.
DECIDED_OUTCOMES: frozenset[InterviewOutcome] = frozenset(
    {InterviewOutcome.PASSED, InterviewOutcome.FAILED}
)

#: Statuses meaning the interview actually took place.
HELD_STATUSES: frozenset[InterviewStatus] = frozenset(
    {InterviewStatus.COMPLETED, InterviewStatus.NO_SHOW}
)

#: Statuses meaning a real interview was booked or held — the test for whether
#: an application "reached an interview" in the conversion metrics. `PLANNED`
#: is a placeholder in the journey timeline, and `CANCELLED` never happened.
REAL_INTERVIEW_STATUSES: frozenset[InterviewStatus] = frozenset(
    {
        InterviewStatus.SCHEDULED,
        InterviewStatus.COMPLETED,
        InterviewStatus.RESCHEDULED,
        InterviewStatus.NO_SHOW,
    }
)


class InterviewTypeKey(StrEnum):
    """Built-in interview types. Custom types live in the `interview_types` table."""

    RECRUITER_SCREEN = "recruiter_screen"
    HR_SCREEN = "hr_screen"
    HIRING_MANAGER = "hiring_manager"
    TECHNICAL = "technical"
    CODING = "coding"
    MACHINE_LEARNING = "machine_learning"
    SYSTEM_DESIGN = "system_design"
    BEHAVIORAL = "behavioral"
    CULTURE_FIT = "culture_fit"
    PANEL = "panel"
    FINAL = "final"
    ONLINE_ASSESSMENT = "online_assessment"
    TAKE_HOME = "take_home"
    OTHER = "other"


#: Display labels and ordering for the built-in types.
BUILTIN_INTERVIEW_TYPES: list[tuple[str, str]] = [
    (InterviewTypeKey.RECRUITER_SCREEN.value, "Recruiter Screen"),
    (InterviewTypeKey.HR_SCREEN.value, "HR Screen"),
    (InterviewTypeKey.HIRING_MANAGER.value, "Hiring Manager"),
    (InterviewTypeKey.TECHNICAL.value, "Technical"),
    (InterviewTypeKey.CODING.value, "Coding"),
    (InterviewTypeKey.MACHINE_LEARNING.value, "Machine Learning"),
    (InterviewTypeKey.SYSTEM_DESIGN.value, "System Design"),
    (InterviewTypeKey.BEHAVIORAL.value, "Behavioral"),
    (InterviewTypeKey.CULTURE_FIT.value, "Culture Fit"),
    (InterviewTypeKey.PANEL.value, "Panel"),
    (InterviewTypeKey.FINAL.value, "Final"),
    (InterviewTypeKey.ONLINE_ASSESSMENT.value, "Online Assessment"),
    (InterviewTypeKey.TAKE_HOME.value, "Take-Home Assignment"),
    (InterviewTypeKey.OTHER.value, "Other"),
]

#: Short badge labels — used on calendar chips and pipeline cards where the
#: full label will not fit. Falls back to the full label for custom types.
INTERVIEW_TYPE_SHORT_LABELS: dict[str, str] = {
    InterviewTypeKey.RECRUITER_SCREEN.value: "Recruiter",
    InterviewTypeKey.HR_SCREEN.value: "HR",
    InterviewTypeKey.HIRING_MANAGER.value: "Hiring Mgr",
    InterviewTypeKey.TECHNICAL.value: "Technical",
    InterviewTypeKey.CODING.value: "Coding",
    InterviewTypeKey.MACHINE_LEARNING.value: "ML",
    InterviewTypeKey.SYSTEM_DESIGN.value: "Sys Design",
    InterviewTypeKey.BEHAVIORAL.value: "Behavioral",
    InterviewTypeKey.CULTURE_FIT.value: "Culture",
    InterviewTypeKey.PANEL.value: "Panel",
    InterviewTypeKey.FINAL.value: "Final",
    InterviewTypeKey.ONLINE_ASSESSMENT.value: "OA",
    InterviewTypeKey.TAKE_HOME.value: "Take-Home",
    InterviewTypeKey.OTHER.value: "Other",
}

#: Types that count toward the "final round" metric.
FINAL_ROUND_TYPES: frozenset[str] = frozenset(
    {InterviewTypeKey.FINAL.value, InterviewTypeKey.HIRING_MANAGER.value}
)

#: Types that count as a "technical" interview for the technical pass rate.
TECHNICAL_TYPES: frozenset[str] = frozenset(
    {
        InterviewTypeKey.TECHNICAL.value,
        InterviewTypeKey.CODING.value,
        InterviewTypeKey.SYSTEM_DESIGN.value,
        InterviewTypeKey.MACHINE_LEARNING.value,
        InterviewTypeKey.ONLINE_ASSESSMENT.value,
        InterviewTypeKey.TAKE_HOME.value,
    }
)

#: Screening rounds. These DO count as interviews in every conversion metric
#: (see domains/analytics/formulas.py); the flag exists because screens are
#: conventionally unnumbered, so they are skipped when auto-assigning round
#: numbers.
SCREENING_TYPES: frozenset[str] = frozenset(
    {InterviewTypeKey.RECRUITER_SCREEN.value, InterviewTypeKey.HR_SCREEN.value}
)


# --------------------------------------------------------------------------
# Follow-ups
# --------------------------------------------------------------------------


class FollowUpStatus(StrEnum):
    """Stored status.

    Note that `due_today` and `overdue` are deliberately NOT stored — they are
    derived from `due_date` at read time (see `FollowUpComputedStatus`). Storing
    them would require a nightly job to keep rows accurate and they would go
    stale the moment the clock rolled over.
    """

    OPEN = "open"
    COMPLETED = "completed"
    SNOOZED = "snoozed"
    CANCELLED = "cancelled"


class FollowUpComputedStatus(StrEnum):
    """Status as presented to the UI, derived from stored status + due date."""

    OPEN = "open"
    DUE_TODAY = "due_today"
    OVERDUE = "overdue"
    COMPLETED = "completed"
    SNOOZED = "snoozed"
    CANCELLED = "cancelled"


class FollowUpRule(StrEnum):
    """Identifies which automation proposed a follow-up, so the same rule does
    not fire twice for the same subject."""

    INTERVIEW_COMPLETED = "interview_completed"
    FOLLOW_UP_CHAIN = "follow_up_chain"
    WAITING_TOO_LONG = "waiting_too_long"
    NO_ACTIVITY = "no_activity"
    MANUAL = "manual"


# --------------------------------------------------------------------------
# Calendar
# --------------------------------------------------------------------------


class CalendarProvider(StrEnum):
    GOOGLE = "google"
    MICROSOFT = "microsoft"


class ConnectionStatus(StrEnum):
    CONNECTED = "connected"
    EXPIRED = "expired"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class EventSource(StrEnum):
    EXTERNAL_PROVIDER = "external_provider"
    APP_CREATED = "app_created"


class EventStatus(StrEnum):
    CONFIRMED = "confirmed"
    TENTATIVE = "tentative"
    CANCELLED = "cancelled"


class EventClassification(StrEnum):
    """How an imported calendar event has been triaged.

    Imported events start `UNCLASSIFIED`. Nothing is treated as an interview
    until a human says so (spec §7, §8).
    """

    UNCLASSIFIED = "unclassified"
    NORMAL_MEETING = "normal_meeting"
    INTERVIEW = "interview"
    RECRUITER_CALL = "recruiter_call"
    ASSESSMENT = "assessment"
    PERSONAL = "personal"
    IGNORED = "ignored"


class EmailProvider(StrEnum):
    """Mail backends. Gmail uses OAuth; everything else goes over IMAP, which
    is the only route Yahoo still offers third-party apps."""

    GMAIL = "gmail"
    MICROSOFT = "microsoft"
    IMAP = "imap"


class ExtractionStatus(StrEnum):
    """Lifecycle of one AI enrichment run."""

    PENDING = "pending"      # queued, not yet sent to the model
    NO_MATCHES = "no_matches"  # no related email found, nothing to read
    EXTRACTED = "extracted"  # model returned a result, not acted on
    APPLIED = "applied"      # records were created or updated from it
    SUGGESTED = "suggested"  # confidence too low to act; awaiting the user
    UNDONE = "undone"        # the user reversed it
    FAILED = "failed"        # the model or transport errored


class SyncState(StrEnum):
    """Write-back state for an app-created interview event."""

    LOCAL_ONLY = "local_only"  # not pushed to any provider
    SYNCED = "synced"  # in sync with the provider copy
    PENDING = "pending"  # local change waiting to be pushed
    FAILED = "failed"  # last push attempt failed


# --------------------------------------------------------------------------
# Activity log
# --------------------------------------------------------------------------


class ActivityType(StrEnum):
    APPLICATION_CREATED = "application_created"
    APPLICATION_UPDATED = "application_updated"
    APPLICATION_STATUS_CHANGED = "application_status_changed"
    APPLICATION_ARCHIVED = "application_archived"
    APPLICATION_RESTORED = "application_restored"
    STAGE_CREATED = "stage_created"
    STAGE_STATUS_CHANGED = "stage_status_changed"
    STAGE_OUTCOME_CHANGED = "stage_outcome_changed"
    STAGE_RESCHEDULED = "stage_rescheduled"
    STAGE_DELETED = "stage_deleted"
    FOLLOW_UP_CREATED = "follow_up_created"
    FOLLOW_UP_COMPLETED = "follow_up_completed"
    FOLLOW_UP_SNOOZED = "follow_up_snoozed"
    FOLLOW_UP_CANCELLED = "follow_up_cancelled"
    PERSON_CREATED = "person_created"
    PERSON_UPDATED = "person_updated"
    PERSON_ARCHIVED = "person_archived"
    PERSON_RESTORED = "person_restored"
    CALENDAR_CONNECTED = "calendar_connected"
    CALENDAR_DISCONNECTED = "calendar_disconnected"
    CALENDAR_SYNCED = "calendar_synced"
    CALENDAR_EVENT_LINKED = "calendar_event_linked"
    CALENDAR_EVENT_CLASSIFIED = "calendar_event_classified"
    NOTE_ADDED = "note_added"
    #: Sign-ins with the recovery password, role changes, account creation. Kept
    #: in the same log so an administrator has one place to look, but tagged so
    #: it can be filtered out of a person's own timeline.
    SECURITY_EVENT = "security_event"
