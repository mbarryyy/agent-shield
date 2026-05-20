"""ADR-0013 §A10 — CSRF double-submit, header transport, constant-time compare.

Architecture:
  * The session row stores ``csrf_token`` (random 32B base64).
  * ``GET /v1/auth/session`` returns ``csrf_token`` ONLY in the JSON body —
    NEVER in the cookie. Cookie carries only ``session_id`` (opaque),
    HttpOnly, so JS reads the body, not the cookie.
  * State-changing requests (POST / PATCH / PUT / DELETE) MUST echo the
    csrf_token in ``X-CSRF-Token``. Server validates via
    ``hmac.compare_digest`` (constant-time) against the session row.

Public surface: ``require_csrf(request, session_row)`` raises ``AppError(403,
"FORBIDDEN")`` on mismatch, returns cleanly on match. The dep layer attaches
this as a FastAPI dependency on every state-changing auth route via the
``Ctx`` wrapper.
"""

from __future__ import annotations

from fastapi import Request

from ..errors import AppError
from .sessions import SessionRow
from .utils import constant_time_equal

# HTTP methods that are state-changing and therefore require the CSRF header.
# GET / HEAD / OPTIONS are safe (RFC 9110 §9.2.1) — no double-submit needed.
STATE_CHANGING_METHODS: frozenset[str] = frozenset({"POST", "PATCH", "PUT", "DELETE"})

# Header name; lowercased for case-insensitive lookup.
CSRF_HEADER_NAME = "X-CSRF-Token"


def is_state_changing(request: Request) -> bool:
    return request.method.upper() in STATE_CHANGING_METHODS


def csrf_token_from_header(request: Request) -> str | None:
    """Read the X-CSRF-Token header (case-insensitive)."""
    return request.headers.get(CSRF_HEADER_NAME) or request.headers.get(CSRF_HEADER_NAME.lower())


def require_csrf(request: Request, session: SessionRow) -> None:
    """Raise 403 ``FORBIDDEN`` if the X-CSRF-Token does not match.

    Constant-time compare via ``hmac.compare_digest`` (delegated through
    ``utils.constant_time_equal``). The error code is the existing
    ``FORBIDDEN`` (errors.ErrorCode) so console error parsing is byte-
    identical to the W3 path.
    """
    if not is_state_changing(request):
        return
    candidate = csrf_token_from_header(request)
    if not candidate or not constant_time_equal(candidate, session.csrf_token):
        raise AppError(403, "FORBIDDEN")


__all__ = [
    "CSRF_HEADER_NAME",
    "STATE_CHANGING_METHODS",
    "csrf_token_from_header",
    "is_state_changing",
    "require_csrf",
]
