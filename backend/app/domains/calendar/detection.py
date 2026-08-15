"""Heuristic interview detection (spec §8).

This module only ever produces a *suggestion*. Nothing here writes an
application, links a stage, or changes a classification on its own — the spec
is explicit that records must not be created from heuristics alone. The output
is a score plus the reasons behind it, which the UI renders as
"Possible interview detected" with Link / Create / Ignore buttons.

Pure functions, no database, so the scoring is directly testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.enums import InterviewTypeKey

#: Phrases that all but confirm an interview, with their weights.
STRONG_SIGNALS: dict[str, float] = {
    "interview": 0.6,
    "recruiter screen": 0.6,
    "phone screen": 0.55,
    "hiring manager": 0.5,
    "technical screen": 0.6,
    "final round": 0.55,
    "onsite loop": 0.55,
    "system design": 0.45,
    "coding challenge": 0.5,
    "take home": 0.4,
    "take-home": 0.4,
    "panel": 0.35,
    "hiring loop": 0.55,
    "candidate": 0.3,
}

MEDIUM_SIGNALS: dict[str, float] = {
    "screening": 0.3,
    "screen": 0.2,
    "coding": 0.25,
    "assessment": 0.3,
    "recruiter": 0.35,
    "talent": 0.2,
    "hiring": 0.25,
    "role": 0.12,
    "position": 0.12,
    "opportunity": 0.12,
    "chat about the": 0.15,
    "intro call": 0.2,
}

#: Phrases that make an interview unlikely. These subtract, so a
#: "Team standup" never gets promoted by an incidental keyword.
NEGATIVE_SIGNALS: dict[str, float] = {
    "standup": 0.7,
    "stand-up": 0.7,
    "retro": 0.6,
    "sprint": 0.5,
    "all hands": 0.7,
    "all-hands": 0.7,
    "lunch": 0.4,
    "birthday": 0.8,
    "dentist": 0.8,
    "doctor": 0.7,
    "holiday": 0.6,
    "vacation": 0.7,
    "pto": 0.6,
    "ooo": 0.6,
    "out of office": 0.7,
    "focus time": 0.8,
    "blocked": 0.5,
    "gym": 0.7,
    "school": 0.5,
    "1:1": 0.5,
    "weekly sync": 0.6,
    "office hours": 0.4,
}

#: Assessment platforms in a link are a very strong signal on their own.
ASSESSMENT_DOMAINS = (
    "hackerrank.com",
    "codesignal.com",
    "leetcode.com",
    "karat.io",
    "coderpad.io",
    "codility.com",
    "woven.teamable.com",
    "testgorilla.com",
)

#: Applicant-tracking / scheduling systems that email calendar invites.
ATS_DOMAINS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "workday.com",
    "myworkday.com",
    "smartrecruiters.com",
    "icims.com",
    "jobvite.com",
    "goodtime.io",
    "modernloop.io",
    "calendly.com",
)

#: Free-mail and internal domains that say nothing about a company.
GENERIC_EMAIL_DOMAINS = (
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "yahoo.com",
    "icloud.com",
    "me.com",
    "proton.me",
    "protonmail.com",
    "aol.com",
)

#: Maps a matched phrase to the interview type it implies.
TYPE_HINTS: list[tuple[str, str]] = [
    ("recruiter screen", InterviewTypeKey.RECRUITER_SCREEN.value),
    ("recruiter call", InterviewTypeKey.RECRUITER_SCREEN.value),
    ("recruiter", InterviewTypeKey.RECRUITER_SCREEN.value),
    ("phone screen", InterviewTypeKey.HR_SCREEN.value),
    ("hr screen", InterviewTypeKey.HR_SCREEN.value),
    ("hiring manager", InterviewTypeKey.HIRING_MANAGER.value),
    ("system design", InterviewTypeKey.SYSTEM_DESIGN.value),
    ("architecture", InterviewTypeKey.SYSTEM_DESIGN.value),
    ("machine learning", InterviewTypeKey.MACHINE_LEARNING.value),
    (" ml ", InterviewTypeKey.MACHINE_LEARNING.value),
    ("coding", InterviewTypeKey.CODING.value),
    ("live code", InterviewTypeKey.CODING.value),
    ("pair program", InterviewTypeKey.CODING.value),
    ("take home", InterviewTypeKey.TAKE_HOME.value),
    ("take-home", InterviewTypeKey.TAKE_HOME.value),
    ("assessment", InterviewTypeKey.ONLINE_ASSESSMENT.value),
    ("online test", InterviewTypeKey.ONLINE_ASSESSMENT.value),
    ("behavioral", InterviewTypeKey.BEHAVIORAL.value),
    ("behavioural", InterviewTypeKey.BEHAVIORAL.value),
    ("culture", InterviewTypeKey.CULTURE_FIT.value),
    ("values", InterviewTypeKey.CULTURE_FIT.value),
    ("panel", InterviewTypeKey.PANEL.value),
    ("final round", InterviewTypeKey.FINAL.value),
    ("final interview", InterviewTypeKey.FINAL.value),
    ("technical", InterviewTypeKey.TECHNICAL.value),
]

#: Score at or above which the UI shows a "Possible interview" suggestion.
SUGGESTION_THRESHOLD = 0.5

#: Common title shapes: "Acme — Technical Interview", "Interview: Acme",
#: "Acme <> Jane Doe".
_TITLE_COMPANY_PATTERNS = [
    re.compile(
        r"^\s*([A-Z][\w&.\- ]{1,40}?)\s*[|\u2013\u2014/:<>-]{1,3}\s*.*interview", re.I
    ),
    re.compile(r"interview\s*[|\u2013\u2014/:-]\s*([A-Z][\w&.\- ]{1,40})", re.I),
    re.compile(r"^\s*([A-Z][\w&.\- ]{1,40}?)\s*<>\s*", re.I),
]

_ROUND_RE = re.compile(r"\b(?:round|r)\s*#?\s*(\d{1,2})\b", re.IGNORECASE)


@dataclass
class DetectionResult:
    score: float
    reasons: list[str] = field(default_factory=list)
    suggested_type: str | None = None
    suggested_company: str | None = None
    suggested_round: int | None = None

    @property
    def is_suggestion(self) -> bool:
        return self.score >= SUGGESTION_THRESHOLD


def _domain(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return email.rsplit("@", 1)[-1].strip().lower()


def _company_from_domain(domain: str | None) -> str | None:
    if not domain:
        return None
    if domain in GENERIC_EMAIL_DOMAINS or domain.endswith(ATS_DOMAINS):
        return None
    label = domain.split(".")[0]
    if len(label) < 2:
        return None
    return label.replace("-", " ").title()


def detect(
    *,
    title: str | None,
    description: str | None = None,
    location: str | None = None,
    meeting_url: str | None = None,
    organizer_email: str | None = None,
    organizer_name: str | None = None,
    attendee_emails: list[str] | None = None,
) -> DetectionResult:
    """Score how likely a calendar event is to be an interview."""
    title_text = (title or "").lower()
    body_text = " ".join(filter(None, [description, location])).lower()
    haystack = f" {title_text} {body_text} "

    score = 0.0
    reasons: list[str] = []

    for phrase, weight in STRONG_SIGNALS.items():
        if phrase in title_text:
            score += weight
            reasons.append(f'Title contains "{phrase}"')
        elif phrase in body_text:
            score += weight * 0.5
            reasons.append(f'Description mentions "{phrase}"')

    for phrase, weight in MEDIUM_SIGNALS.items():
        if phrase in title_text:
            score += weight
            reasons.append(f'Title mentions "{phrase}"')
        elif phrase in body_text:
            score += weight * 0.4

    url_blob = " ".join(filter(None, [meeting_url, description, location])).lower()
    if any(domain in url_blob for domain in ASSESSMENT_DOMAINS):
        score += 0.6
        reasons.append("Links to a coding-assessment platform")

    organizer_domain = _domain(organizer_email)
    all_domains = {organizer_domain} | {
        _domain(email) for email in (attendee_emails or [])
    }
    all_domains.discard(None)
    if any(d and d.endswith(ATS_DOMAINS) for d in all_domains):
        score += 0.5
        reasons.append("Invite came from a recruiting system")

    if organizer_name and any(
        word in organizer_name.lower() for word in ("recruit", "talent", "hiring")
    ):
        score += 0.3
        reasons.append("Organiser looks like a recruiter")

    for phrase, weight in NEGATIVE_SIGNALS.items():
        if phrase in haystack:
            score -= weight
            reasons.append(f'Looks routine — mentions "{phrase}"')

    score = max(0.0, min(1.0, round(score, 3)))

    suggested_type = None
    for phrase, type_key in TYPE_HINTS:
        if phrase in haystack:
            suggested_type = type_key
            break
    if suggested_type is None and score >= SUGGESTION_THRESHOLD:
        suggested_type = InterviewTypeKey.OTHER.value

    round_match = _ROUND_RE.search(title or "")
    suggested_round = int(round_match.group(1)) if round_match else None

    return DetectionResult(
        score=score,
        reasons=reasons[:6],
        suggested_type=suggested_type,
        suggested_company=(
            _company_from_title(title) or _company_from_domain(organizer_domain)
        ),
        suggested_round=suggested_round,
    )


def _company_from_title(title: str | None) -> str | None:
    if not title:
        return None
    for pattern in _TITLE_COMPANY_PATTERNS:
        match = pattern.search(title)
        if match:
            candidate = match.group(1).strip(" -|:<>")
            # Reject generic words that happen to sit in that position.
            if candidate.lower() in {"interview", "technical", "final", "phone", "onsite"}:
                continue
            if 1 < len(candidate) <= 40:
                return candidate
    return None
