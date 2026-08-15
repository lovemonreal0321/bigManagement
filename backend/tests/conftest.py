"""Pytest fixtures.

The environment is configured *before* any `app.*` import so that the settings
singleton (and therefore the engine) points at a throwaway database rather than
the developer's real one.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

_TMP_DIR = Path(tempfile.mkdtemp(prefix="jobsearch-tests-"))
# Ignore the developer's .env entirely. Otherwise real OAuth keys or a custom
# model would leak into the suite and tests would pass or fail per machine.
os.environ["JSCC_ENV_FILE"] = ""
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DIR / 'test.db'}"
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ["AUTO_MIGRATE"] = "false"
os.environ["SECRET_KEY"] = "test-secret-key-not-used-anywhere-real"
os.environ["ADMIN_USERNAME"] = "admin321"
os.environ["ADMIN_PASSWORD"] = "admin321"
os.environ["DEFAULT_TIMEZONE"] = "America/New_York"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.domains.auth.service import ensure_bootstrap  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Person, Workspace  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_database() -> Iterator[None]:
    """Every test starts from an empty schema."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def workspace(db: Session) -> Workspace:
    workspace, _user = ensure_bootstrap(db)
    return workspace


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin321", "password": "admin321"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def make_person(db: Session, workspace: Workspace):
    """Factory for people, so tests can name their own cast."""

    def _make(
        name: str = "John Carter",
        *,
        display_name: str | None = None,
        color: str = "#2563eb",
        timezone: str = "America/New_York",
    ) -> Person:
        person = Person(
            workspace_id=workspace.id,
            name=name,
            display_name=display_name or name.split()[0],
            initials="".join(p[0] for p in name.split()[:2]).upper(),
            color=color,
            timezone=timezone,
        )
        db.add(person)
        db.commit()
        return person

    return _make
