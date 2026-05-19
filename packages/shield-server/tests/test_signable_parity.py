"""Reviewer's post-freeze BYTE-PARITY gate.

The server's W1 ``/v1/operations`` path carries the Elydora EOR
(``models.OperationRecord``). Its signed bytes MUST be byte-identical to the
frozen ``shield_sdk.crypto.sign_eor`` rule (= JCS over the EOR dict minus the
``signature`` key) or every chain verification breaks. These tests prove the
server reproduces the SDK/golden bytes exactly — it never re-derives the
projection, it delegates to the frozen primitives via the ``_crypto`` seam.

(The §4 ``ShieldActionRecord`` projection ``shield_sdk.canonical.
record_signable_dict`` governs the W2 ``/v1/governance/decide`` path — a
different record type; its parity binds when that endpoint is built.)
"""

from __future__ import annotations

import time

import shield_sdk.crypto as sdk_crypto
from shield_server._crypto import ShieldSdkCrypto
from shield_server.ingest import _signable
from shield_server.models import OperationRecord

# contracts/golden/vectors.json :: keypair
GOLD_PRIV = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
GOLD_PUB = "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg"
# contracts/golden/vectors.json :: sign_eor
GOLD_EOR: dict[str, object] = {
    "operation_id": "0193aaaa-bbbb-7ccc-8ddd-eeeeeeeeeeee",
    "agent_id": "agentdojo-banking-v1",
    "payload_hash": "u7j9Bqiba5NFxcGzpHlri1IGIF2lnl6kVlgn4nMhsgU",
    "prev_chain_hash": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "issued_at": 1747526400000,
    "signature": "MUST-BE-IGNORED",
}
GOLD_EOR_SIG = (
    "iQ8HsuBlVQ1w1FCT_6umxS-yQ5IPd7cyR4iZkEq4dlBVTWuP4D7mDLTTbnIaac9kqWWsOSBLlNFIYW3OI5J4BA"
)


def _signing_string(crypto: ShieldSdkCrypto, rec: OperationRecord) -> str:
    return crypto.canonical(_signable(rec))


def test_keypair_matches_golden() -> None:
    assert sdk_crypto.get_public_key_base64url(GOLD_PRIV) == GOLD_PUB


def test_sign_eor_golden_vector() -> None:
    # The frozen primitive itself (sanity that we read the same vectors).
    assert sdk_crypto.sign_eor(GOLD_EOR, GOLD_PRIV) == GOLD_EOR_SIG


def test_server_signable_is_byte_parity_with_sign_eor() -> None:
    """server _signable + canonical + sign_ed25519  ==  shield_sdk.sign_eor."""
    crypto = ShieldSdkCrypto()
    rec = OperationRecord(
        op_version="1.0",
        operation_id="op-parity-1",
        org_id="demo-org",
        agent_id="agentdojo-banking-v1",
        issued_at=1747526400000,
        ttl_ms=30_000,
        nonce="AAAAAAAAAAAAAAAAAAAAAA",
        operation_type="tool_call",
        subject={"tool_call_id": "call_abc"},
        action={"tool": "send_money"},
        payload={"amount": 10000.0, "recipient": "X"},
        payload_hash="u7j9Bqiba5NFxcGzpHlri1IGIF2lnl6kVlgn4nMhsgU",
        prev_chain_hash="A" * 43,
        agent_pubkey_kid="agentdojo-banking-v1-key-v1",
        signature="MUST-BE-IGNORED",
    )
    eor_dict = rec.model_dump(mode="json")

    # 1) server projection == sign_eor's internal projection (drop "signature").
    assert _signable(rec) == {k: v for k, v in eor_dict.items() if k != "signature"}

    # 2) server canonical string == JCS of that projection (frozen primitive).
    assert _signing_string(crypto, rec) == sdk_crypto.jcs_canonicalize(_signable(rec))

    # 3) server sign == shield_sdk.crypto.sign_eor (byte-identical signature).
    server_sig = crypto.sign_ed25519(GOLD_PRIV, _signing_string(crypto, rec).encode("utf-8"))
    assert server_sig == sdk_crypto.sign_eor(eor_dict, GOLD_PRIV)

    # 4) round-trips through the server verify path with the derived pubkey.
    assert crypto.verify_ed25519(GOLD_PUB, _signing_string(crypto, rec).encode("utf-8"), server_sig)
    # Tamper -> reject.
    assert not crypto.verify_ed25519(
        GOLD_PUB, _signing_string(crypto, rec).encode("utf-8"), GOLD_EOR_SIG
    )


def test_chain_hash_uses_int_issued_at_no_str_coercion() -> None:
    crypto = ShieldSdkCrypto()
    now_ms = int(time.time() * 1000)
    h_int = crypto.chain_hash("A" * 43, "ph", "op-1", now_ms)
    # Must equal the frozen primitive called with the raw int (the §4 fix).
    assert h_int == sdk_crypto.compute_chain_hash("A" * 43, "ph", "op-1", now_ms)
