"""Channel-1 synchronous decision gate — `POST /v1/governance/decide`.

Ingests a §4 ``ShieldActionRecord{phase:pre_exec}`` AND returns a signed
``GovernanceVerdict`` in ONE round-trip (SDK §4.3 / ADR-0004). W2 = STUB → the
verdict is always ``PASS`` (the real LangGraph 4-guardian graph lands W3); this
unblocks eval + console from day 1 (the W2 critical-path dependency).

W2 HARD-GATE (reviewer-enforced, carried from G1): the §4 record's
signature/chain bytes are produced by the FROZEN ``shield_sdk.canonical``
module **verbatim** — ``verify_record`` / ``derive_chain_hash`` /
``finalize_verdict`` — never a re-derived projection. This is a DISTINCT record
type and signable rule from the W1 Elydora-EOR ``sign_eor`` path
(``shield_sdk.canonical.record_signable_dict``: ``model_dump(exclude_none)``
minus ``signature``+``chain_hash``; present-null ≡ absent).

Channel-2 (§4.3): every accepted record is fanned to
``shield:actions:{workflow_id}`` for the ``shield-evaluator`` /
``shield-auditor`` consumer groups (at-least-once, replayable). The structured
``intervention_log`` row is written in the ingest transaction (master §2.5 cost
hook #3 ≡ eval §9 dep #2) — server owns the table+write; the token/model
columns are populated by governance's hook #1 counts, never re-implemented here.
"""

from __future__ import annotations

import json
import time

import shield_sdk.canonical as canonical
from shield_sdk.crypto import GENESIS_CHAIN_HASH
from shield_sdk.schema import (
    Decision,
    GovernanceVerdict,
    Guardian,
    Phase,
    ShieldActionRecord,
    VerdictReason,
)

from .config import (
    ACTIONS_STREAM_PREFIX,
    CONSUMER_GROUPS,
    MAX_NONCE_LENGTH,
    MAX_PAYLOAD_SIZE,
    MAX_TTL_MS,
    MIN_TTL_MS,
    Settings,
)
from .errors import AppError
from .storage import Storage

