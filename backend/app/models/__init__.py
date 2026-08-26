"""ORM models.

Every model is imported here so that `Base.metadata` is fully populated for
Alembic autogenerate and `create_all` in tests.
"""

from app.models.activity import Activity
from app.models.application import Application, ApplicationNote
from app.models.calendar import CalendarConnection, CalendarEvent, ExternalCalendar
from app.models.email import AiExtraction, EmailAccount, EmailMessage
from app.models.followup import FollowUp
from app.models.interview import InterviewEvent, InterviewStage, InterviewType
from app.models.job import Job
from app.models.person import Person, ResumeVersion
from app.models.workspace import User, Workspace

__all__ = [
    "Activity",
    "AiExtraction",
    "Application",
    "ApplicationNote",
    "CalendarConnection",
    "CalendarEvent",
    "EmailAccount",
    "EmailMessage",
    "ExternalCalendar",
    "FollowUp",
    "InterviewEvent",
    "InterviewStage",
    "InterviewType",
    "Job",
    "Person",
    "ResumeVersion",
    "User",
    "Workspace",
]
