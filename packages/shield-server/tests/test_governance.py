"""POST /v1/governance/decide — §4 Channel-1 gate (STUB→PASS) + Channel-2.

Uses the REAL frozen shield_sdk.canonical/crypto (pure-Python, no docker) +
MemoryStorage, so the HARD-GATE projection is exercised end-to-end.
"""

from __future__ import annotations

import pytest
import shield_sdk.canonical as canonical
import shield_sdk.crypto as crypto
from shield_sdk.schema import (
    ActionRef,
    Decision,
    GovernanceVerdict,
    Phase,
    ShieldActionRecord,
)
from shield_server import agents as agent_svc
from shield_server.config import CONSUMER_GROUPS, Settings
from shield_server.errors import AppError
from shield_server.governance import decide, record
from shield_server.govseam import NullGovernanceApp
from shield_server.models import RegisterAgentRequest
from shield_server.storage import Storage

_GOV = NullGovernanceApp()  # honest UNSIGNED PASS; server signs


async def _decide(
    storage: Storage, rec: ShieldActionRecord, settings: Settings
) -> GovernanceVerdict:
    """W3 decide-seam shim: inject the deterministic Null gov app."""
    return await decide(storage, rec, settings, _GOV)


ORG = "demo-org"
PRIV = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"  # golden keypair
PUB = crypto.get_public_key_base64url(PRIV)
KID = "agentdojo-banking-v1-key-v1"
AGENT = "agentdojo-banking-v1"


async def _register(
    storage: Storage, *, status: str = "active", key_status: str = "active"
) -> None:
    await agent_svc.register_agent(
        storage,
        RegisterAgentRequest(agent_id=AGENT, keys=[{"kid": KID, "public_key": PUB}]),  # type: ignore[list-item]
        ORG,
    )
    if status != "active":
        await agent_svc.set_agent_status(storage, AGENT, status, ORG)
    if key_status != "active":
        storage.db.agent_keys[KID]["status"] = key_status  # type: ignore[attr-defined]


def _signed_record(
    *, prev: str = "A" * 43, phase: Phase = Phase.PRE_EXEC, **over: object
) -> ShieldActionRecord:
    rec = ShieldActionRecord(
        org_id=ORG,
        agent_id=AGENT,
        agent_pubkey_kid=KID,
        phase=phase,
        run_id="run-0001",
        prev_chain_hash=prev,
        action=ActionRef(tool="send_money", args_digest="sha256:abc"),
        **over,  # type: ignore[arg-type]
    )
    rec.payload.tool_name = "send_money"
    rec.payload.tool_args = {"recipient": "ATTACKER-IBAN", "amount": 10000.0}
    # FROZEN finalize: sets payload_hash then Ed25519 signature (HARD-GATE rule).
    return canonical.finalize_record(rec, PRIV)


@pytest.fixture
def settings() -> Settings:
    return Settings.from_env()


async def test_decide_returns_signed_pass_one_round_trip(
    storage: Storage, settings: Settings
) -> None:
    await _register(storage)
    rec = _signed_record()
    verdict = await _decide(storage, rec, settings)

    assert verdict.decision is Decision.PASS
    assert verdict.record_id == rec.record_id
    assert verdict.correlation_id == rec.correlation_id
    assert verdict.shield_kid == "shield-server-key-v1"
    assert verdict.latency_ms is not None
    # Verdict is signed by the shield-server key (EAR-like, offline-verifiable).
    server_pub = crypto.get_public_key_base64url(settings.server_signing_key)
    assert verdict.signature_by_shield is not None
    assert canonical.verify_verdict(verdict, server_pub) is True

    # Persisted on the per-agent chain + envelope + intervention_log + Channel-2.
    op = await storage.db.fetchrow(
        "SELECT * FROM operations WHERE operation_id = $1 AND org_id = $2",
        rec.record_id,
        ORG,
    )
    assert op is not None and op["seq_no"] == 1
    assert op["chain_hash"] == canonical.derive_chain_hash(rec.prev_chain_hash, rec)
    log = storage.db.intervention_log  # type: ignore[attr-defined]
    assert len(log) == 1 and log[0]["decision"] == "PASS"
    assert log[0]["verdict_id"] == verdict.verdict_id
    stream = "shield:actions:banking"
    entries = storage.cache.streams[stream]  # type: ignore[attr-defined]
    assert len(entries) == 1 and entries[0][1]["record_id"] == rec.record_id
    for g in CONSUMER_GROUPS:
        assert (stream, g) in storage.cache.groups  # type: ignore[attr-defined]


async def test_chain_links_second_record(storage: Storage, settings: Settings) -> None:
    await _register(storage)
    v1 = await _decide(storage, _signed_record(), settings)
    op1 = await storage.db.fetchrow(
        "SELECT * FROM operations WHERE operation_id = $1 AND org_id = $2",
        v1.record_id,
        ORG,
    )
    rec2 = _signed_record(prev=str(op1["chain_hash"]), nonce="NONCE2nonce2nonce2non")
    await _decide(storage, rec2, settings)
    op2 = await storage.db.fetchrow(
        "SELECT * FROM operations WHERE operation_id = $1 AND org_id = $2",
        rec2.record_id,
        ORG,
    )
    assert op2["seq_no"] == 2


