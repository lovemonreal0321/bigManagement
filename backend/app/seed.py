"""Demo seed data (spec §53).

Everything is anchored to *today*, so the dashboard, calendar and analytics all
look alive whenever the seed is run rather than pointing at a fixed date in the
past. Run with:

    python -m app.seed          # wipe demo data and reseed
    python -m app.seed --keep   # only seed if the workspace is empty

The dataset deliberately includes passed, failed, waiting, cancelled and
scheduled interviews, a multi-event final loop, overdue/due-today/upcoming
follow-ups, two live offers and a couple of unclassified "imported" calendar
events, so every screen has something real to render.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, select

from app.core.database import session_scope
from app.core.timeutils import get_tz, utcnow
from app.domains.auth.service import ensure_bootstrap
from app.domains.calendar import detection
from app.enums import (
    ActivityType,
    ApplicationStatus,
    EmploymentType,
    EventClassification,
    EventSource,
    FollowUpRule,
    FollowUpStatus,
    InterviewOutcome,
    InterviewStatus,
    InterviewTypeKey,
    Priority,
    WorkMode,
)
from app.models import (
    Activity,
    Application,
    ApplicationNote,
    CalendarEvent,
    FollowUp,
    InterviewEvent,
    InterviewStage,
    Person,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("seed")


# --------------------------------------------------------------------------
# Declarative dataset
# --------------------------------------------------------------------------


@dataclass
class SeedSlot:
    """One time block inside a stage."""

    label: str
    hour: int
    minute: int = 0
    minutes: int = 60
    type_key: str | None = None


@dataclass
class SeedStage:
    type_key: str
    #: Days from today. Negative is in the past.
    day_offset: int | None
    status: InterviewStatus
    outcome: InterviewOutcome
    round_number: int | None = None
    hour: int = 10
    minutes: int = 60
    notes: str | None = None
    slots: list[SeedSlot] = field(default_factory=list)


@dataclass
class SeedApplication:
    person: str
    company: str
    title: str
    status: ApplicationStatus
    applied_days_ago: int
    location: str
    work_mode: WorkMode
    source: str
    salary: tuple[int, int] | None = None
    priority: Priority = Priority.MEDIUM
    notes: str | None = None
    stages: list[SeedStage] = field(default_factory=list)
    employment_type: EmploymentType = EmploymentType.FULL_TIME


PEOPLE = [
    {
        "name": "John Carter",
        "display_name": "John",
        "initials": "JC",
        "color": "#2563eb",
        "email": "john@example.com",
        "timezone": "America/New_York",
    },
    {
        "name": "David Okafor",
        "display_name": "David",
        "initials": "DO",
        "color": "#ea580c",
        "email": "david@example.com",
        "timezone": "America/Chicago",
    },
    {
        "name": "Sarah Lindqvist",
        "display_name": "Sarah",
        "initials": "SL",
        "color": "#0d9488",
        "email": "sarah@example.com",
        # The app offers PST/CST/EST only, so the demo cast spans exactly those
        # three — Sarah works remotely from the west coast.
        "timezone": "America/Los_Angeles",
    },
]


T = InterviewTypeKey
S = InterviewStatus
Out = InterviewOutcome


APPLICATIONS: list[SeedApplication] = [
    # ---- John ------------------------------------------------------------
    SeedApplication(
        person="John",
        company="Amazon",
        title="Senior AI Engineer",
        status=ApplicationStatus.INTERVIEWING,
        applied_days_ago=26,
        location="Seattle, WA",
        work_mode=WorkMode.REMOTE,
        source="LinkedIn",
        salary=(180_000, 220_000),
        priority=Priority.HIGH,
        notes=(
            "Job posting leans hard on AWS, LLM systems, Python and production "
            "ML. Recruiter mentioned the team ships weekly."
        ),
        stages=[
            SeedStage(T.RECRUITER_SCREEN.value, -21, S.COMPLETED, Out.PASSED, None, 11),
            SeedStage(T.HIRING_MANAGER.value, -16, S.COMPLETED, Out.PASSED, 1, 14),
            SeedStage(T.TECHNICAL.value, 3, S.SCHEDULED, Out.PENDING, 2, 10),
        ],
    ),
    SeedApplication(
        person="John",
        company="NVIDIA",
        title="Deep Learning Engineer",
        status=ApplicationStatus.FINAL_ROUND,
        applied_days_ago=40,
        location="Santa Clara, CA",
        work_mode=WorkMode.HYBRID,
        source="Referral",
        salary=(200_000, 250_000),
        priority=Priority.HIGH,
        stages=[
            SeedStage(T.RECRUITER_SCREEN.value, -35, S.COMPLETED, Out.PASSED, None, 9),
            SeedStage(T.TECHNICAL.value, -28, S.COMPLETED, Out.PASSED, 1, 13),
            SeedStage(T.MACHINE_LEARNING.value, -18, S.COMPLETED, Out.PASSED, 2, 15),
            # A four-slot final loop — one stage, several calendar events (§16).
            SeedStage(
                T.FINAL.value,
                4,
                S.SCHEDULED,
                Out.PENDING,
                3,
                slots=[
                    SeedSlot("Behavioral", 9, 0, 60, T.BEHAVIORAL.value),
                    SeedSlot("System Design", 10, 0, 75, T.SYSTEM_DESIGN.value),
                    SeedSlot("ML Technical", 11, 30, 60, T.MACHINE_LEARNING.value),
                    SeedSlot("Hiring Manager", 14, 0, 45, T.HIRING_MANAGER.value),
                ],
            ),
        ],
    ),
    SeedApplication(
        person="John",
        company="Meta",
        title="Machine Learning Engineer",
        status=ApplicationStatus.WAITING_FOR_FEEDBACK,
        applied_days_ago=33,
        location="Menlo Park, CA",
        work_mode=WorkMode.ONSITE,
        source="Company Site",
        salary=(190_000, 240_000),
        stages=[
            SeedStage(T.RECRUITER_SCREEN.value, -27, S.COMPLETED, Out.PASSED, None, 10),
            SeedStage(T.CODING.value, -9, S.COMPLETED, Out.WAITING, 1, 13,
                      notes="Two medium graph problems. Solved both, ran out of time on follow-ups."),
        ],
    ),
    SeedApplication(
        person="John",
        company="Guidehouse",
        title="Lead Data Scientist",
        status=ApplicationStatus.REJECTED,
        applied_days_ago=52,
        location="Washington, DC",
        work_mode=WorkMode.HYBRID,
        source="Indeed",
        salary=(150_000, 175_000),
        stages=[
            SeedStage(T.HR_SCREEN.value, -45, S.COMPLETED, Out.PASSED, None, 11),
            SeedStage(T.TECHNICAL.value, -38, S.COMPLETED, Out.FAILED, 1, 15,
                      notes="Struggled on the SQL window-function section."),
        ],
    ),
    SeedApplication(
        person="John",
        company="Stripe",
        title="ML Platform Engineer",
        status=ApplicationStatus.GHOSTED,
        applied_days_ago=61,
        location="Remote",
        work_mode=WorkMode.REMOTE,
        source="LinkedIn",
        stages=[
            SeedStage(T.RECRUITER_SCREEN.value, -54, S.COMPLETED, Out.WAITING, None, 12),
        ],
    ),
    SeedApplication(
        person="John",
        company="Anthropic",
        title="Research Engineer",
        status=ApplicationStatus.APPLIED,
        applied_days_ago=5,
        location="Remote",
        work_mode=WorkMode.REMOTE,
        source="Company Site",
        priority=Priority.HIGH,
        salary=(230_000, 300_000),
    ),
    # ---- David -----------------------------------------------------------
    SeedApplication(
        person="David",
        company="Microsoft",
        title="Senior Software Engineer",
        status=ApplicationStatus.INTERVIEWING,
        applied_days_ago=22,
        location="Redmond, WA",
        work_mode=WorkMode.HYBRID,
        source="Referral",
        salary=(170_000, 205_000),
        priority=Priority.HIGH,
        stages=[
            SeedStage(T.RECRUITER_SCREEN.value, -18, S.COMPLETED, Out.PASSED, None, 10),
            SeedStage(T.TECHNICAL.value, -7, S.COMPLETED, Out.PASSED, 1, 14),
            SeedStage(T.HIRING_MANAGER.value, 1, S.SCHEDULED, Out.PENDING, 2, 14),
        ],
    ),
    SeedApplication(
        person="David",
        company="Stripe",
        title="Backend Engineer, Payments",
        status=ApplicationStatus.WAITING_FOR_FEEDBACK,
        applied_days_ago=30,
        location="Remote",
        work_mode=WorkMode.REMOTE,
        source="LinkedIn",
        salary=(175_000, 215_000),
        stages=[
            SeedStage(T.RECRUITER_SCREEN.value, -24, S.COMPLETED, Out.PASSED, None, 9),
            SeedStage(T.SYSTEM_DESIGN.value, -11, S.COMPLETED, Out.WAITING, 1, 16),
        ],
    ),
    SeedApplication(
        person="David",
        company="Datadog",
        title="Staff Engineer, Observability",
        status=ApplicationStatus.OFFER,
        applied_days_ago=48,
        location="New York, NY",
        work_mode=WorkMode.HYBRID,
        source="Recruiter Outreach",
        salary=(210_000, 250_000),
        priority=Priority.URGENT,
        notes="Offer verbal on the call; written version expected this week.",
        stages=[
            SeedStage(T.RECRUITER_SCREEN.value, -43, S.COMPLETED, Out.PASSED, None, 10),
            SeedStage(T.TECHNICAL.value, -36, S.COMPLETED, Out.PASSED, 1, 13),
            SeedStage(T.SYSTEM_DESIGN.value, -27, S.COMPLETED, Out.PASSED, 2, 15),
            SeedStage(T.FINAL.value, -12, S.COMPLETED, Out.PASSED, 3, 11),
        ],
    ),
    SeedApplication(
        person="David",
        company="Shopify",
        title="Senior Backend Developer",
        status=ApplicationStatus.REJECTED,
        applied_days_ago=44,
        location="Remote",
        work_mode=WorkMode.REMOTE,
        source="Indeed",
        stages=[
            SeedStage(T.ONLINE_ASSESSMENT.value, -39, S.COMPLETED, Out.FAILED, None, 18),
        ],
    ),
    SeedApplication(
        person="David",
        company="Cloudflare",
        title="Systems Engineer",
        status=ApplicationStatus.SCREENING,
        applied_days_ago=9,
        location="Austin, TX",
        work_mode=WorkMode.HYBRID,
        source="Company Site",
        salary=(160_000, 195_000),
        stages=[
            SeedStage(T.RECRUITER_SCREEN.value, 2, S.SCHEDULED, Out.PENDING, None, 15),
        ],
    ),
    SeedApplication(
        person="David",
        company="Figma",
        title="Product Engineer",
        status=ApplicationStatus.APPLIED,
        applied_days_ago=3,
        location="San Francisco, CA",
        work_mode=WorkMode.ONSITE,
        source="LinkedIn",
    ),
    # ---- Sarah -----------------------------------------------------------
    SeedApplication(
        person="Sarah",
        company="Spotify",
        title="Senior Data Engineer",
        status=ApplicationStatus.ACCEPTED,
        applied_days_ago=58,
        location="Stockholm, Sweden",
        work_mode=WorkMode.HYBRID,
        source="Referral",
        salary=(95_000, 115_000),
        priority=Priority.URGENT,
        notes="Signed. Start date is the first of next month.",
        stages=[
            SeedStage(T.RECRUITER_SCREEN.value, -52, S.COMPLETED, Out.PASSED, None, 10),
            SeedStage(T.TECHNICAL.value, -45, S.COMPLETED, Out.PASSED, 1, 13),
            SeedStage(T.SYSTEM_DESIGN.value, -37, S.COMPLETED, Out.PASSED, 2, 11),
            SeedStage(T.FINAL.value, -25, S.COMPLETED, Out.PASSED, 3, 14),
        ],
    ),
    SeedApplication(
        person="Sarah",
        company="Klarna",
        title="Staff Data Engineer",
        status=ApplicationStatus.FINAL_ROUND,
        applied_days_ago=35,
        location="Stockholm, Sweden",
        work_mode=WorkMode.HYBRID,
        source="LinkedIn",
        salary=(100_000, 125_000),
        priority=Priority.HIGH,
        stages=[
            SeedStage(T.RECRUITER_SCREEN.value, -30, S.COMPLETED, Out.PASSED, None, 9),
            SeedStage(T.TECHNICAL.value, -20, S.COMPLETED, Out.PASSED, 1, 13),
            SeedStage(T.FINAL.value, 6, S.SCHEDULED, Out.PENDING, 2, 10),
        ],
    ),
    SeedApplication(
        person="Sarah",
        company="Booking.com",
        title="Data Platform Engineer",
        status=ApplicationStatus.INTERVIEWING,
        applied_days_ago=19,
        location="Amsterdam, Netherlands",
        work_mode=WorkMode.ONSITE,
        source="Company Site",
        salary=(90_000, 110_000),
        stages=[
            SeedStage(T.HR_SCREEN.value, -14, S.COMPLETED, Out.PASSED, None, 11),
            SeedStage(T.CODING.value, -2, S.COMPLETED, Out.WAITING, 1, 15),
            SeedStage(T.BEHAVIORAL.value, 8, S.SCHEDULED, Out.PENDING, 2, 13),
        ],
    ),
    SeedApplication(
        person="Sarah",
        company="Zalando",
        title="Senior Analytics Engineer",
        status=ApplicationStatus.REJECTED,
        applied_days_ago=41,
        location="Berlin, Germany",
        work_mode=WorkMode.HYBRID,
        source="Indeed",
        stages=[
            SeedStage(T.RECRUITER_SCREEN.value, -36, S.COMPLETED, Out.PASSED, None, 10),
            SeedStage(T.TECHNICAL.value, -29, S.COMPLETED, Out.FAILED, 1, 14),
            SeedStage(T.BEHAVIORAL.value, -27, S.CANCELLED, Out.CANCELLED, 2, 11),
        ],
    ),
    SeedApplication(
        person="Sarah",
        company="Delivery Hero",
        title="Data Engineer",
        status=ApplicationStatus.ON_HOLD,
        applied_days_ago=27,
        location="Berlin, Germany",
        work_mode=WorkMode.REMOTE,
        source="Recruiter Outreach",
        notes="Team paused hiring for the quarter; recruiter will revisit in Q3.",
        stages=[
            SeedStage(T.RECRUITER_SCREEN.value, -22, S.COMPLETED, Out.PASSED, None, 12),
        ],
    ),
    SeedApplication(
        person="Sarah",
        company="Wise",
        title="Senior Data Engineer",
        status=ApplicationStatus.APPLIED,
        applied_days_ago=6,
        location="London, UK",
        work_mode=WorkMode.HYBRID,
        source="LinkedIn",
        salary=(85_000, 105_000),
    ),
]


#: The bulk of any real job search: applications that never turned into an
#: interview. Without these the conversion funnel reads like an 80% hit rate,
#: which would make the analytics page look invented.
#: (person, company, title, status, days ago, source, screen outcome or None)
QUIET_APPLICATIONS: list[tuple[str, str, str, ApplicationStatus, int, str, str | None]] = [
    ("John", "Google", "Senior ML Engineer", ApplicationStatus.REJECTED, 47, "Company Site", None),
    ("John", "Apple", "ML Infrastructure Engineer", ApplicationStatus.REJECTED, 55, "LinkedIn", None),
    ("John", "Databricks", "Staff ML Engineer", ApplicationStatus.GHOSTED, 68, "LinkedIn", None),
    ("John", "Snowflake", "AI Solutions Engineer", ApplicationStatus.REJECTED, 31, "Indeed", "failed"),
    ("John", "Palantir", "Forward Deployed Engineer", ApplicationStatus.APPLIED, 11, "Referral", None),
    ("John", "Scale AI", "Research Engineer", ApplicationStatus.GHOSTED, 39, "Company Site", None),
    ("David", "Netflix", "Senior Backend Engineer", ApplicationStatus.REJECTED, 50, "LinkedIn", None),
    ("David", "Airbnb", "Backend Engineer", ApplicationStatus.REJECTED, 43, "Company Site", None),
    ("David", "Coinbase", "Platform Engineer", ApplicationStatus.GHOSTED, 57, "Indeed", None),
    ("David", "Reddit", "Senior Engineer, Core", ApplicationStatus.REJECTED, 24, "LinkedIn", "failed"),
    ("David", "Twilio", "Staff Engineer", ApplicationStatus.APPLIED, 8, "Company Site", None),
    ("David", "DoorDash", "Backend Engineer", ApplicationStatus.GHOSTED, 62, "Indeed", None),
    ("David", "Instacart", "Senior Engineer", ApplicationStatus.REJECTED, 36, "LinkedIn", None),
    ("Sarah", "Google", "Data Engineer", ApplicationStatus.REJECTED, 49, "Company Site", None),
    ("Sarah", "Adyen", "Senior Data Engineer", ApplicationStatus.REJECTED, 38, "LinkedIn", "failed"),
    ("Sarah", "N26", "Analytics Engineer", ApplicationStatus.GHOSTED, 54, "Indeed", None),
    ("Sarah", "SoundCloud", "Data Engineer", ApplicationStatus.REJECTED, 45, "LinkedIn", None),
    ("Sarah", "GetYourGuide", "Senior Data Engineer", ApplicationStatus.APPLIED, 13, "Company Site", None),
    ("Sarah", "Trade Republic", "Data Platform Engineer", ApplicationStatus.GHOSTED, 59, "LinkedIn", None),
    ("Sarah", "Personio", "Analytics Engineer", ApplicationStatus.SAVED, 2, "Company Site", None),
]


def _expand_quiet_applications() -> list[SeedApplication]:
    """Turn the compact tuples above into full seed records."""
    expanded: list[SeedApplication] = []
    for person, company, title, status, days, source, screen in QUIET_APPLICATIONS:
        stages: list[SeedStage] = []
        if screen == "failed":
            # Got a screen, did not get past it.
            stages.append(
                SeedStage(
                    T.RECRUITER_SCREEN.value,
                    -(days - 6),
                    S.COMPLETED,
                    Out.FAILED,
                    None,
                    11,
                )
            )
        expanded.append(
            SeedApplication(
                person=person,
                company=company,
                title=title,
                status=status,
                applied_days_ago=days,
                location="Remote",
                work_mode=WorkMode.REMOTE,
                source=source,
                priority=Priority.LOW,
                stages=stages,
            )
        )
    return expanded


APPLICATIONS.extend(_expand_quiet_applications())


#: Unlinked "imported" calendar events, so interview detection and the
#: classification flow are demonstrable without connecting a real account.
DEMO_CALENDAR_EVENTS = [
    {
        "person": "John",
        "title": "Anthropic <> John Carter — Recruiter Screen",
        "description": "Intro call about the Research Engineer role. 30 minutes.",
        "organizer_email": "talent@anthropic.com",
        "organizer_name": "Priya (Talent)",
        "meeting_url": "https://meet.google.com/abc-defg-hij",
        "day_offset": 2,
        "hour": 15,
        "minutes": 30,
    },
    {
        "person": "David",
        "title": "Coding assessment — Figma",
        "description": "Complete the exercise at https://app.codesignal.com/test/xyz",
        "organizer_email": "no-reply@greenhouse.io",
        "organizer_name": "Figma Recruiting",
        "day_offset": 1,
        "hour": 13,
        "minutes": 90,
    },
    {
        "person": "Sarah",
        "title": "Team standup",
        "description": "Daily sync with the current team.",
        "organizer_email": "sarah@example.com",
        "day_offset": 1,
        "hour": 9,
        "minutes": 15,
    },
    {
        "person": "John",
        "title": "Dentist",
        "description": "Six-month check-up.",
        "day_offset": 3,
        "hour": 8,
        "minutes": 45,
    },
]


# --------------------------------------------------------------------------
# Builder
# --------------------------------------------------------------------------


def _at(day: date, hour: int, minute: int, tz_name: str) -> datetime:
    """Build a UTC instant from a local wall-clock time in a person's zone."""
    return datetime.combine(day, time(hour, minute), tzinfo=get_tz(tz_name)).astimezone(
        get_tz("UTC")
    )


