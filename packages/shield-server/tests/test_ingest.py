"""12-step ingest — happy path + every Elydora error branch (memory + FakeCrypto)."""

from __future__ import annotations

import json
import time

import pytest
from shield_server import agents as agent_svc
from shield_server._b64 import b64url_encode
from shield_server.errors import AppError
from shield_server.ingest import _signable, get_operation, submit_operation, verify_operation
from shield_server.models import OperationRecord, RegisterAgentRequest
from shield_server.storage import Storage

from .conftest import FakeCrypto, fake_signature

ORG = "demo-org"
PUBKEY = b64url_encode(b"\x01" * 32)


async def _register(storage: Storage) -> None:
    await agent_svc.register_agent(
        storage,
        RegisterAgentRequest(
            agent_id="agentdojo-banking-v1",
            keys=[{"kid": "k1", "public_key": PUBKEY}],  # type: ignore[list-item]
        ),
        ORG,
    )


def _record(
    crypto: FakeCrypto, *, prev: str, signed: bool = True, **over: object
) -> OperationRecord:
    now = int(time.time() * 1000)
    fields: dict[str, object] = {
        "op_version": "1.0",
        "operation_id": "op-1",
        "org_id": ORG,
        "agent_id": "agentdojo-banking-v1",
        "issued_at": now,
        "ttl_ms": 30_000,
        "nonce": "nonce-1",
        "operation_type": "tool_call",
        "subject": {"tool_call_id": "call_abc"},
        "action": {"tool": "send_money"},
        "payload": {"amount": 10000.0},
        "payload_hash": "ph-abc",
        "prev_chain_hash": prev,
        "agent_pubkey_kid": "k1",
        "signature": "bad",
    }
    fields.update(over)
    rec = OperationRecord(**fields)  # type: ignore[arg-type]
    if signed:
        sig_string = crypto.canonical(_signable(rec))
        rec.signature = fake_signature(PUBKEY, sig_string.encode("utf-8"))
    return rec


async def test_happy_path_then_get_and_verify(storage: Storage, crypto: FakeCrypto) -> None:
    await _register(storage)
    rec = _record(crypto, prev="A" * 43)
    ear = await submit_operation(storage, crypto, rec, "A" * 43)

    assert ear.seq_no == 1
    assert ear.operation_id == "op-1"
    assert ear.chain_hash.startswith("ch_")
    assert ear.elydora_signature.startswith("sig_")
    assert ear.elydora_kid == "elydora-server-key-v1"

    got = await get_operation(storage, "op-1", ORG)
    assert got.operation.chain_hash == ear.chain_hash
    assert got.receipt is not None
    assert got.payload == {"amount": 10000.0}

    valid, checks, errors = await verify_operation(storage, crypto, "op-1", ORG)
    assert valid is True
    assert checks == {"signature": True, "chain": True, "receipt": True}
    assert errors == []


async def test_chain_links_second_op_to_first(storage: Storage, crypto: FakeCrypto) -> None:
    await _register(storage)
    ear1 = await submit_operation(
        storage, crypto, _record(crypto, prev="A" * 43, operation_id="op-1"), "A" * 43
    )
    ear2 = await submit_operation(
        storage,
        crypto,
        _record(crypto, prev=ear1.chain_hash, operation_id="op-2", nonce="nonce-2"),
        "A" * 43,
    )
    assert ear2.seq_no == 2
    valid, _checks, _e = await verify_operation(storage, crypto, "op-2", ORG)
    assert valid is True


async def test_replay_detected(storage: Storage, crypto: FakeCrypto) -> None:
    await _register(storage)
    ear1 = await submit_operation(
        storage, crypto, _record(crypto, prev="A" * 43, operation_id="op-1"), "A" * 43
    )
    with pytest.raises(AppError) as ei:
        await submit_operation(
            storage,
            crypto,
            _record(crypto, prev=ear1.chain_hash, operation_id="op-2"),  # same nonce-1
            "A" * 43,
        )
    assert ei.value.error_code == "REPLAY_DETECTED"


async def test_unknown_agent(storage: Storage, crypto: FakeCrypto) -> None:
    with pytest.raises(AppError) as ei:
        await submit_operation(storage, crypto, _record(crypto, prev="A" * 43), "A" * 43)
    assert ei.value.error_code == "UNKNOWN_AGENT"


async def test_agent_frozen_and_revoked(storage: Storage, crypto: FakeCrypto) -> None:
    await _register(storage)
    await agent_svc.set_agent_status(storage, "agentdojo-banking-v1", "frozen", ORG)
    with pytest.raises(AppError) as ei:
        await submit_operation(storage, crypto, _record(crypto, prev="A" * 43), "A" * 43)
    assert ei.value.error_code == "AGENT_FROZEN"

    await agent_svc.set_agent_status(storage, "agentdojo-banking-v1", "revoked", ORG)
    with pytest.raises(AppError) as ei2:
        await submit_operation(
            storage, crypto, _record(crypto, prev="A" * 43, nonce="n2"), "A" * 43
        )
    assert ei2.value.error_code == "AGENT_FROZEN"


