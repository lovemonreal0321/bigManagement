"""Metric definitions (spec §26, §54).

Every rate in the product is computed here, from real counts, with the
numerator and denominator both carried through to the UI. Nothing is
estimated, smoothed or invented.

--------------------------------------------------------------------------
DEFINITIONS
--------------------------------------------------------------------------

**Interview Pass Rate**
    passed / (passed + failed)

    Only *decided* outcomes form the denominator. Scheduled, waiting,
    cancelled, rescheduled and no-show stages are excluded entirely — a
    pending result is not a failure, and including it would drag the rate
    down purely because a company is slow to reply.

**Technical Pass Rate**
    The same formula restricted to interview types flagged
    `counts_as_technical` (technical, coding, system design, ML, OA,
    take-home, plus any custom type the user marks as technical).

**Application -> Interview**
    applications with at least one *real* interview / applications submitted

    "Real" means a stage that was actually booked or held — status in
    (scheduled, completed, rescheduled, no_show). A `planned` stage is a
    placeholder in the journey timeline, not evidence of a conversion, and a
    stage cancelled before it happened never converted either.

    Recruiter/HR screens DO count. For a job seeker, a recruiter screen is a
    genuine conversion from "sent an application" to "someone is talking to
    me" — the metric would flatter nobody by excluding it.

**First Interview -> Next Round**
    applications with >= 2 real interview stages /
    applications with >= 1 real interview stage

**Final -> Offer**
    applications that reached an offer / applications that reached a final round

    A "final round" is any stage whose type is flagged `counts_as_final`.

**Application -> Offer**
    applications that reached an offer / applications submitted

**Offer Acceptance Rate**
    accepted applications / applications that reached an offer

--------------------------------------------------------------------------
PERIOD SEMANTICS (spec §55)
--------------------------------------------------------------------------

Two different anchors, applied consistently and labelled in the response so a
number is never silently comparing incompatible cohorts:

* **Application-anchored** (`applied_date` in range): the application counts,
  the funnel, and every conversion rate. These are *cohort* metrics — "of the
  applications submitted in this window, how many got somewhere?". Their
  interviews are counted regardless of when they happened, because an
  application submitted on the last day of the range has not had time to
  convert yet and truncating its interviews would understate every rate.

* **Interview-anchored** (`scheduled_start` in range): interview counts, pass
  rates and by-type analytics. These answer "how did the interviews I sat in
  this window go?".

Mixing the two — e.g. dividing interviews-this-month by applications-this-month
— produces a ratio of two unrelated cohorts. The service never does that; the
conversion rates always use the application-anchored counts on both sides.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Below this many decided outcomes a percentage is noise, so the UI shows the
#: raw fraction instead (spec §27).
MIN_MEANINGFUL_DENOMINATOR = 3


@dataclass(frozen=True)
class Rate:
    """A rate that always carries its own evidence."""

    numerator: int
    denominator: int

    @property
    def value(self) -> float | None:
        """Fraction in [0, 1], or None when there is nothing to divide by.

        None is deliberately not 0.0: "no data" and "0%" mean very different
        things and the UI renders them differently.
        """
        if self.denominator <= 0:
            return None
        return self.numerator / self.denominator

    @property
    def percent(self) -> float | None:
        value = self.value
        return None if value is None else round(value * 100, 1)

    @property
    def is_meaningful(self) -> bool:
        return self.denominator >= MIN_MEANINGFUL_DENOMINATOR

    def as_dict(self) -> dict[str, object]:
        return {
            "numerator": self.numerator,
            "denominator": self.denominator,
            "value": self.value,
            "percent": self.percent,
            "is_meaningful": self.is_meaningful,
        }


def rate(numerator: int, denominator: int) -> Rate:
    return Rate(numerator=max(0, numerator), denominator=max(0, denominator))


def pass_rate(passed: int, failed: int) -> Rate:
    """passed / (passed + failed)."""
    return rate(passed, passed + failed)


def application_to_interview(applications_with_interview: int, applications: int) -> Rate:
    return rate(applications_with_interview, applications)


def first_to_next_round(with_two_or_more: int, with_at_least_one: int) -> Rate:
    return rate(with_two_or_more, with_at_least_one)


def final_to_offer(offers: int, finals: int) -> Rate:
    return rate(offers, finals)


def application_to_offer(offers: int, applications: int) -> Rate:
    return rate(offers, applications)


def offer_acceptance(accepted: int, offers: int) -> Rate:
    return rate(accepted, offers)


def conversion_between(current_stage: int, previous_stage: int) -> Rate:
    """Step-to-step conversion inside the funnel (spec §29)."""
    return rate(current_stage, previous_stage)
