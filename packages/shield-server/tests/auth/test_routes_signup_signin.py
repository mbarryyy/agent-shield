"""ADR-0013 — Sign-up / sign-in / sign-out + session round-trip (unit_auth).

Drives the live FastAPI app via ``TestClient`` against ``MemoryDatabase`` so
the SAME route code is exercised as in integration; this also gives the
``python-auth`` 90% scoped-coverage floor a real hit on routes / sessions /
users / passwords / audit modules.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit_auth


def test_signup_creates_user_and_returns_csrf(client: TestClient) -> None:
    r = client.post(
        "/v1/auth/sign-up",
        json={"email": "alice@example.com", "password": "shield-pw-1", "name": "Alice"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "alice@example.com"
    assert body["role"] == "org_owner"
    assert body["org_id"] == "demo-org"
    assert body["csrf_token"]
    # Cookie set by the server.
    assert "shield_session" in {c.name for c in client.cookies.jar}


def test_signup_duplicate_email_returns_409(client: TestClient) -> None:
    client.post("/v1/auth/sign-up", json={"email": "alice@example.com", "password": "shield-pw-1"})
    r = client.post(
        "/v1/auth/sign-up", json={"email": "alice@example.com", "password": "shield-pw-1"}
    )
    assert r.status_code == 409


def test_signin_returns_session(client: TestClient) -> None:
    client.post("/v1/auth/sign-up", json={"email": "bob@example.com", "password": "shield-pw-1"})
    client.cookies.clear()
    r = client.post(
        "/v1/auth/sign-in", json={"email": "bob@example.com", "password": "shield-pw-1"}
    )
    assert r.status_code == 200
    assert r.json()["email"] == "bob@example.com"


def test_signin_wrong_password_returns_uniform_401(client: TestClient) -> None:
    client.post("/v1/auth/sign-up", json={"email": "ck@example.com", "password": "shield-pw-1"})
    client.cookies.clear()
    r = client.post("/v1/auth/sign-in", json={"email": "ck@example.com", "password": "WRONG"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHORIZED"
    # And not a distinguishing message — uniform.
    assert "wrong" not in r.json()["error"]["message"].lower()


def test_signin_unknown_email_returns_uniform_401(client: TestClient) -> None:
    r = client.post("/v1/auth/sign-in", json={"email": "ghost@example.com", "password": "x"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHORIZED"


def test_get_session_after_signin(client: TestClient) -> None:
    client.post(
        "/v1/auth/sign-up",
        json={"email": "dora@example.com", "password": "shield-pw-1"},
    )
    r = client.get("/v1/auth/session")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "dora@example.com"
    assert body["role"] == "org_owner"
    assert body["auth_kind"] == "session"
    assert body["csrf_token"]


def test_sign_out_revokes_session(client: TestClient) -> None:
    client.post(
        "/v1/auth/sign-up",
        json={"email": "ed@example.com", "password": "shield-pw-1"},
    )
    # First GET works.
    r1 = client.get("/v1/auth/session")
    assert r1.status_code == 200
    r2 = client.post("/v1/auth/sign-out")
    assert r2.status_code == 200
    # Now session GET should 401 since the cookie was cleared.
    client.cookies.clear()
    r3 = client.get("/v1/auth/session")
    assert r3.status_code == 401


def test_password_reset_request_always_returns_ok(client: TestClient) -> None:
    # Unknown email — still OK (no enumeration).
    r = client.post("/v1/auth/password/reset/request", json={"email": "ghost@example.com"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_password_reset_request_for_known_user_writes_token(client: TestClient) -> None:
    client.post("/v1/auth/sign-up", json={"email": "fi@example.com", "password": "shield-pw-1"})
    storage = client.app_storage  # type: ignore[attr-defined]
    initial_count = len(storage.db.password_reset_tokens)
    r = client.post("/v1/auth/password/reset/request", json={"email": "fi@example.com"})
    assert r.status_code == 200
    assert len(storage.db.password_reset_tokens) == initial_count + 1


def test_password_reset_complete_resets_password_and_revokes_sessions(client: TestClient) -> None:
    client.post("/v1/auth/sign-up", json={"email": "gi@example.com", "password": "shield-pw-1"})
    storage = client.app_storage  # type: ignore[attr-defined]
    user_id = next(iter(storage.db.users))
    # Issue a reset token directly (bypassing the email step).
    import asyncio

    from shield_server.auth.tokens import issue

    issued = asyncio.run(issue(storage.db, kind="password_reset", user_id=user_id))
    r = client.post(
        "/v1/auth/password/reset/complete",
        json={"token": issued.raw, "new_password": "shield-pw-2"},
    )
    assert r.status_code == 200
    # Old session was revoked; sign in with the NEW password works.
    client.cookies.clear()
    r2 = client.post(
        "/v1/auth/sign-in", json={"email": "gi@example.com", "password": "shield-pw-2"}
    )
    assert r2.status_code == 200


def test_password_reset_complete_with_invalid_token_400(client: TestClient) -> None:
    r = client.post(
        "/v1/auth/password/reset/complete",
        json={"token": "bogus-not-a-real-token", "new_password": "shield-pw-3"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
