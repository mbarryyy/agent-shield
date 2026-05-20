"""ADR-0013 — Enterprise auth package.

Surface:

  W3-byte-compat ``Ctx`` seam (preserved verbatim so existing routes keep
  working unchanged):
      * ``AuthContext`` (frozen dataclass: ``org_id``, ``actor``)
      * ``auth_context(request)`` async dep
      * ``resolve_auth(request, settings)`` sync helper
      * ``_bearer(request)`` helper

  ADR-0013 enterprise surface (submodules; this ``__init__`` re-exports the
  most-used names):
      * ``Principal``, ``principal_context``, ``PrincipalDep``
      * ``require_role(...)``, ``require_2fa_if_admin``, ``require_api_key_principal``
      * ``test_every_route_declares_auth_dep`` — §A2 CI assertion
      * ``compare_w3_tables_byte_identity`` — §A5 fire-drill anchor (forces
        the ``auth-integration`` CI job RED → GREEN once this module is on
        a server-builder PR head)
      * ``authorize_ingest`` — §A8 fail-closed ingest predicate (D1 tri-mode)
      * ``PasswordHasherService`` — §A1 argon2id+pepper+cap-validation
      * ``TotpService`` — §A6 MultiFernet TOTP
      * ``build_email_sender`` — §A4 backend factory (refuses console+enterprise)

The ``auth_context`` async dep is mode-aware:
  * ``open``           → ``AuthContext(org_id=DEMO_ORG_ID, actor="demo")`` —
                         byte-identical to the W3 prototype path so the W3
                         314-test suite stays green.
  * ``enterprise``     → derives ``org_id`` from the resolved Principal
                         (session cookie OR api-key Bearer); ``actor`` is
                         either ``"session"`` or ``"api-key"``. 401
                         UNAUTHORIZED on no auth.
  * ``api_token_only`` → ``AuthContext(org_id=DEMO_ORG_ID, actor="api-token")``
                         on matching ``SHIELD_API_TOKEN``; else 401.

The resolved Principal is cached on ``request.state.principal`` so a route
that uses both deps (``Ctx`` + ``Depends(require_role(...))``) doesn't pay
the DB round-trip twice.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from ..config import DEMO_ORG_ID, Settings
from ..errors import AppError
from .api_keys import authorize_ingest
from .audit import insert_audit
from .dep import (
    PUBLIC_ROUTE_PATHS,
    PrincipalDep,
    principal_context,
    require_2fa_if_admin,
    require_api_key_principal,
    require_role,
    test_every_route_declares_auth_dep,
)
from .email import build_email_sender
from .migration_firedrill import (
    W3_PROTECTED_TABLES,
    compare_w3_tables_byte_identity,
    snapshot_w3_tables,
)
from .passwords import PasswordHasherService
from .principal import (
    ALL_ROLES,
    AuthKind,
    Principal,
    Role,
    api_token_only_principal,
    synthetic_dev_principal,
)
from .totp import TotpService

# Marker for the auth package version; updated by future revisions.
SCAFFOLD_VERSION = "auth-v1"


@dataclass(frozen=True, slots=True)
class AuthContext:
    """The W3 ``Ctx = Annotated[AuthContext, Depends(auth_context)]`` seam.

    Byte-identical fields to the W3 prototype: every existing route reads
    ``ctx.org_id`` (and occasionally ``ctx.actor`` for audit). Adding fields
    here would break the W3 routes' ``Ctx``-typed args; the richer
    ``Principal`` lives behind ``principal_context`` instead.
    """

    org_id: str
    actor: str


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header and header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def resolve_auth(request: Request, settings: Settings) -> AuthContext:
    """W3-compat sync helper — preserves the original three-path resolution.

    The route layer no longer calls this directly (it uses ``auth_context``
    which is principal-aware); kept for any external caller that imports it
    plus the unit tests that exercise the historical surface.
    """
    token = _bearer(request)
    if settings.api_token and token == settings.api_token:
        return AuthContext(org_id=DEMO_ORG_ID, actor="api-token")
    if settings.dev_auth_open:
        return AuthContext(org_id=DEMO_ORG_ID, actor="demo")
    raise AppError(401, "UNAUTHORIZED")


async def auth_context(request: Request) -> AuthContext:
    """Mode-aware dep producing the W3-compat ``AuthContext`` seam.

    Side effect: caches the resolved Principal on ``request.state.principal``
    so a sibling ``Depends(require_role(...))`` doesn't re-walk the cookie
    / api-key resolution path.
    """
    settings: Settings = request.app.state.settings
    if settings.is_open:
        principal = synthetic_dev_principal(DEMO_ORG_ID)
    elif settings.is_api_token_only:
        token = _bearer(request)
        if not settings.api_token or token != settings.api_token:
            raise AppError(401, "UNAUTHORIZED")
        principal = api_token_only_principal(DEMO_ORG_ID)
    else:
        # enterprise — defer to the unified principal_context resolver
        principal = await principal_context(request)
    request.state.principal = principal
    actor = (
        "demo"
        if principal.is_open_synthetic
        else (
            "api-token"
            if principal.auth_kind == "api_token_only"
            else ("api-key" if principal.is_api_key else "session")
        )
    )
    return AuthContext(org_id=principal.org_id, actor=actor)


__all__ = [
    "ALL_ROLES",
    "AuthContext",
    "AuthKind",
    "PUBLIC_ROUTE_PATHS",
    "PasswordHasherService",
    "Principal",
    "PrincipalDep",
    "Role",
    "SCAFFOLD_VERSION",
    "TotpService",
    "W3_PROTECTED_TABLES",
    "_bearer",
    "api_token_only_principal",
    "auth_context",
    "authorize_ingest",
    "build_email_sender",
    "compare_w3_tables_byte_identity",
    "insert_audit",
    "principal_context",
    "require_2fa_if_admin",
    "require_api_key_principal",
    "require_role",
    "resolve_auth",
    "snapshot_w3_tables",
    "synthetic_dev_principal",
    "test_every_route_declares_auth_dep",
]
