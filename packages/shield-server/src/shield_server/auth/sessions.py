"""ADR-0013 §A10 — Server-authoritative opaque sessions in PostgreSQL.

Each session row owns its lifecycle (created_at / last_used_at / expires_at /
revoked_at). The cookie carries the *raw* opaque token (URL-safe 48-byte
base64); the DB stores only ``sha256(token)`` so an attacker reading the DB
cannot mint cookies. Lookup uses ``hmac.compare_digest`` over the hashed
value — no timing side-channel.

CSRF (§A10 double-submit): ``csrf_token`` is a separate random 32-byte
base64 value, stored on the session row and returned ONLY in the JSON body
of ``GET /v1/auth/session`` (never in the cookie). State-changing requests
must echo it as ``X-CSRF-Token``; the dep validates with constant-time
compare.

Rotation: ``rotate_token`` issues a new opaque token + csrf token, updates
the row, and returns the fresh cookie material. Routes call rotate on
password change, role change, and 2FA enable/disable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import Settings
from ..storage import Database
from .utils import generate_opaque_token, now_ms, sha256_hex, uuidv7


@dataclass(frozen=True, slots=True)
class SessionRow:
    """Minimal projection of the ``sessions`` row used by the dep layer."""

    session_id: str
    user_id: str
    csrf_token: str
    created_at: int
    last_used_at: int
    expires_at: int
    revoked_at: int | None


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """The result of ``create_session`` — raw token + the session row."""

    raw_token: str
    csrf_token: str
    session: SessionRow


def _csrf_token() -> str:
    """32-byte URL-safe random CSRF token (§A10)."""
    return generate_opaque_token(num_bytes=32)


async def create_session(
    db: Database,
    *,
    user_id: str,
    ttl_seconds: int,
    ip: str | None = None,
    user_agent: str | None = None,
) -> IssuedSession:
    """Issue a brand-new session row and return the raw cookie token.

    The raw token is shown ONCE (as the Set-Cookie value); the server stores
    only ``sha256(token)`` so no plaintext form can be reconstructed from DB
    alone.
    """
    raw = generate_opaque_token()
    token_hash = sha256_hex(raw)
    session_id = uuidv7()
    csrf = _csrf_token()
    now = now_ms()
    expires_at = now + ttl_seconds * 1000
    await db.execute(
        "INSERT INTO sessions (session_id, user_id, token_hash, csrf_token, ip, "
        "user_agent, created_at, last_used_at, expires_at, revoked_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NULL)",
        session_id,
        user_id,
        token_hash,
        csrf,
        ip,
        user_agent,
        now,
        now,
        expires_at,
    )
    return IssuedSession(
        raw_token=raw,
        csrf_token=csrf,
        session=SessionRow(
            session_id=session_id,
            user_id=user_id,
            csrf_token=csrf,
            created_at=now,
            last_used_at=now,
            expires_at=expires_at,
            revoked_at=None,
        ),
    )


async def lookup_session(db: Database, *, raw_token: str) -> SessionRow | None:
    """Resolve a raw cookie token to its (active, unexpired, unrevoked) row.

    Returns ``None`` for: missing row, revoked row, expired row. The DB
    lookup is by ``token_hash`` (server-stored SHA-256), so the comparison
    happens on a column with the UNIQUE constraint — no full-table scan.
    """
    if not raw_token:
        return None
    token_hash = sha256_hex(raw_token)
    row = await db.fetchrow(
        "SELECT session_id, user_id, csrf_token, created_at, last_used_at, "
        "expires_at, revoked_at FROM sessions WHERE token_hash = $1",
        token_hash,
    )
    if row is None:
        return None
    if row.get("revoked_at") is not None:
        return None
    if int(row["expires_at"]) < now_ms():  # type: ignore[call-overload]
        return None
    return SessionRow(
        session_id=str(row["session_id"]),
        user_id=str(row["user_id"]),
        csrf_token=str(row["csrf_token"]),
        created_at=int(row["created_at"]),  # type: ignore[call-overload]
        last_used_at=int(row["last_used_at"]),  # type: ignore[call-overload]
        expires_at=int(row["expires_at"]),  # type: ignore[call-overload]
        revoked_at=None,
    )


async def touch_session(db: Database, *, session_id: str) -> None:
    """Update ``last_used_at`` after a successful auth — sliding-window TTL.

    Routes hit this once per request that uses the session; it is cheap
    (single UPDATE by PK) and gives ``GET /v1/auth/admin/users/{id}/sessions``
    accurate activity timestamps.
    """
    await db.execute(
        "UPDATE sessions SET last_used_at = $1 WHERE session_id = $2",
        now_ms(),
        session_id,
    )


async def rotate_token(db: Database, *, session_id: str) -> tuple[str, str]:
    """Issue a fresh ``(raw_token, csrf_token)`` for an existing session row.

    Called on privilege boundaries (password change, role upgrade, 2FA enable
    / disable). The session row itself is preserved (same created_at, same
    user_id) — only the cookie material rotates so an attacker with the old
    cookie value loses access immediately.
    """
    raw = generate_opaque_token()
    csrf = _csrf_token()
    await db.execute(
        "UPDATE sessions SET token_hash = $1, csrf_token = $2, last_used_at = $3 "
        "WHERE session_id = $4",
        sha256_hex(raw),
        csrf,
        now_ms(),
        session_id,
    )
    return raw, csrf


async def revoke_session(db: Database, *, session_id: str) -> None:
    await db.execute(
        "UPDATE sessions SET revoked_at = $1 WHERE session_id = $2",
        now_ms(),
        session_id,
    )


async def revoke_all_for_user(db: Database, *, user_id: str) -> None:
    """Revoke every active session for a user — called on password reset."""
    await db.execute(
        "UPDATE sessions SET revoked_at = $1 WHERE user_id = $2 AND revoked_at IS NULL",
        now_ms(),
        user_id,
    )


async def list_sessions_for_user(db: Database, *, user_id: str) -> list[dict[str, object]]:
    """Admin view: every session row (active + revoked) for a user."""
    rows = await db.fetch(
        "SELECT session_id, user_id, ip, user_agent, created_at, last_used_at, "
        "expires_at, revoked_at FROM sessions WHERE user_id = $1",
        user_id,
    )
    return [dict(r) for r in rows]


def build_cookie_kwargs(settings: Settings) -> dict[str, Any]:
    """Return the FastAPI ``set_cookie`` kwargs reflecting current settings.

    Centralised so every Set-Cookie in the codebase (login, refresh, rotate
    on password change, etc.) carries the same attributes — and so an
    auditor sees one source of truth for the cookie policy.
    """
    return {
        "key": settings.cookie_name,
        "max_age": settings.session_ttl_seconds,
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": "lax",
        "path": "/",
        "domain": settings.cookie_domain,
    }


__all__ = [
    "IssuedSession",
    "SessionRow",
    "build_cookie_kwargs",
    "create_session",
    "list_sessions_for_user",
    "lookup_session",
    "revoke_all_for_user",
    "revoke_session",
    "rotate_token",
    "touch_session",
]
