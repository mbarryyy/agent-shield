"""ADR-0013 — Coverage top-up for dep / email / routes / cli edge paths.

Targets the ``python-auth`` 90% scoped floor on ``shield_server.auth``.
Each test exercises a deliberately under-covered branch (timeout / refusal /
error / smtp / argparse) with a minimal monkeypatch.
"""

from __future__ import annotations

import asyncio
import os

import pyotp
import pytest
from fastapi.testclient import TestClient
from shield_server.auth import principal_context
from shield_server.auth.dep import require_api_key_principal
from shield_server.auth.email import Message, SmtpEmailSender
from shield_server.auth.principal import Principal, synthetic_dev_principal
from shield_server.auth.sessions import (
    create_session,
    list_sessions_for_user,
    lookup_session,
    revoke_all_for_user,
    rotate_token,
)
from shield_server.auth.utils import now_ms
from shield_server.config import Settings
from shield_server.errors import AppError
from shield_server.storage import build_memory_storage

pytestmark = pytest.mark.unit_auth


# --- dep layer additional coverage ----------------------------------- #


@pytest.mark.asyncio
async def test_principal_context_enterprise_missing_auth_raises_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHIELD_AUTH_MODE", "enterprise")
    monkeypatch.setenv("SHIELD_SESSION_SECRETS", "k1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    monkeypatch.setenv("SHIELD_PASSWORD_PEPPERS", "p1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    monkeypatch.setenv("SHIELD_AUTH_FERNET_KEYS", "f1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    monkeypatch.setenv("SHIELD_EMAIL_BACKEND", "file")
    from types import SimpleNamespace

    from starlette.requests import Request

    storage = build_memory_storage()
    app_state = SimpleNamespace(settings=Settings.from_env(), storage=storage)
    request = Request(
        {
            "type": "http",
            "headers": [],
            "app": SimpleNamespace(state=app_state),
            "state": {},
        }
    )
    with pytest.raises(AppError) as exc:
        await principal_context(request)
    assert exc.value.status_code == 401


def test_require_api_key_principal_rejects_session() -> None:
    sess_p = Principal(
        org_id="demo-org",
        user_id="u",
        role="org_owner",
        auth_kind="session",
        roles=frozenset({"org_owner"}),
    )
    with pytest.raises(AppError) as exc:
        require_api_key_principal(sess_p)
    assert exc.value.status_code == 403


def test_require_api_key_principal_admits_api_key_and_open() -> None:
    open_p = synthetic_dev_principal("demo-org")
    api_p = Principal(
        org_id="demo-org",
        user_id="api-key:x",
        role="integration_engineer",
        auth_kind="api_key",
        roles=frozenset({"integration_engineer"}),
        api_key_id="x",
    )
    assert require_api_key_principal(open_p) is open_p
    assert require_api_key_principal(api_p) is api_p


# --- sessions service coverage --------------------------------------- #


@pytest.mark.asyncio
async def test_sessions_full_lifecycle() -> None:
    storage = build_memory_storage()
    # Seed a user row so the FK is satisfied at the MemoryDatabase level.
    storage.db.users["u1"] = {"user_id": "u1", "email": "u@x", "created_at": now_ms()}
    sess = await create_session(storage.db, user_id="u1", ttl_seconds=60)
    # Looking up by raw token resolves.
    row = await lookup_session(storage.db, raw_token=sess.raw_token)
    assert row is not None and row.user_id == "u1"
    # Lookup with empty / wrong token returns None.
    assert await lookup_session(storage.db, raw_token="") is None
    assert await lookup_session(storage.db, raw_token="wrong-token") is None
    # Listing sessions by user.
    listed = await list_sessions_for_user(storage.db, user_id="u1")
    assert len(listed) == 1
    # Rotation issues new (raw, csrf).
    new_raw, new_csrf = await rotate_token(storage.db, session_id=sess.session.session_id)
    assert new_raw and new_csrf
    # Old raw token no longer resolves (token_hash changed).
    assert await lookup_session(storage.db, raw_token=sess.raw_token) is None
    # New raw token resolves.
    row2 = await lookup_session(storage.db, raw_token=new_raw)
    assert row2 is not None
    # Revoke-all for user invalidates the row.
    await revoke_all_for_user(storage.db, user_id="u1")
    assert await lookup_session(storage.db, raw_token=new_raw) is None


# --- email smtp backend (mock aiosmtplib) ---------------------------- #


@pytest.mark.asyncio
async def test_smtp_email_sender_calls_aiosmtplib(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def fake_send(
        msg,
        *,
        sender,
        recipients,
        hostname,
        port,
        username,
        password,
        use_tls,
        start_tls,
        timeout,
    ) -> None:
        calls.update(
            sender=sender,
            recipients=recipients,
            hostname=hostname,
            port=port,
            message=msg,
        )

    import aiosmtplib

    monkeypatch.setattr(aiosmtplib, "send", fake_send)
    s = SmtpEmailSender(
        host="localhost",
        port=1025,
        username=None,
        password=None,
        use_tls=False,
        start_tls=False,
    )
    await s.send(Message(to="a@example.com", subject="S", body="B", from_addr="f@example.com"))
    assert calls["recipients"] == ["a@example.com"]
    assert calls["hostname"] == "localhost"
    assert calls["port"] == 1025


# --- routes /session/refresh + admin/api-keys lifecycle -------------- #


def _signup(client: TestClient, *, email: str = "alice@example.com") -> dict:
    """Bootstrap an admin via direct storage seed (enterprise mode hard-
    disables /v1/auth/sign-up per ADR-0013 §A1.c)."""
    from .conftest import bootstrap_admin_via_storage

    return bootstrap_admin_via_storage(client, email=email, password="shield-pw-1")


def test_session_refresh_rotates_cookie_with_csrf(client: TestClient) -> None:
    body = _signup(client, email="rf@example.com")
    csrf = body["csrf_token"]
    r = client.post("/v1/auth/session/refresh", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    body2 = r.json()
    assert body2["csrf_token"] and body2["csrf_token"] != csrf


def test_session_refresh_without_csrf_returns_403(client: TestClient) -> None:
    _signup(client, email="rf2@example.com")
    r = client.post("/v1/auth/session/refresh")
    assert r.status_code == 403


def test_password_change_flow(client: TestClient) -> None:
    body = _signup(client, email="pw@example.com")
    csrf = body["csrf_token"]
    r = client.post(
        "/v1/auth/password/change",
        headers={"X-CSRF-Token": csrf},
        json={"current_password": "shield-pw-1", "new_password": "shield-pw-2"},
    )
    assert r.status_code == 200


def test_password_change_wrong_current_returns_401(client: TestClient) -> None:
    body = _signup(client, email="pw2@example.com")
    csrf = body["csrf_token"]
    r = client.post(
        "/v1/auth/password/change",
        headers={"X-CSRF-Token": csrf},
        json={"current_password": "WRONG", "new_password": "shield-pw-2"},
    )
    assert r.status_code == 401


def test_email_verify_request_and_complete(client: TestClient) -> None:
    _signup(client, email="ev@example.com")
    r = client.post("/v1/auth/email/verify/request")
    assert r.status_code == 200
    storage = client.app_storage  # type: ignore[attr-defined]
    # Find the just-issued token (most recent).
    token_hash = next(iter(storage.db.email_verification_tokens))
    # We can't recover the raw token from the hash; instead issue + consume
    # via the direct helper for the assertion.
    import asyncio as _aio

    from shield_server.auth.tokens import issue

    user_id = next(iter(storage.db.users))
    issued = _aio.run(issue(storage.db, kind="email_verification", user_id=user_id))
    r2 = client.post("/v1/auth/email/verify/complete", json={"token": issued.raw})
    assert r2.status_code == 200
    _ = token_hash


def test_totp_disable_flow(client: TestClient) -> None:
    _signup(client, email="td@example.com")
    setup = client.post("/v1/auth/totp/setup").json()
    code = pyotp.TOTP(setup["secret"]).now()
    client.post("/v1/auth/totp/confirm", json={"code": code})
    # Disable requires current password + a fresh code.
    code2 = pyotp.TOTP(setup["secret"]).now()
    r = client.post(
        "/v1/auth/totp/disable",
        json={"password": "shield-pw-1", "code": code2},
    )
    assert r.status_code == 200


def test_api_keys_issue_list_revoke(client: TestClient) -> None:
    _signup(client, email="ak@example.com")
    r = client.post(
        "/v1/auth/api-keys",
        json={
            "display_name": "ci-key",
            "prefix": "as_test_",
            "agent_id_allowlist": ["ag-1", "ag-2"],
        },
    )
    assert r.status_code == 200
    issued = r.json()
    assert issued["api_key"].startswith("as_test_")
    listed = client.get("/v1/auth/api-keys").json()
    assert len(listed["api_keys"]) == 1
    api_key_id = listed["api_keys"][0]["api_key_id"]
    rd = client.delete(f"/v1/auth/api-keys/{api_key_id}")
    assert rd.status_code == 200


def test_admin_list_sessions_route(client: TestClient) -> None:
    _signup(client, email="ls@example.com")
    storage = client.app_storage  # type: ignore[attr-defined]
    user_id = next(iter(storage.db.users))
    r = client.get(f"/v1/auth/admin/users/{user_id}/sessions")
    assert r.status_code == 200
    assert len(r.json()["sessions"]) >= 1


# --- cli.py argparse path -------------------------------------------- #


def test_cli_argparse_rejects_short_password(monkeypatch: pytest.MonkeyPatch) -> None:
    from shield_server.auth import cli

    rc = cli.main(["seed-admin", "--email", "x@example.com", "--password", "shrt"])
    assert rc == 2


def test_cli_argparse_no_subcommand_prints_help(monkeypatch: pytest.MonkeyPatch) -> None:
    from shield_server.auth import cli

    rc = cli.main([])
    assert rc == 2


def test_cli_prompt_password_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from shield_server.auth.cli import _prompt_password

    # Well-known low-entropy test sentinel (XKCD-936 passphrase) — explicitly
    # signals "this is fixture data" and falls under gitleaks' generic-api-key
    # entropy threshold. NEVER use as a real credential.
    monkeypatch.setenv("SHIELD_SEED_ADMIN_PASSWORD", "correct-horse-battery-staple")
    assert _prompt_password() == "correct-horse-battery-staple"


# Suppress unused import warnings — the symbols above are intentionally
# in scope for hand-edit extension by future contributors.
_ = os
_ = asyncio
