"""Audit keyset pagination + cursor + filters (Elydora audit-service parity)."""

from __future__ import annotations

import pytest
from shield_server.audit import decode_cursor, encode_cursor, query_audit
from shield_server.errors import AppError
from shield_server.models import AuditQueryRequest
from shield_server.storage import Storage

ORG = "demo-org"


def _op(oid: str, created: int, agent: str = "a1", otype: str = "tool_call") -> dict[str, object]:
    return {
        "operation_id": oid,
        "org_id": ORG,
        "agent_id": agent,
        "seq_no": 1,
        "operation_type": otype,
        "issued_at": created,
        "ttl_ms": 1000,
        "nonce": oid,
        "subject": "{}",
        "action": "{}",
        "payload_hash": "ph",
        "prev_chain_hash": "p",
        "chain_hash": "c" + oid,
        "agent_pubkey_kid": "k1",
        "signature": "s",
        "r2_payload_key": None,
        "created_at": created,
    }


def test_cursor_round_trip() -> None:
    c = encode_cursor(123, "op-9")
    assert decode_cursor(c) == (123, "op-9")


def test_decode_cursor_invalid() -> None:
    assert decode_cursor("!!!not-base64!!!") is None
    assert decode_cursor(encode_cursor.__doc__ or "x") is None


async def test_pagination_and_next_cursor(storage: Storage) -> None:
    for i in range(5):
        storage.db.operations[f"op-{i}"] = _op(f"op-{i}", 1000 + i)  # type: ignore[attr-defined]

    page1 = await query_audit(storage, AuditQueryRequest(limit=2), ORG)
    assert [o.operation_id for o in page1.operations] == ["op-4", "op-3"]
    assert page1.total_count == 5
    assert page1.cursor is not None

    page2 = await query_audit(storage, AuditQueryRequest(limit=2, cursor=page1.cursor), ORG)
    assert [o.operation_id for o in page2.operations] == ["op-2", "op-1"]

    page3 = await query_audit(storage, AuditQueryRequest(limit=2, cursor=page2.cursor), ORG)
    assert [o.operation_id for o in page3.operations] == ["op-0"]
    assert page3.cursor is None


async def test_filters(storage: Storage) -> None:
    storage.db.operations["a"] = _op("a", 10, agent="a1", otype="tool_call")  # type: ignore[attr-defined]
    storage.db.operations["b"] = _op("b", 20, agent="a2", otype="decision")  # type: ignore[attr-defined]
    storage.db.operations["c"] = _op("c", 30, agent="a1", otype="tool_call")  # type: ignore[attr-defined]

    by_agent = await query_audit(storage, AuditQueryRequest(agent_id="a1"), ORG)
    assert {o.operation_id for o in by_agent.operations} == {"a", "c"}

    by_type = await query_audit(storage, AuditQueryRequest(operation_type="decision"), ORG)
    assert [o.operation_id for o in by_type.operations] == ["b"]

    windowed = await query_audit(storage, AuditQueryRequest(start_time=15, end_time=25), ORG)
    assert [o.operation_id for o in windowed.operations] == ["b"]


async def test_org_scoped(storage: Storage) -> None:
    op = _op("x", 1)
    op["org_id"] = "other-org"
    storage.db.operations["x"] = op  # type: ignore[attr-defined]
    res = await query_audit(storage, AuditQueryRequest(), ORG)
    assert res.operations == []


async def test_invalid_cursor_and_times(storage: Storage) -> None:
    with pytest.raises(AppError):
        await query_audit(storage, AuditQueryRequest(cursor="@@bad@@"), ORG)
    with pytest.raises(AppError):
        await query_audit(storage, AuditQueryRequest(start_time=-1), ORG)
    with pytest.raises(AppError):
        await query_audit(storage, AuditQueryRequest(end_time=-1), ORG)
