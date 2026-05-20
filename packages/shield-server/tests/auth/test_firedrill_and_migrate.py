"""ADR-0013 §A5 — Migration fire-drill helper (unit_auth).

The integration-suite fire-drill (``tests/integration/auth/test_a5_firedrill_
fulldrill.py``) exercises the helper against the REAL Postgres up/down
cycle. This unit test confirms the helper signature + the byte-identity
comparison logic on synthetic snapshots, so any helper-side regression
surfaces in the cheap python-auth job, not only the slow integration job.
"""

from __future__ import annotations

import pytest
from shield_server.auth.migration_firedrill import (
    W3_PROTECTED_TABLES,
    TableSnapshot,
    W3Snapshot,
    compare_w3_tables_byte_identity,
    snapshot_w3_tables,
)
from shield_server.migrate import MIGRATIONS, _apply_down, _apply_up, read_revision_sql
from shield_server.storage import build_memory_storage

pytestmark = pytest.mark.unit_auth


def test_compare_byte_identity_passes_on_equal_snapshots() -> None:
    pre = W3Snapshot(
        tables={
            t: TableSnapshot(table=t, row_count=2, row_checksum="abc") for t in W3_PROTECTED_TABLES
        }
    )
    post = W3Snapshot(tables=dict(pre.tables))
    compare_w3_tables_byte_identity(pre, post)  # no raise


def test_compare_byte_identity_raises_on_count_drift() -> None:
    pre = W3Snapshot(
        tables={
            t: TableSnapshot(table=t, row_count=2, row_checksum="abc") for t in W3_PROTECTED_TABLES
        }
    )
    post_tables = dict(pre.tables)
    post_tables["agents"] = TableSnapshot(table="agents", row_count=1, row_checksum="abc")
    post = W3Snapshot(tables=post_tables)
    with pytest.raises(AssertionError, match="row_count drift in W3 table 'agents'"):
        compare_w3_tables_byte_identity(pre, post)


def test_compare_byte_identity_raises_on_checksum_drift() -> None:
    pre = W3Snapshot(
        tables={
            t: TableSnapshot(table=t, row_count=2, row_checksum="abc") for t in W3_PROTECTED_TABLES
        }
    )
    post_tables = dict(pre.tables)
    post_tables["operations"] = TableSnapshot(table="operations", row_count=2, row_checksum="XYZ")
    post = W3Snapshot(tables=post_tables)
    with pytest.raises(AssertionError, match="row_checksum drift in W3 table 'operations'"):
        compare_w3_tables_byte_identity(pre, post)


def test_compare_byte_identity_raises_on_table_set_drift() -> None:
    pre = W3Snapshot(
        tables={
            t: TableSnapshot(table=t, row_count=0, row_checksum="z") for t in W3_PROTECTED_TABLES
        }
    )
    post = W3Snapshot(
        tables={
            t: TableSnapshot(table=t, row_count=0, row_checksum="z")
            for t in W3_PROTECTED_TABLES[1:]
        }
    )
    with pytest.raises(AssertionError, match="W3 table set drift"):
        compare_w3_tables_byte_identity(pre, post)


@pytest.mark.asyncio
async def test_snapshot_w3_tables_against_memory_db() -> None:
    storage = build_memory_storage()
    snap = await snapshot_w3_tables(storage.db)
    # Every protected table is present in the snapshot.
    assert set(snap.names) == set(W3_PROTECTED_TABLES)


def test_migrate_migrations_list_versions_4_and_5() -> None:
    versions = [m.version for m in MIGRATIONS]
    assert versions == [4, 5]


def test_migrate_read_revision_sql_loads_files() -> None:
    rev = MIGRATIONS[0]
    up = read_revision_sql(rev, direction="up")
    down = read_revision_sql(rev, direction="down")
    assert "CREATE TABLE IF NOT EXISTS users" in up
    assert "DROP TABLE IF EXISTS users" in down


def test_migrate_read_revision_sql_rejects_bad_direction() -> None:
    rev = MIGRATIONS[0]
    with pytest.raises(ValueError, match="direction"):
        read_revision_sql(rev, direction="sideways")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_apply_down_via_executor_dispatch() -> None:
    calls: list[str] = []

    async def fake_execute(sql: str) -> None:
        calls.append(sql)

    await _apply_down(fake_execute, version=4)
    await _apply_down(fake_execute, version=5)
    assert any("DROP TABLE IF EXISTS users" in c for c in calls)
    assert any("DROP TABLE IF EXISTS api_keys" in c for c in calls)


@pytest.mark.asyncio
async def test_apply_down_unknown_version_raises() -> None:
    async def fake(_sql: str) -> None:
        pass

    with pytest.raises(ValueError, match="no down migration"):
        await _apply_down(fake, version=99)
    # The W3 baseline (version 1) has NO down — must also raise.
    with pytest.raises(ValueError, match="no down migration"):
        await _apply_down(fake, version=1)


@pytest.mark.asyncio
async def test_apply_up_via_executor_dispatch() -> None:
    calls: list[str] = []

    async def fake_execute(sql: str) -> None:
        calls.append(sql)

    await _apply_up(fake_execute, MIGRATIONS[0])
    await _apply_up(fake_execute, MIGRATIONS[1])
    assert any("CREATE TABLE IF NOT EXISTS users" in c for c in calls)
    assert any("CREATE TABLE IF NOT EXISTS api_keys" in c for c in calls)
