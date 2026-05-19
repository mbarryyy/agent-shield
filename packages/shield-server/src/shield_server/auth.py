"""Minimal auth context.

Per sdk_layer_design.md §1.4/§2 Better-Auth + 5-role RBAC is DISCARDED for the
single-tenant prototype. Default = "open" dev-auth: every request resolves to a
fixed demo org so the Elydora console (`credentials: 'include'`, redirects to
/login on 401) boots unchanged with no session backend. If `SHIELD_API_TOKEN`
is set, a matching `Authorization: Bearer <token>` is also accepted; in
non-open mode a valid token is required (UNAUTHORIZED otherwise).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from .config import DEMO_ORG_ID, Settings
from .errors import AppError


@dataclass(frozen=True, slots=True)
class AuthContext:
    org_id: str
    actor: str


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header and header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def resolve_auth(request: Request, settings: Settings) -> AuthContext:
    token = _bearer(request)
    if settings.api_token and token == settings.api_token:
        return AuthContext(org_id=DEMO_ORG_ID, actor="api-token")
    if settings.dev_auth_open:
        return AuthContext(org_id=DEMO_ORG_ID, actor="demo")
    raise AppError(401, "UNAUTHORIZED")


async def auth_context(request: Request) -> AuthContext:
    settings: Settings = request.app.state.settings
    return resolve_auth(request, settings)
