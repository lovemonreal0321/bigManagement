"""Database engine, session factory and the declarative base.

SQLite specifics that matter here:

* Foreign keys are **off** by default in SQLite. Without the pragma below,
  every `ForeignKey` in the schema would be decorative. We turn it on for every
  connection.
* WAL journalling lets the API read while a background sync writes.
* `check_same_thread=False` is required because FastAPI runs sync endpoints in
  a threadpool, so a session may touch a connection from a different thread.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


def _make_engine(url: str) -> Engine:
    connect_args: dict[str, Any] = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(
        url,
        connect_args=connect_args,
        echo=False,
        future=True,
        # A single shared file DB; the pool keeps connections warm.
        pool_pre_ping=True,
    )


engine = _make_engine(settings.database_url)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    """Enable FK enforcement + WAL on every SQLite connection."""
    module = type(dbapi_connection).__module__
    if "sqlite3" not in module:
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        # Wait rather than immediately raising "database is locked" when the
        # sync job and a request collide.
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def session_scope() -> Session:
    """Standalone session for scripts and background jobs.

    Caller owns commit/rollback/close.
    """
    return SessionLocal()