def clear_demo_data(db) -> None:
    """Remove everything except the workspace, user and interview types."""
    db.execute(delete(Activity))
    db.execute(delete(FollowUp))
    db.execute(delete(InterviewEvent))
    db.execute(delete(InterviewStage))
    db.execute(delete(ApplicationNote))
    db.execute(delete(Application))
    db.execute(delete(CalendarEvent))
    db.execute(delete(Person))
    db.commit()


def seed(*, reset: bool = True) -> None:
    db = session_scope()
    try:
        workspace, _user = ensure_bootstrap(db)

        existing = db.scalar(select(Person.id).limit(1))
        if existing and not reset:
            logger.info("workspace already has data; nothing to do (--keep)")
            return
        if reset:
            clear_demo_data(db)

        today = utcnow().date()

        people: dict[str, Person] = {}
        for order, spec in enumerate(PEOPLE):
            person = Person(
                workspace_id=workspace.id,
                name=spec["name"],
                display_name=spec["display_name"],
                initials=spec["initials"],
                color=spec["color"],
                email=spec["email"],
                timezone=spec["timezone"],
                sort_order=order,
            )
            db.add(person)
            people[spec["display_name"]] = person
        db.flush()

        stage_count = 0
        event_count = 0
        follow_up_count = 0

        for spec in APPLICATIONS:
            person = people[spec.person]
            applied = today - timedelta(days=spec.applied_days_ago)
            application = Application(
                workspace_id=workspace.id,
                person_id=person.id,
                company_name=spec.company,
                job_title=spec.title,
                job_url=f"https://jobs.example.com/{spec.company.lower().replace(' ', '-')}",
                location=spec.location,
                work_mode=spec.work_mode.value,
                employment_type=spec.employment_type.value,
                salary_min=spec.salary[0] if spec.salary else None,
                salary_max=spec.salary[1] if spec.salary else None,
                salary_currency="EUR" if spec.person == "Sarah" else "USD",
                source=spec.source,
                applied_date=applied,
                status=spec.status.value,
                priority=spec.priority.value,
                notes=spec.notes,
                last_activity_at=_at(applied, 9, 0, person.timezone),
            )
            db.add(application)
            db.flush()

            db.add(
                Activity(
                    workspace_id=workspace.id,
                    person_id=person.id,
                    application_id=application.id,
                    type=ActivityType.APPLICATION_CREATED.value,
                    message=(
                        f"{person.display_name} added {spec.company} — {spec.title}"
                    ),
                    created_at=_at(applied, 9, 0, person.timezone),
                )
            )

            latest_activity = application.last_activity_at

            for index, stage_spec in enumerate(spec.stages, start=1):
                stage = InterviewStage(
                    application_id=application.id,
                    round_number=stage_spec.round_number,
                    sequence=index,
                    name=_stage_name(stage_spec),
                    type_key=stage_spec.type_key,
                    status=stage_spec.status.value,
                    outcome=stage_spec.outcome.value,
                    notes=stage_spec.notes,
                )
                db.add(stage)
                db.flush()
                stage_count += 1

                if stage_spec.day_offset is not None:
                    day = today + timedelta(days=stage_spec.day_offset)
                    if stage_spec.slots:
                        for slot_index, slot in enumerate(stage_spec.slots):
                            start = _at(day, slot.hour, slot.minute, person.timezone)
                            db.add(
                                InterviewEvent(
                                    interview_stage_id=stage.id,
                                    title=slot.label,
                                    type_key=slot.type_key,
                                    starts_at=start,
                                    ends_at=start + timedelta(minutes=slot.minutes),
                                    timezone=person.timezone,
                                    meeting_url="https://meet.google.com/loop-demo",
                                    sequence=slot_index,
                                    source=EventSource.APP_CREATED.value,
                                )
                            )
                            event_count += 1
                        starts = [
                            _at(day, s.hour, s.minute, person.timezone)
                            for s in stage_spec.slots
                        ]
                        ends = [
                            _at(day, s.hour, s.minute, person.timezone)
                            + timedelta(minutes=s.minutes)
                            for s in stage_spec.slots
                        ]
                        stage.scheduled_start = min(starts)
                        stage.scheduled_end = max(ends)
                    else:
                        start = _at(day, stage_spec.hour, 0, person.timezone)
                        end = start + timedelta(minutes=stage_spec.minutes)
                        db.add(
                            InterviewEvent(
                                interview_stage_id=stage.id,
                                title=stage.name,
                                starts_at=start,
                                ends_at=end,
                                timezone=person.timezone,
                                meeting_url="https://zoom.us/j/demo",
                                sequence=0,
                                source=EventSource.APP_CREATED.value,
                            )
                        )
                        event_count += 1
                        stage.scheduled_start = start
                        stage.scheduled_end = end

                    if stage_spec.outcome in (
                        InterviewOutcome.PASSED,
                        InterviewOutcome.FAILED,
                    ):
                        stage.result_date = day + timedelta(days=2)

                    if stage.scheduled_end and stage.scheduled_end > latest_activity:
                        latest_activity = stage.scheduled_end

                    db.add(
                        Activity(
                            workspace_id=workspace.id,
                            person_id=person.id,
                            application_id=application.id,
                            interview_stage_id=stage.id,
                            type=ActivityType.STAGE_CREATED.value,
                            message=(
                                f"{person.display_name} added {stage.name} "
                                f"for {spec.company}"
                            ),
                            created_at=stage.scheduled_start
                            or application.last_activity_at,
                        )
                    )
                    if stage_spec.outcome in (
                        InterviewOutcome.PASSED,
                        InterviewOutcome.FAILED,
                    ):
                        db.add(
                            Activity(
                                workspace_id=workspace.id,
                                person_id=person.id,
                                application_id=application.id,
                                interview_stage_id=stage.id,
                                type=ActivityType.STAGE_OUTCOME_CHANGED.value,
                                message=(
                                    f"{spec.company} {stage.name} outcome changed "
                                    f"from Waiting to {stage_spec.outcome.value.title()}"
                                ),
                                meta={"from": "waiting", "to": stage_spec.outcome.value},
                                created_at=(stage.scheduled_end or latest_activity)
                                + timedelta(days=2),
                            )
                        )

            # Applications that reached an offer get the status-change activity
            # row the analytics "ever reached offer" check looks for.
            if spec.status in (
                ApplicationStatus.OFFER,
                ApplicationStatus.NEGOTIATING,
                ApplicationStatus.ACCEPTED,
            ):
                db.add(
                    Activity(
                        workspace_id=workspace.id,
                        person_id=person.id,
                        application_id=application.id,
                        type=ActivityType.APPLICATION_STATUS_CHANGED.value,
                        message=(
                            f"{person.display_name}'s {spec.company} application "
                            "moved from Final Round to Offer"
                        ),
                        meta={"from": "final_round", "to": "offer"},
                        created_at=latest_activity + timedelta(days=3),
                    )
                )
                latest_activity = latest_activity + timedelta(days=3)

            application.last_activity_at = latest_activity
            if spec.notes:
                db.add(
                    ApplicationNote(application_id=application.id, body=spec.notes)
                )

        db.flush()

        follow_up_count = _seed_follow_ups(db, workspace, people, today)
        _seed_calendar_events(db, people, today)

        db.commit()

        logger.info("Seeded demo data:")
        logger.info("  people             %s", len(people))
        logger.info("  applications       %s", len(APPLICATIONS))
        logger.info("  interview stages   %s", stage_count)
        logger.info("  interview events   %s", event_count)
        logger.info("  follow-ups         %s", follow_up_count)
        logger.info("  calendar events    %s", len(DEMO_CALENDAR_EVENTS))
    finally:
        db.close()


