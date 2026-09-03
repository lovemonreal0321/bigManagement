"""Job CRUD, decoration and the jobs dashboard."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.core.timeutils import local_date, utcnow
from app.domains.activity import service as activity_service
from app.domains.jobs.money import derive_amounts, gross_per_paycheck, pay_dates
from app.enums import (
    LIVE_JOB_STATUSES,
    OFFER_STATUSES,
    ActivityType,
    JobStatus,
)
from app.models import (
    Activity,
    Application,
    InterviewStage,
    Job,
    Person,
    Workspace,
)
from app.schemas.job import (
    JobCreate,
    JobOut,
    JobPersonSummary,
    JobSummary,
    JobUpdate,
    PayDateOut,
    PendingOffer,
)

#: How many paydays ahead to project. A quarter of fortnightly cheques is
#: enough to answer "when am I next paid, and what is coming this quarter"
#: without turning the page into a calendar.
UPCOMING_PAY_DATES = 6

#: Statuses that mean an offer is on the table, as stored values.
OFFER_STATUS_VALUES = {status.value for status in OFFER_STATUSES}


def list_pending_offers(
    db: Session, workspace: Workspace, person_ids: list[str]
) -> list[PendingOffer]:
    """Offers on the board that nobody has turned into a job yet.

    A job carries a salary, a start date and a pay period — none of which an
    application knows — so reaching "offer" does not create one on its own.
    What it does do is show up here, one click from being recorded, which is
    the answer to "I marked an offer, why is the Jobs page empty".

    An offer that already has a job against it drops off the list.
    """
    if not person_ids:
        return []

    taken = {
        application_id
        for application_id in db.scalars(
            select(Job.application_id).where(
                Job.workspace_id == workspace.id, Job.application_id.is_not(None)
            )
        )
        if application_id
    }

    applications = db.scalars(
        select(Application)
        .where(
            Application.workspace_id == workspace.id,
            Application.person_id.in_(person_ids),
            Application.status.in_(OFFER_STATUS_VALUES),
        )
        .order_by(Application.updated_at.desc())
    )

    people = {
        person.id: person
        for person in db.scalars(
            select(Person).where(Person.id.in_(person_ids))
        )
    }

    offers: list[PendingOffer] = []
    for application in applications:
        if application.id in taken:
            continue
        person = people.get(application.person_id)
        if person is None:
            continue
        offers.append(
            PendingOffer(
                application_id=application.id,
                person_id=person.id,
                person_name=person.display_name,
                person_color=person.color,
                person_initials=person.initials,
                company_name=application.company_name,
                job_title=application.job_title,
                status=application.status,
                offered_date=_offered_on(db, application, person),
                interview_stage_id=_last_stage_id(db, application.id),
            )
        )
    return offers


def _offered_on(
    db: Session, application: Application, person: Person
) -> date | None:
    """The day this application reached an offer, from the status log.

    Read in the person's timezone. The log is UTC, and a New York offer
    recorded in the evening lands on the next UTC day — dating it tomorrow
    would be wrong on the form it prefills.
    """
    moment = db.scalar(
        select(Activity.created_at)
        .where(
            Activity.application_id == application.id,
            Activity.type == ActivityType.APPLICATION_STATUS_CHANGED.value,
            func.json_extract(Activity.meta, "$.to").in_(OFFER_STATUS_VALUES),
        )
        .order_by(Activity.created_at.desc())
        .limit(1)
    )
    if moment is not None:
        return local_date(moment, person.timezone)
    # An offer recorded before the log existed, or seeded straight into the
    # status. The applied date is the only honest answer left.
    return application.applied_date


def _last_stage_id(db: Session, application_id: str) -> str | None:
    """The furthest interview it reached, so the job can point back at it."""
    return db.scalar(
        select(InterviewStage.id)
        .where(InterviewStage.application_id == application_id)
        .order_by(InterviewStage.round_number.desc(), InterviewStage.sequence.desc())
        .limit(1)
    )


def get_job(db: Session, workspace: Workspace, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None or job.workspace_id != workspace.id:
        raise NotFoundError("That job could not be found.", code="job_not_found")
    return job


def _validate_links(
    db: Session, workspace: Workspace, person_id: str, payload: JobCreate | JobUpdate
) -> None:
    """An application or interview a job points at must belong to the same person."""
    if getattr(payload, "application_id", None):
        application = db.get(Application, payload.application_id)
        if application is None or application.workspace_id != workspace.id:
            raise ValidationError(
                "That application could not be found.", code="unknown_application"
            )
        if application.person_id != person_id:
            raise ValidationError(
                "That application belongs to a different person.",
                code="person_mismatch",
            )
    if getattr(payload, "interview_stage_id", None):
        stage = db.get(InterviewStage, payload.interview_stage_id)
        if stage is None:
            raise ValidationError(
                "That interview could not be found.", code="unknown_stage"
            )


def list_jobs(
    db: Session,
    workspace: Workspace,
    person_ids: list[str] | None = None,
    *,
    statuses: list[str] | None = None,
    include_ended: bool = True,
) -> list[Job]:
    stmt = select(Job).where(Job.workspace_id == workspace.id)
    if person_ids is not None:
        stmt = stmt.where(Job.person_id.in_(person_ids))
    if statuses:
        stmt = stmt.where(Job.status.in_(statuses))
    elif not include_ended:
        stmt = stmt.where(Job.status.in_(sorted(LIVE_JOB_STATUSES)))

    # Live jobs first, then most recent start — the ones being worked matter
    # most, and a finished job is history.
    return sorted(
        db.scalars(stmt).unique(),
        key=lambda job: (
            job.status not in LIVE_JOB_STATUSES,
            -(job.start_date or job.offered_date or date.min).toordinal(),
        ),
    )


def create_job(db: Session, workspace: Workspace, payload: JobCreate) -> Job:
    person = db.get(Person, payload.person_id)
    if person is None or person.workspace_id != workspace.id:
        raise NotFoundError("That person could not be found.", code="person_not_found")
    _validate_links(db, workspace, person.id, payload)

    annual, hourly = derive_amounts(
        salary_type=payload.salary_type.value,
        annual_amount=payload.annual_amount,
        hourly_amount=payload.hourly_amount,
        hours_per_week=payload.hours_per_week,
        weeks_per_year=payload.weeks_per_year,
    )

    job = Job(
        workspace_id=workspace.id,
        person_id=person.id,
        application_id=payload.application_id,
        interview_stage_id=payload.interview_stage_id,
        company_name=payload.company_name.strip(),
        title=payload.title.strip(),
        job_type=payload.job_type.value,
        status=payload.status.value,
        location=payload.location,
        offered_date=payload.offered_date or local_date(utcnow(), person.timezone),
        start_date=payload.start_date,
        end_date=payload.end_date,
        end_reason=payload.end_reason.value if payload.end_reason else None,
        end_note=payload.end_note,
        salary_type=payload.salary_type.value,
        annual_amount=annual,
        hourly_amount=hourly,
        currency=payload.currency,
        hours_per_week=payload.hours_per_week,
        weeks_per_year=payload.weeks_per_year,
        pay_period=payload.pay_period.value,
        first_pay_date=payload.first_pay_date,
        notes=payload.notes,
    )
    db.add(job)
    db.flush()

    activity_service.log(
        db,
        workspace_id=workspace.id,
        activity_type=ActivityType.APPLICATION_UPDATED,
        message=f"{person.display_name} added a job at {job.company_name}",
        person_id=person.id,
        application_id=job.application_id,
        meta={"job_id": job.id, "job_status": job.status},
    )
    db.commit()
    return job


def update_job(
    db: Session, workspace: Workspace, job_id: str, payload: JobUpdate
) -> Job:
    job = get_job(db, workspace, job_id)
    _validate_links(db, workspace, job.person_id, payload)
    data = payload.model_dump(exclude_unset=True)

    for field in (
        "company_name",
        "title",
        "location",
        "offered_date",
        "start_date",
        "end_date",
        "end_note",
        "currency",
        "first_pay_date",
        "application_id",
        "interview_stage_id",
        "notes",
        "hours_per_week",
        "weeks_per_year",
        "annual_amount",
        "hourly_amount",
    ):
        if field in data:
            setattr(job, field, data[field])

    for field in ("job_type", "status", "salary_type", "pay_period", "end_reason"):
        if field in data:
            value = data[field]
            setattr(job, field, value.value if hasattr(value, "value") else value)

    if job.start_date and job.end_date and job.end_date < job.start_date:
        raise ValidationError(
            "A job cannot end before it starts.", code="end_before_start"
        )

    # Recompute the derived figure only when something it depends on moved, so
    # a hand-corrected counterpart survives an unrelated edit.
    money_touched = {
        "salary_type",
        "annual_amount",
        "hourly_amount",
        "hours_per_week",
        "weeks_per_year",
    } & set(data)
    if money_touched:
        quoted = job.salary_type
        annual = job.annual_amount
        hourly = job.hourly_amount
        # The figure the user did not just type is the one to recompute.
        if quoted == "hourly" and "annual_amount" not in data:
            annual = None
        if quoted == "annual" and "hourly_amount" not in data:
            hourly = None
        job.annual_amount, job.hourly_amount = derive_amounts(
            salary_type=quoted,
            annual_amount=annual,
            hourly_amount=hourly,
            hours_per_week=job.hours_per_week,
            weeks_per_year=job.weeks_per_year,
        )

    db.commit()
    return job


def end_job(
    db: Session,
    workspace: Workspace,
    job_id: str,
    *,
    end_date: date | None,
    reason: str | None,
    note: str | None,
) -> Job:
    """Close a job out. Kept as its own action because "it ended" is a moment
    worth recording, not a field edit."""
    job = get_job(db, workspace, job_id)
    person = db.get(Person, job.person_id)

    job.status = JobStatus.ENDED.value
    job.end_date = end_date or local_date(utcnow(), person.timezone if person else None)
    job.end_reason = reason
    job.end_note = note

    activity_service.log(
        db,
        workspace_id=workspace.id,
        activity_type=ActivityType.APPLICATION_UPDATED,
        message=(
            f"{person.display_name if person else 'Someone'}'s job at "
            f"{job.company_name} ended"
        ),
        person_id=job.person_id,
        meta={"job_id": job.id, "end_reason": reason},
    )
    db.commit()
    return job


def delete_job(db: Session, workspace: Workspace, job_id: str) -> None:
    job = get_job(db, workspace, job_id)
    db.delete(job)
    db.commit()


# --------------------------------------------------------------------------
# Decoration
# --------------------------------------------------------------------------


def _today_for(job: Job) -> date:
    person = job.person
    return local_date(utcnow(), person.timezone if person else None)


def decorate(job: Job) -> JobOut:
    """Add the derived money and payday fields the UI shows."""
    out = JobOut.model_validate(job)
    person = job.person
    if person is not None:
        out.person_name = person.display_name
        out.person_color = person.color
        out.person_initials = person.initials

    out.is_live = job.status in LIVE_JOB_STATUSES
    out.gross_per_paycheck = gross_per_paycheck(job.annual_amount, job.pay_period)

    today = _today_for(job)
    if job.start_date:
        end = job.end_date or today
        out.tenure_days = max((end - job.start_date).days, 0)

    # An ended job has no upcoming paydays; a job not yet accepted has no
    # schedule to speak of either.
    if job.first_pay_date and out.is_live:
        upcoming = pay_dates(
            job.first_pay_date,
            job.pay_period,
            count=UPCOMING_PAY_DATES,
            after=today,
            until=job.end_date,
        )
        out.upcoming_pay_dates = [
            PayDateOut(date=day, amount=out.gross_per_paycheck, is_next=index == 0)
            for index, day in enumerate(upcoming)
        ]
        out.next_pay_date = upcoming[0] if upcoming else None

    if job.application is not None:
        out.application_company = job.application.company_name
    return out


def build_summary(
    db: Session, workspace: Workspace, people: list[Person]
) -> JobSummary:
    """The Jobs dashboard for the selected people."""
    person_ids = [person.id for person in people]
    jobs = list_jobs(db, workspace, person_ids or None)
    decorated = [decorate(job) for job in jobs]

    live = [job for job in decorated if job.is_live]
    offered = [job for job in decorated if job.status == JobStatus.OFFERED.value]
    ended = [job for job in decorated if job.status == JobStatus.ENDED.value]

    # Only live jobs count as income: an offer is not money, and an ended job
    # has stopped being money.
    total_annual = round(sum(job.annual_amount or 0 for job in live), 2)

    with_pay = [job for job in live if job.next_pay_date]
    soonest = min(with_pay, key=lambda job: job.next_pay_date, default=None)

    by_person: list[JobPersonSummary] = []
    for person in people:
        theirs = [job for job in live if job.person_id == person.id]
        their_pay = [job.next_pay_date for job in theirs if job.next_pay_date]
        by_person.append(
            JobPersonSummary(
                person_id=person.id,
                person_name=person.display_name,
                person_color=person.color,
                person_initials=person.initials,
                live_count=len(theirs),
                total_annual=round(sum(job.annual_amount or 0 for job in theirs), 2),
                next_pay_date=min(their_pay) if their_pay else None,
            )
        )

    return JobSummary(
        live_count=len(live),
        offered_count=len(offered),
        ended_count=len(ended),
        total_annual=total_annual,
        # Mixed currencies would need conversion rates this app does not have,
        # so the summary reports the most common one and the list shows each.
        currency=(live[0].currency if live else "USD"),
        next_pay_date=soonest.next_pay_date if soonest else None,
        next_pay_amount=soonest.gross_per_paycheck if soonest else None,
        next_pay_job_id=soonest.id if soonest else None,
        by_person=by_person,
    )