async def test_replay_detected(storage: Storage, settings: Settings) -> None:
    await _register(storage)
    rec = _signed_record()
    await _decide(storage, rec, settings)
    rec2 = _signed_record(
        prev=str(
            (
                await storage.db.fetchrow(
                    "SELECT * FROM operations WHERE operation_id = $1 AND org_id = $2",
                    rec.record_id,
                    ORG,
                )
            )["chain_hash"]
        )
    )
    rec2.nonce = rec.nonce  # same nonce -> replay
    rec2 = canonical.finalize_record(rec2, PRIV)
    with pytest.raises(AppError) as ei:
        await _decide(storage, rec2, settings)
    assert ei.value.error_code == "REPLAY_DETECTED"


async def test_unknown_agent(storage: Storage, settings: Settings) -> None:
    with pytest.raises(AppError) as ei:
        await _decide(storage, _signed_record(), settings)
    assert ei.value.error_code == "UNKNOWN_AGENT"


async def test_agent_frozen(storage: Storage, settings: Settings) -> None:
    await _register(storage, status="frozen")
    with pytest.raises(AppError) as ei:
        await _decide(storage, _signed_record(), settings)
    assert ei.value.error_code == "AGENT_FROZEN"


async def test_key_revoked(storage: Storage, settings: Settings) -> None:
    await _register(storage, key_status="revoked")
    with pytest.raises(AppError) as ei:
        await _decide(storage, _signed_record(), settings)
    assert ei.value.error_code == "KEY_REVOKED"


async def test_invalid_signature_rejected(storage: Storage, settings: Settings) -> None:
    await _register(storage)
    rec = _signed_record()
    rec.signature = "tampered" + (rec.signature or "")[8:]
    with pytest.raises(AppError) as ei:
        await _decide(storage, rec, settings)
    assert ei.value.error_code == "INVALID_SIGNATURE"


async def test_prev_hash_mismatch(storage: Storage, settings: Settings) -> None:
    await _register(storage)
    with pytest.raises(AppError) as ei:
        await _decide(storage, _signed_record(prev="WRONG"), settings)
    assert ei.value.error_code == "PREV_HASH_MISMATCH"
    assert ei.value.details == {"expected": "A" * 43, "actual": "WRONG"}


async def test_phase_must_be_pre_exec(storage: Storage, settings: Settings) -> None:
    await _register(storage)
    rec = _signed_record()
    rec.phase = Phase.POST_EXEC
    with pytest.raises(AppError) as ei:
        await _decide(storage, rec, settings)
    assert ei.value.error_code == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"ttl_ms": 10}, "VALIDATION_ERROR"),
        ({"ttl_ms": 999_999}, "VALIDATION_ERROR"),
        ({"issued_at": 1, "ttl_ms": 1000}, "TTL_EXPIRED"),
    ],
)
async def test_validation_branches(
    storage: Storage, settings: Settings, over: dict[str, object], code: str
) -> None:
    await _register(storage)
    with pytest.raises(AppError) as ei:
        await _decide(storage, _signed_record(**over), settings)
    assert ei.value.error_code == code


# --- POST /v1/governance/record (Channel-2 post_exec ingest; no verdict) ----


async def test_record_post_exec_acks_and_fans_no_verdict(
    storage: Storage, settings: Settings
) -> None:
    await _register(storage)
    rec = _signed_record(phase=Phase.POST_EXEC, verdict_ref="vrd-123")
    ack = await record(storage, rec, settings)

    assert ack == {
        "accepted": True,
        "record_id": rec.record_id,
        "correlation_id": rec.correlation_id,
        "chain_hash": canonical.derive_chain_hash(rec.prev_chain_hash, rec),
        "seq_no": 1,
    }
    op = await storage.db.fetchrow(
        "SELECT * FROM operations WHERE operation_id = $1 AND org_id = $2",
        rec.record_id,
        ORG,
    )
    assert op is not None and op["seq_no"] == 1
    # post_exec is async: NO intervention_log row (decision-keyed only).
    assert storage.db.intervention_log == []  # type: ignore[attr-defined]
    stream = "shield:actions:banking"
    entries = storage.cache.streams[stream]  # type: ignore[attr-defined]
    assert len(entries) == 1
    assert entries[0][1]["phase"] == "post_exec"
    assert entries[0][1]["verdict_id"] == "vrd-123"
    for g in CONSUMER_GROUPS:
        assert (stream, g) in storage.cache.groups  # type: ignore[attr-defined]


async def test_record_rejects_pre_exec(storage: Storage, settings: Settings) -> None:
    await _register(storage)
    with pytest.raises(AppError) as ei:
        await record(storage, _signed_record(phase=Phase.PRE_EXEC), settings)
    assert ei.value.error_code == "VALIDATION_ERROR"


async def test_decide_then_post_exec_share_one_chain(storage: Storage, settings: Settings) -> None:
    await _register(storage)
    v = await _decide(storage, _signed_record(), settings)
    op1 = await storage.db.fetchrow(
        "SELECT * FROM operations WHERE operation_id = $1 AND org_id = $2",
        v.record_id,
        ORG,
    )
    post = _signed_record(
        phase=Phase.POST_EXEC,
        prev=str(op1["chain_hash"]),
        nonce="POSTnoncePOSTnoncePOST",
        verdict_ref=v.verdict_id,
    )
    ack = await record(storage, post, settings)
    assert ack["seq_no"] == 2  # pre_exec(1) → post_exec(2) on the same chain


async def test_record_invalid_signature_rejected(storage: Storage, settings: Settings) -> None:
    await _register(storage)
    rec = _signed_record(phase=Phase.POST_EXEC)
    rec.signature = "tampered" + (rec.signature or "")[8:]
    with pytest.raises(AppError) as ei:
        await record(storage, rec, settings)
    assert ei.value.error_code == "INVALID_SIGNATURE"