def _stage_name(spec: SeedStage) -> str:
    labels = {
        T.RECRUITER_SCREEN.value: "Recruiter Screen",
        T.HR_SCREEN.value: "HR Screen",
        T.HIRING_MANAGER.value: "Hiring Manager",
        T.TECHNICAL.value: "Technical Interview",
        T.CODING.value: "Coding Interview",
        T.MACHINE_LEARNING.value: "ML Technical",
        T.SYSTEM_DESIGN.value: "System Design",
        T.BEHAVIORAL.value: "Behavioral Interview",
        T.CULTURE_FIT.value: "Culture Fit",
        T.PANEL.value: "Panel Interview",
        T.FINAL.value: "Final Interview",
        T.ONLINE_ASSESSMENT.value: "Online Assessment",
        T.TAKE_HOME.value: "Take-Home Assignment",
    }
    return labels.get(spec.type_key, "Interview")


def _seed_follow_ups(db, workspace, people: dict[str, Person], today: date) -> int:
    """Follow-ups covering every bucket the board renders."""
    applications = {
        (a.company_name, a.person_id): a
        for a in db.scalars(select(Application))
    }

    def find(company: str, person_name: str) -> Application | None:
        person = people[person_name]
        return applications.get((company, person.id))

    def latest_stage(application: Application) -> InterviewStage | None:
        return db.scalars(
            select(InterviewStage)
            .where(InterviewStage.application_id == application.id)
            .order_by(InterviewStage.sequence.desc())
            .limit(1)
        ).first()

    plan = [
        # (company, person, title, reason, due offset in days, status, rule)
        (
            "Meta",
            "John",
            "Chase the coding interview result",
            "Interview completed and there is still no answer.",
            -4,
            FollowUpStatus.OPEN,
            FollowUpRule.INTERVIEW_COMPLETED,
            Priority.HIGH,
        ),
        (
            "Stripe",
            "David",
            "Follow up on the system design round",
            "Recruiter said feedback would come within a week.",
            -1,
            FollowUpStatus.OPEN,
            FollowUpRule.INTERVIEW_COMPLETED,
            Priority.HIGH,
        ),
        (
            "Booking.com",
            "Sarah",
            "Expected result from the coding round",
            "Recruiter promised an update today.",
            0,
            FollowUpStatus.OPEN,
            FollowUpRule.INTERVIEW_COMPLETED,
            Priority.MEDIUM,
        ),
        (
            "Amazon",
            "John",
            "Send thank-you note after the technical",
            "Worth a short note the day after the interview.",
            4,
            FollowUpStatus.OPEN,
            FollowUpRule.MANUAL,
            Priority.LOW,
        ),
        (
            "Klarna",
            "Sarah",
            "Confirm final round logistics",
            "Check whether the final is onsite or remote.",
            3,
            FollowUpStatus.OPEN,
            FollowUpRule.MANUAL,
            Priority.MEDIUM,
        ),
        (
            "Delivery Hero",
            "Sarah",
            "Check back on the paused role",
            "Team paused hiring; recruiter suggested revisiting later.",
            21,
            FollowUpStatus.SNOOZED,
            FollowUpRule.MANUAL,
            Priority.LOW,
        ),
        (
            "Datadog",
            "David",
            "Review the written offer",
            "Compare against the Microsoft process before responding.",
            2,
            FollowUpStatus.OPEN,
            FollowUpRule.MANUAL,
            Priority.URGENT,
        ),
        (
            "Guidehouse",
            "John",
            "Ask for interview feedback",
            "Requested notes on the technical round.",
            -12,
            FollowUpStatus.COMPLETED,
            FollowUpRule.INTERVIEW_COMPLETED,
            Priority.LOW,
        ),
        (
            "Spotify",
            "Sarah",
            "Return the signed contract",
            "Offer accepted; paperwork returned.",
            -8,
            FollowUpStatus.COMPLETED,
            FollowUpRule.MANUAL,
            Priority.HIGH,
        ),
    ]

    count = 0
    for company, person_name, title, reason, offset, status, rule, priority in plan:
        application = find(company, person_name)
        if application is None:
            continue
        stage = latest_stage(application)
        due = today + timedelta(days=offset)
        follow_up = FollowUp(
            person_id=application.person_id,
            application_id=application.id,
            interview_stage_id=stage.id if stage else None,
            title=title,
            reason=reason,
            due_date=due,
            status=status.value,
            priority=priority.value,
            auto_generated=rule is not FollowUpRule.MANUAL,
            rule_key=rule.value,
            completed_at=(
                utcnow() - timedelta(days=abs(offset))
                if status is FollowUpStatus.COMPLETED
                else None
            ),
            snoozed_until=due if status is FollowUpStatus.SNOOZED else None,
        )
        db.add(follow_up)
        count += 1
    return count


