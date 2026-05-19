"""12-step ingest — REAL infra (docker-compose Postgres + Redis + MinIO).

Run by `integration.yml` / `make integration` after `python -m
shield_server.migrate`. Split into:

  * non-crypto assertions that run for real NOW (validation gate, the Redis
    replay primitive, the asyncpg agent round-trip, the MinIO object round-trip
    — i.e. every ingest step that does not need the §4 crypto), and
  * the full 12-step `submit_operation` + verify, **skipped until
    `crypto_frozen()`** — the W1 HARD DEPENDENCY: JCS/Ed25519/chain-hash live
    in `shield_sdk.crypto`, ported byte-exact + golden-vector-frozen by
    sdk-builder (Task #2 / ADR-0007 v1.1). After that lands and this worktree
    rebases onto v1.1, the skip flips and the crypto e2e asserts for real.

This keeps the integration suite GREEN for G1 while making the blocking
dependency visible in CI output (an explicit skip with the reason).
"""

from __future__ import annotations

import time
import uuid

import pytest
import pytest_asyncio
from shield_server import agents as agent_svc
from shield_server._crypto import ShieldSdkCrypto, crypto_frozen
from shield_server.config import Settings
from shield_server.errors import AppError
from shield_server.ingest import submit_operation, verify_operation
from shield_server.migrate import apply as apply_migrations
from shield_server.models import OperationRecord, RegisterAgentRequest
from shield_server.storage import Storage, build_storage

pytestmark = pytest.mark.integration

ORG = "demo-org"


@pytest_asyncio.fixture
async def storage() -> Storage:
    settings = Settings.from_env()
    await apply_migrations(settings.database_url)  # idempotent
    return await build_storage(settings)


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _record(agent_id: str, **over: object) -> OperationRecord:
    fields: dict[str, object] = {
        "op_version": "1.0",
        "operation_id": _uid("op"),
        "org_id": ORG,
        "agent_id": agent_id,
        "issued_at": int(time.time() * 1000),
        "ttl_ms": 30_000,
        "nonce": _uid("nonce"),
        "operation_type": "tool_call",
        "subject": {"tool_call_id": "call_abc"},
        "action": {"tool": "send_money"},
        "payload": {"amount": 10000.0},
        "payload_hash": "ph-abc",
        "prev_chain_hash": "A" * 43,
        "agent_pubkey_kid": "k1",
        "signature": "sig",
    }
    fields.update(over)
    return OperationRecord(**fields)  # type: ignore[arg-type]


async def _register(storage: Storage) -> tuple[str, str]:
    # Elydora `agent_keys.kid` is a GLOBAL primary key (migrations/001_initial.sql),
    # so every registration in the shared integration DB needs a unique kid.
    agent_id = _uid("agentdojo-banking")
    kid = _uid("k")
    await agent_svc.register_agent(
        storage,
        RegisterAgentRequest(
            agent_id=agent_id,
            keys=[{"kid": kid, "public_key": "AAAA"}],  # type: ignore[list-item]
        ),
        ORG,
    )
    return agent_id, kid


async def test_agent_round_trip_real_postgres(storage: Storage) -> None:
    agent_id, kid = await _register(storage)
    got = await agent_svc.get_agent(storage, agent_id, ORG)
    assert got.agent.agent_id == agent_id
    assert got.keys[0].kid == kid


async def test_minio_object_round_trip(storage: Storage) -> None:
    key = f"{ORG}/it/{_uid('obj')}"
    await storage.objects.put(key, b'{"hello":"shield"}', "application/json")
    assert await storage.objects.get(key) == b'{"hello":"shield"}'
    assert await storage.objects.get(f"{ORG}/it/missing-{uuid.uuid4().hex}") is None


async def test_redis_replay_primitive(storage: Storage) -> None:
    key = f"nonce:{ORG}:{_uid('n')}"
    assert await storage.cache.set_if_absent(key, "1", 30) is True
    # Second claim of the same nonce must be rejected (REPLAY_DETECTED basis).
    assert await storage.cache.set_if_absent(key, "1", 30) is False


async def test_validation_gate_runs_pre_crypto(storage: Storage) -> None:
    agent_id, _kid = await _register(storage)
    bad = _record(agent_id, op_version="9.9")
    with pytest.raises(AppError) as ei:
        await submit_operation(storage, ShieldSdkCrypto(), bad, "A" * 43)
    assert ei.value.error_code == "VALIDATION_ERROR"

    expired = _record(agent_id, issued_at=1, ttl_ms=1000)
    with pytest.raises(AppError) as ei2:
        await submit_operation(storage, ShieldSdkCrypto(), expired, "A" * 43)
    assert ei2.value.error_code == "TTL_EXPIRED"


async def test_unknown_agent_real_db(storage: Storage) -> None:
    with pytest.raises(AppError) as ei:
        await submit_operation(storage, ShieldSdkCrypto(), _record("no-such-agent"), "A" * 43)
    assert ei.value.error_code == "UNKNOWN_AGENT"


@pytest.mark.skipif(
    not crypto_frozen(),
    reason=(
        "W1 HARD DEP: shield_sdk.crypto (JCS/Ed25519/chain-hash) is the W0 stub "
        "until sdk-builder Task #2 / ADR-0007 v1.1 freezes it + golden vectors; "
        "rebase feat/server onto v1.1 to enable the crypto e2e."
    ),
)
async def test_full_12_step_ingest_with_real_crypto(storage: Storage) -> None:
    from shield_server._b64 import b64url_encode

    crypto = ShieldSdkCrypto()
    agent_id = _uid("agentdojo-banking")
    kid = _uid("k")
    pubkey = b64url_encode(b"\x01" * 32)
    await agent_svc.register_agent(
        storage,
        RegisterAgentRequest(
            agent_id=agent_id,
            keys=[{"kid": kid, "public_key": pubkey}],  # type: ignore[list-item]
        ),
        ORG,
    )
    rec = _record(agent_id, agent_pubkey_kid=kid)
    # Once crypto is frozen, sign the signable projection with the real port.
    from shield_server.ingest import _signable

    rec.signature = crypto.sign_ed25519(  # placeholder until a signing helper lands
        b"\x01" * 32, crypto.canonical(_signable(rec))
    )
    ear = await submit_operation(storage, crypto, rec, b64url_encode(b"\x02" * 32))
    assert ear.seq_no >= 1
    valid, checks, _errors = await verify_operation(storage, crypto, rec.operation_id, ORG)
    assert checks["chain"] is True and valid is True
