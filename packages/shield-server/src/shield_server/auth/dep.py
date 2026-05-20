"""ADR-0013 §A2 + §A9 + §A11 — FastAPI dep layer for the unified auth contract.

The dep layer ALWAYS executes (§A2) and ALWAYS produces a populated
``Principal``. Modes:

  * ``open``           → synthetic dev_principal (all 5 roles, demo-org).
                         Preserves W3 314-test default behaviour byte-identically.
  * ``enterprise``     → resolve session cookie OR api-key Bearer. If neither
                         resolves, raise ``UNAUTHORIZED``.
  * ``api_token_only`` → legacy ``SHIELD_API_TOKEN`` Bearer only; synthetic
                         api_token principal. Session routes are NOT mounted
                         under this mode (§A11) — they 404 cleanly.

The CI assertion ``test_every_route_declares_auth_dep(app)`` walks all routes
and refuses any handler without ``Depends(principal_context)`` or
``Depends(require_role(...))``. Naked routes leak through both modes — the
assertion makes that a CI failure (§A2 forcing-function).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.routing import APIRoute

from ..config import DEMO_ORG_ID, Settings
from ..errors import AppError
from .api_keys import lookup_api_key, touch_api_key
from .principal import (
    ALL_ROLES,
    Principal,
    Role,
    api_token_only_principal,
    synthetic_dev_principal,
)
from .sessions import SessionRow, lookup_session, touch_session
from .users import find_by_user_id, primary_membership


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header and header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


async def _resolve_session(request: Request, settings: Settings) -> Principal | None:
    """Try the session-cookie path. Returns the principal or None to fall through."""
    raw_cookie = request.cookies.get(settings.cookie_name)
    if not raw_cookie:
        return None
    storage = request.app.state.storage
    session_row: SessionRow | None = await lookup_session(storage.db, raw_token=raw_cookie)
    if session_row is None:
        return None
    user = await find_by_user_id(storage.db, user_id=session_row.user_id)
    if user is None or user.status != "active":
        return None
    membership = await primary_membership(storage.db, user_id=user.user_id)
    if membership is None:
        return None
    org_id, role = membership
    # Sliding-window touch; ignored on cache failure.
    await touch_session(storage.db, session_id=session_row.session_id)
    return Principal(
        org_id=org_id,
        user_id=user.user_id,
        role=role,
        auth_kind="session",
        roles=frozenset({role}),
        session_id=session_row.session_id,
        email=user.email,
        totp_enabled=user.totp_enabled,
    )


async def _resolve_api_key(request: Request) -> Principal | None:
    """Try the SDK api-key Bearer path."""
    raw = _bearer(request)
    if not raw or not (raw.startswith("as_live_") or raw.startswith("as_test_")):
        return None
    storage = request.app.state.storage
    row = await lookup_api_key(storage.db, raw_key=raw)
    if row is None:
        return None
    # api-keys never get an admin role — they're orthogonal to RBAC; we give
    # the ingest-permitting synthetic role ``integration_engineer`` so any
    # ``require_role(integration_engineer)`` admits them, but they CANNOT
    # satisfy a session-only role (e.g. compliance_auditor) — by orthogonality.
    await touch_api_key(storage.db, api_key_id=row.api_key_id)
    return Principal(
        org_id=row.org_id,
        user_id=f"api-key:{row.api_key_id}",
        role="integration_engineer",
        auth_kind="api_key",
        roles=frozenset({"integration_engineer"}),
        api_key_id=row.api_key_id,
        api_key_agent_id=row.agent_id,
        api_key_agent_id_allowlist=row.agent_id_allowlist,
    )


async def _resolve_api_token_only(request: Request, settings: Settings) -> Principal | None:
    """Legacy ``SHIELD_API_TOKEN`` Bearer (§A11)."""
    raw = _bearer(request)
    if settings.api_token and raw == settings.api_token:
        return api_token_only_principal(DEMO_ORG_ID)
    return None


async def principal_context(request: Request) -> Principal:
    """The §A2 single-source dep — ALWAYS yields a populated ``Principal``.

    Per-mode resolution:
      * open: synthetic dev_principal.
      * enterprise: session OR api-key; else 401 UNAUTHORIZED.
      * api_token_only: ``SHIELD_API_TOKEN`` Bearer; else 401.
    """
    settings: Settings = request.app.state.settings
    if settings.is_open:
        return synthetic_dev_principal(DEMO_ORG_ID)
    if settings.is_api_token_only:
        p = await _resolve_api_token_only(request, settings)
        if p is None:
            raise AppError(401, "UNAUTHORIZED")
        return p
    # enterprise
    p = await _resolve_session(request, settings)
    if p is not None:
        return p
    p = await _resolve_api_key(request)
    if p is not None:
        return p
    raise AppError(401, "UNAUTHORIZED")


PrincipalDep = Annotated[Principal, Depends(principal_context)]


def require_role(*roles: Role) -> Callable[..., Any]:
    """Dep factory returning ``Principal`` only if its role matches; else 403.

    Open-mode short-circuit: the synthetic dev_principal carries all 5 roles
    so any ``require_role(...)`` admits it — preserves W3 default behaviour
    when ``SHIELD_AUTH_MODE=open``. Fail-closed: if the principal lacks the
    role, ``AppError(403, "FORBIDDEN")``.
    """
    allowed = frozenset(roles) if roles else frozenset(ALL_ROLES)

    async def _dep(principal: PrincipalDep) -> Principal:
        if principal.is_open_synthetic or principal.has_role(*allowed):
            return principal
        raise AppError(403, "FORBIDDEN")

    _dep.__name__ = f"require_role({','.join(sorted(allowed))})"
    return _dep


def require_2fa_if_admin(principal: PrincipalDep) -> Principal:
    """ADR-0013 §A9 — force TOTP for org_owner/security_admin sessions.

    Open-mode synthetic + api_key are exempt (they're not the human admin
    role surface). For session-bound admins without totp_enabled, raise
    ``AppError(403, ...)`` with ``error.detail = {code, redirect}`` so the
    console can route to ``/settings/2fa-setup?force=admin_role``.
    """
    if principal.is_open_synthetic or principal.is_api_key:
        return principal
    if principal.is_admin and not principal.totp_enabled:
        raise AppError(
            403,
            "FORBIDDEN",
            details={
                "code": "totp_setup_required",
                "redirect": "/settings/2fa-setup?force=admin_role",
            },
        )
    return principal


def require_api_key_principal(principal: PrincipalDep) -> Principal:
    """Ingest-only dep: §A8 — accept only api_key + open-mode synthetic.

    Rejects human sessions on SDK ingest endpoints (the orthogonality
    invariant: a console session cookie must NEVER satisfy ``/v1/operations``
    or ``/v1/governance/decide`` ingest). Open-mode synthetic is admitted
    so CI keeps W3's 314 tests green (they don't carry an api-key).
    """
    if principal.is_open_synthetic or principal.is_api_key:
        return principal
    raise AppError(403, "FORBIDDEN")


# --- the §A2 CI assertion: every route must declare an auth dep -------- #


# Routes that intentionally do NOT require auth (public surface). Adding to
# this list is an ADR-anchored decision — the assertion fails otherwise.
PUBLIC_ROUTE_PATHS: frozenset[str] = frozenset(
    {
        "/healthz",
        "/.well-known/elydora/jwks.json",
        # Auth bootstrap endpoints — they MUST be reachable unauthenticated.
        "/v1/auth/sign-up",
        "/v1/auth/sign-in",
        "/v1/auth/totp/recovery",
        "/v1/auth/password/reset/request",
        "/v1/auth/password/reset/complete",
        "/v1/auth/email/verify/complete",
        "/v1/auth/invites/accept",
        # OpenAPI / docs (FastAPI default).
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
    }
)


_AUTH_DEP_NAMES: frozenset[str] = frozenset(
    {
        principal_context.__name__,
        # the auth_context name lives in auth/__init__.py — kept here as a
        # string to avoid an import cycle at module-load time.
        "auth_context",
        # `require_role(...)` factory produces named callables of the form
        # `require_role(...)`; detection matches via prefix.
        "require_role",
        require_2fa_if_admin.__name__,
        require_api_key_principal.__name__,
    }
)


def _route_carries_auth_dep(route: APIRoute) -> bool:
    """Return True iff any of the route's deps is one of the recognised auth deps."""
    deps = getattr(route, "dependant", None)
    if deps is None:
        return False
    # FastAPI's Dependant has nested `dependencies`; flatten one level since
    # all the auth deps are direct (no chains in our wiring).
    queue = [deps]
    seen: set[int] = set()
    while queue:
        node = queue.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        for sub in getattr(node, "dependencies", []) or []:
            queue.append(sub)
        call = getattr(node, "call", None)
        if call is None:
            continue
        name = getattr(call, "__name__", "")
        if name in _AUTH_DEP_NAMES or name.startswith("require_role("):
            return True
    return False


def test_every_route_declares_auth_dep(app: Any) -> None:
    """§A2 forcing-function: assert no route bypasses the auth dep layer.

    Walks every ``APIRoute`` on the app; for non-public paths assert at
    least one of the recognised auth deps is on the chain. The CI job
    ``python-auth`` invokes this directly; a new "naked" route causes a
    test failure with the offending path.
    """
    offenders: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path in PUBLIC_ROUTE_PATHS:
            continue
        if _route_carries_auth_dep(route):
            continue
        methods = sorted(route.methods or [])
        offenders.append(f"{route.path} {methods}")
    if offenders:
        raise AssertionError(
            "§A2 violation: the following routes do NOT declare an auth dep "
            f"(would bypass both open and enterprise modes): {offenders}. "
            "Add Depends(principal_context) / Depends(require_role(...)) or "
            "add the path to PUBLIC_ROUTE_PATHS with an ADR justification."
        )


__all__ = [
    "PUBLIC_ROUTE_PATHS",
    "PrincipalDep",
    "principal_context",
    "require_2fa_if_admin",
    "require_api_key_principal",
    "require_role",
    "test_every_route_declares_auth_dep",
]
