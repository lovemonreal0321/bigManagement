"""Scheduling-conflict detection (spec §30, §43).

The rule that matters: **a conflict is only ever between two events belonging
to the same Person.** John at 10:00 and David at 10:00 is the normal state of a
shared workspace, not a problem, and flagging it would make the warning
worthless.
"""

from __future__ import annotations

from datetime import datetime
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutils import overlaps, to_tz
from app.enums import EventClassification, InterviewStatus
from app.models import (
    Application,
    CalendarEvent,
    InterviewEvent,
    InterviewStage,
    Person,
    Workspace,
)
from app.schemas.analytics import ScheduleConflict

#: External events with these classifications are treated as real commitments
#: that can clash with an interview. Ordinary meetings and personal events are
#: left out — flagging every overlap with a routine meeting would bury the
#: signal the panel exists to surface.
BLOCKING_CLASSIFICATIONS = {
    EventClassification.INTERVIEW.value,
    EventClassification.RECRUITER_CALL.value,
    EventClassification.ASSESSMENT.value,
}


class _Block:
    __slots__ = ("ends_at", "person_id", "source_id", "starts_at", "title")

    def __init__(
        self, person_id: str, title: str, starts_at: datetime, ends_at: datetime, source_id: str
    ) -> None:
        self.person_id = person_id
        self.title = title
        self.starts_at = starts_at
        self.ends_at = ends_at
        self.source_id = source_id


def collect_blocks(
    db: Session, person_ids: list[str], *, start: datetime, end: datetime
) -> list[_Block]:
    """Every time commitment worth checking, across both sources."""
    blocks: list[_Block] = []
    if not person_ids:
        return blocks

    rows = db.execute(
        select(InterviewEvent, Application.person_id, Application.company_name)
        .join(InterviewStage, InterviewStage.id == InterviewEvent.interview_stage_id)
        .join(Application, Application.id == InterviewStage.application_id)
        .where(
            Application.person_id.in_(person_ids),
            Application.archived_at.is_(None),
            InterviewStage.status == InterviewStatus.SCHEDULED.value,
            InterviewEvent.starts_at < end,
            InterviewEvent.ends_at > start,
        )
    )
    for event, person_id, company in rows:
        blocks.append(
            _Block(
                person_id=person_id,
                title=f"{company} — {event.title}",
                starts_at=event.starts_at,
                ends_at=event.ends_at,
                source_id=f"interview:{event.id}",
            )
        )

    linked_calendar_ids = {
        row
        for row in db.scalars(
            select(InterviewEvent.calendar_event_id).where(
                InterviewEvent.calendar_event_id.is_not(None)
            )
        )
    }

    external = db.scalars(
        select(CalendarEvent).where(
            CalendarEvent.person_id.in_(person_ids),
            CalendarEvent.deleted_at.is_(None),
            CalendarEvent.is_all_day.is_(False),
            CalendarEvent.classification.in_(sorted(BLOCKING_CLASSIFICATIONS)),
            CalendarEvent.starts_at < end,
            CalendarEvent.ends_at > start,
        )
    )
    for event in external:
        # Skip events already represented by an interview block, or the same
        # meeting would conflict with itself.
        if event.id in linked_calendar_ids:
            continue
        blocks.append(
            _Block(
                person_id=event.person_id,
                title=event.title,
                starts_at=event.starts_at,
                ends_at=event.ends_at,
                source_id=f"calendar:{event.id}",
            )
        )

    return blocks


def find_conflicts(
    db: Session,
    workspace: Workspace,
    people: list[Person],
    *,
    start: datetime,
    end: datetime,
) -> list[ScheduleConflict]:
    person_ids = [p.id for p in people]
    by_id = {p.id: p for p in people}
    blocks = collect_blocks(db, person_ids, start=start, end=end)

    grouped: dict[str, list[_Block]] = {}
    for block in blocks:
        grouped.setdefault(block.person_id, []).append(block)

    conflicts: list[ScheduleConflict] = []
    for person_id, person_blocks in grouped.items():
        person = by_id.get(person_id)
        if person is None:
            continue
        person_blocks.sort(key=lambda b: b.starts_at)
        for first, second in combinations(person_blocks, 2):
            if not overlaps(first.starts_at, first.ends_at, second.starts_at, second.ends_at):
                continue
            overlap_start = max(first.starts_at, second.starts_at)
            overlap_end = min(first.ends_at, second.ends_at)
            minutes = int((overlap_end - overlap_start).total_seconds() // 60)
            tz = person.timezone
            conflicts.append(
                ScheduleConflict(
                    person_id=person.id,
                    person_name=person.display_name,
                    person_color=person.color,
                    first_title=first.title,
                    first_start=to_tz(first.starts_at, tz).isoformat(),
                    first_end=to_tz(first.ends_at, tz).isoformat(),
                    second_title=second.title,
                    second_start=to_tz(second.starts_at, tz).isoformat(),
                    second_end=to_tz(second.ends_at, tz).isoformat(),
                    overlap_minutes=minutes,
                )
            )

    conflicts.sort(key=lambda c: c.first_start)
    return conflicts
