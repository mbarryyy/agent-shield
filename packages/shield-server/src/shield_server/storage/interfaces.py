"""Storage adapter protocols — the Pythonic equivalent of Elydora
`packages/server/src/adapters/interfaces.ts` (Database / ObjectStore / Cache).

The 12-step ingest, audit and agent services depend ONLY on these protocols, so
the exact same business logic runs against the in-memory fakes (unit tests, no
docker) and the asyncpg/MinIO/Redis adapters (integration job, real infra) —
preserving Elydora's `db.batch()` atomicity guarantee via `transaction()`.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol


class Tx(Protocol):
    """A statement executor bound to an open transaction."""

    async def execute(self, sql: str, *args: object) -> None: ...


class Database(Protocol):
    async def fetchrow(self, sql: str, *args: object) -> dict[str, object] | None: ...

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]: ...

    async def fetchval(self, sql: str, *args: object) -> object: ...

    async def execute(self, sql: str, *args: object) -> None: ...

    def transaction(self) -> AbstractAsyncContextManager[Tx]:
        """Atomic batch — mirrors D1.batch()/PostgresAdapter.batch (BEGIN/COMMIT)."""
        ...


class ObjectStore(Protocol):
    async def put(self, key: str, body: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes | None: ...


class Cache(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set_if_absent(self, key: str, value: str, ttl_seconds: int) -> bool:
        """SET NX EX — returns False if the key already existed (replay)."""
        ...

    async def set(self, key: str, value: str) -> None: ...

    # Channel-2 (§4.3) Redis Streams — async action fan-out.
    async def ensure_group(self, stream: str, group: str) -> None:
        """Idempotently create the consumer group (MKSTREAM)."""
        ...

    async def xadd(self, stream: str, fields: dict[str, str]) -> str:
        """Append one entry to the stream; returns the message id."""
        ...
