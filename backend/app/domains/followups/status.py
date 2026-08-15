"""Follow-up status derivation.

Pure functions, no database — this is the logic spec §57 asks to be tested
directly.

Why derive rather than store: "overdue" is a function of the clock. If it were
a stored column, every row would need a nightly job to stay honest and would be
wrong for anyone in a different timezone. `due_date` plus the viewer's day is
always correct.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.enums import FollowUpComputedStatus, FollowUpStatus


@dataclass(frozen=True)
class FollowUpState:
    status: FollowUpComputedStatus
    #: Positive when overdue, negative when due in future, 0 when due today.
    #: None for completed/cancelled items, where "days" is meaningless.
    days_overdue: int | None
    days_until_due: int | None


def compute_state(
    *,
    stored_status: str,
    due_date: date,
    today: date,
    snoozed_until: date | None = None,
) -> FollowUpState:
    """Map stored status + dates onto the status the UI shows.

    A snooze that has run out silently reverts to the normal due/overdue
    calculation rather than needing a job to flip the row back.
    """
    if stored_status == FollowUpStatus.COMPLETED.value:
        return FollowUpState(FollowUpComputedStatus.COMPLETED, None, None)
    if stored_status == FollowUpStatus.CANCELLED.value:
        return FollowUpState(FollowUpComputedStatus.CANCELLED, None, None)

    if (
        stored_status == FollowUpStatus.SNOOZED.value
        and snoozed_until is not None
        and snoozed_until > today
    ):
        return FollowUpState(
            FollowUpComputedStatus.SNOOZED,
            None,
            (snoozed_until - today).days,
        )

    delta = (today - due_date).days
    if delta > 0:
        return FollowUpState(FollowUpComputedStatus.OVERDUE, delta, -delta)
    if delta == 0:
        return FollowUpState(FollowUpComputedStatus.DUE_TODAY, 0, 0)
    return FollowUpState(FollowUpComputedStatus.OPEN, 0, -delta)


def is_actionable(state: FollowUpState) -> bool:
    """Does this belong in the "needs attention" buckets?"""
    return state.status in (
        FollowUpComputedStatus.OVERDUE,
        FollowUpComputedStatus.DUE_TODAY,
    )


def describe(state: FollowUpState) -> str:
    """Human phrasing used on cards, e.g. "2 days overdue"."""
    match state.status:
        case FollowUpComputedStatus.OVERDUE:
            days = state.days_overdue or 0
            return f"{days} day{'s' if days != 1 else ''} overdue"
        case FollowUpComputedStatus.DUE_TODAY:
            return "Due today"
        case FollowUpComputedStatus.OPEN:
            days = state.days_until_due or 0
            if days == 1:
                return "Due tomorrow"
            return f"Due in {days} days"
        case FollowUpComputedStatus.SNOOZED:
            days = state.days_until_due or 0
            return f"Snoozed for {days} day{'s' if days != 1 else ''}"
        case FollowUpComputedStatus.COMPLETED:
            return "Completed"
        case _:
            return "Cancelled"
