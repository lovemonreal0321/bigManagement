"""Prompts for interview extraction.

Versioned: `PROMPT_VERSION` is stored on every extraction, so when the prompt
changes it is obvious which results came from which wording.
"""

from __future__ import annotations

from dataclasses import dataclass

PROMPT_VERSION = "2026-08-15.1"

SYSTEM_PROMPT = """\
You extract structured facts about a job interview from a calendar event and \
the emails related to it.

You are given ONE calendar event and the emails matched to it. Your job is to \
say what interview this is: which company, which role, and which round.

Rules:
- Only state what the sources support. Never invent a company, role or round.
- If something is not stated, use null. Do not guess a plausible value.
- The round number must come from explicit evidence: wording like "second \
round", "R3", "final", "next step", or a clear sequence in the thread. If the \
emails do not establish it, use null.
- "is_interview" is false for ordinary meetings, personal events, standups, \
and recruiter newsletters or marketing mail.
- confidence reflects how certain you are about company AND role together. \
Use below 0.5 when you are inferring rather than reading.

Return ONLY a JSON object with exactly this shape:

{
  "is_interview": boolean,
  "company": string|null,
  "role": string|null,
  "round_number": integer|null,
  "interview_type": one of ["recruiter_screen","hr_screen","hiring_manager",
      "technical","coding","machine_learning","system_design","behavioral",
      "culture_fit","panel","final","online_assessment","take_home","other"]|null,
  "stage_name": string|null,
  "interviewers": [string],
  "location_or_link": string|null,
  "salary_mentioned": string|null,
  "next_steps": string|null,
  "confidence": number between 0 and 1,
  "reasoning": string (one or two sentences citing the evidence)
}
"""


@dataclass
class ExtractionSource:
    """The evidence given to the model for one event."""

    event_title: str
    event_start: str
    event_end: str
    event_location: str | None
    event_description: str | None
    organizer: str | None
    attendees: list[str]
    person_name: str
    person_email: str | None
    messages: list[dict[str, str]]
    known_companies: list[str]


def build_user_prompt(source: ExtractionSource) -> str:
    lines: list[str] = []
    lines.append("CALENDAR EVENT")
    lines.append(f"Title: {source.event_title}")
    lines.append(f"Starts: {source.event_start}")
    lines.append(f"Ends: {source.event_end}")
    if source.event_location:
        lines.append(f"Location: {source.event_location}")
    if source.organizer:
        lines.append(f"Organizer: {source.organizer}")
    if source.attendees:
        lines.append(f"Attendees: {', '.join(source.attendees[:15])}")
    if source.event_description:
        lines.append(f"Description: {source.event_description[:1500]}")

    lines.append("")
    lines.append(f"CANDIDATE: {source.person_name}" + (f" <{source.person_email}>" if source.person_email else ""))

    if source.known_companies:
        # Helps the model reuse an existing application rather than inventing a
        # near-duplicate company name.
        lines.append("")
        lines.append(
            "COMPANIES ALREADY TRACKED FOR THIS CANDIDATE (prefer an exact match "
            "if the event clearly belongs to one): "
            + ", ".join(source.known_companies[:40])
        )

    lines.append("")
    if source.messages:
        lines.append(f"RELATED EMAILS ({len(source.messages)}, newest first)")
        for index, message in enumerate(source.messages, start=1):
            lines.append("")
            lines.append(f"--- Email {index} ---")
            lines.append(f"Date: {message.get('date', 'unknown')}")
            lines.append(f"From: {message.get('from', 'unknown')}")
            lines.append(f"Subject: {message.get('subject', '(no subject)')}")
            body = (message.get("body") or "").strip()
            if body:
                lines.append("Body:")
                lines.append(body)
    else:
        lines.append("RELATED EMAILS: none found.")
        lines.append(
            "Base your answer on the calendar event alone, and lower confidence "
            "accordingly."
        )

    lines.append("")
    lines.append("Return the JSON object now.")
    return "\n".join(lines)
