"""Channel-2 (async stream) consumer — governance side.

master design §2.3 Channel-2: in the server ingest transaction every record is
``XADD``-ed to ``shield:actions:{workflow_id}``; governance consumes it via a
Redis consumer group (at-least-once, replayable). This module ships:

* :class:`Channel2Transport` — a minimal Protocol (ensure_group / read / ack).
* :class:`RedisChannel2Transport` — the real ``redis.asyncio`` Streams
  implementation (``XGROUP CREATE … MKSTREAM`` / ``XREADGROUP`` / ``XACK``);
  ``redis`` imported lazily so unit CI needs no Redis.
* :class:`InMemoryChannel2Transport` — a deterministic in-proc double for
  tests (implements the same Protocol).
* :class:`Channel2Consumer` — decodes each entry into the FROZEN §4
  :class:`~shield_sdk.schema.ShieldActionRecord` (imported, NEVER redeclared),
  dispatches to an async handler, ACKs only on success (at-least-once).

SEAM (governance↔server, brokered by team-lead): the stream-entry field
layout. This consumer reads field ``"record"`` = the ShieldActionRecord JSON
(preferred) and also tolerates a flat JSON record, so converging with
server-builder's exact ``XADD`` map is a one-line change in
:func:`decode_record`. Flagged to team-lead for server↔governance convergence.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from pydantic import ValidationError
from shield_sdk.schema import ShieldActionRecord  # frozen §4 — imported, never redeclared

DEFAULT_STREAM_PREFIX = "shield:actions"
DEFAULT_GROUP = "shield-governance"


def stream_key(workflow_id: str, *, prefix: str = DEFAULT_STREAM_PREFIX) -> str:
    return f"{prefix}:{workflow_id}"


@dataclass(frozen=True, slots=True)
class StreamEntry:
    """One Redis stream entry: an id + its string field map."""

    id: str
    fields: dict[str, str]


@runtime_checkable
class Channel2Transport(Protocol):
    async def ensure_group(self, stream: str, group: str) -> None: ...

    async def read(
        self, stream: str, group: str, consumer: str, *, count: int, block_ms: int
    ) -> list[StreamEntry]: ...

    async def ack(self, stream: str, group: str, ids: Sequence[str]) -> None: ...


def decode_record(entry: StreamEntry) -> ShieldActionRecord:
    """Decode a stream entry into the frozen §4 ShieldActionRecord.

    Accepts ``fields["record"]`` = the record JSON (the converged contract) or,
    tolerantly, the entry fields themselves as a flat JSON-ish record.
    """
    raw = entry.fields.get("record")
    if raw is not None:
        return ShieldActionRecord.model_validate_json(raw)
    return ShieldActionRecord.model_validate(entry.fields)


@dataclass(slots=True)
class InMemoryChannel2Transport:
    """Deterministic in-process transport double (no Redis) for unit tests."""

    _streams: dict[str, list[StreamEntry]] = field(default_factory=dict)
    _groups: set[tuple[str, str]] = field(default_factory=set)
    _cursor: dict[tuple[str, str], int] = field(default_factory=dict)
    _acked: set[tuple[str, str, str]] = field(default_factory=set)
    _seq: int = 0

    def publish(self, stream: str, record: ShieldActionRecord) -> str:
        self._seq += 1
        eid = f"{self._seq}-0"
        self._streams.setdefault(stream, []).append(
            StreamEntry(id=eid, fields={"record": record.model_dump_json()})
        )
        return eid

    async def ensure_group(self, stream: str, group: str) -> None:
        self._groups.add((stream, group))
        self._streams.setdefault(stream, [])
        self._cursor.setdefault((stream, group), 0)

    async def read(
        self, stream: str, group: str, consumer: str, *, count: int, block_ms: int
    ) -> list[StreamEntry]:
        entries = self._streams.get(stream, [])
        pos = self._cursor.get((stream, group), 0)
        batch = entries[pos : pos + count]
        self._cursor[(stream, group)] = pos + len(batch)
        return batch

    async def ack(self, stream: str, group: str, ids: Sequence[str]) -> None:
        for i in ids:
            self._acked.add((stream, group, i))

    def acked_ids(self, stream: str, group: str) -> set[str]:
        return {i for (s, g, i) in self._acked if s == stream and g == group}


class RedisChannel2Transport:
    """Real ``redis.asyncio`` Streams transport. ``redis`` imported lazily."""

    def __init__(self, redis_client: Any) -> None:
        self._r = redis_client

    @classmethod
    async def connect(cls, url: str) -> RedisChannel2Transport:
        from redis.asyncio import from_url  # lazy: unit CI needs no redis server

        return cls(from_url(url, decode_responses=True))

    async def ensure_group(self, stream: str, group: str) -> None:
        from redis.exceptions import ResponseError

        try:
            # MKSTREAM so the group can be created before the first XADD.
            await self._r.xgroup_create(stream, group, id="0", mkstream=True)
        except ResponseError as exc:  # BUSYGROUP = already exists -> idempotent
            if "BUSYGROUP" not in str(exc):
                raise

    async def read(
        self, stream: str, group: str, consumer: str, *, count: int, block_ms: int
    ) -> list[StreamEntry]:
        resp = await self._r.xreadgroup(group, consumer, {stream: ">"}, count=count, block=block_ms)
        out: list[StreamEntry] = []
        for _stream, messages in resp or []:
            for msg_id, fields in messages:
                out.append(StreamEntry(id=str(msg_id), fields=dict(fields)))
        return out

    async def ack(self, stream: str, group: str, ids: Sequence[str]) -> None:
        if ids:
            await self._r.xack(stream, group, *ids)


class Channel2Consumer:
    """Pull records off ``shield:actions:{workflow_id}`` and dispatch them.

    At-least-once: a record is ACKed only after its handler completes without
    raising, so a crashed handler re-delivers the record on the next read.
    """

    def __init__(
        self,
        transport: Channel2Transport,
        *,
        prefix: str = DEFAULT_STREAM_PREFIX,
        group: str = DEFAULT_GROUP,
        consumer: str = "gov-1",
    ) -> None:
        self._t = transport
        self._prefix = prefix
        self._group = group
        self._consumer = consumer

    async def run_once(
        self,
        workflow_id: str,
        handler: Callable[[ShieldActionRecord], Awaitable[None]],
        *,
        count: int = 16,
        block_ms: int = 1000,
    ) -> int:
        """Process up to ``count`` pending records once. Returns the number
        successfully handled + ACKed."""
        stream = stream_key(workflow_id, prefix=self._prefix)
        await self._t.ensure_group(stream, self._group)
        entries = await self._t.read(
            stream, self._group, self._consumer, count=count, block_ms=block_ms
        )
        handled = 0
        for entry in entries:
            try:
                record = decode_record(entry)
            except (ValidationError, ValueError):
                # Poison message (bad JSON or schema-invalid): do NOT ack
                # (server/DLQ policy is team-lead's seam decision); skip so a
                # valid sibling still progresses. (json.JSONDecodeError is a
                # ValueError subclass; pydantic raises ValidationError.)
                continue
            await handler(record)
            await self._t.ack(stream, self._group, [entry.id])
            handled += 1
        return handled
