"""Channel-2 consumer: InMemory transport, decode round-trip, at-least-once."""

from __future__ import annotations

import pytest
from shield_governance.channel2 import (
    Channel2Consumer,
    InMemoryChannel2Transport,
    RedisChannel2Transport,
    StreamEntry,
    decode_record,
    stream_key,
)
from shield_sdk.schema import ActionPayload, Phase, ShieldActionRecord

WF = "banking"


def _rec(i: int) -> ShieldActionRecord:
    return ShieldActionRecord(
        run_id="run-1",
        step_index=i,
        phase=Phase.PRE_EXEC,
        payload=ActionPayload(tool_name="send_money", tool_args={"recipient": "A", "amount": 1}),
    )


def test_stream_key() -> None:
    assert stream_key(WF) == "shield:actions:banking"
    assert stream_key(WF, prefix="x") == "x:banking"


def test_decode_round_trip() -> None:
    rec = _rec(0)
    entry = StreamEntry(id="1-0", fields={"record": rec.model_dump_json()})
    back = decode_record(entry)
    assert back.run_id == rec.run_id
    assert back.payload.tool_name == "send_money"


@pytest.mark.asyncio
async def test_consumer_processes_and_acks_all() -> None:
    t = InMemoryChannel2Transport()
    stream = stream_key(WF)
    for i in range(3):
        t.publish(stream, _rec(i))

    seen: list[ShieldActionRecord] = []

    async def handler(r: ShieldActionRecord) -> None:
        seen.append(r)

    consumer = Channel2Consumer(t)
    n = await consumer.run_once(WF, handler, count=10, block_ms=0)
    assert n == 3
    assert [r.step_index for r in seen] == [0, 1, 2]
    assert t.acked_ids(stream, "shield-governance") == {"1-0", "2-0", "3-0"}


def test_decode_flat_record_path() -> None:
    # No "record" field -> tolerant flat fallback: the fields ARE a
    # model-validatable minimal record (schema defaults fill the rest).
    back = decode_record(StreamEntry(id="9-0", fields={"run_id": "run-1", "phase": "pre_exec"}))
    assert back.run_id == "run-1" and back.phase.value == "pre_exec"


class _FakeRedis:
    """Minimal async redis stub exercising the Streams transport mapping."""

    def __init__(self) -> None:
        self.groups: list[tuple[str, str]] = []
        self.acked: list[tuple[str, str, tuple[str, ...]]] = []
        self.busy = False

    async def xgroup_create(self, stream: str, group: str, id: str, mkstream: bool) -> None:
        if self.busy:
            from redis.exceptions import ResponseError

            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        self.groups.append((stream, group))

    async def xreadgroup(
        self, group: str, consumer: str, streams: dict[str, str], count: int, block: int
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        return [("shield:actions:banking", [("5-0", {"record": _rec(0).model_dump_json()})])]

    async def xack(self, stream: str, group: str, *ids: str) -> None:
        self.acked.append((stream, group, ids))


@pytest.mark.asyncio
async def test_redis_transport_logic_with_fake_client() -> None:
    fake = _FakeRedis()
    t = RedisChannel2Transport(fake)
    await t.ensure_group("shield:actions:banking", "g")
    assert fake.groups == [("shield:actions:banking", "g")]

    fake.busy = True  # BUSYGROUP must be swallowed (idempotent)
    await t.ensure_group("shield:actions:banking", "g")

    entries = await t.read("shield:actions:banking", "g", "c", count=10, block_ms=0)
    assert len(entries) == 1 and entries[0].id == "5-0"
    assert decode_record(entries[0]).run_id == "run-1"

    await t.ack("shield:actions:banking", "g", ["5-0"])
    assert fake.acked == [("shield:actions:banking", "g", ("5-0",))]
    await t.ack("shield:actions:banking", "g", [])  # empty -> no-op
    assert len(fake.acked) == 1


@pytest.mark.asyncio
async def test_redis_ensure_group_reraises_non_busygroup() -> None:
    from redis.exceptions import ResponseError

    class _Boom:
        async def xgroup_create(self, *a: object, **k: object) -> None:
            raise ResponseError("WRONGTYPE not a stream")

    with pytest.raises(ResponseError, match="WRONGTYPE"):
        await RedisChannel2Transport(_Boom()).ensure_group("s", "g")


@pytest.mark.asyncio
async def test_poison_message_skipped_not_acked_sibling_progresses() -> None:
    t = InMemoryChannel2Transport()
    stream = stream_key(WF)
    # Poison first (distinct, non-generated id), then a valid sibling.
    t._streams.setdefault(stream, []).append(
        StreamEntry(id="poison-0", fields={"record": "{bad json"})
    )
    valid_id = t.publish(stream, _rec(7))  # generated id "1-0"

    handled: list[int] = []

    async def handler(r: ShieldActionRecord) -> None:
        handled.append(r.step_index)

    n = await Channel2Consumer(t).run_once(WF, handler, count=10, block_ms=0)
    assert n == 1
    assert handled == [7]
    acked = t.acked_ids(stream, "shield-governance")
    assert valid_id in acked  # sibling progressed + ACKed
    assert "poison-0" not in acked  # poison NOT acked (re-deliverable)
