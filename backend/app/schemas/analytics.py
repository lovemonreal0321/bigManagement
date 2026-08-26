"""Analytics schemas."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class RateOut(BaseModel):
    """A rate plus the counts behind it (spec §27: always show n/d)."""

    numerator: int
    denominator: int
    value: float | None = None
    percent: float | None = None
    is_meaningful: bool = False


class PeriodOut(BaseModel):
    key: str
    label: str
    start: date | None
    end: date | None


class VolumeCounts(BaseModel):
    """Raw counts (spec §25)."""

    applications: int = 0
    applications_with_interview: int = 0
    interview_stages: int = 0
    interviews_held: int = 0
    passed: int = 0
    failed: int = 0
    waiting: int = 0
    scheduled: int = 0
    cancelled: int = 0
    final_rounds: int = 0
    offers: int = 0
    accepted: int = 0
    rejected: int = 0


class ConversionMetrics(BaseModel):
    """Spec §26."""

    application_to_interview: RateOut
    first_to_next_round: RateOut
    interview_pass_rate: RateOut
    technical_pass_rate: RateOut
    final_to_offer: RateOut
    application_to_offer: RateOut
    offer_acceptance: RateOut


class TypePerformance(BaseModel):
    """Spec §27."""

    type_key: str
    label: str
    short_label: str
    passed: int
    failed: int
    total_decided: int
    scheduled: int
    waiting: int
    rate: RateOut


class FunnelStep(BaseModel):
    key: str
    label: str
    count: int
    #: Conversion from the previous step.
    conversion_from_previous: RateOut | None = None
    #: Conversion from the very first step.
    conversion_from_start: RateOut | None = None


class PersonComparisonRow(BaseModel):
    """Spec §28 — informational, never a leaderboard."""

    person_id: str
    person_name: str
    person_color: str
    person_initials: str
    applications: int
    interviews_held: int
    interview_stages: int
    pass_rate: RateOut
    final_rounds: int
    offers: int
    accepted: int


class WorkloadDay(BaseModel):
    day: date
    person_id: str
    person_name: str
    person_color: str
    count: int
    is_heavy: bool


class WorkloadPerson(BaseModel):
    person_id: str
    person_name: str
    person_color: str
    person_initials: str
    interview_count: int
    busiest_day: date | None = None
    busiest_day_count: int = 0


class ScheduleConflict(BaseModel):
    """Two overlapping events for the SAME person (spec §43)."""

    person_id: str
    person_name: str
    person_color: str
    first_title: str
    first_start: str
    first_end: str
    second_title: str
    second_start: str
    second_end: str
    overlap_minutes: int


class WorkloadOut(BaseModel):
    """Spec §30."""

    start: date
    end: date
    per_person: list[WorkloadPerson] = Field(default_factory=list)
    heavy_days: list[WorkloadDay] = Field(default_factory=list)
    conflicts: list[ScheduleConflict] = Field(default_factory=list)
    heavy_day_threshold: int = 3


class TimeSeriesPoint(BaseModel):
    bucket: str
    applications: int = 0
    interviews: int = 0
    offers: int = 0


class JobOutcome(BaseModel):
    """What the search actually produced, in the period.

    Application-side metrics stop at "offer". This is the other end: offers
    that turned into work, and what that work pays.
    """

    jobs_started: int
    jobs_ended: int
    offers_open: int
    live_jobs: int
    #: Annual pay across live jobs. Gross, and only jobs being worked — an
    #: offer is not income.
    total_annual: float
    currency: str


class AnalyticsOut(BaseModel):
    period: PeriodOut
    person_ids: list[str]
    volume: VolumeCounts
    conversions: ConversionMetrics
    by_type: list[TypePerformance] = Field(default_factory=list)
    funnel: list[FunnelStep] = Field(default_factory=list)
    comparison: list[PersonComparisonRow] = Field(default_factory=list)
    trend: list[TimeSeriesPoint] = Field(default_factory=list)
    jobs: JobOutcome | None = None
    #: Explains which anchor each block uses, so the UI can caption honestly.
    notes: dict[str, str] = Field(default_factory=dict)
