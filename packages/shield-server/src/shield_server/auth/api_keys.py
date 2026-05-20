"""ADR-0013 §A8 / D1 — Tri-mode SDK API keys + ``authorize_ingest`` predicate.

Tri-mode scope (D1):
  * ``org-wide``       — ``agent_id IS NULL`` AND ``agent_id_allowlist IS NULL``.
                         Default UI; the key carries the full org's agents.
  * ``single-agent``   — ``agent_id`` non-NULL. Strictest — only the named agent.
  * ``allowlist``      — ``agent_id_allowlist`` non-NULL TEXT[]. Bounded subset.

``authorize_ingest(principal, record)`` is fail-closed in the order listed in
ADR-0013 §A8: org-mismatch → org-wide membership → single-agent equality →
allowlist membership. Each deny returns a stable ``reason`` string that the
``API_KEY_AUTHZ_DENY`` audit row carries; the response surfaces a uniform 403
with ``error.detail.reason`` so the console can show "scope mismatch" without
exposing the actual key shape.

Token format (display-only, per §A7): prefix ``as_live_`` for production keys
and ``as_test_`` for test keys; the suffix is the random opaque material. The
SHA-256 of the full string is stored in ``token_hash`` — the prefix carries
no entropy and is purely a human cue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..storage import Database
from .principal import Principal
from .utils import generate_opaque_token, now_ms, sha256_hex, uuidv7

KeyPrefix = Literal["as_live_", "as_test_"]


@dataclass(frozen=True, slots=True)
class ApiKeyRow:
    """Row projection consumed by ``authorize_ingest`` + the admin endpoints."""

    api_key_id: str
    org_id: str
    agent_id: str | None
    agent_id_allowlist: tuple[str, ...] | None
    prefix: KeyPrefix
    display_name: str
    created_by: str
    created_at: int
    expires_at: int | None
    last_used_at: int | None
    revoked_at: int | None


@dataclass(frozen=True, slots=True)
class IssuedApiKey:
    """The raw key (shown ONCE on issue) + the row."""

    raw_key: str
    row: ApiKeyRow


@dataclass(frozen=True, slots=True)
class AuthzAllow:
    pass


@dataclass(frozen=True, slots=True)
class AuthzDeny:
    reason: Literal[
        "record_org_mismatch",
        "agent_outside_org",
        "agent_outside_key_scope",
        "agent_outside_allowlist",
    ]
    http: int = 403


AuthzResult = AuthzAllow | AuthzDeny


# --- issue / lookup / list / revoke ------------------------------------ #


async def issue_api_key(
    db: Database,
    *,
    org_id: str,
    created_by: str,
    prefix: KeyPrefix,
    display_name: str = "",
    agent_id: str | None = None,
    agent_id_allowlist: tuple[str, ...] | None = None,
    expires_at: int | None = None,
) -> IssuedApiKey:
    """Issue a fresh api_key row; return the raw key for one-time display.

    The caller's UI is responsible for showing the raw key ONCE then
    discarding it — the server stores only ``sha256(raw_key)``.
    """
    if agent_id is not None and agent_id_allowlist is not None:
        raise ValueError(
            "api_key cannot carry both agent_id and agent_id_allowlist; "
            "use exactly one of the three modes (org-wide / single-agent / allowlist)."
        )
    api_key_id = uuidv7()
    suffix = generate_opaque_token(num_bytes=32)
    raw_key = f"{prefix}{suffix}"
    token_hash = sha256_hex(raw_key)
    now = now_ms()
    await db.execute(
        "INSERT INTO api_keys (api_key_id, org_id, agent_id, agent_id_allowlist, "
        "token_hash, prefix, display_name, created_by, created_at, expires_at, "
        "last_used_at, revoked_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NULL, NULL)",
        api_key_id,
        org_id,
        agent_id,
        list(agent_id_allowlist) if agent_id_allowlist else None,
        token_hash,
        prefix,
        display_name,
        created_by,
        now,
        expires_at,
    )
    return IssuedApiKey(
        raw_key=raw_key,
        row=ApiKeyRow(
            api_key_id=api_key_id,
            org_id=org_id,
            agent_id=agent_id,
            agent_id_allowlist=agent_id_allowlist,
            prefix=prefix,
            display_name=display_name,
            created_by=created_by,
            created_at=now,
            expires_at=expires_at,
            last_used_at=None,
            revoked_at=None,
        ),
    )


def _row_to_dataclass(row: dict[str, object]) -> ApiKeyRow:
    raw_allowlist = row.get("agent_id_allowlist")
    allowlist: tuple[str, ...] | None
    if raw_allowlist is None:
        allowlist = None
    elif isinstance(raw_allowlist, (list, tuple)):
        allowlist = tuple(str(x) for x in raw_allowlist)
    else:
        allowlist = None
    prefix_raw = str(row.get("prefix") or "as_live_")
    prefix: KeyPrefix = prefix_raw if prefix_raw in ("as_live_", "as_test_") else "as_live_"  # type: ignore[assignment]
    return ApiKeyRow(
        api_key_id=str(row["api_key_id"]),
        org_id=str(row["org_id"]),
        agent_id=(str(row["agent_id"]) if row.get("agent_id") is not None else None),
        agent_id_allowlist=allowlist,
        prefix=prefix,
        display_name=str(row.get("display_name") or ""),
        created_by=str(row["created_by"]),
        created_at=int(row["created_at"]),  # type: ignore[call-overload]
        expires_at=(int(row["expires_at"]) if row.get("expires_at") is not None else None),  # type: ignore[call-overload]
        last_used_at=(int(row["last_used_at"]) if row.get("last_used_at") is not None else None),  # type: ignore[call-overload]
        revoked_at=(int(row["revoked_at"]) if row.get("revoked_at") is not None else None),  # type: ignore[call-overload]
    )


async def lookup_api_key(db: Database, *, raw_key: str) -> ApiKeyRow | None:
    """Resolve a raw bearer token to its row, enforcing not-revoked + not-expired."""
    if not raw_key:
        return None
    token_hash = sha256_hex(raw_key)
    row = await db.fetchrow(
        "SELECT api_key_id, org_id, agent_id, agent_id_allowlist, prefix, "
        "display_name, created_by, created_at, expires_at, last_used_at, "
        "revoked_at FROM api_keys WHERE token_hash = $1",
        token_hash,
    )
    if row is None:
        return None
    if row.get("revoked_at") is not None:
        return None
    expires_at = row.get("expires_at")
    if expires_at is not None and int(expires_at) < now_ms():  # type: ignore[call-overload]
        return None
    return _row_to_dataclass(row)


async def touch_api_key(db: Database, *, api_key_id: str) -> None:
    await db.execute(
        "UPDATE api_keys SET last_used_at = $1 WHERE api_key_id = $2",
        now_ms(),
        api_key_id,
    )


async def revoke_api_key(db: Database, *, api_key_id: str) -> None:
    await db.execute(
        "UPDATE api_keys SET revoked_at = $1 WHERE api_key_id = $2",
        now_ms(),
        api_key_id,
    )


async def list_api_keys_for_org(db: Database, *, org_id: str) -> list[ApiKeyRow]:
    rows = await db.fetch(
        "SELECT api_key_id, org_id, agent_id, agent_id_allowlist, prefix, "
        "display_name, created_by, created_at, expires_at, last_used_at, "
        "revoked_at FROM api_keys WHERE org_id = $1",
        org_id,
    )
    return [_row_to_dataclass(r) for r in rows]


# --- the §A8 fail-closed predicate -------------------------------------- #


async def agents_in_org(db: Database, *, org_id: str) -> frozenset[str]:
    """Return the set of agent_ids registered against ``org_id``.

    The §A8 predicate calls this once per ingest to check
    ``record.agent_id ∈ org`` for org-wide keys. Cheap (single indexed
    query); the route layer may cache per request if many records arrive
    in a burst.
    """
    rows = await db.fetch("SELECT agent_id FROM agents WHERE org_id = $1", org_id)
    return frozenset(str(r["agent_id"]) for r in rows)


async def authorize_ingest(
    db: Database, *, principal: Principal, record_org_id: str, record_agent_id: str
) -> AuthzResult:
    """ADR-0013 §A8 — fail-closed authorisation for /v1/governance/{decide,record} ingest.

    Order of checks (verbatim from §A8):
      1. ``principal.org_id == record.org_id`` else 403 ``record_org_mismatch``.
      2. If key.agent_id is None and key.agent_id_allowlist is None →
         org-wide: ``record.agent_id ∈ storage.agents_in_org(principal.org_id)``
         else 403 ``agent_outside_org``.
      3. If key.agent_id is not None → equality, else 403 ``agent_outside_key_scope``.
      4. If key.agent_id_allowlist is not None → membership, else 403
         ``agent_outside_allowlist``.
    """
    # Clause 1 — org match. NON-NEGOTIABLE. Even if the key carries
    # broader scope, an org-mismatch is a hard deny (the principal cannot
    # speak for another org regardless of agent scope).
    if principal.org_id != record_org_id:
        return AuthzDeny(reason="record_org_mismatch")
    agent_id = principal.api_key_agent_id
    allowlist = principal.api_key_agent_id_allowlist
    # Clause 2 — org-wide (both None)
    if agent_id is None and allowlist is None:
        members = await agents_in_org(db, org_id=principal.org_id)
        if record_agent_id not in members:
            return AuthzDeny(reason="agent_outside_org")
        return AuthzAllow()
    # Clause 3 — single-agent equality
    if agent_id is not None:
        if record_agent_id != agent_id:
            return AuthzDeny(reason="agent_outside_key_scope")
        return AuthzAllow()
    # Clause 4 — allowlist membership
    assert allowlist is not None  # pragma: no cover - clauses 2/3 cover the None paths
    if record_agent_id not in allowlist:
        return AuthzDeny(reason="agent_outside_allowlist")
    return AuthzAllow()


__all__ = [
    "ApiKeyRow",
    "AuthzAllow",
    "AuthzDeny",
    "AuthzResult",
    "IssuedApiKey",
    "KeyPrefix",
    "agents_in_org",
    "authorize_ingest",
    "issue_api_key",
    "list_api_keys_for_org",
    "lookup_api_key",
    "revoke_api_key",
    "touch_api_key",
]
