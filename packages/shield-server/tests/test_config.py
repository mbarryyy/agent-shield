"""Settings.from_env() startup validation — P3 signing-key fail-loud.

Enterprise deployments must inject a real ``SHIELD_SERVER_SIGNING_KEY``; the
``"A" * 43`` dev default is a publicly-known Ed25519 seed (it is the genesis
chain-hash constant) and must never silently sign production verdicts. This
mirrors the existing §A1 argon2-cap / §A4 email-backend ``from_env`` refusals:
a misconfigured enterprise deployment fails LOUDLY at startup, not silently.
``open`` / dev mode is unaffected (the dev default is expected there).
"""

from __future__ import annotations

import pytest
from shield_server.config import DEV_DEFAULT_SIGNING_KEY, Settings


def test_from_env_raises_enterprise_with_default_signing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enterprise + the dev default signing key ⇒ refuse to start."""
    monkeypatch.setenv("SHIELD_AUTH_MODE", "enterprise")
    monkeypatch.delenv("SHIELD_SERVER_SIGNING_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SHIELD_SERVER_SIGNING_KEY"):
        Settings.from_env()


def test_from_env_ok_enterprise_with_real_signing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enterprise + a real (non-default) signing key ⇒ constructs fine."""
    real_key = "B" * 43
    monkeypatch.setenv("SHIELD_AUTH_MODE", "enterprise")
    monkeypatch.setenv("SHIELD_SERVER_SIGNING_KEY", real_key)
    settings = Settings.from_env()
    assert settings.is_enterprise
    assert settings.server_signing_key == real_key


def test_from_env_ok_open_with_default_signing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Open/dev mode with the dev default key is allowed (行为不变)."""
    monkeypatch.setenv("SHIELD_AUTH_MODE", "open")
    monkeypatch.delenv("SHIELD_SERVER_SIGNING_KEY", raising=False)
    settings = Settings.from_env()
    assert settings.is_open
    assert settings.server_signing_key == DEV_DEFAULT_SIGNING_KEY
