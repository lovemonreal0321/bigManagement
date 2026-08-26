"""Analytics aggregation (spec §25-§30).

Every number here comes from a database aggregate. Read
`domains/analytics/formulas.py` first — it defines what each metric means and
which cohort anchor it uses.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.timeutils import local_date, range_bounds, utcnow
from app.domains.analytics import formulas
from app.domains.analytics.periods import Period
from app.domains.interviews.types import TypeRegistry, load_registry
from app.enums import (
    HELD_STATUSES,
    OFFER_STATUSES,
    REAL_INTERVIEW_STATUSES,
    ActivityType,
    ApplicationStatus,
    InterviewOutcome,
    InterviewStatus,
)
from app.models import Activity, Application, InterviewStage, Person, Workspace
from app.schemas.analytics import (
    AnalyticsOut,
    ConversionMetrics,
    FunnelStep,
    JobOutcome,
    PeriodOut,
    PersonComparisonRow,
    RateOut,
    TimeSeriesPoint,
    TypePerformance,
    VolumeCounts,
)

REAL_STATUS_VALUES = [s.value for s in REAL_INTERVIEW_STATUSES]
HELD_STATUS_VALUES = [s.value for s in HELD_STATUSES]
OFFER_STATUS_VALUES = [s.value for s in OFFER_STATUSES]

#: An application's effective submission date. `applied_date` is the truth;
#: `created_at` is the fallback for rows saved before they were sent.
APPLIED_DAY = func.coalesce(Application.applied_date, func.date(Application.created_at))


def _to_rate(rate: formulas.Rate) -> RateOut:
    return RateOut(**rate.as_dict())  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Cohort selection
# --------------------------------------------------------------------------


def _application_cohort_stmt(
    workspace: Workspace, person_ids: list[str], period: Period
) -> Select:
    """Applications *submitted* in the period — the application-anchored cohort."""
    stmt = select(Application.id).where(
        Application.workspace_id == workspace.id,
        Application.person_id.in_(person_ids),
    )
    if period.start is not None:
        stmt = stmt.where(period.start.isoformat() <= APPLIED_DAY)
    if period.end is not None:
        stmt = stmt.where(period.end.isoformat() >= APPLIED_DAY)
    return stmt


def _stage_period_clause(period: Period, tz: str | None):
    """Interviews that *happened* in the period — the interview-anchored cohort."""
    if period.start is None or period.end is None:
        return None
    start, end = range_bounds(period.start, period.end, tz)
    return (InterviewStage.scheduled_start >= start, InterviewStage.scheduled_start < end)


# --------------------------------------------------------------------------
# Offer detection
# --------------------------------------------------------------------------


def _applications_that_reached_offer(db: Session, application_ids: list[str]) -> set[str]:
    """Applications that received an offer at any point.

    Current status alone is not enough: an offer that was declined ends up as
    `withdrawn`, and one that lapsed as `rejected`. The activity log records
    every status transition, so it is consulted for historical offers too.
    """
    if not application_ids:
        return set()

    reached = set(
        db.scalars(
            select(Application.id).where(
                Application.id.in_(application_ids),
                Application.status.in_(OFFER_STATUS_VALUES),
            )
        )
    )

    historical = db.scalars(
        select(Activity.application_id).where(
            Activity.application_id.in_(application_ids),
            Activity.type == ActivityType.APPLICATION_STATUS_CHANGED.value,
            func.json_extract(Activity.meta, "$.to").in_(OFFER_STATUS_VALUES),
        )
    )
    reached.update(a for a in historical if a)
    return reached


# --------------------------------------------------------------------------
# Core computation
# --------------------------------------------------------------------------


def compute_analytics(
    db: Session,
    workspace: Workspace,
    people: list[Person],
    period: Period,
    *,
    registry: TypeRegistry | None = None,
    include_comparison: bool = True,
    include_trend: bool = True,
) -> AnalyticsOut:
    registry = registry or load_registry(db, workspace.id)
    person_ids = [p.id for p in people]
    tz = workspace.default_timezone

    empty = AnalyticsOut(
        period=PeriodOut(
            key=period.key, label=period.label, start=period.start, end=period.end
        ),
        person_ids=person_ids,
        volume=VolumeCounts(),
        conversions=_empty_conversions(),
        notes=_notes(),
    )
    if not person_ids:
        return empty

    # ---- application-anchored cohort -------------------------------------
    cohort_ids = list(db.scalars(_application_cohort_stmt(workspace, person_ids, period)))
    applications_count = len(cohort_ids)

    stages_by_app: dict[str, list[InterviewStage]] = defaultdict(list)
    if cohort_ids:
        for stage in db.scalars(
            select(InterviewStage).where(InterviewStage.application_id.in_(cohort_ids))
        ):
            stages_by_app[stage.application_id].append(stage)

    final_keys = registry.final_keys
    apps_with_interview = 0
    apps_with_two = 0
    apps_with_final = 0
    for app_id in cohort_ids:
        real = [s for s in stages_by_app[app_id] if s.status in REAL_STATUS_VALUES]
        if real:
            apps_with_interview += 1
        if len(real) >= 2:
            apps_with_two += 1
        if any(s.type_key in final_keys for s in real):
            apps_with_final += 1

    offer_ids = _applications_that_reached_offer(db, cohort_ids)
    offers_count = len(offer_ids)
    accepted_count = (
        db.scalar(
            select(func.count(Application.id)).where(
                Application.id.in_(cohort_ids),
                Application.status == ApplicationStatus.ACCEPTED.value,
            )
        )
        or 0
        if cohort_ids
        else 0
    )
    rejected_count = (
        db.scalar(
            select(func.count(Application.id)).where(
                Application.id.in_(cohort_ids),
                Application.status == ApplicationStatus.REJECTED.value,
            )
        )
        or 0
        if cohort_ids
        else 0
    )

    # ---- interview-anchored cohort ---------------------------------------
    stage_stmt = (
        select(InterviewStage)
        .join(Application, Application.id == InterviewStage.application_id)
        .where(
            Application.workspace_id == workspace.id,
            Application.person_id.in_(person_ids),
        )
    )
    clause = _stage_period_clause(period, tz)
    if clause is not None:
        stage_stmt = stage_stmt.where(*clause)
    period_stages = list(db.scalars(stage_stmt))

    volume = VolumeCounts(
        applications=applications_count,
        applications_with_interview=apps_with_interview,
        interview_stages=len(period_stages),
        interviews_held=sum(1 for s in period_stages if s.status in HELD_STATUS_VALUES),
        passed=sum(1 for s in period_stages if s.outcome == InterviewOutcome.PASSED.value),
        failed=sum(1 for s in period_stages if s.outcome == InterviewOutcome.FAILED.value),
        waiting=sum(
            1 for s in period_stages if s.outcome == InterviewOutcome.WAITING.value
        ),
        scheduled=sum(
            1 for s in period_stages if s.status == InterviewStatus.SCHEDULED.value
        ),
        cancelled=sum(
            1 for s in period_stages if s.status == InterviewStatus.CANCELLED.value
        ),
        final_rounds=sum(1 for s in period_stages if s.type_key in final_keys),
        offers=offers_count,
        accepted=accepted_count,
        rejected=rejected_count,
    )

    technical_keys = registry.technical_keys
    tech_passed = sum(
        1
        for s in period_stages
        if s.type_key in technical_keys and s.outcome == InterviewOutcome.PASSED.value
    )
    tech_failed = sum(
        1
        for s in period_stages
        if s.type_key in technical_keys and s.outcome == InterviewOutcome.FAILED.value
    )

    conversions = ConversionMetrics(
        application_to_interview=_to_rate(
            formulas.application_to_interview(apps_with_interview, applications_count)
        ),
        first_to_next_round=_to_rate(
            formulas.first_to_next_round(apps_with_two, apps_with_interview)
        ),
        interview_pass_rate=_to_rate(formulas.pass_rate(volume.passed, volume.failed)),
        technical_pass_rate=_to_rate(formulas.pass_rate(tech_passed, tech_failed)),
        final_to_offer=_to_rate(formulas.final_to_offer(offers_count, apps_with_final)),
        application_to_offer=_to_rate(
            formulas.application_to_offer(offers_count, applications_count)
        ),
        offer_acceptance=_to_rate(formulas.offer_acceptance(accepted_count, offers_count)),
    )

    result = AnalyticsOut(
        period=PeriodOut(
            key=period.key, label=period.label, start=period.start, end=period.end
        ),
        person_ids=person_ids,
        volume=volume,
        conversions=conversions,
        by_type=_by_type(period_stages, registry),
        funnel=_funnel(
            applications_count,
            apps_with_interview,
            apps_with_two,
            apps_with_final,
            offers_count,
        ),
        notes=_notes(),
    )

    result.jobs = _job_outcome(db, workspace, person_ids, period)

    if include_comparison and len(people) > 1:
        result.comparison = _comparison(db, workspace, people, period, registry)
    if include_trend:
        result.trend = _trend(db, workspace, person_ids, period, tz)
    return result


def _job_outcome(
    db: Session, workspace: Workspace, person_ids: list[str], period: Period
) -> JobOutcome:
    """The far end of the funnel: offers that became work, and what it pays.

    Counted by when a job *started* or *ended*, so the period means the same
    thing it does elsewhere on the page. The money figure is deliberately not
    period-scoped — "what is being earned" is a present-tense question.
    """
    from app.enums import LIVE_JOB_STATUSES, JobStatus
    from app.models import Job

    stmt = select(Job).where(Job.workspace_id == workspace.id)
    if person_ids:
        stmt = stmt.where(Job.person_id.in_(person_ids))
    jobs = list(db.scalars(stmt).unique())

    def within(day) -> bool:
        if day is None:
            return False
        if period.start and day < period.start:
            return False
        return not (period.end and day > period.end)

    live = [job for job in jobs if job.status in LIVE_JOB_STATUSES]
    return JobOutcome(
        jobs_started=sum(1 for job in jobs if within(job.start_date)),
        jobs_ended=sum(1 for job in jobs if within(job.end_date)),
        offers_open=sum(1 for job in jobs if job.status == JobStatus.OFFERED.value),
        live_jobs=len(live),
        total_annual=round(sum(job.annual_amount or 0 for job in live), 2),
        currency=(live[0].currency if live else "USD"),
    )


def _empty_conversions() -> ConversionMetrics:
    zero = _to_rate(formulas.rate(0, 0))
    return ConversionMetrics(
        application_to_interview=zero,
        first_to_next_round=zero,
        interview_pass_rate=zero,
        technical_pass_rate=zero,
        final_to_offer=zero,
        application_to_offer=zero,
        offer_acceptance=zero,
    )


def _notes() -> dict[str, str]:
    return {
        "application_anchor": (
            "Application counts, the funnel and all conversion rates cover "
            "applications submitted in this period. Their interviews are counted "
            "whenever they happened, so recent applications are not penalised for "
            "not having converted yet."
        ),
        "interview_anchor": (
            "Interview counts, pass rates and by-type performance cover interviews "
            "that took place in this period."
        ),
        "pass_rate": (
            "Pass rate = passed / (passed + failed). Scheduled, waiting, cancelled "
            "and rescheduled interviews are excluded from the denominator."
        ),
    }


def _by_type(
    stages: list[InterviewStage], registry: TypeRegistry
) -> list[TypePerformance]:
    """Per-interview-type performance (spec §27)."""
    buckets: dict[str, dict[str, int]] = defaultdict(
        lambda: {"passed": 0, "failed": 0, "scheduled": 0, "waiting": 0}
    )
    for stage in stages:
        bucket = buckets[stage.type_key]
        match stage.outcome:
            case InterviewOutcome.PASSED.value:
                bucket["passed"] += 1
            case InterviewOutcome.FAILED.value:
                bucket["failed"] += 1
            case InterviewOutcome.WAITING.value:
                bucket["waiting"] += 1
        if stage.status == InterviewStatus.SCHEDULED.value:
            bucket["scheduled"] += 1

    rows: list[TypePerformance] = []
    for type_key, counts in buckets.items():
        info = registry.get(type_key)
        rate = formulas.pass_rate(counts["passed"], counts["failed"])
        rows.append(
            TypePerformance(
                type_key=type_key,
                label=info.label,
                short_label=info.short_label,
                passed=counts["passed"],
                failed=counts["failed"],
                total_decided=rate.denominator,
                scheduled=counts["scheduled"],
                waiting=counts["waiting"],
                rate=_to_rate(rate),
            )
        )
    # Most-evidence first, so the reliable numbers lead.
    rows.sort(key=lambda r: (-r.total_decided, r.label))
    return rows


def _funnel(
    applications: int,
    with_interview: int,
    with_second: int,
    with_final: int,
    offers: int,
) -> list[FunnelStep]:
    """Applied -> First Interview -> Second Round -> Final -> Offer (spec §29)."""
    raw = [
        ("applied", "Applied", applications),
        ("first_interview", "First Interview", with_interview),
        ("second_round", "Second Round", with_second),
        ("final", "Final", with_final),
        ("offer", "Offer", offers),
    ]
    steps: list[FunnelStep] = []
    start_count = applications
    for index, (key, label, count) in enumerate(raw):
        step = FunnelStep(key=key, label=label, count=count)
        if index > 0:
            step.conversion_from_previous = _to_rate(
                formulas.conversion_between(count, raw[index - 1][2])
            )
            step.conversion_from_start = _to_rate(
                formulas.conversion_between(count, start_count)
            )
        steps.append(step)
    return steps


def _comparison(
    db: Session,
    workspace: Workspace,
    people: list[Person],
    period: Period,
    registry: TypeRegistry,
) -> list[PersonComparisonRow]:
    """Side-by-side per-person numbers (spec §28). Informational only."""
    rows: list[PersonComparisonRow] = []
    for person in people:
        single = compute_analytics(
            db,
            workspace,
            [person],
            period,
            registry=registry,
            include_comparison=False,
            include_trend=False,
        )
        rows.append(
            PersonComparisonRow(
                person_id=person.id,
                person_name=person.display_name,
                person_color=person.color,
                person_initials=person.initials,
                applications=single.volume.applications,
                interviews_held=single.volume.interviews_held,
                interview_stages=single.volume.interview_stages,
                pass_rate=single.conversions.interview_pass_rate,
                final_rounds=single.volume.final_rounds,
                offers=single.volume.offers,
                accepted=single.volume.accepted,
            )
        )
    return rows


def _trend(
    db: Session,
    workspace: Workspace,
    person_ids: list[str],
    period: Period,
    tz: str | None,
) -> list[TimeSeriesPoint]:
    """Weekly (or daily, for short windows) activity trend."""
    end = period.end or local_date(utcnow(), tz)
    start = period.start or (end - timedelta(days=83))
    span_days = (end - start).days + 1
    bucket_days = 1 if span_days <= 21 else 7

    buckets: dict[str, TimeSeriesPoint] = {}
    cursor = start
    while cursor <= end:
        key = cursor.isoformat()
        buckets[key] = TimeSeriesPoint(bucket=key)
        cursor += timedelta(days=bucket_days)
    if not buckets:
        return []

    bucket_starts = sorted(buckets)

    def bucket_for(day: date) -> str | None:
        if day < start or day > end:
            return None
        offset = (day - start).days // bucket_days
        index = min(offset, len(bucket_starts) - 1)
        return bucket_starts[index]

    for applied_day, count in db.execute(
        select(APPLIED_DAY, func.count(Application.id))
        .where(
            Application.workspace_id == workspace.id,
            Application.person_id.in_(person_ids),
            start.isoformat() <= APPLIED_DAY,
            end.isoformat() >= APPLIED_DAY,
        )
        .group_by(APPLIED_DAY)
    ):
        if not applied_day:
            continue
        day = date.fromisoformat(str(applied_day)[:10])
        key = bucket_for(day)
        if key:
            buckets[key].applications += int(count or 0)

    window_start, window_end = range_bounds(start, end, tz)
    for stage in db.scalars(
        select(InterviewStage)
        .join(Application, Application.id == InterviewStage.application_id)
        .where(
            Application.workspace_id == workspace.id,
            Application.person_id.in_(person_ids),
            InterviewStage.scheduled_start >= window_start,
            InterviewStage.scheduled_start < window_end,
        )
    ):
        if stage.scheduled_start is None:
            continue
        key = bucket_for(local_date(stage.scheduled_start, tz))
        if key:
            buckets[key].interviews += 1

    offer_rows = db.execute(
        select(Activity.created_at, func.count(Activity.id))
        .where(
            Activity.workspace_id == workspace.id,
            Activity.person_id.in_(person_ids),
            Activity.type == ActivityType.APPLICATION_STATUS_CHANGED.value,
            func.json_extract(Activity.meta, "$.to").in_(OFFER_STATUS_VALUES),
            Activity.created_at >= window_start,
            Activity.created_at < window_end,
        )
        .group_by(Activity.created_at)
    )
    for created_at, count in offer_rows:
        if created_at is None:
            continue
        moment = created_at if isinstance(created_at, datetime) else None
        if moment is None:
            continue
        key = bucket_for(local_date(moment, tz))
        if key:
            buckets[key].offers += int(count or 0)

    return [buckets[k] for k in bucket_starts]


# --------------------------------------------------------------------------
# Workload + conflicts (spec §30, §43)
# --------------------------------------------------------------------------


def compute_workload(
    db: Session,
    workspace: Workspace,
    people: list[Person],
    *,
    start: date,
    end: date,
    heavy_threshold: int = 3,
):
    """Interview load per person per day, plus same-person conflicts."""
    from app.domains.calendar.conflicts import find_conflicts
    from app.schemas.analytics import WorkloadDay, WorkloadOut, WorkloadPerson

    person_ids = [p.id for p in people]
    result = WorkloadOut(
        start=start, end=end, heavy_day_threshold=heavy_threshold
    )
    if not person_ids:
        return result

    tz = workspace.default_timezone
    window_start, window_end = range_bounds(start, end, tz)

    from app.models import InterviewEvent

    rows = db.execute(
        select(InterviewEvent, Application.person_id)
        .join(InterviewStage, InterviewStage.id == InterviewEvent.interview_stage_id)
        .join(Application, Application.id == InterviewStage.application_id)
        .where(
            Application.person_id.in_(person_ids),
            Application.archived_at.is_(None),
            InterviewStage.status.in_(
                [InterviewStatus.SCHEDULED.value, InterviewStatus.COMPLETED.value]
            ),
            InterviewEvent.starts_at >= window_start,
            InterviewEvent.starts_at < window_end,
        )
    )

    per_person: dict[str, int] = defaultdict(int)
    per_person_day: dict[tuple[str, date], int] = defaultdict(int)
    for event, person_id in rows:
        person = next((p for p in people if p.id == person_id), None)
        day = local_date(event.starts_at, person.timezone if person else tz)
        per_person[person_id] += 1
        per_person_day[(person_id, day)] += 1

    by_id = {p.id: p for p in people}
    for person in people:
        days = [
            (day, count)
            for (pid, day), count in per_person_day.items()
            if pid == person.id
        ]
        busiest = max(days, key=lambda item: item[1], default=None)
        result.per_person.append(
            WorkloadPerson(
                person_id=person.id,
                person_name=person.display_name,
                person_color=person.color,
                person_initials=person.initials,
                interview_count=per_person[person.id],
                busiest_day=busiest[0] if busiest else None,
                busiest_day_count=busiest[1] if busiest else 0,
            )
        )

    for (person_id, day), count in sorted(per_person_day.items(), key=lambda i: i[0][1]):
        if count >= heavy_threshold:
            person = by_id[person_id]
            result.heavy_days.append(
                WorkloadDay(
                    day=day,
                    person_id=person_id,
                    person_name=person.display_name,
                    person_color=person.color,
                    count=count,
                    is_heavy=True,
                )
            )

    result.conflicts = find_conflicts(
        db, workspace, people, start=window_start, end=window_end
    )
    return result
