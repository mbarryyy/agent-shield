"""ADR-0013 §A2 / §A9 / §A11 — Principal + dep-layer enforcement (unit).

Covers principal construction (open-synthetic + api_token_only); the
``require_role`` factory; the §A9 ``require_2fa_if_admin`` admin gate; the
§A2 ``test_every_route_declares_auth_dep`` invariant on the live app.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from shield_server.auth import (
    ALL_ROLES,
    PUBLIC_ROUTE_PATHS,
    Principal,
    api_token_only_principal,
    require_2fa_if_admin,
    require_role,
    synthetic_dev_principal,
)

# Alias the §A2 CI assertion away from ``test_*`` to keep pytest from
# auto-collecting it as a test function (signature: ``app``).
from shield_server.auth import (
    test_every_route_declares_auth_dep as assert_every_route_declares_auth_dep,
)
from shield_server.errors import AppError

pytestmark = pytest.mark.unit_auth


def test_synthetic_dev_principal_has_all_5_roles() -> None:
    p = synthetic_dev_principal("demo-org")
    assert set(p.roles) == set(ALL_ROLES)
    assert p.is_open_synthetic
    assert not p.is_session
    assert not p.is_api_key


def test_api_token_only_principal_is_org_owner() -> None:
    p = api_token_only_principal("demo-org")
    assert p.role == "org_owner"
    assert p.auth_kind == "api_token_only"


@pytest.mark.asyncio
async def test_require_role_admits_open_synthetic_regardless_of_role() -> None:
    dep = require_role("compliance_auditor")
    p = synthetic_dev_principal("demo-org")
    out = await dep(p)
    assert out is p


@pytest.mark.asyncio
async def test_require_role_rejects_principal_lacking_role() -> None:
    dep = require_role("compliance_auditor")
    p = Principal(
        org_id="demo-org",
        user_id="u",
        role="readonly_investigator",
        auth_kind="session",
        roles=frozenset({"readonly_investigator"}),
    )
    with pytest.raises(AppError) as exc:
        await dep(p)
    assert exc.value.status_code == 403


def test_require_2fa_if_admin_admits_non_admin_session() -> None:
    p = Principal(
        org_id="demo-org",
        user_id="u",
        role="readonly_investigator",
        auth_kind="session",
        roles=frozenset({"readonly_investigator"}),
        totp_enabled=False,
    )
    assert require_2fa_if_admin(p) is p


def test_require_2fa_if_admin_admits_api_key_and_open() -> None:
    open_p = synthetic_dev_principal("demo-org")
    api_p = Principal(
        org_id="demo-org",
        user_id="api-key:x",
        role="integration_engineer",
        auth_kind="api_key",
        roles=frozenset({"integration_engineer"}),
        api_key_id="x",
    )
    assert require_2fa_if_admin(open_p) is open_p
    assert require_2fa_if_admin(api_p) is api_p


def test_require_2fa_if_admin_blocks_session_admin_without_totp() -> None:
    admin = Principal(
        org_id="demo-org",
        user_id="u",
        role="org_owner",
        auth_kind="session",
        roles=frozenset({"org_owner"}),
        totp_enabled=False,
    )
    with pytest.raises(AppError) as exc:
        require_2fa_if_admin(admin)
    assert exc.value.status_code == 403
    assert (exc.value.details or {}).get("code") == "totp_setup_required"


def test_every_route_declares_auth_dep_is_clean_on_real_app(client: TestClient) -> None:
    """§A2 CI assertion: walking the enterprise app must surface no naked routes."""
    assert_every_route_declares_auth_dep(client.app)


def test_public_route_set_documented() -> None:
    """Sanity: PUBLIC_ROUTE_PATHS contains the bootstrap + healthcheck paths."""
    assert "/healthz" in PUBLIC_ROUTE_PATHS
    assert "/v1/auth/sign-in" in PUBLIC_ROUTE_PATHS
    assert "/v1/auth/sign-up" in PUBLIC_ROUTE_PATHS
    assert "/v1/auth/password/reset/complete" in PUBLIC_ROUTE_PATHS


# ---- Principal helper-property coverage ------------------------------- #


def test_principal_is_admin_and_role_membership() -> None:
    p = Principal(
        org_id="demo-org",
        user_id="u",
        role="security_admin",
        auth_kind="session",
        roles=frozenset({"security_admin"}),
    )
    assert p.is_admin
    assert p.has_role("security_admin")
    assert not p.has_role("readonly_investigator")
