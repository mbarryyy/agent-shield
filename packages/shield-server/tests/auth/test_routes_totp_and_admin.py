"""ADR-0013 — TOTP setup/confirm/disable/recovery + admin user/session/role/invite (unit_auth)."""

from __future__ import annotations

import pyotp
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit_auth


def _signup(client: TestClient, *, email: str = "tu@example.com") -> dict:
    """Bootstrap an admin via direct storage seed (enterprise mode hard-
    disables /v1/auth/sign-up per ADR-0013 §A1.c)."""
    from .conftest import bootstrap_admin_via_storage

    return bootstrap_admin_via_storage(client, email=email, password="shield-pw-1")


def test_totp_setup_returns_uri_and_secret(client: TestClient) -> None:
    _signup(client)
    r = client.post("/v1/auth/totp/setup")
    assert r.status_code == 200
    body = r.json()
    assert body["provisioning_uri"].startswith("otpauth://totp/")
    assert body["secret"]


def test_totp_confirm_enables_and_returns_recovery_codes(client: TestClient) -> None:
    _signup(client, email="vt@example.com")
    setup = client.post("/v1/auth/totp/setup").json()
    code = pyotp.TOTP(setup["secret"]).now()
    r = client.post("/v1/auth/totp/confirm", json={"code": code})
    assert r.status_code == 200
    body = r.json()
    assert len(body["recovery_codes"]) == 10
    # User row marked totp_enabled.
    storage = client.app_storage  # type: ignore[attr-defined]
    user_row = next(iter(storage.db.users.values()))
    assert user_row["totp_enabled"] is True


def test_totp_confirm_with_wrong_code_400(client: TestClient) -> None:
    _signup(client, email="wt@example.com")
    client.post("/v1/auth/totp/setup")
    r = client.post("/v1/auth/totp/confirm", json={"code": "000000"})
    assert r.status_code == 400


def test_signin_after_totp_enabled_requires_code(client: TestClient) -> None:
    _signup(client, email="xt@example.com")
    setup = client.post("/v1/auth/totp/setup").json()
    code = pyotp.TOTP(setup["secret"]).now()
    client.post("/v1/auth/totp/confirm", json={"code": code})
    client.cookies.clear()
    # First attempt without TOTP code → 401 with totp_required hint.
    r = client.post("/v1/auth/sign-in", json={"email": "xt@example.com", "password": "shield-pw-1"})
    assert r.status_code == 401
    # Second attempt with TOTP code → 200.
    code2 = pyotp.TOTP(setup["secret"]).now()
    r2 = client.post(
        "/v1/auth/sign-in",
        json={"email": "xt@example.com", "password": "shield-pw-1", "totp_code": code2},
    )
    assert r2.status_code == 200


def test_admin_list_users(client: TestClient) -> None:
    _signup(client, email="admin@example.com")
    r = client.get("/v1/auth/admin/users")
    assert r.status_code == 200
    body = r.json()
    assert any(u["email"] == "admin@example.com" for u in body["users"])


def test_admin_role_change_audits(client: TestClient) -> None:
    _signup(client, email="admin@example.com")
    storage = client.app_storage  # type: ignore[attr-defined]
    user_id = next(iter(storage.db.users))
    r = client.post(
        f"/v1/auth/admin/users/{user_id}/role",
        json={"role": "security_admin"},
    )
    assert r.status_code == 200
    # Memberships table updated.
    m = storage.db.memberships[(user_id, "demo-org")]
    assert m["role"] == "security_admin"
    # Audit row.
    events = [a["event"] for a in storage.db.audit_log_auth]
    assert "ROLE_CHANGE" in events


def test_admin_invite_creates_invite_row(client: TestClient) -> None:
    _signup(client, email="admin@example.com")
    r = client.post(
        "/v1/auth/admin/invite",
        json={"email": "newcomer@example.com", "role": "integration_engineer"},
    )
    assert r.status_code == 200
    storage = client.app_storage  # type: ignore[attr-defined]
    assert len(storage.db.invites) == 1
    inv = next(iter(storage.db.invites.values()))
    assert inv["email"] == "newcomer@example.com"
    assert inv["role"] == "integration_engineer"


def test_admin_session_revoke(client: TestClient) -> None:
    _signup(client, email="admin@example.com")
    storage = client.app_storage  # type: ignore[attr-defined]
    session_id = next(iter(storage.db.sessions))
    r = client.post(f"/v1/auth/admin/sessions/{session_id}/revoke")
    assert r.status_code == 200
    sess = storage.db.sessions[session_id]
    assert sess["revoked_at"] is not None


def test_totp_recovery_consumes_single_use(client: TestClient) -> None:
    _signup(client, email="rt@example.com")
    setup = client.post("/v1/auth/totp/setup").json()
    code = pyotp.TOTP(setup["secret"]).now()
    confirm = client.post("/v1/auth/totp/confirm", json={"code": code}).json()
    recovery_codes = confirm["recovery_codes"]
    client.cookies.clear()
    # Use one recovery code to sign in (bypasses TOTP).
    r = client.post(
        "/v1/auth/totp/recovery",
        json={"email": "rt@example.com", "recovery_code": recovery_codes[0]},
    )
    assert r.status_code == 200
    # Using the SAME recovery code again should fail (single-use).
    client.cookies.clear()
    r2 = client.post(
        "/v1/auth/totp/recovery",
        json={"email": "rt@example.com", "recovery_code": recovery_codes[0]},
    )
    assert r2.status_code == 401
