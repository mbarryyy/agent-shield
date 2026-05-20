"""ADR-0013 — ``shield-server seed-admin`` auto-creates the ``organizations``
row (unit_auth).

Drives ``_seed_admin_via_db`` against ``MemoryDatabase`` so the CLI's
direct-DB flow is exercised without docker-compose Postgres. Verifies:

  * Brand-new ``--org`` id auto-creates the organizations row + user +
    membership.
  * Pre-existing ``--org`` id (e.g. ``demo-org`` after W3 migrate seed) is
    a no-op for the org INSERT (``ON CONFLICT DO NOTHING``) and proceeds
    to create the user + membership.
  * Idempotency: re-running with the SAME --email is a no-op (the
    existing-user short-circuit kicks in, the org row is not duplicated).
  * The CLI help text declares the auto-create behaviour so operators
    know the contract.
"""

from __future__ import annotations

import asyncio

import pytest
from shield_server.auth.cli import (
    _ensure_organization,
    _seed_admin_via_db,
)
from shield_server.auth.cli import (
    main as cli_main,
)
from shield_server.storage import build_memory_storage

pytestmark = pytest.mark.unit_auth


def test_seed_admin_creates_org_when_missing() -> None:
    """Brand-new --org id: organizations row + users row + memberships row."""
    storage = build_memory_storage()
    result = asyncio.run(
        _seed_admin_via_db(
            storage.db,
            email="bootstrap@example.com",
            org="fresh-org",
            name="Bootstrap",
            password="shield-pw-1",
        )
    )
    assert "created org_owner" in result
    # organizations row created.
    assert "fresh-org" in storage.db.organizations
    assert storage.db.organizations["fresh-org"]["name"] == "fresh-org"
    # user + membership.
    users = [u for u in storage.db.users.values() if u["email"] == "bootstrap@example.com"]
    assert len(users) == 1
    user_id = users[0]["user_id"]
    assert (user_id, "fresh-org") in storage.db.memberships
    assert storage.db.memberships[(user_id, "fresh-org")]["role"] == "org_owner"


def test_seed_admin_no_op_on_existing_org() -> None:
    """Pre-existing --org id: org INSERT is ON CONFLICT DO NOTHING; user
    + membership still created (assuming a NEW email)."""
    storage = build_memory_storage()
    # Pre-seed demo-org row (simulating the standard W3 migrate seed).
    asyncio.run(_ensure_organization(storage.db, org_id="demo-org", name="Demo Org"))
    assert storage.db.organizations["demo-org"]["name"] == "Demo Org"
    # Second call with same --org must NOT overwrite ('Demo Org' stays).
    result = asyncio.run(
        _seed_admin_via_db(
            storage.db,
            email="admin@example.com",
            org="demo-org",
            name="Admin",
            password="shield-pw-1",
        )
    )
    assert "created org_owner" in result
    assert storage.db.organizations["demo-org"]["name"] == "Demo Org"  # preserved


def test_seed_admin_idempotent_on_repeat_email() -> None:
    """Re-running with the same --email is a no-op (existing-user short-
    circuit). The org INSERT is also a no-op (ON CONFLICT)."""
    storage = build_memory_storage()
    first = asyncio.run(
        _seed_admin_via_db(
            storage.db,
            email="dup@example.com",
            org="dup-org",
            name="Dup",
            password="shield-pw-1",
        )
    )
    assert "created org_owner" in first
    # Second call with the SAME email + org.
    second = asyncio.run(
        _seed_admin_via_db(
            storage.db,
            email="dup@example.com",
            org="dup-org",
            name="Dup",
            password="shield-pw-1",
        )
    )
    assert "already exists" in second
    assert "no-op" in second
    # Still exactly ONE user + ONE org row.
    assert len([u for u in storage.db.users.values() if u["email"] == "dup@example.com"]) == 1
    assert "dup-org" in storage.db.organizations


def test_seed_admin_cli_help_documents_auto_create(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The --org help text MUST declare the auto-create behaviour so
    operators know what they're getting from the CLI contract."""
    with pytest.raises(SystemExit):
        cli_main(["seed-admin", "--help"])
    out = capsys.readouterr().out
    assert "--org" in out
    # argparse wraps the help text across lines; collapse whitespace before
    # matching so the assertion isn't fragile against terminal-width wrapping.
    collapsed = " ".join(out.split())
    assert "auto-created if not present" in collapsed


def test_ensure_organization_is_idempotent() -> None:
    """Direct test of the helper used by the CLI — two INSERTs of the
    same org_id produce exactly one row, with the FIRST row's values
    preserved (ON CONFLICT DO NOTHING semantics)."""
    storage = build_memory_storage()
    asyncio.run(_ensure_organization(storage.db, org_id="x-org", name="First"))
    first_created_at = storage.db.organizations["x-org"]["created_at"]
    asyncio.run(_ensure_organization(storage.db, org_id="x-org", name="Second"))
    # ``name`` stays as the FIRST value (DO NOTHING semantics).
    assert storage.db.organizations["x-org"]["name"] == "First"
    assert storage.db.organizations["x-org"]["created_at"] == first_created_at
    # Exactly one row.
    assert len(storage.db.organizations) == 1
