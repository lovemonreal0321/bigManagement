"""Moonshot / Kimi client.

The API is OpenAI-compatible, so this is a thin, dependency-free wrapper over
the chat-completions endpoint rather than another SDK.

Two things are deliberate:

* **JSON mode plus a schema in the prompt.** Structured output is requested via
  `response_format`, and the shape is also spelled out in the system prompt, so
  a model that ignores the flag still tends to produce parseable output. The
  parser then tolerates code fences and leading prose.
* **The app works without a key.** Everything degrades to "no enrichment" and
  says so; nothing else in the product depends on this being configured.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)


class AiNotConfiguredError(AppError):
    status_code = 503
    code = "ai_not_configured"
    message = (
        "AI enrichment is not configured. Add KIMI_API_KEY to the backend .env "
        "file and restart."
    )


class AiError(AppError):
    status_code = 502
    code = "ai_request_failed"
    message = "The AI model could not be reached."

    def __init__(self, message: str | None = None, **kwargs: Any) -> None:
        kwargs.setdefault("retryable", True)
        super().__init__(message, **kwargs)


@dataclass
class AiResponse:
    content: str
    model: str
    tokens_used: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    def json(self) -> dict[str, Any]:
        return parse_json_object(self.content)


def is_configured() -> bool:
    return settings.kimi_configured


def complete(
    *,
    system: str,
    user: str,
    temperature: float = 0.1,
    max_tokens: int | None = None,
    json_mode: bool = True,
) -> AiResponse:
    """One chat completion. Raises `AiNotConfiguredError` when there is no key."""
    if not settings.kimi_api_key:
        raise AiNotConfiguredError()
    if not settings.ai_enabled:
        raise AiNotConfiguredError(
            "AI enrichment is switched off (AI_ENABLED=false).", code="ai_disabled"
        )

    payload: dict[str, Any] = {
        "model": settings.kimi_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        # Low temperature: this is extraction, not writing.
        "temperature": temperature,
        "max_tokens": max_tokens or settings.kimi_max_output_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    url = f"{settings.kimi_base_url.rstrip('/')}/chat/completions"
    try:
        with httpx.Client(timeout=settings.kimi_timeout_seconds) as client:
            response = client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.kimi_api_key}",
                    "Content-Type": "application/json",
                },
            )
    except httpx.TimeoutException as exc:
        raise AiError("The AI model took too long to respond.", code="ai_timeout") from exc
    except httpx.HTTPError as exc:
        logger.warning("kimi transport error: %s", exc)
        raise AiError(
            f"Could not reach the AI endpoint at {settings.kimi_base_url}.",
            code="ai_unreachable",
        ) from exc

    if response.status_code == 401:
        raise AiError(
            "The AI provider rejected the API key. Check KIMI_API_KEY, and that "
            "it matches the endpoint region (.ai keys do not work on .cn).",
            code="ai_unauthorized",
            retryable=False,
        )
    if response.status_code == 429:
        raise AiError(
            "The AI provider is rate limiting requests. Try again shortly.",
            code="ai_rate_limited",
        )
    if response.status_code >= 400:
        raise AiError(
            f"The AI provider returned an error: {_error_detail(response)}",
            code="ai_api_error",
            details={"status": response.status_code},
            retryable=False,
        )

    try:
        body = response.json()
    except ValueError as exc:  # pragma: no cover - non-JSON success body
        raise AiError("The AI provider returned an unreadable response.") from exc

    choices = body.get("choices") or []
    if not choices:
        raise AiError("The AI provider returned no completion.")

    usage = body.get("usage") or {}
    return AiResponse(
        content=(choices[0].get("message") or {}).get("content") or "",
        model=body.get("model") or settings.kimi_model,
        tokens_used=int(usage.get("total_tokens") or 0),
        raw=body,
    )


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return (response.text or response.reason_phrase)[:200]
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)[:200]
    return str(error or payload)[:200]


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json_object(content: str) -> dict[str, Any]:
    """Parse a JSON object out of a model response.

    Tolerates the three things models actually do: fenced code blocks, prose
    before the JSON, and trailing commentary.
    """
    if not content or not content.strip():
        raise AiError("The AI returned an empty response.", code="ai_empty_response")

    text = content.strip()

    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Fall back to the outermost {...} span.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    raise AiError(
        "The AI response could not be read as JSON.",
        code="ai_unparseable_response",
        retryable=False,
    )
