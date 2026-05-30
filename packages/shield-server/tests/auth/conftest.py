"""ADR-0013 unit_auth — shared fixtures.

Brings up a fully-wired enterprise app against ``MemoryDatabase`` so unit
tests exercise the REAL routes / dep / session / totp / password code paths
(and the ``python-auth`` 90% scoped coverage floor hits all the same modules
CI does).

Two client fixtures:

  * ``client`` — enterprise mode (the production default for prod
    deployments). ``/v1/auth/sign-up`` is hard-disabled per ADR-0013 §A1.c
    (D5 implementation detail); tests that need an authenticated user
    bootstrap via ``bootstrap_admin_via_storage(client, ...)``.

  * ``open_client`` — open mode with the ``auth_router`` explicitly mounted
    so the few tests that EXERCISE the public ``/v1/auth/sign-up`` route
    have a target. Open-mode production behaviour is byte-unchanged (the
    auth_router is NOT mounted by ``create_app`` under ``open``); this
    fixture mounts it test-only.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from shield_server.app import create_app
from shield_server.auth import (
    PasswordHasherService,
    TotpService,
    build_email_sender,
)
from shield_server.auth.routes import auth_router
from shield_server.auth.sessions import build_cookie_kwargs, create_session
from shield_server.auth.users import create_user
from shield_server.auth.utils import now_ms
from shield_server.config import Settings
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
    # Enterprise mode refuses the publicly-known dev signing seed at startup
    # (config.DEV_DEFAULT_SIGNING_KEY); inject a real non-default key, as a
    # real enterprise deployment must.
    monkeypatch.setenv(
        "SHIELD_SERVER_SIGNING_KEY",
        "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
    )
    monkeypatch.setenv("SHIELD_ALLOW_INSECURE_COOKIES", "1")


@pytest.fixture
def settings() -> Settings:
    return Settings.from_env()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Enterprise-mode TestClient with memory storage.

    The memory storage models the new auth SQL shapes (users/sessions/...);
    routes hit them through the exact production SQL strings. Sign-up is
    DISABLED in this mode per ADR-0013 §A1.c — tests bootstrap users via
    ``bootstrap_admin_via_storage(client, ...)``.
    """
    storage = build_memory_storage()
    app = create_app(storage=storage, settings=Settings.from_env())
    with TestClient(app) as c:
        c.app_storage = storage  # type: ignore[attr-defined]
        yield c
    import shutil

    shutil.rmtree(os.environ.get("SHIELD_EMAIL_FILE_DIR", ""), ignore_errors=True)


@pytest.fixture
def open_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Open-mode TestClient with ``auth_router`` MANUALLY mounted.

    Production open-mode behaviour is preserved (``create_app`` only mounts
    ``auth_router`` under enterprise); this fixture explicitly attaches the
    router + the password / TOTP / email state so tests can exercise the
    open-mode-permitted ``/v1/auth/sign-up`` happy path (§A1.c
    "open mode 行为不变" guarantee verified by tests).
    """
    monkeypatch.setenv("SHIELD_AUTH_MODE", "open")
    settings = Settings.from_env().with_allow_open_auth(True)
    storage = build_memory_storage()
    app = create_app(storage=storage, settings=settings)
    # Open mode does NOT auto-mount; attach the router + the enterprise-only
    # ``app.state`` it depends on, just for the test surface.
    app.include_router(auth_router)
    app.state.password_hasher = PasswordHasherService.from_settings(settings)
    app.state.totp_service = TotpService.from_settings(settings)
    app.state.email_sender = build_email_sender(settings)
    with TestClient(app) as c:
        c.app_storage = storage  # type: ignore[attr-defined]
        yield c
    import shutil

    shutil.rmtree(os.environ.get("SHIELD_EMAIL_FILE_DIR", ""), ignore_errors=True)


def bootstrap_admin_via_storage(
    client: TestClient,
    *,
    email: str = "admin@example.com",
    password: str = "shield-pw-1",
    name: str = "Admin",
    role: str = "org_owner",
    org_id: str = "demo-org",
) -> dict:
    """Direct-DB bootstrap of an authenticated user.

    Replaces the ``/v1/auth/sign-up`` route for test SETUP under enterprise
    mode (where sign-up is hard-disabled per ADR-0013 §A1.c). Hashes the
    password via the real ``PasswordHasherService`` (so §A1 argon2id semantics
    are exercised), inserts ``users`` + ``memberships`` rows, mints a session
    row, and sets the ``shield_session`` cookie on the client.

    Returns the same shape ``/v1/auth/sign-up`` historically returned
    (``user_id, email, role, org_id, csrf_token``) so call sites that read
    those fields keep working.
    """
    import asyncio

    storage = client.app_storage  # type: ignore[attr-defined]
    app = client.app
    hasher: PasswordHasherService = app.state.password_hasher

    async def _seed() -> dict:
        user = await create_user(
            storage.db,
            hasher,
            email=email,
            password=password,
            name=name,
            org_id=org_id,
            role=role,  # type: ignore[arg-type]
        )
        sess = await create_session(
            storage.db,
            user_id=user.user_id,
            ttl_seconds=app.state.settings.session_ttl_seconds,
        )
        cookie_kwargs = build_cookie_kwargs(app.state.settings)
        # Use dict-style cookie set so httpx anchors it to the client's
        # base_url (testserver) automatically — explicit ``domain="testserver"``
        # on httpx.Cookies.set does NOT match how httpx scopes by base_url and
        # silently drops the cookie on subsequent requests.
        client.cookies[cookie_kwargs["key"]] = sess.raw_token
        return {
            "user_id": user.user_id,
            "email": user.email,
            "role": role,
            "org_id": org_id,
            "csrf_token": sess.csrf_token,
        }

    return asyncio.run(_seed())


def signup(
    client: TestClient, *, email: str = "alice@example.com", password: str = "shield-pw-1"
) -> dict:
    """Legacy helper — now an alias for ``bootstrap_admin_via_storage``.

    The original ``client.post('/v1/auth/sign-up', ...)`` call no longer
    works under enterprise mode (ADR-0013 §A1.c). All existing call sites
    keep working because the returned dict has the same shape.
    """
    return bootstrap_admin_via_storage(client, email=email, password=password)


def signin(client: TestClient, *, email: str, password: str, totp_code: str | None = None) -> dict:
    """Sign in via the real ``/v1/auth/sign-in`` route (still admitted in
    enterprise mode — only ``/sign-up`` is disabled per §A1.c)."""
    body: dict = {"email": email, "password": password}
    if totp_code is not None:
        body["totp_code"] = totp_code
    r = client.post("/v1/auth/sign-in", json=body)
    r.raise_for_status()
    return r.json()


# ``now_ms`` is re-exported for tests that need an obvious timestamp value
# in fixtures; keeps the import surface small and centralised.
__all__ = ["bootstrap_admin_via_storage", "now_ms", "signin", "signup"]
