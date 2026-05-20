"""ADR-0013 §A5 — Full migration fire-drill against real Postgres.

End-to-end exercise of the up→down cycle:

  1. Apply W3 baseline + every ADR-0013 up revision.
  2. Seed fixture rows into the W3 protected tables.
  3. Snapshot every protected table with ``snapshot_w3_tables``.
  4. Apply 005-down and 004-down via ``_apply_down``.
  5. Re-snapshot.
  6. Call ``compare_w3_tables_byte_identity`` — MUST raise nothing.

Runs only under ``SHIELD_AUTH_MODE=enterprise`` (the auth-integration job),
gated by the ``integration_auth`` marker. Requires the docker-compose
Postgres reachable on ``DATABASE_URL``; skips otherwise so local devs
without infra can still run other integration_auth tests.

Implementation note: all DB operations live inside a SINGLE ``asyncio.run``
block. asyncpg connections are bound to the event loop that created them,
so we cannot open the connection in a pytest fixture (separate loop) and
then use it inside the test's loop.
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytestmark = pytest.mark.integration_auth


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://shield:shield@localhost:5432/shield?sslmode=disable",
    )


def _ssl_param(dsn: str) -> object:
    """Mirror ``migrate.apply``'s SSL handling: default False, sslmode= wins."""
    lowered = dsn.lower()
    for token in ("sslmode=require", "sslmode=verify-ca", "sslmode=verify-full"):
        if token in lowered:
            return True
    return False


def test_a5_firedrill_byte_identity_across_up_down() -> None:
    """Full §A5 fire-drill — up → fixture → snapshot → down → snapshot → compare."""
    try:
        import asyncpg
    except ImportError:  # pragma: no cover
        pytest.skip("asyncpg not installed")

    from shield_server.auth.migration_firedrill import (
        compare_w3_tables_byte_identity,
        snapshot_w3_tables,
    )
    from shield_server.migrate import MIGRATIONS, SCHEMA_SQL, _apply_down

    dsn = _dsn()
    ssl_param = _ssl_param(dsn)

    async def run() -> None:
        try:
            conn = await asyncpg.connect(dsn, ssl=ssl_param)
        except (OSError, ConnectionError) as exc:  # pragma: no cover
            pytest.skip(f"Postgres not reachable at {dsn}: {exc}")
            return
        try:
            # 1. Apply W3 baseline + every ADR-0013 up revision.
            await conn.execute(SCHEMA_SQL)
            for rev in MIGRATIONS:
                await conn.execute(rev.up_path.read_text())
            # 2. Seed fixture rows into the protected set.
            await conn.execute(
                "INSERT INTO organizations (org_id, name, created_at, updated_at) "
                "VALUES ('a5-fixture-org', 'A5 Fixture', 1, 1) "
                "ON CONFLICT (org_id) DO NOTHING"
            )
            await conn.execute(
                "INSERT INTO agents (agent_id, org_id, display_name, "
                "responsible_entity, integration_type, status, created_at, updated_at) "
                "VALUES ('a5-fixture-agent', 'a5-fixture-org', 'A5', 'A5', 'sdk', "
                "'active', 1, 1) ON CONFLICT (agent_id) DO NOTHING"
            )

            class _ConnDB:
                async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
                    return [dict(r) for r in await conn.fetch(sql, *args)]

            # 3. Snapshot BEFORE down-migration.
            pre = await snapshot_w3_tables(_ConnDB())
            # 4. Run the auth-down chain (5 then 4) via the internal helper.
            await _apply_down(conn.execute, version=5)
            await _apply_down(conn.execute, version=4)
            # 5. Re-snapshot.
            post = await snapshot_w3_tables(_ConnDB())
            # 6. Assert W3 byte-identity.
            compare_w3_tables_byte_identity(pre, post)
            # Cleanup — reapply auth up so subsequent integration tests are
            # not affected by this drill.
            for rev in MIGRATIONS:
                await conn.execute(rev.up_path.read_text())
        finally:
            await conn.close()

    asyncio.run(run())
