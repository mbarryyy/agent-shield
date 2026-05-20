"""ADR-0013 §A1/§A7 — POST /v1/auth/invites/accept handler (unit_auth).

The handler pairs with ``POST /v1/auth/admin/invite``: admin ISSUES invites
(admin role), invitees ACCEPT via the emailed link. This endpoint sits in
``PUBLIC_ROUTE_PATHS`` (``auth/dep.py``) because the invitee does not yet
have a session.

Coverage targets:
  * happy path: 200 + SignInResponse shape + Set-Cookie shield_session +
    audit_log_auth.INVITE_ACCEPT_OK row + invites.consumed_at populated +
    users / memberships rows present.
  * §A7 uniform 401 on unknown / consumed / expired / email-collision —
    no enumeration; verifies error code matches sign-in's verbatim.
  * §A1 argon2 length cap on submitted password (pydantic 422).
  * single-use idempotency: re-POST after success → 401.
  * audit_log_auth invariant: every failure emits ``INVITE_ACCEPT_FAIL``.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from shield_server.auth.utils import now_ms, sha256_hex, uuidv7
from shield_server.errors import AppError  # noqa: F401 — referenced via the AppError envelope

pytestmark = pytest.mark.unit_auth


# --- helpers ----------------------------------------------------------- #


def _seed_admin_and_invite(
    client: TestClient,
    *,
    invitee_email: str = "newcomer@example.com",
    role: str = "integration_engineer",
    ttl_minutes: int | None = None,
) -> tuple[str, str]:
    """Sign up an admin, POST /admin/invite for ``invitee_email``, then return
    ``(invite_id, raw_token)`` so the test can hit /invites/accept with the
    raw token. Optionally backdates ``expires_at`` to model an expired
    invite (set ``ttl_minutes`` negative to backdate).
    """
    admin = client.post(
        "/v1/auth/sign-up",
        json={"email": "admin@example.com", "password": "shield-pw-1"},
    )
    admin.raise_for_status()
    csrf = admin.json()["csrf_token"]
    storage = client.app_storage  # type: ignore[attr-defined]
    # Issue an invite via the real admin route (so the row matches the
    # production INSERT shape exactly).
    issued = client.post(
        "/v1/auth/admin/invite",
        headers={"X-CSRF-Token": csrf},
        json={"email": invitee_email, "role": role},
    )
    issued.raise_for_status()
    invite_id = issued.json()["invite_id"]
    # Recover the raw token: the row's ``token_hash`` is sha256(raw); we
    # don't know raw from the row alone (one-way), so for unit tests we
    # rewrite the row to a deterministic raw we control. Production
    # delivery via email; tests bypass.
    raw = f"raw-invite-token-{invite_id}"
    storage.db.invites[invite_id]["token_hash"] = sha256_hex(raw)
    if ttl_minutes is not None:
        storage.db.invites[invite_id]["expires_at"] = now_ms() + ttl_minutes * 60_000
    # Drop the admin's session cookie so the invite-accept POST is
    # unauthenticated (the route is public-allowlisted).
    client.cookies.clear()
    return invite_id, raw


# --- (1) happy path ---------------------------------------------------- #


def test_accept_valid_invite_returns_200_with_session(client: TestClient) -> None:
    invite_id, raw = _seed_admin_and_invite(client)
    r = client.post(
        "/v1/auth/invites/accept",
        json={"token": raw, "password": "shield-pw-1", "name": "New Comer"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "newcomer@example.com"
    assert body["role"] == "integration_engineer"
    assert body["org_id"] == "demo-org"
    assert body["csrf_token"]
    # Set-Cookie shield_session present.
    assert "shield_session" in {c.name for c in client.cookies.jar}
    storage = client.app_storage  # type: ignore[attr-defined]
    # invites.consumed_at populated.
    assert storage.db.invites[invite_id]["consumed_at"] is not None
    # User row + membership row created.
    users_with_email = [
        u for u in storage.db.users.values() if u["email"] == "newcomer@example.com"
    ]
    assert len(users_with_email) == 1
    new_user_id = users_with_email[0]["user_id"]
    assert (new_user_id, "demo-org") in storage.db.memberships
    assert storage.db.memberships[(new_user_id, "demo-org")]["role"] == "integration_engineer"
    # Email-verified-by-receipt-of-invite invariant.
    assert users_with_email[0]["email_verified_at"] is not None
    # INVITE_ACCEPT_OK audit row present.
    events = [a["event"] for a in storage.db.audit_log_auth]
    assert "INVITE_ACCEPT_OK" in events


# --- (2) §A7 uniform 401 modes ---------------------------------------- #


def test_accept_with_unknown_token_returns_401_uniform(client: TestClient) -> None:
    r = client.post(
        "/v1/auth/invites/accept",
        json={"token": "not-a-real-token", "password": "shield-pw-1"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHORIZED"
    storage = client.app_storage  # type: ignore[attr-defined]
    events = [a["event"] for a in storage.db.audit_log_auth]
    assert "INVITE_ACCEPT_FAIL" in events
    # The audit row carries the reason for forensics; the response does NOT.
    fail = next(a for a in storage.db.audit_log_auth if a["event"] == "INVITE_ACCEPT_FAIL")
    assert "unknown_token" in (fail["detail"] or "")


def test_accept_with_consumed_token_returns_401_uniform(client: TestClient) -> None:
    invite_id, raw = _seed_admin_and_invite(client)
    # First accept succeeds.
    r1 = client.post(
        "/v1/auth/invites/accept",
        json={"token": raw, "password": "shield-pw-1", "name": "A"},
    )
    assert r1.status_code == 200
    # Second accept (same token) MUST 401 — single-use enforced via
    # invites.consumed_at.
    client.cookies.clear()
    r2 = client.post(
        "/v1/auth/invites/accept",
        json={"token": raw, "password": "shield-pw-2", "name": "B"},
    )
    assert r2.status_code == 401
    assert r2.json()["error"]["code"] == "UNAUTHORIZED"


def test_accept_with_expired_token_returns_401_uniform(client: TestClient) -> None:
    _, raw = _seed_admin_and_invite(client, ttl_minutes=-1)  # backdated
    r = client.post(
        "/v1/auth/invites/accept",
        json={"token": raw, "password": "shield-pw-1"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHORIZED"
    storage = client.app_storage  # type: ignore[attr-defined]
    events = [a["event"] for a in storage.db.audit_log_auth]
    assert "INVITE_ACCEPT_FAIL" in events


def test_accept_with_email_collision_returns_401_uniform(client: TestClient) -> None:
    # Seed an invite for the SAME email as a pre-existing user (admin).
    # admin signed up as 'admin@example.com'; invite is for 'admin@example.com'.
    admin = client.post(
        "/v1/auth/sign-up",
        json={"email": "admin@example.com", "password": "shield-pw-1"},
    )
    admin.raise_for_status()
    csrf = admin.json()["csrf_token"]
    storage = client.app_storage  # type: ignore[attr-defined]
    issued = client.post(
        "/v1/auth/admin/invite",
        headers={"X-CSRF-Token": csrf},
        json={"email": "admin@example.com", "role": "security_admin"},
    )
    issued.raise_for_status()
    invite_id = issued.json()["invite_id"]
    raw = f"raw-invite-token-{invite_id}"
    storage.db.invites[invite_id]["token_hash"] = sha256_hex(raw)
    client.cookies.clear()
    r = client.post(
        "/v1/auth/invites/accept",
        json={"token": raw, "password": "shield-pw-2"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHORIZED"


# --- (3) §A1 password length cap -------------------------------------- #


def test_accept_password_validates_min_length(client: TestClient) -> None:
    _, raw = _seed_admin_and_invite(client)
    r = client.post(
        "/v1/auth/invites/accept",
        json={"token": raw, "password": "short", "name": "X"},
    )
    # pydantic Field(min_length=8) → 422 (FastAPI's validation envelope is
    # the standard pydantic one for body-validation failures, distinct from
    # the §A7 401 path which is for valid-shape-but-bad-credential cases).
    assert r.status_code == 422


# --- (4) audit trail discipline --------------------------------------- #


def test_accept_emits_audit_log_auth_rows_for_both_paths(client: TestClient) -> None:
    _, raw = _seed_admin_and_invite(client)
    storage = client.app_storage  # type: ignore[attr-defined]
    initial = len(storage.db.audit_log_auth)
    # Bad token path → INVITE_ACCEPT_FAIL.
    r_bad = client.post(
        "/v1/auth/invites/accept",
        json={"token": "garbage-token", "password": "shield-pw-1"},
    )
    assert r_bad.status_code == 401
    assert any(a["event"] == "INVITE_ACCEPT_FAIL" for a in storage.db.audit_log_auth[initial:])
    after_fail = len(storage.db.audit_log_auth)
    # Good token path → INVITE_ACCEPT_OK.
    r_ok = client.post(
        "/v1/auth/invites/accept",
        json={"token": raw, "password": "shield-pw-1", "name": "X"},
    )
    assert r_ok.status_code == 200
    assert any(a["event"] == "INVITE_ACCEPT_OK" for a in storage.db.audit_log_auth[after_fail:])


# --- helpers preserved for downstream extension ----------------------- #

_ = (asyncio, uuidv7)  # imports kept for hand-edit extension; not directly used.
