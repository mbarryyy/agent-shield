"""asyncpg-backed Database adapter (REWRITE of Elydora adapters/postgres.ts).

Network glue is `# pragma: no cover`: it is exercised by the integration job
(`integration.yml` -> docker-compose Postgres), not the unit-coverage gate,
matching the repo's established convention for infra adapters. `batch()`'s
atomicity is preserved via a single asyncpg transaction (Elydora db.batch()).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    import asyncpg


class _PgTx:  # pragma: no cover - integration-only
    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    async def execute(self, sql: str, *args: object) -> None:
        await self._conn.execute(sql, *args)


class PostgresDatabase:  # pragma: no cover - integration-only network glue
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresDatabase:
        import asyncpg

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=8)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def fetchrow(self, sql: str, *args: object) -> dict[str, object] | None:
        row = await self._pool.fetchrow(sql, *args)
        return dict(row) if row is not None else None

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        return [dict(r) for r in await self._pool.fetch(sql, *args)]

    async def fetchval(self, sql: str, *args: object) -> object:
        return await self._pool.fetchval(sql, *args)

    async def execute(self, sql: str, *args: object) -> None:
        await self._pool.execute(sql, *args)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[_PgTx]:
        async with self._pool.acquire() as conn, conn.transaction():
            yield _PgTx(conn)
