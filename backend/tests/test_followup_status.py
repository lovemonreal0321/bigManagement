"""Follow-up due/overdue derivation tests (spec §57)."""

from __future__ import annotations

from datetime import date

from app.domains.followups.status import compute_state, describe, is_actionable
from app.enums import FollowUpComputedStatus, FollowUpStatus

TODAY = date(2026, 8, 14)


def _state(
    due: date, status: str = FollowUpStatus.OPEN.value, snoozed: date | None = None
):
    return compute_state(
        stored_status=status, due_date=due, today=TODAY, snoozed_until=snoozed
    )


class TestComputedStatus:
    def test_past_due_is_overdue(self) -> None:
        state = _state(date(2026, 8, 12))
        assert state.status is FollowUpComputedStatus.OVERDUE
        assert state.days_overdue == 2

    def test_due_today(self) -> None:
        state = _state(TODAY)
        assert state.status is FollowUpComputedStatus.DUE_TODAY
        assert state.days_overdue == 0

    def test_future_is_open(self) -> None:
        state = _state(date(2026, 8, 20))
        assert state.status is FollowUpComputedStatus.OPEN
        assert state.days_until_due == 6

    def test_completed_ignores_the_due_date(self) -> None:
        state = _state(date(2026, 1, 1), status=FollowUpStatus.COMPLETED.value)
        assert state.status is FollowUpComputedStatus.COMPLETED
        assert state.days_overdue is None

    def test_cancelled_ignores_the_due_date(self) -> None:
        state = _state(date(2026, 1, 1), status=FollowUpStatus.CANCELLED.value)
        assert state.status is FollowUpComputedStatus.CANCELLED


class TestSnooze:
    def test_active_snooze_hides_the_item(self) -> None:
        state = _state(
            date(2026, 8, 10),
            status=FollowUpStatus.SNOOZED.value,
            snoozed=date(2026, 8, 20),
        )
        assert state.status is FollowUpComputedStatus.SNOOZED
        assert state.days_until_due == 6

    def test_expired_snooze_reverts_to_overdue(self) -> None:
        """No nightly job needed: an elapsed snooze simply stops applying."""
        state = _state(
            date(2026, 8, 10),
            status=FollowUpStatus.SNOOZED.value,
            snoozed=date(2026, 8, 12),
        )
        assert state.status is FollowUpComputedStatus.OVERDUE
        assert state.days_overdue == 4

    def test_snooze_ending_today_is_no_longer_hidden(self) -> None:
        state = _state(
            TODAY, status=FollowUpStatus.SNOOZED.value, snoozed=TODAY
        )
        assert state.status is FollowUpComputedStatus.DUE_TODAY

    def test_snoozed_without_a_date_behaves_normally(self) -> None:
        state = _state(date(2026, 8, 12), status=FollowUpStatus.SNOOZED.value)
        assert state.status is FollowUpComputedStatus.OVERDUE


class TestActionability:
    def test_overdue_and_due_today_need_attention(self) -> None:
        assert is_actionable(_state(date(2026, 8, 12)))
        assert is_actionable(_state(TODAY))

    def test_future_and_snoozed_do_not(self) -> None:
        assert not is_actionable(_state(date(2026, 9, 1)))
        assert not is_actionable(
            _state(TODAY, FollowUpStatus.SNOOZED.value, date(2026, 9, 1))
        )


class TestDescription:
    def test_overdue_wording(self) -> None:
        assert describe(_state(date(2026, 8, 12))) == "2 days overdue"

    def test_singular_day(self) -> None:
        assert describe(_state(date(2026, 8, 13))) == "1 day overdue"

    def test_due_today_wording(self) -> None:
        assert describe(_state(TODAY)) == "Due today"

    def test_tomorrow_wording(self) -> None:
        assert describe(_state(date(2026, 8, 15))) == "Due tomorrow"

    def test_future_wording(self) -> None:
        assert describe(_state(date(2026, 8, 20))) == "Due in 6 days"


def test_timezone_matters_for_overdue() -> None:
    """The same follow-up can be overdue for one person and not another.

    `compute_state` takes the viewer's local day rather than a server date,
    which is what makes that possible.
    """
    due = date(2026, 8, 14)
    berlin_today = date(2026, 8, 15)  # already tomorrow in Berlin
    new_york_today = date(2026, 8, 14)

    berlin = compute_state(
        stored_status=FollowUpStatus.OPEN.value, due_date=due, today=berlin_today
    )
    new_york = compute_state(
        stored_status=FollowUpStatus.OPEN.value, due_date=due, today=new_york_today
    )
    assert berlin.status is FollowUpComputedStatus.OVERDUE
    assert new_york.status is FollowUpComputedStatus.DUE_TODAY