async def test_key_revoked_and_missing(storage: Storage, crypto: FakeCrypto) -> None:
    await _register(storage)
    await agent_svc.revoke_key(storage, "agentdojo-banking-v1", "k1", ORG)
    with pytest.raises(AppError) as ei:
        await submit_operation(storage, crypto, _record(crypto, prev="A" * 43), "A" * 43)
    assert ei.value.error_code == "KEY_REVOKED"

    rec = _record(crypto, prev="A" * 43, nonce="n3", agent_pubkey_kid="missing")
    with pytest.raises(AppError) as ei2:
        await submit_operation(storage, crypto, rec, "A" * 43)
    assert ei2.value.error_code == "INVALID_SIGNATURE"


async def test_invalid_signature(storage: Storage, crypto: FakeCrypto) -> None:
    await _register(storage)
    rec = _record(crypto, prev="A" * 43, signed=False)
    with pytest.raises(AppError) as ei:
        await submit_operation(storage, crypto, rec, "A" * 43)
    assert ei.value.error_code == "INVALID_SIGNATURE"


async def test_prev_hash_mismatch(storage: Storage, crypto: FakeCrypto) -> None:
    await _register(storage)
    rec = _record(crypto, prev="WRONGPREV")
    with pytest.raises(AppError) as ei:
        await submit_operation(storage, crypto, rec, "A" * 43)
    assert ei.value.error_code == "PREV_HASH_MISMATCH"
    assert ei.value.details == {"expected": "A" * 43, "actual": "WRONGPREV"}


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"op_version": "9.9"}, "VALIDATION_ERROR"),
        ({"operation_id": "  "}, "VALIDATION_ERROR"),
        ({"nonce": "x" * 65}, "VALIDATION_ERROR"),
        ({"issued_at": 0}, "VALIDATION_ERROR"),
        ({"ttl_ms": 10}, "VALIDATION_ERROR"),
        ({"ttl_ms": 999_999}, "VALIDATION_ERROR"),
    ],
)
async def test_validation_errors(
    storage: Storage, crypto: FakeCrypto, over: dict[str, object], code: str
) -> None:
    await _register(storage)
    rec = _record(crypto, prev="A" * 43, signed=False, **over)
    with pytest.raises(AppError) as ei:
        await submit_operation(storage, crypto, rec, "A" * 43)
    assert ei.value.error_code == code


async def test_ttl_expired(storage: Storage, crypto: FakeCrypto) -> None:
    await _register(storage)
    rec = _record(crypto, prev="A" * 43, signed=False)
    rec.issued_at = 1
    rec.ttl_ms = 1_000
    with pytest.raises(AppError) as ei:
        await submit_operation(storage, crypto, rec, "A" * 43)
    assert ei.value.error_code == "TTL_EXPIRED"


async def test_payload_too_large(storage: Storage, crypto: FakeCrypto) -> None:
    await _register(storage)
    rec = _record(crypto, prev="A" * 43, signed=False)
    rec.payload = {"blob": "x" * (256 * 1024 + 1)}
    with pytest.raises(AppError) as ei:
        await submit_operation(storage, crypto, rec, "A" * 43)
    assert ei.value.error_code == "PAYLOAD_TOO_LARGE"


async def test_get_operation_not_found(storage: Storage) -> None:
    with pytest.raises(AppError) as ei:
        await get_operation(storage, "missing", ORG)
    assert ei.value.error_code == "NOT_FOUND"


async def test_verify_detects_tampered_chain(storage: Storage, crypto: FakeCrypto) -> None:
    await _register(storage)
    await submit_operation(
        storage, crypto, _record(crypto, prev="A" * 43, operation_id="op-1"), "A" * 43
    )
    # Tamper the stored chain_hash -> verify must flag chain=False.
    storage.db.operations["op-1"]["chain_hash"] = "ch_tampered"  # type: ignore[attr-defined]
    valid, checks, errors = await verify_operation(storage, crypto, "op-1", ORG)
    assert valid is False
    assert checks["chain"] is False
    assert any("Chain hash mismatch" in e for e in errors)


async def test_signable_excludes_signature(crypto: FakeCrypto) -> None:
    rec = _record(crypto, prev="A" * 43)
    assert "signature" not in _signable(rec)
    assert json.loads(crypto.canonical(_signable(rec)))["op_version"] == "1.0"
