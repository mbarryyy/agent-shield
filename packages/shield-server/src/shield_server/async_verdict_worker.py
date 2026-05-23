"""Background Channel-2 async verdict worker.

The governance package computes unsigned late verdicts. This server-side worker
is the signing, storage, and ``shield:verdicts`` publication boundary.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from shield_governance.auditor import Auditor
from shield_governance.channel2 import (
    Channel2Consumer,
    Channel2Transport,
    RedisChannel2Transport,
    StreamEntry,
)
from shield_governance.evaluator import Evaluator, EvaluatorConfig
from shield_governance.graph import make_async_channel2_handler
from shield_governance.supervisor import Supervisor
from shield_governance.verdicts import AsyncVerdictHandoff
from shield_sdk.schema import ShieldActionRecord

from .config import CONSUMER_GROUPS, Settings
from .governance import publish_async_verdict
from .storage import Cache, Storage, build_storage

LOG = logging.getLogger(__name__)
DEFAULT_GROUP = CONSUMER_GROUPS[0]
DEFAULT_CONSUMER = "shield-server-async-verdict-worker"


@dataclass(slots=True)
class CacheChannel2Transport:
    """Channel-2 transport backed by the server Cache protocol.

    The production worker should use :class:`RedisChannel2Transport` for real
    consumer-group ACKs. This adapter keeps unit tests and local one-shot runs
    on the same server ``Cache`` seam without adding Redis-only methods to the
    shared cache protocol.
    """

    cache: Cache
    _cursor: dict[tuple[str, str], int] = field(default_factory=dict)
    _acked: set[tuple[str, str, str]] = field(default_factory=set)

    async def ensure_group(self, stream: str, group: str) -> None:
        await self.cache.ensure_group(stream, group)
        self._cursor.setdefault((stream, group), 0)

    async def read(
        self, stream: str, group: str, consumer: str, *, count: int, block_ms: int
    ) -> list[StreamEntry]:
        if count <= 0:
            return []
        entries = await self.cache.xrange(stream)
        pos = self._cursor.get((stream, group), 0)
        batch = entries[pos : pos + count]
        self._cursor[(stream, group)] = pos + len(batch)
        return [StreamEntry(id=msg_id, fields=dict(fields)) for msg_id, fields in batch]

    async def ack(self, stream: str, group: str, ids: Sequence[str]) -> None:
        for msg_id in ids:
            self._acked.add((stream, group, msg_id))

    def acked_ids(self, stream: str, group: str) -> set[str]:
        return {msg_id for s, g, msg_id in self._acked if s == stream and g == group}


class AsyncVerdictWorker:
    """Consume Channel-2 action records and publish signed late verdicts."""

    def __init__(
        self,
        *,
        storage: Storage,
        settings: Settings,
        transport: Channel2Transport,
        evaluator: Evaluator | None = None,
        auditor: Auditor | None = None,
        supervisor: Supervisor | None = None,
        group: str = DEFAULT_GROUP,
        consumer: str = DEFAULT_CONSUMER,
        logger: logging.Logger | None = None,
    ) -> None:
        self._storage = storage
        self._settings = settings
        self._transport = transport
        self._group = group
        self._consumer = consumer
        self._logger = logger or LOG

        async def on_verdict(handoff: AsyncVerdictHandoff) -> None:
            if await self._already_published(handoff.record):
                return
            await publish_async_verdict(
                self._storage,
                handoff.record,
                handoff.verdict,
                self._settings,
                guardian_evidence=handoff.guardian_evidence,
            )

        self._handler = make_async_channel2_handler(
            evaluator=evaluator
            or Evaluator(EvaluatorConfig(run_invariant=False, run_hallucination=False)),
            auditor=auditor or Auditor(),
            supervisor=supervisor or Supervisor(),
            on_verdict=on_verdict,
        )

    async def run_once(
        self,
        workflow_id: str,
        *,
        count: int = 16,
        block_ms: int = 1000,
    ) -> int:
        """Process one batch and return the number of valid ACKed entries."""
        consumer = Channel2Consumer(
            self._transport,
            group=self._group,
            consumer=self._consumer,
        )
        handled = await consumer.run_once(
            workflow_id,
            self._handle_record,
            count=count,
            block_ms=block_ms,
        )
        return int(handled)

    async def run_loop(
        self,
        workflow_id: str,
        *,
        count: int = 16,
        block_ms: int = 1000,
        interval_seconds: float = 1.0,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Run until ``stop_event`` is set or the task is cancelled."""
        while stop_event is None or not stop_event.is_set():
            handled = await self.run_once(workflow_id, count=count, block_ms=block_ms)
            if handled == 0:
                await asyncio.sleep(interval_seconds)

    async def _handle_record(self, record: ShieldActionRecord) -> None:
        if await self._already_published(record):
            return
        try:
            await self._handler(record)
        except Exception as exc:
            self._logger.warning(
                "async verdict worker failed for record_id=%s error_class=%s",
                record.record_id,
                exc.__class__.__name__,
            )
            raise

    async def _already_published(self, record: ShieldActionRecord) -> bool:
        row = await self._storage.db.fetchrow(
            "SELECT * FROM governance_verdicts WHERE record_id = $1",
            record.record_id,
        )
        return row is not None


async def run_once(
    *,
    storage: Storage,
    settings: Settings,
    workflow_id: str,
    transport: Channel2Transport | None = None,
    count: int = 16,
    block_ms: int = 1000,
) -> int:
    """Convenience one-shot entry point for tests and local verification."""
    worker = AsyncVerdictWorker(
        storage=storage,
        settings=settings,
        transport=transport or CacheChannel2Transport(storage.cache),
    )
    return await worker.run_once(workflow_id, count=count, block_ms=block_ms)


async def _main_async(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m shield_server.async_verdict_worker",
        description="Run the Agent Shield Channel-2 async verdict worker.",
    )
    parser.add_argument("--workflow-id", default="banking")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit.")
    parser.add_argument("--count", type=int, default=16)
    parser.add_argument("--block-ms", type=int, default=1000)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()
    storage = await build_storage(settings)
    transport = await RedisChannel2Transport.connect(settings.redis_url)
    worker = AsyncVerdictWorker(storage=storage, settings=settings, transport=transport)
    if args.once:
        handled = await worker.run_once(args.workflow_id, count=args.count, block_ms=args.block_ms)
        LOG.info(
            "async verdict worker one-shot handled=%s workflow_id=%s",
            handled,
            args.workflow_id,
        )
        return 0
    await worker.run_loop(
        args.workflow_id,
        count=args.count,
        block_ms=args.block_ms,
        interval_seconds=args.interval_seconds,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_main_async(argv))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
