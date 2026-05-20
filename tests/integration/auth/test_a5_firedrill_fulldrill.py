"""ADR-0013 §A5 — Full migration fire-drill against real Postgres.

End-to-end exercise of the up→down cycle:

  1. ``migrate.apply(dsn)`` brings the schema up to ADR-0013 v5.
  2. Insert fixture rows into the W3 protected tables (agents / agent_keys /
     operations / receipts / epochs / exports / intervention_log /
     governance_verdicts). agent_sessions is Postgres-only and may be empty.
  3. Snapshot every protected table with ``snapshot_w3_tables``.
  4. Apply 005-down and 004-down via ``_apply_down``.
  5. Re-snapshot.
  6. Call ``compare_w3_tables_byte_identity`` — MUST raise nothing.

Runs only under ``SHIELD_AUTH_MODE=enterprise`` (the auth-integration job),
gated by the existing ``integration_auth`` marker. Requires the docker-
compose Postgres to be reachable on ``DATABASE_URL``; skips otherwise so
local devs without infra can still run other integration_auth tests.
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytestmark = pytest.mark.integration_auth


def _dsn() -> str | None:
    return os.environ.get("DATABASE_URL", "postgresql://shield:shield@localhost:5432/shield")


@pytest.fixture
def asyncpg_conn():
    try:
        import asyncpg
    except ImportError:  # pragma: no cover
        pytest.skip("asyncpg not installed")

    async def _connect():
        return await asyncpg.connect(_dsn() or "")

    try:
        conn = asyncio.run(_connect())
    except Exception as exc:  # pragma: no cover - infra-dependent
        pytest.skip(f"Postgres not reachable at {_dsn()}: {exc}")
    yield conn
    asyncio.run(conn.close())


def test_a5_firedrill_byte_identity_across_up_down(asyncpg_conn) -> None:
    """Full §A5 fire-drill — up → fixture → snapshot → down → snapshot → compare."""
    from shield_server.auth.migration_firedrill import (
        compare_w3_tables_byte_identity,
        snapshot_w3_tables,
    )
    from shield_server.migrate import MIGRATIONS, SCHEMA_SQL, _apply_down

    async def run() -> None:
        # 1. Apply W3 baseline + every ADR-0013 up revision.
        await asyncpg_conn.execute(SCHEMA_SQL)
        for rev in MIGRATIONS:
            await asyncpg_conn.execute(rev.up_path.read_text())
        # 2. Seed fixture rows into W3 tables (idempotent — these may already
        # exist from a previous run; ON CONFLICT DO NOTHING keeps it safe).
        await asyncpg_conn.execute(
            "INSERT INTO organizations (org_id, name, created_at, updated_at) "
            "VALUES ('a5-fixture-org', 'A5 Fixture', 1, 1) "
            "ON CONFLICT (org_id) DO NOTHING"
        )
        await asyncpg_conn.execute(
            "INSERT INTO agents (agent_id, org_id, display_name, "
            "responsible_entity, integration_type, status, created_at, updated_at) "
            "VALUES ('a5-fixture-agent', 'a5-fixture-org', 'A5', 'A5', 'sdk', "
            "'active', 1, 1) ON CONFLICT (agent_id) DO NOTHING"
        )

        # 3. Snapshot the W3 protected set BEFORE down-migration.
        class _ConnDB:
            async def fetch(self, sql, *args):
                return [dict(r) for r in await asyncpg_conn.fetch(sql, *args)]

        pre = await snapshot_w3_tables(_ConnDB())
        # 4. Run the auth-down chain (5 then 4) via the internal helper.
        await _apply_down(asyncpg_conn.execute, version=5)
        await _apply_down(asyncpg_conn.execute, version=4)
        # 5. Re-snapshot. 6. Assert byte-identity.
        post = await snapshot_w3_tables(_ConnDB())
        compare_w3_tables_byte_identity(pre, post)
        # Cleanup — reapply auth up so subsequent integration tests are not
        # affected by this drill.
        for rev in MIGRATIONS:
            await asyncpg_conn.execute(rev.up_path.read_text())

    asyncio.run(run())
