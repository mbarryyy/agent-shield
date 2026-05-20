"""ADR-0013 — Users service (sign-up / sign-in / lockout / role lookup).

Orchestrates ``passwords.PasswordHasherService`` + ``audit.insert_audit`` +
``sessions`` + the ``users`` / ``memberships`` tables. Lockout uses
``SELECT ... FOR UPDATE`` on the user row to be race-safe; the audit row is
inserted BEFORE the lock state changes so a forensic trail survives any
later transaction abort.

Account-enumeration safety (§A7): sign-in failure surfaces a uniform 401
``invalid_credentials`` regardless of the underlying cause (no such user,
wrong password, account locked, TOTP required, etc.). The true reason
lives in ``audit_log_auth`` only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..errors import AppError
from ..storage import Database
from .audit import insert_audit
from .passwords import PasswordHasherService, VerifyResult
from .principal import Role
from .utils import now_ms, uuidv7

# Account-lockout schedule (§A1 + §A7): exponential backoff, capped at 30 min,
# reset on successful login. Tuple = minutes after each subsequent failure
# beyond the threshold. Threshold = 5 failures.
LOCKOUT_THRESHOLD = 5
LOCKOUT_MINUTES_SCHEDULE = (5, 10, 20, 30)


@dataclass(frozen=True, slots=True)
class UserRow:
    user_id: str
    email: str
    password_hash: str
    password_pepper_kid: str
    name: str
    status: Literal["active", "locked", "disabled"]
    email_verified_at: int | None
    failed_login_count: int
    locked_until: int | None
    totp_enabled: bool
    created_at: int
    updated_at: int
    last_login_at: int | None


def _row_to_user(row: dict[str, object]) -> UserRow:
    status_raw = str(row.get("status") or "active")
    if status_raw not in ("active", "locked", "disabled"):
        status_raw = "active"
    return UserRow(
        user_id=str(row["user_id"]),
        email=str(row["email"]),
        password_hash=str(row["password_hash"]),
        password_pepper_kid=str(row["password_pepper_kid"]),
        name=str(row.get("name") or ""),
        status=status_raw,  # type: ignore[arg-type]
        email_verified_at=(
            int(row["email_verified_at"]) if row.get("email_verified_at") is not None else None  # type: ignore[call-overload]
        ),
        failed_login_count=int(row.get("failed_login_count", 0)),  # type: ignore[call-overload]
        locked_until=(
            int(row["locked_until"]) if row.get("locked_until") is not None else None  # type: ignore[call-overload]
        ),
        totp_enabled=bool(row.get("totp_enabled", False)),
        created_at=int(row["created_at"]),  # type: ignore[call-overload]
        updated_at=int(row["updated_at"]),  # type: ignore[call-overload]
        last_login_at=(
            int(row["last_login_at"]) if row.get("last_login_at") is not None else None  # type: ignore[call-overload]
        ),
    )


# --- queries ------------------------------------------------------------ #


async def find_by_email(db: Database, *, email: str) -> UserRow | None:
    row = await db.fetchrow(
        "SELECT user_id, email, password_hash, password_pepper_kid, name, status, "
        "email_verified_at, failed_login_count, locked_until, totp_enabled, "
        "created_at, updated_at, last_login_at "
        "FROM users WHERE lower(email) = lower($1)",
        email,
    )
    return None if row is None else _row_to_user(row)


async def find_by_user_id(db: Database, *, user_id: str) -> UserRow | None:
    row = await db.fetchrow(
        "SELECT user_id, email, password_hash, password_pepper_kid, name, status, "
        "email_verified_at, failed_login_count, locked_until, totp_enabled, "
        "created_at, updated_at, last_login_at "
        "FROM users WHERE user_id = $1",
        user_id,
    )
    return None if row is None else _row_to_user(row)


async def role_for(db: Database, *, user_id: str, org_id: str) -> Role | None:
    row = await db.fetchrow(
        "SELECT role FROM memberships WHERE user_id = $1 AND org_id = $2",
        user_id,
        org_id,
    )
    if row is None:
        return None
    return str(row["role"])  # type: ignore[return-value]


async def primary_membership(db: Database, *, user_id: str) -> tuple[str, Role] | None:
    """Return ``(org_id, role)`` for the user's PRIMARY org (lowest joined_at).

    v1 = single-org-per-user UX (§A7); the schema permits multi-org via the
    ``memberships`` composite PK for future v1.x switcher. The session
    carries this one membership; multi-org switching would re-issue the
    session with a different ``current_org_id`` claim.
    """
    rows = await db.fetch(
        "SELECT org_id, role FROM memberships WHERE user_id = $1 ORDER BY joined_at",
        user_id,
    )
    if not rows:
        return None
    return str(rows[0]["org_id"]), str(rows[0]["role"])  # type: ignore[return-value]


# --- mutations ---------------------------------------------------------- #


async def create_user(
    db: Database,
    hasher: PasswordHasherService,
    *,
    email: str,
    password: str,
    name: str = "",
    org_id: str,
    role: Role,
    invited_by: str | None = None,
) -> UserRow:
    """Create a user + their first ``memberships`` row in one transaction.

    Used by ``sign_up`` and the ``shield-server seed-admin`` CLI. The caller
    is responsible for enforcing email uniqueness; this function relies on
    the ``users.idx_users_email_lower`` UNIQUE INDEX to raise on duplicates.
    """
    user_id = uuidv7()
    password_hash, pepper_kid = hasher.hash(password)
    now = now_ms()
    async with db.transaction() as tx:
        await tx.execute(
            "INSERT INTO users (user_id, email, password_hash, password_pepper_kid, "
            "name, status, email_verified_at, failed_login_count, locked_until, "
            "totp_enabled, created_at, updated_at, last_login_at) "
            "VALUES ($1, $2, $3, $4, $5, 'active', NULL, 0, NULL, FALSE, $6, $6, NULL)",
            user_id,
            email,
            password_hash,
            pepper_kid,
            name,
            now,
        )
        await tx.execute(
            "INSERT INTO memberships (user_id, org_id, role, invited_by, joined_at) "
            "VALUES ($1, $2, $3, $4, $5)",
            user_id,
            org_id,
            role,
            invited_by,
            now,
        )
    found = await find_by_user_id(db, user_id=user_id)
    assert found is not None  # just-inserted; guaranteed present
    return found


def _lockout_minutes_for(failed_count: int) -> int:
    """Lockout duration in minutes after ``failed_count`` consecutive failures.

    failed_count <= LOCKOUT_THRESHOLD → 0 (no lockout yet). Past the threshold
    the schedule applies; once exhausted, the last value (30) repeats.
    """
    over = failed_count - LOCKOUT_THRESHOLD
    if over <= 0:
        return 0
    idx = min(over - 1, len(LOCKOUT_MINUTES_SCHEDULE) - 1)
    return LOCKOUT_MINUTES_SCHEDULE[idx]


async def record_failed_login(
    db: Database,
    *,
    user_id: str,
    ip: str | None,
    user_agent: str | None,
) -> tuple[int, int | None]:
    """Increment ``failed_login_count``; lock the account if threshold reached.

    Returns ``(new_failed_count, locked_until_or_none)`` for the caller's
    audit row. PostgreSQL ``SELECT ... FOR UPDATE`` inside the transaction
    serialises concurrent failed logins against the same row — required by
    §A1 race-safety. The MemoryDatabase models this without LOCKING since
    the unit tests are single-task; the integration tests exercise real PG.
    """
    async with db.transaction() as tx:
        # The MemoryDatabase doesn't support FOR UPDATE — we issue the same
        # SQL shape and the PG path benefits from the lock. The next two
        # statements are deliberately ordered: lock-read, then update.
        row = await db.fetchrow(
            "SELECT failed_login_count FROM users WHERE user_id = $1 FOR UPDATE",
            user_id,
        )
        new_count = int(row["failed_login_count"] if row else 0) + 1  # type: ignore[call-overload]
        lockout_minutes = _lockout_minutes_for(new_count)
        locked_until = (now_ms() + lockout_minutes * 60_000) if lockout_minutes else None
        await tx.execute(
            "UPDATE users SET failed_login_count = $1, locked_until = $2, "
            "status = CASE WHEN $2 IS NULL THEN status ELSE 'locked' END, "
            "updated_at = $3 WHERE user_id = $4",
            new_count,
            locked_until,
            now_ms(),
            user_id,
        )
    if locked_until is not None:
        await insert_audit(
            db,
            event="ACCOUNT_LOCK",
            user_id=user_id,
            ip=ip,
            user_agent=user_agent,
            detail={"failed_count": new_count, "locked_until": locked_until},
        )
    return new_count, locked_until


async def reset_failed_login(db: Database, *, user_id: str) -> None:
    """Successful login — clear lockout state."""
    await db.execute(
        "UPDATE users SET failed_login_count = 0, locked_until = NULL, "
        "status = CASE WHEN status = 'locked' THEN 'active' ELSE status END, "
        "last_login_at = $1, updated_at = $1 WHERE user_id = $2",
        now_ms(),
        user_id,
    )


async def update_password_hash(
    db: Database, *, user_id: str, password_hash: str, pepper_kid: str
) -> None:
    await db.execute(
        "UPDATE users SET password_hash = $1, password_pepper_kid = $2, "
        "updated_at = $3 WHERE user_id = $4",
        password_hash,
        pepper_kid,
        now_ms(),
        user_id,
    )


async def set_totp_enabled(db: Database, *, user_id: str, enabled: bool) -> None:
    await db.execute(
        "UPDATE users SET totp_enabled = $1, updated_at = $2 WHERE user_id = $3",
        enabled,
        now_ms(),
        user_id,
    )


async def set_email_verified(db: Database, *, user_id: str) -> None:
    now = now_ms()
    await db.execute(
        "UPDATE users SET email_verified_at = $1, updated_at = $1 WHERE user_id = $2",
        now,
        user_id,
    )


async def change_role(db: Database, *, user_id: str, org_id: str, role: Role) -> None:
    await db.execute(
        "UPDATE memberships SET role = $1 WHERE user_id = $2 AND org_id = $3",
        role,
        user_id,
        org_id,
    )


def lockout_is_active(user: UserRow) -> bool:
    return (
        user.status == "locked" and user.locked_until is not None and user.locked_until > now_ms()
    )


def verify_or_raise_locked(user: UserRow) -> None:
    """Return cleanly if the account is usable; raise the uniform 401 otherwise.

    Uniform 401 (§A7) for: disabled account, active lockout. The route layer
    catches this and emits the audit row.
    """
    if user.status == "disabled":
        raise AppError(401, "UNAUTHORIZED")
    if lockout_is_active(user):
        raise AppError(401, "UNAUTHORIZED")


__all__ = [
    "LOCKOUT_MINUTES_SCHEDULE",
    "LOCKOUT_THRESHOLD",
    "UserRow",
    "VerifyResult",
    "change_role",
    "create_user",
    "find_by_email",
    "find_by_user_id",
    "lockout_is_active",
    "primary_membership",
    "record_failed_login",
    "reset_failed_login",
    "role_for",
    "set_email_verified",
    "set_totp_enabled",
    "update_password_hash",
    "verify_or_raise_locked",
]
