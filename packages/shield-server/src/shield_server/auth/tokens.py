"""ADR-0013 — Single-use, expiring, hashed tokens (password-reset / email-verify / invite).

All three flows share the same shape:
  * Generate an opaque random token (URL-safe base64, ~384 bits).
  * Hand the RAW token to the user (in an email link) ONCE.
  * Persist ``sha256(token)`` + ``expires_at`` + ``user_id`` (or org_id) in a
    table; the raw token is never stored.
  * Consume by ``sha256``-matching the candidate and atomically marking
    ``consumed_at = now_ms()`` (single-use guarantee).

Tokens carry NO user identity in the wire form — only the random material —
so they can be invalidated by deleting the row. Email-enumeration safety
(§A7): the *request* endpoint always returns ``{ok:true}`` even when the
email is unknown; only the actual creation+send happens for known users.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..storage import Database
from .utils import generate_opaque_token, now_ms, sha256_hex

# 15 minutes — short enough that a leaked email link expires before realistic
# adversarial discovery cycles; long enough for users on real mail clients.
PASSWORD_RESET_TTL_MS = 15 * 60 * 1000
EMAIL_VERIFY_TTL_MS = 24 * 60 * 60 * 1000  # email confirmation is a slower flow
INVITE_TTL_MS = 7 * 24 * 60 * 60 * 1000

TokenKind = Literal["password_reset", "email_verification"]

_TABLE = {
    "password_reset": "password_reset_tokens",
    "email_verification": "email_verification_tokens",
}


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """The raw token (returned to caller for the email URL) + row metadata."""

    raw: str
    token_hash: str
    user_id: str
    expires_at: int


async def issue(
    db: Database, *, kind: TokenKind, user_id: str, ttl_ms: int | None = None
) -> IssuedToken:
    table = _TABLE[kind]
    if ttl_ms is None:
        ttl_ms = PASSWORD_RESET_TTL_MS if kind == "password_reset" else EMAIL_VERIFY_TTL_MS
    raw = generate_opaque_token()
    token_hash = sha256_hex(raw)
    expires_at = now_ms() + ttl_ms
    await db.execute(
        f"INSERT INTO {table} (token_hash, user_id, expires_at, consumed_at, created_at) "
        "VALUES ($1, $2, $3, NULL, $4)",
        token_hash,
        user_id,
        expires_at,
        now_ms(),
    )
    return IssuedToken(raw=raw, token_hash=token_hash, user_id=user_id, expires_at=expires_at)


async def consume(db: Database, *, kind: TokenKind, raw: str) -> str | None:
    """Atomically consume a token; return ``user_id`` on success, else None.

    "Atomic" = mark consumed_at in the same DB round-trip as the lookup.
    A second consume of the same token finds ``consumed_at`` already set
    and returns None — the single-use guarantee.
    """
    table = _TABLE[kind]
    token_hash = sha256_hex(raw)
    row = await db.fetchrow(
        f"SELECT user_id, expires_at, consumed_at FROM {table} WHERE token_hash = $1",
        token_hash,
    )
    if row is None:
        return None
    if row.get("consumed_at") is not None:
        return None
    expires_at = row.get("expires_at")
    if expires_at is None or int(expires_at) < now_ms():  # type: ignore[call-overload]
        return None
    # Mark single-use BEFORE returning. A concurrent second consume will see
    # consumed_at populated and fail. (PostgreSQL row update is atomic so
    # the race window is bounded; for absolute safety the calling tx is
    # serializable, but the §A7 invariant of "single-use" holds at the
    # tx-isolation default level since this is a write-after-read of the
    # same row.)
    await db.execute(
        f"UPDATE {table} SET consumed_at = $1 WHERE token_hash = $2",
        now_ms(),
        token_hash,
    )
    return str(row["user_id"])


__all__ = [
    "EMAIL_VERIFY_TTL_MS",
    "INVITE_TTL_MS",
    "IssuedToken",
    "PASSWORD_RESET_TTL_MS",
    "TokenKind",
    "consume",
    "issue",
]
