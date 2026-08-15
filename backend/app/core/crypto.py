"""Symmetric encryption for stored credentials.

Used for IMAP app passwords, which — unlike OAuth tokens — cannot be scoped or
revoked per-app by the provider, so they must not sit in the database as
plaintext.

The key is derived from `SECRET_KEY`. That has one consequence worth stating
plainly: **if `SECRET_KEY` changes, previously stored passwords cannot be
decrypted** and those accounts must be reconnected. `SECRET_KEY` defaults to a
random value per boot, so anyone using IMAP must pin it in `.env` — the app
warns loudly at connect time if it looks unpinned.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

logger = logging.getLogger(__name__)


class DecryptionError(RuntimeError):
    """Stored ciphertext could not be read with the current key."""


def _fernet() -> Fernet:
    # Fernet needs a 32-byte urlsafe-base64 key; SECRET_KEY is arbitrary text.
    digest = hashlib.sha256(f"jscc-credential-v1:{settings.secret_key}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise DecryptionError(
            "Stored credentials could not be read. This usually means SECRET_KEY "
            "changed since the account was connected — reconnect the account."
        ) from exc
