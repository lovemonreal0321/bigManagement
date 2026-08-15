"""Application error types and their HTTP translation.

Spec §58: users see a friendly message, never a raw server error or traceback.
Every error carries a stable machine `code` so the frontend can react (e.g.
render a "Reconnect" button for `calendar_connection_expired`).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for expected, user-presentable failures."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "error"
    message: str = "Something went wrong."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or {}
        self.retryable = retryable
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "retryable": self.retryable,
            }
        }


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "That record could not be found."


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"
    message = "Some of the information provided is not valid."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "That action conflicts with the current state."


class AuthError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"
    message = "Please sign in again."


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"
    message = "You do not have access to that."


class ProviderNotConfiguredError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "provider_not_configured"
    message = "This calendar provider has not been configured on the server yet."


class CalendarConnectionExpiredError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "calendar_connection_expired"
    message = "The calendar connection expired. Please reconnect the account."


class CalendarSyncError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "calendar_sync_failed"
    message = "Unable to sync the calendar right now."

    def __init__(self, message: str | None = None, **kwargs: Any) -> None:
        kwargs.setdefault("retryable", True)
        super().__init__(message, **kwargs)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Flatten pydantic's structure into "field: message" lines the UI can show.
        fields: dict[str, str] = {}
        for err in exc.errors():
            location = [str(part) for part in err.get("loc", []) if part != "body"]
            fields[".".join(location) or "request"] = err.get("msg", "Invalid value")
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Some of the information provided is not valid.",
                    "details": {"fields": fields},
                    "retryable": False,
                }
            },
        )

    @app.exception_handler(IntegrityError)
    async def _integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
        logger.warning("integrity error: %s", exc, exc_info=False)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": {
                    "code": "conflict",
                    "message": (
                        "That change conflicts with existing data. It may already "
                        "exist, or something it depends on was removed."
                    ),
                    "details": {},
                    "retryable": False,
                }
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def _db_error(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("database error", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "database_error",
                    "message": "Unable to reach the database. Please try again.",
                    "details": {},
                    "retryable": True,
                }
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Log the real thing server-side; return something safe to the client.
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Something went wrong on our end. Please try again.",
                    "details": {},
                    "retryable": True,
                }
            },
        )
