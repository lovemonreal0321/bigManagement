"""The signing key must survive a restart.

Regression test for a bug that made the app unusable on a fresh machine: with
SECRET_KEY unset, a new random key was generated per process, so any restart —
or a second uvicorn worker — invalidated tokens the instant they were issued
and the user was told their session had expired seconds after signing in.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import SECRET_KEY_FILE_NAME, _load_or_create_secret_key


def test_key_is_created_once_and_reused(tmp_path: Path) -> None:
    first, persisted_first = _load_or_create_secret_key(tmp_path)
    second, persisted_second = _load_or_create_secret_key(tmp_path)

    assert persisted_first and persisted_second
    assert first == second, "a restart must not change the signing key"
    assert (tmp_path / SECRET_KEY_FILE_NAME).read_text().strip() == first


def test_key_is_long_enough_to_be_a_real_secret(tmp_path: Path) -> None:
    key, _ = _load_or_create_secret_key(tmp_path)
    assert len(key) >= 32


def test_separate_installs_get_separate_keys(tmp_path: Path) -> None:
    a, _ = _load_or_create_secret_key(tmp_path / "one")
    b, _ = _load_or_create_secret_key(tmp_path / "two")
    assert a != b


def test_blank_file_is_replaced(tmp_path: Path) -> None:
    """A truncated or empty key file must not yield an empty secret."""
    (tmp_path / SECRET_KEY_FILE_NAME).write_text("   \n")
    key, persisted = _load_or_create_secret_key(tmp_path)
    assert persisted
    assert key.strip()


def test_unwritable_location_reports_ephemeral(tmp_path: Path) -> None:
    """When it cannot persist, it must say so rather than pretend."""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o500)  # read + execute, no write
    try:
        key, persisted = _load_or_create_secret_key(blocked)
        assert key  # still usable for this process
        assert persisted is False
    finally:
        blocked.chmod(0o700)


def test_token_survives_a_simulated_restart(tmp_path: Path, monkeypatch) -> None:
    """Issue a token, rebuild settings as a restart would, and still decode it."""
    import app.core.config as config
    from app.core import security

    key, _ = _load_or_create_secret_key(tmp_path)
    monkeypatch.setattr(config.settings, "secret_key", key)
    token, _expires = security.create_access_token("user-123")

    # A restart re-reads the key from disk rather than generating a new one.
    reloaded, _ = _load_or_create_secret_key(tmp_path)
    monkeypatch.setattr(config.settings, "secret_key", reloaded)

    claims = security.decode_access_token(token)
    assert claims is not None, "token must still verify after a restart"
    assert claims["sub"] == "user-123"


def test_token_does_not_survive_a_changed_key(monkeypatch) -> None:
    """The inverse, so the test above is proving something."""
    import app.core.config as config
    from app.core import security

    monkeypatch.setattr(config.settings, "secret_key", "key-one-" + "x" * 40)
    token, _ = security.create_access_token("user-123")
    monkeypatch.setattr(config.settings, "secret_key", "key-two-" + "y" * 40)
    assert security.decode_access_token(token) is None


@pytest.mark.parametrize("configured", [True, False])
def test_ephemeral_flag_reflects_reality(configured: bool) -> None:
    from app.core.config import Settings

    settings = (
        Settings(secret_key="explicitly-configured-" + "z" * 30)
        if configured
        else Settings()
    )
    if configured:
        assert settings.secret_key_is_ephemeral is False
