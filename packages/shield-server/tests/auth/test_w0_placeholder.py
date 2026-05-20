"""W0-scaffold unit_auth coverage for `shield_server.auth` (ADR-0013).

Exercises every line of the W3 prototype surface byte-preserved into the new
auth package (AuthContext, _bearer header parsing, resolve_auth's three paths,
auth_context async wrapper). Gives the `python-auth` job's
`--cov=shield_server.auth --cov-fail-under=90` gate a passing target on W0
without inventing semantics; server-builder's slice replaces these placeholders
with real enterprise-auth tests (sessions, RBAC, api-keys, TOTP, audit).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Request
from shield_server import auth as auth_pkg
from shield_server.auth import AuthContext, _bearer, auth_context, resolve_auth
from shield_server.config import DEMO_ORG_ID
from shield_server.errors import AppError

pytestmark = pytest.mark.unit_auth


def _req(headers: dict[str, str] | None = None, *, app_settings: Any = None) -> Request:
    """Minimal ASGI scope for a Request used by _bearer / auth_context."""
    scope: dict[str, Any] = {
        "type": "http",
        "headers": [
            (k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()
        ],
    }
    if app_settings is not None:
        scope["app"] = SimpleNamespace(state=SimpleNamespace(settings=app_settings))
    return Request(scope)


# --- package surface ----------------------------------------------------- #


def test_auth_package_marker() -> None:
    assert auth_pkg.SCAFFOLD_VERSION == "auth-w0-scaffold"
    assert set(auth_pkg.__all__) == {
        "SCAFFOLD_VERSION",
        "AuthContext",
        "auth_context",
        "resolve_auth",
    }


# --- AuthContext dataclass ---------------------------------------------- #


def test_auth_context_is_frozen() -> None:
    ctx = AuthContext(org_id="o", actor="a")
    assert ctx.org_id == "o" and ctx.actor == "a"
    with pytest.raises(FrozenInstanceError):
        ctx.org_id = "other"  # type: ignore[misc]


# --- _bearer header parsing --------------------------------------------- #


def test_bearer_absent_header() -> None:
    assert _bearer(_req()) is None


def test_bearer_non_bearer_scheme_returns_none() -> None:
    assert _bearer(_req({"authorization": "Basic dXNlcjpwYXNz"})) is None


def test_bearer_extracts_and_strips_token() -> None:
    assert _bearer(_req({"authorization": "Bearer   abc-def_123  "})) == "abc-def_123"


def test_bearer_is_case_insensitive_on_scheme() -> None:
    assert _bearer(_req({"authorization": "BEARER xyz"})) == "xyz"


# --- resolve_auth: three paths ------------------------------------------ #


def test_resolve_auth_api_token_match_returns_api_token_actor() -> None:
    settings = SimpleNamespace(api_token="s3cr3t", dev_auth_open=False)
    ctx = resolve_auth(_req({"authorization": "Bearer s3cr3t"}), settings)
    assert ctx == AuthContext(org_id=DEMO_ORG_ID, actor="api-token")


def test_resolve_auth_falls_back_to_dev_demo_when_open() -> None:
    settings = SimpleNamespace(api_token=None, dev_auth_open=True)
    ctx = resolve_auth(_req(), settings)
    assert ctx == AuthContext(org_id=DEMO_ORG_ID, actor="demo")


def test_resolve_auth_token_mismatch_then_not_open_raises_401() -> None:
    settings = SimpleNamespace(api_token="real", dev_auth_open=False)
    with pytest.raises(AppError) as exc:
        resolve_auth(_req({"authorization": "Bearer wrong"}), settings)
    assert exc.value.status_code == 401
    assert exc.value.error_code == "UNAUTHORIZED"


def test_resolve_auth_no_token_no_open_raises_401() -> None:
    settings = SimpleNamespace(api_token="real", dev_auth_open=False)
    with pytest.raises(AppError) as exc:
        resolve_auth(_req(), settings)
    assert exc.value.status_code == 401


# --- auth_context async wrapper ----------------------------------------- #


async def test_auth_context_reads_settings_from_app_state() -> None:
    settings = SimpleNamespace(api_token=None, dev_auth_open=True)
    request = _req(app_settings=settings)
    ctx = await auth_context(request)
    assert ctx == AuthContext(org_id=DEMO_ORG_ID, actor="demo")
