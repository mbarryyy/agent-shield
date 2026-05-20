"""ADR-0013 §A8 + D1 — Tri-mode api-keys + ``authorize_ingest`` fail-closed (unit_auth).

The 5 mandated security tests (a–e) live ALSO at
``tests/integration/auth/test_api_key_scope.py`` against the real DB; this
unit-level pass covers MemoryDatabase + lookup/issue/revoke roundtrip plus
the orthogonality cross-check (e).
"""

from __future__ import annotations

import asyncio

import pytest
import shield_sdk.canonical as canonical
import shield_sdk.crypto as crypto
from shield_sdk.schema import ShieldActionRecord
from shield_server.auth.api_keys import (
    AuthzAllow,
    AuthzDeny,
    authorize_ingest,
    issue_api_key,
    list_api_keys_for_org,
    lookup_api_key,
    revoke_api_key,
)
from shield_server.auth.principal import Principal
from shield_server.storage import build_memory_storage

pytestmark = pytest.mark.unit_auth


def _principal_for(row: object) -> Principal:
    """Build a Principal that mirrors how the dep layer wraps an api_key row."""
    from shield_server.auth.api_keys import ApiKeyRow

    assert isinstance(row, ApiKeyRow)
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


async def _setup_org(storage, *, org_id: str, user_id: str, agent_ids: list[str]) -> None:
    """Seed the agents table so org-wide membership checks have anchors."""
    from shield_server.auth.utils import now_ms

    storage.db.users[user_id] = {
        "user_id": user_id,
        "email": "u@x",
        "password_hash": "x",
        "password_pepper_kid": "p1",
        "name": "u",
        "status": "active",
        "email_verified_at": None,
        "failed_login_count": 0,
        "locked_until": None,
        "totp_enabled": False,
        "created_at": now_ms(),
        "updated_at": now_ms(),
        "last_login_at": None,
    }
    for ag in agent_ids:
        await storage.db.execute(
            "INSERT INTO agents (agent_id, org_id, display_name, "
            "responsible_entity, integration_type, status, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            ag,
            org_id,
            ag,
            "owner",
            "sdk",
            "active",
            now_ms(),
            now_ms(),
        )


def test_authorize_ingest_org_wide_allow_and_deny() -> None:
    storage = build_memory_storage()

    async def run() -> None:
        await _setup_org(storage, org_id="org-A", user_id="u1", agent_ids=["ag-1", "ag-2"])
        issued = await issue_api_key(storage.db, org_id="org-A", created_by="u1", prefix="as_live_")
        p = _principal_for(issued.row)
        # (d) Valid record → ALLOW.
        ok = await authorize_ingest(
            storage.db, principal=p, record_org_id="org-A", record_agent_id="ag-1"
        )
        assert isinstance(ok, AuthzAllow)
        # (a) Org mismatch → DENY.
        d = await authorize_ingest(
            storage.db, principal=p, record_org_id="org-B", record_agent_id="ag-1"
        )
        assert isinstance(d, AuthzDeny) and d.reason == "record_org_mismatch"
        # Agent not in org's agents table → DENY.
        d2 = await authorize_ingest(
            storage.db, principal=p, record_org_id="org-A", record_agent_id="ag-OUT"
        )
        assert isinstance(d2, AuthzDeny) and d2.reason == "agent_outside_org"

    asyncio.run(run())


def test_authorize_ingest_single_agent_key() -> None:
    storage = build_memory_storage()

    async def run() -> None:
        await _setup_org(storage, org_id="org-A", user_id="u1", agent_ids=["ag-x", "ag-y"])
        issued = await issue_api_key(
            storage.db,
            org_id="org-A",
            created_by="u1",
            prefix="as_live_",
            agent_id="ag-x",
        )
        p = _principal_for(issued.row)
        # (c) Mismatch — record claims ag-y, key bound to ag-x.
        d = await authorize_ingest(
            storage.db, principal=p, record_org_id="org-A", record_agent_id="ag-y"
        )
        assert isinstance(d, AuthzDeny) and d.reason == "agent_outside_key_scope"
        # Match → ALLOW.
        ok = await authorize_ingest(
            storage.db, principal=p, record_org_id="org-A", record_agent_id="ag-x"
        )
        assert isinstance(ok, AuthzAllow)

    asyncio.run(run())


def test_authorize_ingest_allowlist() -> None:
    storage = build_memory_storage()

    async def run() -> None:
        await _setup_org(storage, org_id="org-A", user_id="u1", agent_ids=["ag-x", "ag-y", "ag-z"])
        issued = await issue_api_key(
            storage.db,
            org_id="org-A",
            created_by="u1",
            prefix="as_live_",
            agent_id_allowlist=("ag-x", "ag-y"),
        )
        p = _principal_for(issued.row)
        # (b) Outside the allowlist.
        d = await authorize_ingest(
            storage.db, principal=p, record_org_id="org-A", record_agent_id="ag-z"
        )
        assert isinstance(d, AuthzDeny) and d.reason == "agent_outside_allowlist"
        # Inside → ALLOW.
        ok = await authorize_ingest(
            storage.db, principal=p, record_org_id="org-A", record_agent_id="ag-x"
        )
        assert isinstance(ok, AuthzAllow)

    asyncio.run(run())


def test_api_key_roundtrip_lookup_revoke() -> None:
    storage = build_memory_storage()

    async def run() -> None:
        await _setup_org(storage, org_id="org-A", user_id="u1", agent_ids=["ag-x"])
        issued = await issue_api_key(storage.db, org_id="org-A", created_by="u1", prefix="as_test_")
        row = await lookup_api_key(storage.db, raw_key=issued.raw_key)
        assert row is not None and row.api_key_id == issued.row.api_key_id
        listed = await list_api_keys_for_org(storage.db, org_id="org-A")
        assert len(listed) == 1
        await revoke_api_key(storage.db, api_key_id=issued.row.api_key_id)
        # After revoke, lookup returns None.
        assert await lookup_api_key(storage.db, raw_key=issued.raw_key) is None

    asyncio.run(run())


def test_authorize_ingest_orthogonality_signature_independent() -> None:
    """(e) — even with the api-key DENIED, the record's Ed25519 signature
    must still verify via FROZEN ``canonical.verify_record`` independently
    of the api-key (D1 ⨉ sdk-builder S5 orthogonality)."""
    PRIV = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
    PUB = crypto.get_public_key_base64url(PRIV)
    storage = build_memory_storage()

    async def run() -> None:
        await _setup_org(storage, org_id="org-A", user_id="u1", agent_ids=["ag-x"])
        issued = await issue_api_key(
            storage.db,
            org_id="org-A",
            created_by="u1",
            prefix="as_live_",
            agent_id="ag-x",
        )
        p = _principal_for(issued.row)
        rec = ShieldActionRecord(
            org_id="org-B",  # MISMATCH → api-key will deny
            agent_id="ag-x",
            agent_pubkey_kid="kid-1",
            phase="pre_exec",
            run_id="run-1",
        )
        rec = canonical.finalize_record(rec, PRIV)
        # api-key authorize → DENY (record_org_mismatch).
        d = await authorize_ingest(
            storage.db, principal=p, record_org_id=rec.org_id, record_agent_id=rec.agent_id
        )
        assert isinstance(d, AuthzDeny) and d.reason == "record_org_mismatch"
        # BUT the record's Ed25519 signature MUST still verify — proves the
        # two authorities (api-key scope + record signature) are orthogonal.
        assert canonical.verify_record(rec, PUB) is True

    asyncio.run(run())
