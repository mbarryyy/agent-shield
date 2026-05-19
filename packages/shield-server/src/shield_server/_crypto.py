"""Crypto seam — the server's *only* coupling to the §4 crypto.

POST-FREEZE (v1.1 on main, ADR-0007). JCS-RFC8785 / SHA-256 / Ed25519 are the
byte-exact Elydora port in ``shield_sdk.crypto`` (single source of truth, never
redeclared here). The server's W1 ``/v1/operations`` path carries the **Elydora
EOR** (`models.OperationRecord`); its signed bytes must be byte-identical to the
frozen ``shield_sdk.crypto.sign_eor`` rule (= ``jcs_canonicalize`` over the EOR
dict minus the ``signature`` key) — pinned by the ``contracts/golden/vectors.json``
``sign_eor`` / ``chain_hash`` vectors. (The §4 ``ShieldActionRecord`` projection
``shield_sdk.canonical.record_signable_dict`` governs the W2
``/v1/governance/decide`` path; it is a different record type.)

Frozen API shapes adopted here:
  * ``jcs_canonicalize(value) -> str``                       (str, not bytes)
  * ``compute_chain_hash(prev, payload_hash, op_id, issued_at: int) -> str``
  * ``sign_ed25519(private_key_base64url: str, data: bytes) -> str``
  * ``verify_ed25519(public_key_base64url: str, data: bytes, sig_b64url: str)``
"""

from __future__ import annotations

from typing import Protocol

import shield_sdk.crypto as sdk_crypto

# Imported, never redeclared (the no-padding 43-char genesis is frozen in shield_sdk).
GENESIS_CHAIN_HASH = sdk_crypto.GENESIS_CHAIN_HASH


class CryptoProvider(Protocol):
    """The crypto surface the 12-step ingest needs (frozen §4 primitives)."""

    def canonical(self, value: object) -> str:
        """JCS-RFC8785 canonical string (the signed message body)."""
        ...

    def verify_ed25519(self, public_key_b64url: str, message: bytes, signature: str) -> bool: ...

    def chain_hash(
        self, prev: str, payload_hash: str, operation_id: str, issued_at: int
    ) -> str: ...

    def receipt_hash(self, receipt_fields: dict[str, object]) -> str: ...

    def sign_ed25519(self, private_key_b64url: str, message: bytes) -> str: ...


class ShieldSdkCrypto:
    """Production provider — delegates verbatim to the frozen shield_sdk.crypto."""

    def canonical(self, value: object) -> str:
        return sdk_crypto.jcs_canonicalize(value)

    def verify_ed25519(self, public_key_b64url: str, message: bytes, signature: str) -> bool:
        return sdk_crypto.verify_ed25519(public_key_b64url, message, signature)

    def chain_hash(self, prev: str, payload_hash: str, operation_id: str, issued_at: int) -> str:
        # Elydora computeChainHash: SHA-256(`{prev}|{payload_hash}|{op_id}|{issued_at}`);
        # issued_at is the unix-epoch-ms INT per frozen §4.1 (no str() coercion).
        return sdk_crypto.compute_chain_hash(prev, payload_hash, operation_id, issued_at)

    def receipt_hash(self, receipt_fields: dict[str, object]) -> str:
        # Elydora computeReceiptHash = sha256_b64url(JCS(receiptFields)) =
        # exactly compute_payload_hash's contract (SHA-256 over JCS(value)).
        return sdk_crypto.compute_payload_hash(receipt_fields)

    def sign_ed25519(self, private_key_b64url: str, message: bytes) -> str:
        return sdk_crypto.sign_ed25519(private_key_b64url, message)


def crypto_frozen() -> bool:
    """True once sdk-builder's byte-exact port is on main (post-v1.1: True).

    Probes a pure call; the old W0 stub raised NotImplementedError, the frozen
    port returns a hash. Kept so the crypto-gated integration e2e auto-enables
    on the v1.1 rebase without a manual edit.
    """
    try:
        sdk_crypto.compute_payload_hash({"_probe": 1})
    except NotImplementedError:
        return False
    except Exception:  # pragma: no cover - any other failure => treat as not ready
        return False
    return True