def _seed_calendar_events(db, people: dict[str, Person], today: date) -> None:
    """Imported-looking events, including two that should trigger a suggestion
    and two that clearly should not."""
    for index, spec in enumerate(DEMO_CALENDAR_EVENTS):
        person = people[spec["person"]]
        day = today + timedelta(days=spec["day_offset"])
        start = _at(day, spec["hour"], 0, person.timezone)
        result = detection.detect(
            title=spec["title"],
            description=spec.get("description"),
            meeting_url=spec.get("meeting_url"),
            organizer_email=spec.get("organizer_email"),
            organizer_name=spec.get("organizer_name"),
        )
        db.add(
            CalendarEvent(
                person_id=person.id,
                provider="google",
                provider_event_id=f"demo-event-{index}",
                ical_uid=f"demo-{index}@example.com",
                title=spec["title"],
                description=spec.get("description"),
                meeting_url=spec.get("meeting_url"),
                organizer_email=spec.get("organizer_email"),
                organizer_name=spec.get("organizer_name"),
                starts_at=start,
                ends_at=start + timedelta(minutes=spec["minutes"]),
                start_timezone=person.timezone,
                end_timezone=person.timezone,
                source=EventSource.EXTERNAL_PROVIDER.value,
                classification=EventClassification.UNCLASSIFIED.value,
                detection_score=result.score,
                detection_reasons=result.reasons,
                last_synced_at=utcnow(),
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo data")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Only seed when the workspace is empty (does not wipe existing data)",
    )
    args = parser.parse_args()
    seed(reset=not args.keep)


if __name__ == "__main__":
    main()
