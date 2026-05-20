"""ADR-0013 §A1.c (D5 implementation detail) — enterprise mode hard-disables
``/v1/auth/sign-up``.

Three required tests:

  1. ``test_signup_403_in_enterprise_mode`` — POST /sign-up under enterprise
     mode returns 403 ``ENTERPRISE_MODE_SIGNUP_DISABLED`` (the auth_router
     IS mounted under enterprise; the handler refuses at entry).
  2. ``test_signup_still_works_in_open_mode`` — POST /sign-up under open
     mode (with the auth_router test-mounted) returns 200 + session.
     "Open mode 行为不变" guarantee.
  3. ``test_error_envelope_carries_human_message`` — the 403 response body
     carries the canonical human-readable message ("Self-service sign-up
     is disabled in enterprise mode. New users must arrive via invite
     from an org admin.") so the console can surface it verbatim.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit_auth


def test_signup_403_in_enterprise_mode(client: TestClient) -> None:
    """Enterprise mode: /sign-up is hard-disabled at handler entry."""
    r = client.post(
        "/v1/auth/sign-up",
        json={"email": "newhire@example.com", "password": "shield-pw-1", "name": "X"},
    )
    assert r.status_code == 403, r.text
    body = r.json()
    assert body["error"]["code"] == "ENTERPRISE_MODE_SIGNUP_DISABLED"
    # No user was created (handler refused BEFORE any DB write).
    storage = client.app_storage  # type: ignore[attr-defined]
    assert all(u["email"] != "newhire@example.com" for u in storage.db.users.values())


def test_signup_still_works_in_open_mode(open_client: TestClient) -> None:
    """Open mode 行为不变: /sign-up still creates a user + session."""
    r = open_client.post(
        "/v1/auth/sign-up",
        json={"email": "open@example.com", "password": "shield-pw-1", "name": "Open"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "open@example.com"
    assert body["role"] == "org_owner"
    assert body["csrf_token"]
    storage = open_client.app_storage  # type: ignore[attr-defined]
    assert any(u["email"] == "open@example.com" for u in storage.db.users.values())


def test_error_envelope_carries_human_message(client: TestClient) -> None:
    """The 403 ``message`` field is the canonical human-readable explanation
    the console surfaces verbatim — no enumeration-safety obscuring here
    (the refusal reason is the SAME regardless of email validity)."""
    r = client.post(
        "/v1/auth/sign-up",
        json={"email": "newhire@example.com", "password": "shield-pw-1"},
    )
    assert r.status_code == 403
    body = r.json()
    assert body["error"]["code"] == "ENTERPRISE_MODE_SIGNUP_DISABLED"
    msg = body["error"]["message"]
    assert "disabled in enterprise mode" in msg
    assert "invite" in msg.lower()
