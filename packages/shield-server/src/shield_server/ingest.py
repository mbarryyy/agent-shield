"""The 12-step Elydora ingest — faithful port of
Related_Work/Elydora-Open-Source-main/packages/server/src/services/operation-service.ts
(`submitOperation` / `getOperation` / `verifyOperation`).

Step order, error codes, hash inputs and the operation/receipt row shapes are
kept 1:1 so the chain stays cross-impl compatible with Elydora's reference SDK
and the console's verification view. Crypto (steps 5/7/11) is delegated to the
`CryptoProvider` seam (`_crypto.py`) — production = `shield_sdk.crypto`
(HARD-DEP-gated on sdk-builder Task #2; see _crypto.py docstring + the PR).
"""

from __future__ import annotations

import json
import time
from typing import cast

from ._crypto import GENESIS_CHAIN_HASH, CryptoProvider
from ._ids import generate_uuid7
from .config import (
    ELYDORA_KID,
    MAX_NONCE_LENGTH,
    MAX_PAYLOAD_SIZE,
    MAX_TTL_MS,
    MIN_TTL_MS,
)
from .errors import AppError
from .models import EAR, GetOperationResponse, Operation, OperationRecord, Receipt
from .storage import Storage

_REQUIRED_STRINGS = (
    "operation_id",
    "org_id",
    "agent_id",
    "nonce",
    "operation_type",
    "payload_hash",
    "prev_chain_hash",
    "agent_pubkey_kid",
    "signature",
)


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def validate_record_fields(rec: OperationRecord, received_at: int) -> None:
    """Port of validateEORFields (operation-service.ts:575-633)."""
    if rec.op_version != "1.0":
        raise AppError(400, "VALIDATION_ERROR", "Unsupported protocol version.")

    for field in _REQUIRED_STRINGS:
        value = getattr(rec, field)
        if not isinstance(value, str) or value.strip() == "":
            raise AppError(400, "VALIDATION_ERROR", f"Missing required field: {field}")

    if len(rec.nonce) > MAX_NONCE_LENGTH:
        raise AppError(400, "VALIDATION_ERROR", "Nonce too long.")

    if not isinstance(rec.issued_at, int) or rec.issued_at <= 0:
        raise AppError(400, "VALIDATION_ERROR", "Invalid issued_at.")

    if not isinstance(rec.ttl_ms, int):
        raise AppError(400, "VALIDATION_ERROR", "Missing ttl_ms.")
    if rec.ttl_ms < MIN_TTL_MS:
        raise AppError(400, "VALIDATION_ERROR", "TTL too low.")
    if rec.ttl_ms > MAX_TTL_MS:
        raise AppError(400, "VALIDATION_ERROR", "TTL too high.")

    # TTL expiration (issued_at + ttl_ms must not be in the past).
    if rec.issued_at + rec.ttl_ms < received_at:
        raise AppError(400, "TTL_EXPIRED")

    if rec.payload is not None:
        payload_str = rec.payload if isinstance(rec.payload, str) else _json(rec.payload)
        if len(payload_str.encode("utf-8")) > MAX_PAYLOAD_SIZE:
            raise AppError(400, "PAYLOAD_TOO_LARGE")


def _signable(rec: OperationRecord) -> dict[str, object]:
    """The exact EOR signable dict — BYTE-PARITY with the frozen
    ``shield_sdk.crypto.sign_eor`` rule (= the EOR dict minus the ``signature``
    key). ``model_dump(mode="json")`` reproduces all Elydora EOR fields incl.
    present-null (Elydora EOR keeps ``payload: null``), so JCS over this is
    byte-identical to ``sign_eor`` and to Elydora ``buildSignableEOR``
    (operation-service.ts:553-570). Pinned by the ``sign_eor`` golden vector.
    No projection is re-derived: it is delegated to the frozen primitive."""
    return {k: v for k, v in rec.model_dump(mode="json").items() if k != "signature"}


