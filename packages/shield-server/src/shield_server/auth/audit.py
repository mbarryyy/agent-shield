"""ADR-0013 §A7 — audit_log_auth SINK.

Mirrors the W3 ``intervention_log`` SINK pattern: every auth event lands in a
single, append-only table (``audit_log_auth``) with ``event`` + structured
``detail`` JSONB. The list of events is closed (Literal); adding one is an
ADR-anchored decision.

The helper is import-cycle-free: depends only on the ``Database`` Protocol and
the stdlib JSON encoder. Tests at ``tests/auth/test_audit.py`` exercise the
shape; ``MemoryDatabase`` models the INSERT shape.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from ..storage import Database
from .utils import now_ms, uuidv7

AuthEvent = Literal[
    "STARTED_IN_OPEN_MODE",
    "SIGN_UP_OK",
    "SIGN_UP_FAIL",
    "SIGN_IN_OK",
    "SIGN_IN_FAIL",
    "SIGN_IN_LOCKED",
    "SIGN_IN_TOTP_REQUIRED",
    "SIGN_IN_TOTP_FAIL",
    "SIGN_IN_TOTP_OK",
    "SIGN_IN_RECOVERY_OK",
    "SIGN_OUT",
    "SESSION_REFRESH",
    "SESSION_REVOKE",
    "PASSWORD_RESET_REQUEST",
    "PASSWORD_RESET_COMPLETE",
    "PASSWORD_CHANGE",
    "EMAIL_VERIFY_REQUEST",
    "EMAIL_VERIFY_COMPLETE",
    "TOTP_SETUP",
    "TOTP_CONFIRM",
    "TOTP_DISABLE",
    "ROLE_CHANGE",
    "INVITE_SEND",
    "INVITE_ACCEPT",
    "API_KEY_ISSUE",
    "API_KEY_REVOKE",
    "API_KEY_AUTHZ_DENY",
    "RATELIMIT_BLOCK",
    "ACCOUNT_LOCK",
    "ACCOUNT_UNLOCK",
]


async def insert_audit(
    db: Database,
    *,
    event: AuthEvent,
    user_id: str | None = None,
    org_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    detail: dict[str, Any] | None = None,
) -> str:
    """Insert one row into ``audit_log_auth``; return the new ``audit_id``.

    Always succeeds: an audit-row failure should never block an in-flight
    sign-in / sign-out; production deployments must monitor the table
    write rate. ``detail`` is JSON-serialised via ``json.dumps`` so non-
    asyncpg backends (MemoryDatabase) get a plain str, which they then
    parse / store as appropriate.
    """
    audit_id = uuidv7()
    detail_json = json.dumps(detail or {}, sort_keys=True, separators=(",", ":"))
    await db.execute(
        "INSERT INTO audit_log_auth "
        "(audit_id, user_id, org_id, event, ip, user_agent, detail, created_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        audit_id,
        user_id,
        org_id,
        event,
        ip,
        user_agent,
        detail_json,
        now_ms(),
    )
    return audit_id


__all__ = ["AuthEvent", "insert_audit"]
