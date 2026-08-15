"""Turn a model response into validated, safe-to-apply facts.

Kept separate from both the HTTP client and the database so the shape of a
result — and every rule about what is trustworthy — can be tested without
either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.enums import InterviewTypeKey

VALID_TYPE_KEYS = {t.value for t in InterviewTypeKey}

#: Values models emit when they mean "unknown" but ignore the instruction to
#: use null.
_NULLISH = {"", "null", "none", "n/a", "na", "unknown", "not specified", "tbd", "-"}

MAX_COMPANY_LEN = 120
MAX_ROLE_LEN = 160
MAX_ROUND = 20


@dataclass
class ExtractionResult:
    """A validated extraction. Everything here is safe to write."""

    is_interview: bool = False
    company: str | None = None
    role: str | None = None
    round_number: int | None = None
    interview_type: str | None = None
    stage_name: str | None = None
    interviewers: list[str] = field(default_factory=list)
    location_or_link: str | None = None
    salary_mentioned: str | None = None
    next_steps: str | None = None
    confidence: float = 0.0
    reasoning: str | None = None
    #: Fields the model returned that had to be dropped or corrected.
    warnings: list[str] = field(default_factory=list)

    @property
    def is_actionable(self) -> bool:
        """Enough to create something meaningful.

        A company is the minimum: an application without one is not a record
        anyone can use.
        """
        return self.is_interview and bool(self.company)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_interview": self.is_interview,
            "company": self.company,
            "role": self.role,
            "round_number": self.round_number,
            "interview_type": self.interview_type,
            "stage_name": self.stage_name,
            "interviewers": self.interviewers,
            "location_or_link": self.location_or_link,
            "salary_mentioned": self.salary_mentioned,
            "next_steps": self.next_steps,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "warnings": self.warnings,
        }


def _clean_str(value: Any, *, max_length: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    text = " ".join(value.split()).strip()
    if not text or text.lower() in _NULLISH:
        return None
    return text[:max_length]


def _clean_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def parse_result(payload: dict[str, Any]) -> ExtractionResult:
    """Validate a raw model object into an `ExtractionResult`.

    Never raises on bad content: anything unusable is dropped and recorded in
    `warnings`, because a partially-correct extraction is still useful and a
    hard failure here would lose the whole run.
    """
    result = ExtractionResult()
    warnings: list[str] = []

    result.is_interview = _clean_bool(payload.get("is_interview"))
    result.company = _clean_str(payload.get("company"), max_length=MAX_COMPANY_LEN)
    result.role = _clean_str(payload.get("role"), max_length=MAX_ROLE_LEN)
    result.stage_name = _clean_str(payload.get("stage_name"), max_length=200)
    result.location_or_link = _clean_str(payload.get("location_or_link"), max_length=500)
    result.salary_mentioned = _clean_str(payload.get("salary_mentioned"), max_length=120)
    result.next_steps = _clean_str(payload.get("next_steps"), max_length=500)
    result.reasoning = _clean_str(payload.get("reasoning"), max_length=1000)

    # -- round number ------------------------------------------------------
    raw_round = payload.get("round_number")
    if raw_round is not None:
        try:
            round_number = int(raw_round)
            if 1 <= round_number <= MAX_ROUND:
                result.round_number = round_number
            else:
                warnings.append(f"Ignored implausible round number {round_number}")
        except (TypeError, ValueError):
            warnings.append(f"Ignored unreadable round number {raw_round!r}")

    # -- interview type ----------------------------------------------------
    raw_type = _clean_str(payload.get("interview_type"), max_length=64)
    if raw_type:
        normalised = raw_type.lower().replace(" ", "_").replace("-", "_")
        if normalised in VALID_TYPE_KEYS:
            result.interview_type = normalised
        else:
            # An unknown label is not worth guessing at; "other" is honest.
            warnings.append(f"Unknown interview type {raw_type!r}, using 'other'")
            result.interview_type = InterviewTypeKey.OTHER.value

    # -- interviewers ------------------------------------------------------
    raw_interviewers = payload.get("interviewers")
    if isinstance(raw_interviewers, list):
        names = [
            cleaned
            for item in raw_interviewers[:12]
            if (cleaned := _clean_str(item, max_length=120))
        ]
        result.interviewers = names
    elif raw_interviewers is not None:
        single = _clean_str(raw_interviewers, max_length=120)
        if single:
            result.interviewers = [single]

    # -- confidence --------------------------------------------------------
    raw_confidence = payload.get("confidence")
    try:
        confidence = float(raw_confidence)
        if confidence > 1 and confidence <= 100:
            # Some models answer in percent despite the instruction.
            confidence = confidence / 100
        result.confidence = max(0.0, min(1.0, round(confidence, 3)))
    except (TypeError, ValueError):
        result.confidence = 0.0
        warnings.append("Missing or unreadable confidence, treated as 0")

    # A claimed interview with no company is not something to act on, and
    # saying so is more useful than silently creating a blank record.
    if result.is_interview and not result.company:
        warnings.append("Model reported an interview but no company")

    result.warnings = warnings
    return result