async def submit_operation(
    storage: Storage,
    crypto: CryptoProvider,
    rec: OperationRecord,
    server_signing_key: str,
) -> EAR:
    """submitOperation 12-step ingest (operation-service.ts:56-297)."""
    received_at = int(time.time() * 1000)

    # Step 1 — validate fields (TTL bounds/expiry, size, nonce length, required).
    validate_record_fields(rec, received_at)

    # Step 2 — replay detection (nonce SET NX EX = op TTL seconds).
    nonce_key = f"nonce:{rec.org_id}:{rec.nonce}"
    nonce_ttl = -(-rec.ttl_ms // 1000)  # ceil(ttl_ms / 1000)
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

    # Step 5 — verify Ed25519 over JCS(signable EOR). public_key is the stored
    # base64url string (frozen verify_ed25519 takes the b64url key, not bytes).
    signing_string = crypto.canonical(_signable(rec))
    public_key_b64url = str(agent_key["public_key"])
    if not crypto.verify_ed25519(public_key_b64url, signing_string.encode("utf-8"), rec.signature):
        raise AppError(400, "INVALID_SIGNATURE")

    # Step 6 — prev_chain_hash must equal the agent's latest stored chain_hash.
    latest = await storage.db.fetchrow(
        "SELECT chain_hash, seq_no FROM operations WHERE agent_id = $1 "
        "ORDER BY seq_no DESC LIMIT 1",
        rec.agent_id,
    )
    expected_prev = str(latest["chain_hash"]) if latest else GENESIS_CHAIN_HASH
    next_seq = int(cast(int, latest["seq_no"])) + 1 if latest else 1
    if rec.prev_chain_hash != expected_prev:
        raise AppError(
            400,
            "PREV_HASH_MISMATCH",
            "The previous chain hash does not match.",
            {"expected": expected_prev, "actual": rec.prev_chain_hash},
        )

    # Step 7 — server-derive chain_hash (never trusted from the client).
    chain_hash = crypto.chain_hash(
        rec.prev_chain_hash, rec.payload_hash, rec.operation_id, rec.issued_at
    )

    # Step 8 — build the persisted Operation row.
    r2_payload_key = f"{rec.org_id}/{rec.agent_id}/{rec.operation_id}"
    operation = Operation(
        operation_id=rec.operation_id,
        org_id=rec.org_id,
        agent_id=rec.agent_id,
        seq_no=next_seq,
        operation_type=rec.operation_type,
        issued_at=rec.issued_at,
        ttl_ms=rec.ttl_ms,
        nonce=rec.nonce,
        subject=_json(rec.subject),
        action=_json(rec.action),
        payload_hash=rec.payload_hash,
        prev_chain_hash=rec.prev_chain_hash,
        chain_hash=chain_hash,
        agent_pubkey_kid=rec.agent_pubkey_kid,
        signature=rec.signature,
        r2_payload_key=r2_payload_key,
        created_at=received_at,
    )

    # Step 9 — store the full signed envelope in the object store.
    await storage.objects.put(
        r2_payload_key,
        rec.model_dump_json().encode("utf-8"),
        "application/json",
    )

    # Step 10 — enqueue for async processing. W2: XADD shield:actions:{workflow}.
    receipt_id = generate_uuid7()
    queue_message_id = receipt_id

    # Step 11 — generate + sign the EAR receipt.
    receipt_fields: dict[str, object] = {
        "receipt_version": "1.0",
        "receipt_id": receipt_id,
        "operation_id": rec.operation_id,
        "org_id": rec.org_id,
        "agent_id": rec.agent_id,
        "server_received_at": received_at,
        "seq_no": next_seq,
        "chain_hash": chain_hash,
        "queue_message_id": queue_message_id,
    }
    receipt_hash = crypto.receipt_hash(receipt_fields)
    # server_signing_key is the base64url Ed25519 seed (frozen sign_ed25519
    # takes the b64url string, not raw bytes).
    elydora_signature = crypto.sign_ed25519(server_signing_key, receipt_hash.encode("utf-8"))
    ear = EAR(
        receipt_version="1.0",
        receipt_id=receipt_id,
        operation_id=rec.operation_id,
        org_id=rec.org_id,
        agent_id=rec.agent_id,
        server_received_at=received_at,
        seq_no=next_seq,
        chain_hash=chain_hash,
        queue_message_id=queue_message_id,
        receipt_hash=receipt_hash,
        elydora_kid=ELYDORA_KID,
        elydora_signature=elydora_signature,
    )
    r2_receipt_key = f"{rec.org_id}/{rec.agent_id}/receipts/{rec.operation_id}"
    await storage.objects.put(
        r2_receipt_key, ear.model_dump_json().encode("utf-8"), "application/json"
    )

    # Step 12 — persist operation + receipt atomically (Elydora db.batch()).
    async with storage.db.transaction() as tx:
        await tx.execute(
            "INSERT INTO operations (operation_id, org_id, agent_id, seq_no, "
            "operation_type, issued_at, ttl_ms, nonce, subject, action, "
            "payload_hash, prev_chain_hash, chain_hash, agent_pubkey_kid, "
            "signature, r2_payload_key, created_at) VALUES "
            "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)",
            operation.operation_id,
            operation.org_id,
            operation.agent_id,
            operation.seq_no,
            operation.operation_type,
            operation.issued_at,
            operation.ttl_ms,
            operation.nonce,
            operation.subject,
            operation.action,
            operation.payload_hash,
            operation.prev_chain_hash,
            operation.chain_hash,
            operation.agent_pubkey_kid,
            operation.signature,
            operation.r2_payload_key,
            operation.created_at,
        )
        await tx.execute(
            "INSERT INTO receipts (receipt_id, operation_id, r2_receipt_key, "
            "created_at) VALUES ($1,$2,$3,$4)",
            receipt_id,
            rec.operation_id,
            r2_receipt_key,
            received_at,
        )

    # Forward-looking chain hint (authoritative chain stays UNIQUE(agent_id,seq_no)).
    await storage.cache.set(f"chain:{rec.agent_id}:latest", chain_hash)
    return ear


async def get_operation(storage: Storage, operation_id: str, org_id: str) -> GetOperationResponse:
    """getOperation (operation-service.ts:303-342)."""
    row = await storage.db.fetchrow(
        "SELECT * FROM operations WHERE operation_id = $1 AND org_id = $2",
        operation_id,
        org_id,
    )
    if row is None:
        raise AppError(404, "NOT_FOUND", "Operation not found.")
    operation = Operation.model_validate(row)

    receipt_row = await storage.db.fetchrow(
        "SELECT * FROM receipts WHERE operation_id = $1", operation_id
    )
    receipt = Receipt.model_validate(receipt_row) if receipt_row else None

    payload: dict[str, object] | None = None
    if operation.r2_payload_key:
        raw = await storage.objects.get(operation.r2_payload_key)
        if raw is not None:
            try:
                envelope = json.loads(raw)
                candidate = envelope.get("payload")
                payload = candidate if isinstance(candidate, dict) else None
            except (ValueError, AttributeError):  # pragma: no cover - best-effort
                payload = None
    return GetOperationResponse(operation=operation, receipt=receipt, payload=payload)


async def verify_operation(
    storage: Storage, crypto: CryptoProvider, operation_id: str, org_id: str
) -> tuple[bool, dict[str, bool], list[str]]:
    """verifyOperation (operation-service.ts:348-544): independent re-derivation
    of signature + chain + receipt. Merkle is W4 (epochs not yet produced) so it
    is reported as pending (omitted) here."""
    errors: list[str] = []
    sig_ok = chain_ok = receipt_ok = False

    row = await storage.db.fetchrow(
        "SELECT * FROM operations WHERE operation_id = $1 AND org_id = $2",
        operation_id,
        org_id,
    )
    if row is None:
        raise AppError(404, "NOT_FOUND", "Operation not found.")
    operation = Operation.model_validate(row)

    if not operation.r2_payload_key:  # pragma: no cover - rows always carry a key
        return (
            False,
            {"signature": False, "chain": False, "receipt": False},
            ["Operation has no object-store payload key."],
        )
    raw = await storage.objects.get(operation.r2_payload_key)
    if raw is None:
        return (
            False,
            {"signature": False, "chain": False, "receipt": False},
            ["Record evidence not found in the object store."],
        )
    rec = OperationRecord.model_validate_json(raw)

    # Signature.
    agent_key = await storage.db.fetchrow(
        "SELECT * FROM agent_keys WHERE kid = $1 AND agent_id = $2",
        rec.agent_pubkey_kid,
        rec.agent_id,
    )
    if agent_key is not None:
        sig_ok = crypto.verify_ed25519(
            str(agent_key["public_key"]),
            crypto.canonical(_signable(rec)).encode("utf-8"),
            rec.signature,
        )
        if not sig_ok:
            errors.append("Ed25519 signature verification failed.")
    else:
        errors.append(f'Signing key "{rec.agent_pubkey_kid}" not found.')

    # Chain hash (recompute + previous-link check).
    expected_chain = crypto.chain_hash(
        operation.prev_chain_hash,
        operation.payload_hash,
        operation.operation_id,
        operation.issued_at,
    )
    chain_ok = expected_chain == operation.chain_hash
    if not chain_ok:
        errors.append("Chain hash mismatch vs recomputed value.")
    if operation.seq_no > 1:
        prev = await storage.db.fetchrow(
            "SELECT chain_hash FROM operations WHERE agent_id = $1 AND seq_no = $2",
            operation.agent_id,
            operation.seq_no - 1,
        )
        if prev is not None and str(prev["chain_hash"]) != operation.prev_chain_hash:
            chain_ok = False
            errors.append("prev_chain_hash does not link to the previous operation.")

    # Receipt.
    receipt_row = await storage.db.fetchrow(
        "SELECT * FROM receipts WHERE operation_id = $1", operation_id
    )
    if receipt_row is not None:
        ear_raw = await storage.objects.get(str(receipt_row["r2_receipt_key"]))
        if ear_raw is not None:
            ear = json.loads(ear_raw)
            recomputed = crypto.receipt_hash(
                {
                    "receipt_version": ear["receipt_version"],
                    "receipt_id": ear["receipt_id"],
                    "operation_id": ear["operation_id"],
                    "org_id": ear["org_id"],
                    "agent_id": ear["agent_id"],
                    "server_received_at": ear["server_received_at"],
                    "seq_no": ear["seq_no"],
                    "chain_hash": ear["chain_hash"],
                    "queue_message_id": ear["queue_message_id"],
                }
            )
            if recomputed == ear["receipt_hash"]:
                receipt_ok = True
            else:
                errors.append("Receipt hash does not match recomputed value.")
        else:  # pragma: no cover - defensive
            errors.append("Receipt evidence not found in the object store.")
    else:  # pragma: no cover - receipts always written with the operation
        errors.append("No receipt found for this operation.")

    valid = sig_ok and chain_ok and receipt_ok
    return valid, {"signature": sig_ok, "chain": chain_ok, "receipt": receipt_ok}, errors