_REQUIRED = (
    "record_id",
    "correlation_id",
    "org_id",
    "agent_id",
    "nonce",
    "payload_hash",
    "prev_chain_hash",
    "agent_pubkey_kid",
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _validate_pre_exec(rec: ShieldActionRecord, received_at: int) -> None:
    if rec.phase != Phase.PRE_EXEC:
        raise AppError(400, "VALIDATION_ERROR", "decide requires phase=pre_exec.")
    if rec.shield_version != "1.1":
        raise AppError(400, "VALIDATION_ERROR", "Unsupported shield_version.")
    for field in _REQUIRED:
        value = getattr(rec, field)
        if not isinstance(value, str) or value.strip() == "":
            raise AppError(400, "VALIDATION_ERROR", f"Missing required field: {field}")
    if rec.signature is None or rec.signature.strip() == "":
        raise AppError(400, "VALIDATION_ERROR", "Missing signature.")
    if len(rec.nonce) > MAX_NONCE_LENGTH:
        raise AppError(400, "VALIDATION_ERROR", "Nonce too long.")
    if not isinstance(rec.issued_at, int) or rec.issued_at <= 0:
        raise AppError(400, "VALIDATION_ERROR", "Invalid issued_at.")
    if rec.ttl_ms < MIN_TTL_MS:
        raise AppError(400, "VALIDATION_ERROR", "TTL too low.")
    if rec.ttl_ms > MAX_TTL_MS:
        raise AppError(400, "VALIDATION_ERROR", "TTL too high.")
    if rec.issued_at + rec.ttl_ms < received_at:
        raise AppError(400, "TTL_EXPIRED")
    payload_bytes = rec.payload.model_dump_json().encode("utf-8")
    if len(payload_bytes) > MAX_PAYLOAD_SIZE:
        raise AppError(400, "PAYLOAD_TOO_LARGE")


def _stub_pass_verdict(rec: ShieldActionRecord, latency_ms: float) -> GovernanceVerdict:
    """W2 stub gate. W3 swaps this for the LangGraph 4-guardian aggregate."""
    return GovernanceVerdict(
        record_id=rec.record_id,
        correlation_id=rec.correlation_id,
        run_id=rec.run_id,
        decision=Decision.PASS,
        risk_score=0.0,
        reasons=[
            VerdictReason(
                agent=Guardian.DEFENDER,
                label="STUB_PASS",
                detail="W2 stub gate — real LangGraph multi-agent verdict lands W3.",
                score=0.0,
            )
        ],
        served_at=_now_ms(),
        shield_kid=None,  # set by finalize_verdict's caller via shield_kid below
        latency_ms=latency_ms,
    )


async def decide(
    storage: Storage, rec: ShieldActionRecord, settings: Settings
) -> GovernanceVerdict:
    """One round-trip: ingest+chain the pre_exec record, fan to Channel-2, and
    return the signed (STUB PASS) GovernanceVerdict."""
    from .config import SHIELD_KID

    received_at = _now_ms()
    started = time.perf_counter()

    # Step 1 — validate the §4 pre_exec record.
    _validate_pre_exec(rec, received_at)

    # Step 2 — nonce replay (SET NX EX = op TTL seconds).
    nonce_key = f"nonce:{rec.org_id}:{rec.nonce}"
    nonce_ttl = -(-rec.ttl_ms // 1000)
    if not await storage.cache.set_if_absent(nonce_key, "1", nonce_ttl):
        raise AppError(400, "REPLAY_DETECTED")

    # Step 3 — agent lookup + status.
    agent = await storage.db.fetchrow(
        "SELECT * FROM agents WHERE agent_id = $1 AND org_id = $2",
        rec.agent_id,
        rec.org_id,
    )
    if agent is None:
        raise AppError(404, "UNKNOWN_AGENT")
    if agent["status"] == "frozen":
        raise AppError(403, "AGENT_FROZEN")
    if agent["status"] == "revoked":
        raise AppError(403, "AGENT_FROZEN", "The agent has been revoked.")

    # Step 4 — key lookup + status.
    agent_key = await storage.db.fetchrow(
        "SELECT * FROM agent_keys WHERE kid = $1 AND agent_id = $2",
        rec.agent_pubkey_kid,
        rec.agent_id,
    )
    if agent_key is None:
        raise AppError(400, "INVALID_SIGNATURE", "Signing key not found for agent.")
    if agent_key["status"] == "revoked":
        raise AppError(403, "KEY_REVOKED")
    if agent_key["status"] == "retired":
        raise AppError(403, "KEY_REVOKED", "The signing key is retired.")

    # Step 5 — verify Ed25519 over the FROZEN §4 signable projection.
    # HARD-GATE: shield_sdk.canonical.verify_record reproduces record_signable_dict
    # bytes exactly (exclude_none / drop signature+chain_hash) — no re-derivation.
    if not canonical.verify_record(rec, str(agent_key["public_key"])):
        raise AppError(400, "INVALID_SIGNATURE")

    # Step 6 — prev_chain_hash must equal the agent's latest stored chain_hash
    # (one per-agent chain shared with the W1 EOR path; record_id == op id).
    latest = await storage.db.fetchrow(
        "SELECT chain_hash, seq_no FROM operations WHERE agent_id = $1 "
        "ORDER BY seq_no DESC LIMIT 1",
        rec.agent_id,
    )
    expected_prev = str(latest["chain_hash"]) if latest else GENESIS_CHAIN_HASH
    next_seq = int(str(latest["seq_no"])) + 1 if latest else 1
    if rec.prev_chain_hash != expected_prev:
        raise AppError(
            400,
            "PREV_HASH_MISMATCH",
            "The previous chain hash does not match.",
            {"expected": expected_prev, "actual": rec.prev_chain_hash},
        )

    # Step 7 — server-derive chain_hash (FROZEN; never trusted from client).
    chain_hash = canonical.derive_chain_hash(rec.prev_chain_hash, rec)

    # Step 8 — persist the record on the per-agent chain + MinIO envelope.
    r2_key = f"{rec.org_id}/{rec.agent_id}/{rec.record_id}"
    record_json = rec.model_dump_json()
    await storage.objects.put(r2_key, record_json.encode("utf-8"), "application/json")

    # Step 9 — build + sign the STUB PASS verdict (one round-trip).
    latency_ms = (time.perf_counter() - started) * 1000.0
    verdict = _stub_pass_verdict(rec, latency_ms)
    verdict.shield_kid = SHIELD_KID
    verdict = canonical.finalize_verdict(verdict, settings.server_signing_key)

    # Step 10 — atomic persist: operations row + intervention_log (hook #3).
    async with storage.db.transaction() as tx:
        await tx.execute(
            "INSERT INTO operations (operation_id, org_id, agent_id, seq_no, "
            "operation_type, issued_at, ttl_ms, nonce, subject, action, "
            "payload_hash, prev_chain_hash, chain_hash, agent_pubkey_kid, "
            "signature, r2_payload_key, created_at) VALUES "
            "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)",
            rec.record_id,
            rec.org_id,
            rec.agent_id,
            next_seq,
            rec.operation_type,
            rec.issued_at,
            rec.ttl_ms,
            rec.nonce,
            _json(rec.subject),
            _json(rec.action.model_dump(mode="json")),
            rec.payload_hash,
            rec.prev_chain_hash,
            chain_hash,
            rec.agent_pubkey_kid,
            rec.signature,
            r2_key,
            received_at,
        )
        await tx.execute(
            "INSERT INTO intervention_log (verdict_id, record_id, correlation_id, "
            "run_id, decision, step_index, triggered_rule_id, tokens_in, "
            "tokens_out, model_id, served_via, latency_ms, created_at) VALUES "
            "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)",
            verdict.verdict_id,
            rec.record_id,
            rec.correlation_id,
            rec.run_id,
            verdict.decision.value,
            rec.step_index,
            None,  # triggered_rule_id — set by the real W3 graph
            0,  # tokens_in  — governance hook #1 populates (W3); server owns table only
            0,  # tokens_out
            None,  # model_id
            None,  # served_via
            verdict.latency_ms,
            received_at,
        )

    # Step 11 — Channel-2 fan-out (at-least-once; consumer groups idempotent).
    stream = f"{ACTIONS_STREAM_PREFIX}:{rec.workflow_id}"
    for group in CONSUMER_GROUPS:
        await storage.cache.ensure_group(stream, group)
    await storage.cache.xadd(
        stream,
        {
            "record_id": rec.record_id,
            "correlation_id": rec.correlation_id,
            "phase": rec.phase.value,
            "seq_no": str(next_seq),
            "chain_hash": chain_hash,
            "verdict_id": verdict.verdict_id,
            "record": record_json,
        },
    )
    # Forward-looking chain hint (authoritative chain = UNIQUE(agent_id,seq_no)).
    await storage.cache.set(f"chain:{rec.agent_id}:latest", chain_hash)
    return verdict
