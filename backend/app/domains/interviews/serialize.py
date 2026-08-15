"""Pure ORM -> schema conversion for interviews.

Kept free of database access and service imports so both the applications and
interviews domains can use it without an import cycle.
"""

from __future__ import annotations

from app.domains.interviews.types import TypeRegistry, stage_badge
from app.models import InterviewEvent, InterviewStage
from app.schemas.interview import InterviewEventOut, InterviewStageOut


def event_to_out(
    event: InterviewEvent, registry: TypeRegistry, stage: InterviewStage | None = None
) -> InterviewEventOut:
    # A loop slot may carry its own type; otherwise it inherits the stage's.
    effective_key = event.type_key or (stage.type_key if stage else None)
    info = registry.get(effective_key)
    return InterviewEventOut(
        id=event.id,
        interview_stage_id=event.interview_stage_id,
        calendar_event_id=event.calendar_event_id,
        title=event.title,
        type_key=effective_key,
        type_label=info.label,
        type_short_label=info.short_label,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        timezone=event.timezone,
        location=event.location,
        meeting_url=event.meeting_url,
        interviewer_names=event.interviewer_names,
        sequence=event.sequence,
        source=event.source,
        sync_state=event.sync_state,
        sync_error=event.sync_error,
    )


def stage_to_out(
    stage: InterviewStage,
    registry: TypeRegistry,
    *,
    include_events: bool = True,
) -> InterviewStageOut:
    info = registry.get(stage.type_key)
    events = (
        [event_to_out(e, registry, stage) for e in stage.events] if include_events else []
    )
    return InterviewStageOut(
        id=stage.id,
        application_id=stage.application_id,
        round_number=stage.round_number,
        sequence=stage.sequence,
        name=stage.name,
        type_key=stage.type_key,
        type_label=info.label,
        type_short_label=info.short_label,
        stage_badge=stage_badge(stage.round_number, info.short_label),
        status=stage.status,
        outcome=stage.outcome,
        scheduled_start=stage.scheduled_start,
        scheduled_end=stage.scheduled_end,
        result_date=stage.result_date,
        notes=stage.notes,
        created_at=stage.created_at,
        updated_at=stage.updated_at,
        events=events,
        event_count=len(stage.events) if include_events else 0,
    )
