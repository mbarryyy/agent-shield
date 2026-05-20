"""ADR-0013 §A5 — CI migration fire-drill helper.

The forcing-function test ``tests/integration/auth/test_a5_firedrill_wired.py``
imports the exact symbol path ``shield_server.auth.migration_firedrill.
compare_w3_tables_byte_identity`` — this module is the dispositive landing of
that helper. When this file lands on a server-builder PR, the ``auth-
integration`` CI job flips from RED (ImportError at collection) to GREEN.

The helper enforces the W3 byte-identity invariant from ADR-0013 §A5:

    W3_PROTECTED_TABLES = (
        "agents", "agent_keys", "operations", "receipts",
        "epochs", "exports", "agent_sessions",
        "intervention_log", "governance_verdicts",
    )
    for t in W3_PROTECTED_TABLES:
        assert post_down.row_count(t)    == pre_up.row_count(t),    f"row count drift in {t}"
        assert post_down.row_checksum(t) == pre_up.row_checksum(t), f"row checksum drift in {t}"

``row_checksum`` is SHA-256 of the sorted serialisation of every row, so a
silent UPDATE on an existing row (same count) is caught — count alone is
insufficient. The full fire-drill integration test invokes ``migrate.apply``
up, inserts fixture rows in the W3 tables, runs ``migrate._apply_down`` over
the auth revisions, and asserts ``compare_w3_tables_byte_identity`` raises
nothing — proving down-migration NEVER touches the W3 protected tables.

This module is import-safe (no DB connection at import time); the helper takes
a ``Database`` protocol instance so it works against both ``MemoryDatabase``
(unit/cov) and ``PostgresDatabase`` (integration).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

# ADR-0013 §A5: the canonical list of W3 tables that auth down-migrations are
# FORBIDDEN to touch. Adding any auth-owned table here would silently let auth
# down-migration data-loss through; the list is intentionally W3-only.
W3_PROTECTED_TABLES: tuple[str, ...] = (
    "agents",
    "agent_keys",
    "operations",
    "receipts",
    "epochs",
    "exports",
    "agent_sessions",
    "intervention_log",
    "governance_verdicts",
)


class _DBLike(Protocol):
    """The subset of ``shield_server.storage.Database`` this helper needs."""

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]: ...


@dataclass(frozen=True, slots=True)
class TableSnapshot:
    """A pre-/post- snapshot of one protected table.

    ``row_count`` and ``row_checksum`` together pin the table's full content:
    count guards against insert/delete; checksum guards against silent updates
    that preserve count. Storing them separately makes the assertion messages
    name the failing invariant (count vs checksum) for fast triage.
    """

    table: str
    row_count: int
    row_checksum: str  # hex SHA-256 of canonical-JSON-sorted row serialisation


@dataclass(frozen=True, slots=True)
class W3Snapshot:
    """Snapshot of every protected table at one point in time."""

    tables: dict[str, TableSnapshot] = field(default_factory=dict)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self.tables.keys())


def _canonical_row_bytes(row: dict[str, object]) -> bytes:
    """Stable byte serialisation of one row for hashing.

    JCS-like canonical form: keys sorted lexicographically; ``default=str``
    for asyncpg-returned types (Decimal, datetime, UUID, bytea-as-memoryview)
    so the helper is portable across MemoryDatabase + PostgresDatabase row
    shapes without needing per-type wire knowledge.
    """
    return json.dumps(row, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha256_hex_of_sorted_rows(rows: Iterable[dict[str, object]]) -> str:
    """SHA-256 over the sorted row serialisations (order-independent)."""
    encoded = sorted(_canonical_row_bytes(r) for r in rows)
    h = hashlib.sha256()
    for blob in encoded:
        h.update(blob)
        h.update(b"\n")  # length-extension barrier between rows
    return h.hexdigest()


async def _table_exists(db: _DBLike, table: str) -> bool:
    """Return True iff ``table`` is a public-schema table.

    The fire-drill takes pre-snapshot AFTER auth-up has run and post-snapshot
    AFTER auth-down has run — both moments the W3 tables MUST exist; if a
    table is missing in either moment that itself is a §A5 violation that
    surfaces in ``compare_w3_tables_byte_identity`` as a clear error, not a
    silent missing-row pass.
    """
    rows = await db.fetch(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = $1",
        table,
    )
    return len(rows) == 1


async def snapshot_w3_tables(
    db: _DBLike,
    *,
    tables: tuple[str, ...] = W3_PROTECTED_TABLES,
) -> W3Snapshot:
    """Snapshot every protected table's row_count + row_checksum.

    Tables that do not yet exist in the schema are skipped — older clones
    of this repo (pre-W3) may not have ``governance_verdicts``; the fire-
    drill on those clones still proves "auth down does not modify the
    tables that DO exist", and tables that didn't exist pre-up are not
    expected to exist post-down either (their absence is consistent).
    Missing tables are recorded with the sentinel ``"__missing__"`` so a
    drift (table present in one snapshot, missing in the other) is loud.
    """
    out: dict[str, TableSnapshot] = {}
    for t in tables:
        if not await _table_exists(db, t):
            out[t] = TableSnapshot(table=t, row_count=-1, row_checksum="__missing__")
            continue
        # ``SELECT *`` so a column-shape drift between snapshots shows up in
        # the checksum (a silent ALTER on a W3 table would change row dict
        # keys → checksum bytes differ → §A5 violation surfaces).
        rows = await db.fetch(f"SELECT * FROM {t}")  # noqa: S608 (table is from a fixed allowlist)
        out[t] = TableSnapshot(
            table=t,
            row_count=len(rows),
            row_checksum=_sha256_hex_of_sorted_rows(rows),
        )
    return W3Snapshot(tables=out)


def compare_w3_tables_byte_identity(pre_up: W3Snapshot, post_down: W3Snapshot) -> None:
    """Assert byte-identity of W3 protected tables across an up→down cycle.

    Raises ``AssertionError`` naming the offending table AND the failing
    invariant (count vs checksum vs presence) on first drift; otherwise
    returns ``None``. Designed for the §A5 fire-drill integration test:

        pre  = await snapshot_w3_tables(db)
        await _apply_down(db, rev=5)
        await _apply_down(db, rev=4)
        post = await snapshot_w3_tables(db)
        compare_w3_tables_byte_identity(pre, post)
    """
    if pre_up.names != post_down.names:
        only_pre = set(pre_up.names) - set(post_down.names)
        only_post = set(post_down.names) - set(pre_up.names)
        raise AssertionError(
            f"§A5: W3 table set drift across up→down — only_pre={sorted(only_pre)!r} "
            f"only_post={sorted(only_post)!r}"
        )
    for name in pre_up.names:
        pre = pre_up.tables[name]
        post = post_down.tables[name]
        if pre.row_count != post.row_count:
            raise AssertionError(
                f"§A5: row_count drift in W3 table {name!r}: "
                f"pre_up={pre.row_count} post_down={post.row_count} — "
                "auth down-migration must not insert/delete W3 rows."
            )
        if pre.row_checksum != post.row_checksum:
            raise AssertionError(
                f"§A5: row_checksum drift in W3 table {name!r}: "
                f"pre_up={pre.row_checksum} post_down={post.row_checksum} — "
                "auth down-migration must not UPDATE W3 rows (count was preserved "
                "but row content changed, the silent-update class)."
            )


__all__ = [
    "W3_PROTECTED_TABLES",
    "TableSnapshot",
    "W3Snapshot",
    "snapshot_w3_tables",
    "compare_w3_tables_byte_identity",
]
