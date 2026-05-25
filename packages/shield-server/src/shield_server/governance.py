"""§4 governance ingest — Channel-1 sync gate + Channel-2 record ingest.

* ``decide``  → ``POST /v1/governance/decide`` : ingests a
  ``ShieldActionRecord{phase:pre_exec}`` AND returns a signed
  ``GovernanceVerdict`` in ONE round-trip (SDK §4.3 / ADR-0004). W2 = STUB →
  always ``PASS`` (the real gov ``decide()`` pipeline — deterministic
  Defender + Phase-B Evaluator agent + Supervisor/Auditor scaffold — lands
  W3+); unblocks eval + console day 1 (the W2 critical-path dependency).
* ``record`` → ``POST /v1/governance/record`` : ingests a
  ``ShieldActionRecord{phase:post_exec}`` — async (NO verdict), chain-linked,
  fanned to Channel-2 so the Evaluator/Auditor consume the outcome. This is
  the ``record_path`` sdk-builder's ``ShieldRecorder`` targets.

W2 HARD-GATE (reviewer-enforced, carried from G1): the §4 record/verdict
signature & chain bytes are produced by the FROZEN ``shield_sdk.canonical``
module **verbatim** — ``verify_record`` / ``derive_chain_hash`` /
``finalize_verdict`` — never a re-derived projection. DISTINCT record type and
signable rule from the W1 Elydora-EOR ``sign_eor`` path
(``shield_sdk.canonical.record_signable_dict``: ``model_dump(exclude_none)``
minus ``signature``+``chain_hash``; present-null ≡ absent).

Channel-2 (§4.3): every accepted record (both phases) is fanned to
``shield:actions:{workflow_id}`` for the ``shield-evaluator`` /
``shield-auditor`` consumer groups (at-least-once, replayable). The structured
``intervention_log`` row is written ONLY on the decision (``decide``) path
(master §2.5 cost hook #3 ≡ eval §9 dep #2) — server owns the table+write; the
token/model columns are populated by governance's hook #1, never here.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence

import shield_sdk.canonical as canonical
from shield_governance.evidence import GuardianEvidence
from shield_sdk.crypto import GENESIS_CHAIN_HASH
from shield_sdk.schema import GovernanceVerdict, Phase, ShieldActionRecord

from .config import (
    ACTIONS_STREAM_PREFIX,
    CONSUMER_GROUPS,
    MAX_NONCE_LENGTH,
    MAX_PAYLOAD_SIZE,
    MAX_TTL_MS,
    MIN_TTL_MS,
    VERDICTS_STREAM_PREFIX,
    Settings,
)
from .errors import AppError
from .govseam import GovernanceApp
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


def guardian_evidence_key(verdict_key: str) -> str:
    return f"{verdict_key}.guardian_evidence"


def _guardian_evidence_payload(
    rec: ShieldActionRecord, rows: Sequence[GuardianEvidence]
) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for row in rows:
        item: dict[str, object] = {
            "record_id": rec.record_id,
            "correlation_id": rec.correlation_id,
            "guardian": row.guardian.value,
            "decision": row.decision.value,
            "reasons": list(row.reasons),
            "model_id": row.model_id,
            "served_via": None if row.served_via is None else row.served_via.value,
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
            "latency_ms": row.latency_ms,
            "cost_usd": row.cost_usd,
        }
        if row.memory is not None:
            memory = dict(row.memory)
            item["memory"] = memory
            for key in ("memory_backend", "collection", "query_id", "hit_count", "missing_reason"):
                if key in memory:
                    item[key] = memory[key]
            if memory.get("latency_ms") is not None:
                item["memory_latency_ms"] = memory["latency_ms"]
            top_hits = memory.get("top_hits")
            if isinstance(top_hits, list) and top_hits and isinstance(top_hits[0], dict):
                item["top_hit_id"] = top_hits[0].get("id")
                item["score"] = top_hits[0].get("score")
                item["distance"] = top_hits[0].get("distance")
        if row.tool_calls:
            item["tool_calls"] = list(row.tool_calls)
        payload.append(item)
    return payload


def _validate(rec: ShieldActionRecord, received_at: int, expected_phase: Phase) -> None:
    if rec.phase != expected_phase:
        raise AppError(
            400, "VALIDATION_ERROR", f"This route requires phase={expected_phase.value}."
        )
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
    if len(rec.payload.model_dump_json().encode("utf-8")) > MAX_PAYLOAD_SIZE:
        raise AppError(400, "PAYLOAD_TOO_LARGE")


async def _ingest_prefix(
    storage: Storage, rec: ShieldActionRecord, received_at: int, expected_phase: Phase
) -> tuple[str, int, str, str]:
    """Steps 1–8 shared by decide (pre_exec) and record (post_exec):
    validate → nonce-replay → agent/key status → FROZEN Ed25519 verify →
    prev==latest → server-derive chain_hash → MinIO envelope. Returns
    ``(chain_hash, next_seq, r2_key, record_json)``."""
    _validate(rec, received_at, expected_phase)

    nonce_key = f"nonce:{rec.org_id}:{rec.nonce}"
    if not await storage.cache.set_if_absent(nonce_key, "1", -(-rec.ttl_ms // 1000)):
        raise AppError(400, "REPLAY_DETECTED")

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

    # HARD-GATE: FROZEN shield_sdk.canonical.verify_record reproduces
    # record_signable_dict bytes exactly (exclude_none / drop signature+
    # chain_hash) — never a re-derived projection.
    if not canonical.verify_record(rec, str(agent_key["public_key"])):
        raise AppError(400, "INVALID_SIGNATURE")

    # One per-agent chain shared with the W1 EOR path (record_id == op id).
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

    chain_hash = canonical.derive_chain_hash(rec.prev_chain_hash, rec)
    r2_key = f"{rec.org_id}/{rec.agent_id}/{rec.record_id}"
    record_json = rec.model_dump_json()
    await storage.objects.put(r2_key, record_json.encode("utf-8"), "application/json")
    return chain_hash, next_seq, r2_key, record_json


def _operations_insert(
    rec: ShieldActionRecord, next_seq: int, chain_hash: str, r2_key: str, received_at: int
) -> tuple[str, tuple[object, ...]]:
    sql = (
        "INSERT INTO operations (operation_id, org_id, agent_id, seq_no, "
        "operation_type, issued_at, ttl_ms, nonce, subject, action, "
        "payload_hash, prev_chain_hash, chain_hash, agent_pubkey_kid, "
        "signature, r2_payload_key, created_at, correlation_id, run_id, "
        "phase) VALUES "
        "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)"
    )
    args: tuple[object, ...] = (
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
        rec.correlation_id,  # W3 PR-S2: queryable for the console READ contract
        rec.run_id,
        rec.phase.value,
    )
    return sql, args


async def _fan_channel2(
    storage: Storage,
    rec: ShieldActionRecord,
    chain_hash: str,
    next_seq: int,
    verdict_id: str,
) -> None:
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
            "verdict_id": verdict_id,
            "record": rec.model_dump_json(),
        },
    )
    # Forward-looking chain hint (authoritative chain = UNIQUE(agent_id,seq_no)).
    await storage.cache.set(f"chain:{rec.agent_id}:latest", chain_hash)


async def _fan_verdicts(
    storage: Storage, rec: ShieldActionRecord, verdict: GovernanceVerdict
) -> None:
    """W3 PR-S3 — Channel-2 `shield:verdicts:{workflow_id}` producer. The
    server OWNS this producer side (as with `shield:actions`); gov emits late
    async outcomes on, and the console SSE renders, THIS exact LOCKED FLAT
    8-field envelope (str values, decode_responses=True) — no re-guessing."""
    stream = f"{VERDICTS_STREAM_PREFIX}:{rec.workflow_id}"
    for group in CONSUMER_GROUPS:
        await storage.cache.ensure_group(stream, group)
    await storage.cache.xadd(
        stream,
        {
            "verdict_id": verdict.verdict_id,
            "record_id": rec.record_id,
            "correlation_id": rec.correlation_id,
            "run_id": rec.run_id,
            "decision": verdict.decision.value,
            "risk_score": str(verdict.risk_score),
            "phase": rec.phase.value,
            "verdict": verdict.model_dump_json(),
        },
    )


def _governance_verdict_insert(
    rec: ShieldActionRecord,
    verdict: GovernanceVerdict,
    verdict_key: str,
    created_at: int,
) -> tuple[str, tuple[object, ...]]:
    sql = (
        "INSERT INTO governance_verdicts (verdict_id, record_id, "
        "correlation_id, run_id, org_id, agent_id, decision, risk_score, "
        "latency_ms, prevented_loss, r2_verdict_key, created_at) VALUES "
        "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)"
    )
    args: tuple[object, ...] = (
        verdict.verdict_id,
        rec.record_id,
        rec.correlation_id,
        rec.run_id,
        rec.org_id,
        rec.agent_id,
        verdict.decision.value,
        verdict.risk_score,
        verdict.latency_ms,
        # Server persists the value supplied by governance/sdk; it does not
        # infer or synthesize prevented loss.
        verdict.obligations.prevented_loss or 0.0,
        verdict_key,
        created_at,
    )
    return sql, args


async def publish_async_verdict(
    storage: Storage,
    rec: ShieldActionRecord,
    verdict: GovernanceVerdict,
    settings: Settings,
    *,
    guardian_evidence: Sequence[GuardianEvidence] = (),
) -> GovernanceVerdict:
    """Server-owned boundary for late Channel-2 governance verdicts.

    Governance computes an unsigned async outcome. This function forces the
    action-record identity, attaches server timing/kid fields, signs with the
    shield-server key, stores the signed envelope, and publishes the locked
    ``shield:verdicts`` stream envelope.
    """
    from .config import SHIELD_KID

    started = time.perf_counter()
    verdict.record_id = rec.record_id
    verdict.correlation_id = rec.correlation_id
    verdict.run_id = rec.run_id
    verdict.served_at = _now_ms()
    verdict.latency_ms = (time.perf_counter() - started) * 1000.0
    verdict.shield_kid = SHIELD_KID
    signed = canonical.finalize_verdict(verdict, settings.server_signing_key)
    verdict_key = f"{rec.org_id}/{rec.agent_id}/verdicts/{signed.verdict_id}"
    await storage.objects.put(
        verdict_key, signed.model_dump_json().encode("utf-8"), "application/json"
    )
    evidence_payload = _guardian_evidence_payload(rec, guardian_evidence)
    if evidence_payload:
        await storage.objects.put(
            guardian_evidence_key(verdict_key),
            _json(evidence_payload).encode("utf-8"),
            "application/json",
        )
    sql, args = _governance_verdict_insert(rec, signed, verdict_key, _now_ms())
    await storage.db.execute(sql, *args)
    await _fan_verdicts(storage, rec, signed)
    return signed


async def decide(
    storage: Storage,
    rec: ShieldActionRecord,
    settings: Settings,
    gov_app: GovernanceApp,
) -> GovernanceVerdict:
    """Channel-1 sync gate (pre_exec), one round-trip:

      ingest+chain (server) → gov_app.decide(rec) returns the UNSIGNED verdict
      (governance owns the decision) → server attaches served_at/latency/
      shield_kid, forces the chained-record identity, and SIGNS with the
      shield-server key (server owns signing) → intervention_log + Channel-2.

    Default ``gov_app`` is the honest ``NullGovernanceApp`` (UNSIGNED PASS,
    explicitly a staged-delivery stub) until gov Task #21 lands.
    """
    from .config import SHIELD_KID

    received_at = _now_ms()
    started = time.perf_counter()
    chain_hash, next_seq, r2_key, _json_rec = await _ingest_prefix(
        storage, rec, received_at, Phase.PRE_EXEC
    )

    # Governance owns the DECISION (UNSIGNED). Server owns the chained-record
    # identity → force the id fields so intervention_log / XADD keys always
    # match the ingested record regardless of what gov returns.
    verdict = await gov_app.decide(rec)
    verdict.record_id = rec.record_id
    verdict.correlation_id = rec.correlation_id
    verdict.run_id = rec.run_id
    verdict.served_at = _now_ms()
    verdict.latency_ms = (time.perf_counter() - started) * 1000.0
    verdict.shield_kid = SHIELD_KID
    # Server owns signing (the shield-server key) — verdict arrives UNSIGNED.
    verdict = canonical.finalize_verdict(verdict, settings.server_signing_key)

    # W3 PR-S2: object-store the signed verdict envelope (backs the console
    # verdict tab; offline-verifiable like the record/EAR envelopes).
    verdict_key = f"{rec.org_id}/{rec.agent_id}/verdicts/{verdict.verdict_id}"
    await storage.objects.put(
        verdict_key, verdict.model_dump_json().encode("utf-8"), "application/json"
    )

    async with storage.db.transaction() as tx:
        sql, args = _operations_insert(rec, next_seq, chain_hash, r2_key, received_at)
        await tx.execute(sql, *args)
        sql, args = _governance_verdict_insert(rec, verdict, verdict_key, received_at)
        await tx.execute(sql, *args)
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
            0,  # tokens_in  — governance hook #1 populates W3; server owns table only
            0,  # tokens_out
            None,  # model_id
            None,  # served_via
            verdict.latency_ms,
            received_at,
        )

    await _fan_channel2(storage, rec, chain_hash, next_seq, verdict.verdict_id)
    await _fan_verdicts(storage, rec, verdict)  # W3 PR-S3 Channel-2 verdicts
    return verdict


async def record(
    storage: Storage, rec: ShieldActionRecord, settings: Settings
) -> dict[str, object]:
    """Channel-2 ingest (post_exec): ingest+chain the outcome record and fan it
    to ``shield:actions``. ASYNC — no verdict, no intervention_log row (that is
    decision-keyed; the post_exec carries ``verdict_ref`` to its gate). Returns
    a lightweight 202 ack."""
    received_at = _now_ms()
    chain_hash, next_seq, r2_key, _json_rec = await _ingest_prefix(
        storage, rec, received_at, Phase.POST_EXEC
    )

    async with storage.db.transaction() as tx:
        sql, args = _operations_insert(rec, next_seq, chain_hash, r2_key, received_at)
        await tx.execute(sql, *args)

    await _fan_channel2(storage, rec, chain_hash, next_seq, rec.verdict_ref or "")
    return {
        "accepted": True,
        "record_id": rec.record_id,
        "correlation_id": rec.correlation_id,
        "chain_hash": chain_hash,
        "seq_no": next_seq,
    }


# W3 PR-S5 — HITL resume. The LangGraph interrupt resume schema
# (gov §3.3 / langgraph prebuilt/interrupt.py:87-105).
RESUME_DECISIONS = ("accept", "edit", "response", "ignore")


async def resume(
    storage: Storage,
    settings: Settings,
    gov_app: GovernanceApp,
    incident_id: str,
    decision: str,
    payload: dict[str, object] | None,
    org_id: str = "demo-org",
) -> GovernanceVerdict:
    """W3 PR-S5 — thin HITL resume gate. Server owns route+auth+validation +
    SIGNING + the server-authoritative resume-STATE (the incidents-list
    status); governance owns the semantics (LangGraph ``Command(resume=…)``
    re-entry of the paused incident, gov §3.3). ``incident_id`` is the
    ESCALATE gate verdict_id. Returns the server-signed post-resume verdict."""
    from .config import SHIELD_KID

    if decision not in RESUME_DECISIONS:
        raise AppError(
            400,
            "VALIDATION_ERROR",
            f"decision must be one of {', '.join(RESUME_DECISIONS)}.",
        )
    started = time.perf_counter()
    thread_id = await _resume_thread_id(storage, org_id, incident_id)
    verdict = await gov_app.resume(thread_id, decision, payload)
    verdict.served_at = _now_ms()
    verdict.latency_ms = (time.perf_counter() - started) * 1000.0
    verdict.shield_kid = SHIELD_KID
    # Server owns signing (the shield-server key) — verdict arrives UNSIGNED.
    verdict = canonical.finalize_verdict(verdict, settings.server_signing_key)

    # Server-authoritative resume-STATE: mark the incident (= the ESCALATE gate
    # verdict_id) resolved so GET /v1/governance/incidents flips pending→
    # resolved on the SAME id. Tolerant: no-op if the incident isn't recorded.
    await storage.db.execute(
        "UPDATE governance_verdicts SET resolution = $1, resolved_at = $2 WHERE verdict_id = $3",
        decision,
        _now_ms(),
        incident_id,
    )
    return verdict


async def _resume_thread_id(storage: Storage, org_id: str, incident_id: str) -> str:
    """Map the console/server incident id (ESCALATE verdict_id) back to the
    LangGraph thread id (run_id). Older tests and the NullGovernanceApp pass
    arbitrary ids, so unresolved ids remain unchanged."""
    row = await storage.db.fetchrow(
        "SELECT * FROM governance_verdicts WHERE verdict_id = $1 AND org_id = $2",
        incident_id,
        org_id,
    )
    if row is None:
        return incident_id
    run_id = row.get("run_id")
    return incident_id if run_id is None else str(run_id)
