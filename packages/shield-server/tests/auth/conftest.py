"""ADR-0013 unit_auth — shared fixtures.

Brings up a fully-wired enterprise app against ``MemoryDatabase`` so unit
tests exercise the REAL routes/dep/session/totp/password code paths (and the
``python-auth`` 90% scoped coverage floor hits all the same modules CI does).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from shield_server.app import create_app
from shield_server.config import Settings
from shield_server.migrate import _SEED_DEMO_ORG  # noqa: F401 — reserved for future use
from shield_server.storage import build_memory_storage


@pytest.fixture(autouse=True)
def _enterprise_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set up the enterprise-mode env that the python-auth CI job uses."""
    monkeypatch.setenv("SHIELD_AUTH_MODE", "enterprise")
    monkeypatch.setenv("SHIELD_EMAIL_BACKEND", "file")
    monkeypatch.setenv("SHIELD_EMAIL_FILE_DIR", "/tmp/shield-test-mailbox")
    monkeypatch.setenv(
        "SHIELD_SESSION_SECRETS",
        "k1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    )
    monkeypatch.setenv(
        "SHIELD_PASSWORD_PEPPERS",
        "p1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    )
    monkeypatch.setenv(
        "SHIELD_AUTH_FERNET_KEYS",
        "f1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )
    monkeypatch.setenv("SHIELD_ALLOW_INSECURE_COOKIES", "1")


@pytest.fixture
def settings() -> Settings:
    return Settings.from_env()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Enterprise-mode TestClient with memory storage + a seeded demo-org row.

    The memory storage models the new auth SQL shapes (users/sessions/...);
    routes hit them through the exact production SQL strings.
    """
    storage = build_memory_storage()
    # The memory DB doesn't model the organizations table seed; auth routes
    # don't read organizations directly, so omitting that row is harmless.
    app = create_app(storage=storage, settings=Settings.from_env())
    with TestClient(app) as c:
        # Mount storage onto the client for fixture-level introspection.
        c.app_storage = storage  # type: ignore[attr-defined]
        yield c
    # Cleanup the file-mailbox between tests so message counts are deterministic.
    import shutil

    shutil.rmtree(os.environ.get("SHIELD_EMAIL_FILE_DIR", ""), ignore_errors=True)


def signup(
    client: TestClient, *, email: str = "alice@example.com", password: str = "shield-pw-1"
) -> dict:
    """Sign up a fresh user; return the parsed response body."""
    r = client.post(
        "/v1/auth/sign-up", json={"email": email, "password": password, "name": "Alice"}
    )
    r.raise_for_status()
    return r.json()


def signin(client: TestClient, *, email: str, password: str, totp_code: str | None = None) -> dict:
    body: dict = {"email": email, "password": password}
    if totp_code is not None:
        body["totp_code"] = totp_code
    r = client.post("/v1/auth/sign-in", json=body)
    r.raise_for_status()
    return r.json()
