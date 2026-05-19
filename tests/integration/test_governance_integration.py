"""W2 G2 integration — the two-phase gate + Channel-2 Stream fan-out against
REAL docker infra (Postgres + Redis Streams + MinIO).

Run by `integration.yml` / `make integration` after `python -m
shield_server.migrate` (which now creates the W2 `intervention_log` table).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
import shield_sdk.canonical as canonical
import shield_sdk.crypto as crypto
from shield_sdk.schema import ActionRef, ShieldActionRecord
from shield_server import agents as agent_svc
from shield_server.config import CONSUMER_GROUPS, Settings
from shield_server.governance import decide
from shield_server.migrate import apply as apply_migrations
from shield_server.models import RegisterAgentRequest
from shield_server.storage import Storage, build_storage

pytestmark = pytest.mark.integration

ORG = "demo-org"
PRIV = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
PUB = crypto.get_public_key_base64url(PRIV)


@pytest_asyncio.fixture
async def storage() -> Storage:
    settings = Settings.from_env()
    await apply_migrations(settings.database_url)  # idempotent; creates intervention_log
    return await build_storage(settings)


def _uid(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:12]}"


async def test_two_phase_gate_and_channel2_fanout(storage: Storage) -> None:
    settings = Settings.from_env()
    agent_id = _uid("agentdojo-banking")
    kid = _uid("k")
    await agent_svc.register_agent(
        storage,
        RegisterAgentRequest(
            agent_id=agent_id,
            keys=[{"kid": kid, "public_key": PUB}],  # type: ignore[list-item]
        ),
        ORG,
    )

    rec = ShieldActionRecord(
        org_id=ORG,
        agent_id=agent_id,
        agent_pubkey_kid=kid,
        workflow_id="banking",
        phase="pre_exec",
        run_id="run-0001",
        nonce=_uid("n").replace("-", "")[:22],
        action=ActionRef(tool="send_money", args_digest="sha256:abc"),
    )
    rec.payload.tool_name = "send_money"
    rec.payload.tool_args = {"recipient": "ATTACKER-IBAN", "amount": 10000.0}
    rec = canonical.finalize_record(rec, PRIV)

    # ONE round-trip: ingest pre_exec + signed PASS verdict.
    verdict = await decide(storage, rec, settings)
    assert verdict.decision.value == "PASS"
    server_pub = crypto.get_public_key_base64url(settings.server_signing_key)
    assert canonical.verify_verdict(verdict, server_pub) is True

    # Chain row persisted in REAL Postgres.
    op = await storage.db.fetchrow(
        "SELECT * FROM operations WHERE operation_id = $1 AND org_id = $2",
        rec.record_id,
        ORG,
    )
    assert op is not None
    assert op["chain_hash"] == canonical.derive_chain_hash(rec.prev_chain_hash, rec)

    # intervention_log row written in REAL Postgres (cost hook #3).
    row = await storage.db.fetchrow(
        "SELECT * FROM intervention_log WHERE verdict_id = $1", verdict.verdict_id
    )
    assert row is not None and row["decision"] == "PASS"
    assert row["record_id"] == rec.record_id and row["tokens_in"] == 0

    # Channel-2: REAL Redis stream entry + consumer groups created.
    stream = "shield:actions:banking"
    redis = storage.cache._client  # type: ignore[attr-defined]
    length = await redis.xlen(stream)
    assert length >= 1
    groups = {g["name"] for g in await redis.xinfo_groups(stream)}
    for g in CONSUMER_GROUPS:
        assert g in groups


async def test_decide_replay_rejected_real_redis(storage: Storage) -> None:
    settings = Settings.from_env()
    agent_id = _uid("agentdojo-banking")
    kid = _uid("k")
    await agent_svc.register_agent(
        storage,
        RegisterAgentRequest(
            agent_id=agent_id,
            keys=[{"kid": kid, "public_key": PUB}],  # type: ignore[list-item]
        ),
        ORG,
    )
    rec = ShieldActionRecord(
        org_id=ORG,
        agent_id=agent_id,
        agent_pubkey_kid=kid,
        phase="pre_exec",
        run_id="run-0001",
        nonce=_uid("n").replace("-", "")[:22],
    )
    rec.payload.tool_name = "send_money"
    rec = canonical.finalize_record(rec, PRIV)
    await decide(storage, rec, settings)

    op = await storage.db.fetchrow(
        "SELECT * FROM operations WHERE operation_id = $1 AND org_id = $2",
        rec.record_id,
        ORG,
    )
    dup = ShieldActionRecord(
        org_id=ORG,
        agent_id=agent_id,
        agent_pubkey_kid=kid,
        phase="pre_exec",
        run_id="run-0001",
        nonce=rec.nonce,
        prev_chain_hash=str(op["chain_hash"]),
    )
    dup.payload.tool_name = "send_money"
    dup = canonical.finalize_record(dup, PRIV)
    from shield_server.errors import AppError

    with pytest.raises(AppError) as ei:
        await decide(storage, dup, settings)
    assert ei.value.error_code == "REPLAY_DETECTED"


async def test_post_exec_record_fans_channel2_real_redis(storage: Storage) -> None:
    from shield_server.governance import record

    settings = Settings.from_env()
    agent_id = _uid("agentdojo-banking")
    kid = _uid("k")
    await agent_svc.register_agent(
        storage,
        RegisterAgentRequest(
            agent_id=agent_id,
            keys=[{"kid": kid, "public_key": PUB}],  # type: ignore[list-item]
        ),
        ORG,
    )
    rec = ShieldActionRecord(
        org_id=ORG,
        agent_id=agent_id,
        agent_pubkey_kid=kid,
        workflow_id="banking",
        phase="post_exec",
        run_id="run-0001",
        verdict_ref="vrd-int-1",
        nonce=_uid("n").replace("-", "")[:22],
    )
    rec.payload.tool_name = "send_money"
    rec = canonical.finalize_record(rec, PRIV)

    ack = await record(storage, rec, settings)
    assert ack["accepted"] is True and ack["seq_no"] == 1

    op = await storage.db.fetchrow(
        "SELECT * FROM operations WHERE operation_id = $1 AND org_id = $2",
        rec.record_id,
        ORG,
    )
    assert op is not None
    # post_exec is async → NO intervention_log row for this record.
    il = await storage.db.fetchrow(
        "SELECT * FROM intervention_log WHERE record_id = $1", rec.record_id
    )
    assert il is None
    # Channel-2: REAL Redis stream carries the post_exec entry.
    redis = storage.cache._client  # type: ignore[attr-defined]
    assert await redis.xlen("shield:actions:banking") >= 1
