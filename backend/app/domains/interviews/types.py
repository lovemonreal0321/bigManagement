"""Interview-type registry helpers and stage badge rendering.

The badge is the thing the user said the original design was missing: every
interview step carries a visible "R2 · Technical" tag wherever it appears —
calendar chips, pipeline cards, journey timeline, upcoming lists.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import INTERVIEW_TYPE_SHORT_LABELS, InterviewTypeKey
from app.models import InterviewType


@dataclass(frozen=True)
class TypeInfo:
    key: str
    label: str
    short_label: str
    counts_as_technical: bool
    counts_as_final: bool
    counts_as_screening: bool


#: Used when a stage references a type that was deleted or never existed.
UNKNOWN_TYPE = TypeInfo(
    key=InterviewTypeKey.OTHER.value,
    label="Other",
    short_label="Other",
    counts_as_technical=False,
    counts_as_final=False,
    counts_as_screening=False,
)


class TypeRegistry:
    """Loaded once per request and passed down, so rendering N stage badges
    costs one query rather than N (spec §56)."""

    def __init__(self, types: list[InterviewType]) -> None:
        self._by_key: dict[str, TypeInfo] = {
            t.key: TypeInfo(
                key=t.key,
                label=t.label,
                short_label=t.short_label or INTERVIEW_TYPE_SHORT_LABELS.get(t.key, t.label),
                counts_as_technical=t.counts_as_technical,
                counts_as_final=t.counts_as_final,
                counts_as_screening=t.counts_as_screening,
            )
            for t in types
        }

    def get(self, key: str | None) -> TypeInfo:
        if not key:
            return UNKNOWN_TYPE
        return self._by_key.get(key, UNKNOWN_TYPE)

    def label(self, key: str | None) -> str:
        return self.get(key).label

    def short_label(self, key: str | None) -> str:
        return self.get(key).short_label

    @property
    def keys(self) -> set[str]:
        return set(self._by_key)

    @property
    def technical_keys(self) -> set[str]:
        return {k for k, v in self._by_key.items() if v.counts_as_technical}

    @property
    def final_keys(self) -> set[str]:
        return {k for k, v in self._by_key.items() if v.counts_as_final}

    @property
    def screening_keys(self) -> set[str]:
        return {k for k, v in self._by_key.items() if v.counts_as_screening}

    def all(self) -> list[TypeInfo]:
        return list(self._by_key.values())


def load_registry(db: Session, workspace_id: str) -> TypeRegistry:
    types = list(
        db.scalars(
            select(InterviewType)
            .where(InterviewType.workspace_id == workspace_id)
            .order_by(InterviewType.sort_order, InterviewType.label)
        )
    )
    return TypeRegistry(types)


def stage_badge(round_number: int | None, type_short_label: str) -> str:
    """Render the step tag.

    "R2 · Technical" when the round is numbered, otherwise just the type —
    plenty of processes are not numbered (spec §14), and "R None · Technical"
    would be worse than no prefix.
    """
    if round_number is not None and round_number > 0:
        return f"R{round_number} · {type_short_label}"
    return type_short_label


def default_stage_name(round_number: int | None, type_label: str) -> str:
    if round_number is not None and round_number > 0:
        return f"Round {round_number} — {type_label}"
    return type_label
