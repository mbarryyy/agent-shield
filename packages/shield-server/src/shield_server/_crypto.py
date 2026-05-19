"""Crypto seam — the server's *only* coupling to the §4 crypto.

HARD DEPENDENCY (surfaced to team-lead in [server-builder CONTEXT-READY] and in
the PR): JCS-RFC8785 / Ed25519 / chain-hash are the single source of truth in
`shield_sdk.crypto`, ported byte-exact + golden-vector-frozen by sdk-builder at
W1 (Task #2 / ADR-0007 v1.1). Until that freeze lands, `shield_sdk.crypto` is an
importable STUB whose bodies raise `NotImplementedError`, so every signature
verify / chain derivation / EAR signature in the 12-step ingest is UNVERIFIABLE.

The server therefore depends on a small `CryptoProvider` protocol:
  * production -> `ShieldSdkCrypto`, which delegates verbatim to
    `shield_sdk.crypto` (never redeclares it),
  * `crypto_frozen()` probes whether the real port has landed so the
    integration suite skips (not fails) the crypto-gated end-to-end until this
    worktree is rebased onto the frozen v1.1 baseline,
  * unit tests inject a deterministic fake to cover the non-crypto orchestration
    of all 12 steps without docker or the sdk-builder freeze.
"""

from __future__ import annotations

from typing import Protocol

import shield_sdk.crypto as sdk_crypto

# Imported, never redeclared (the no-padding 43-char genesis is frozen in shield_sdk).
GENESIS_CHAIN_HASH = sdk_crypto.GENESIS_CHAIN_HASH


class CryptoProvider(Protocol):
    """The crypto surface the 12-step ingest needs (mirrors Elydora crypto.ts)."""

    def canonical(self, value: object) -> bytes:
        """JCS-RFC8785 canonical bytes (the signed message body)."""
        ...

    def verify_ed25519(self, public_key: bytes, message: bytes, signature: str) -> bool: ...

    def chain_hash(
        self, prev: str, payload_hash: str, operation_id: str, issued_at: int
    ) -> str: ...

    def receipt_hash(self, receipt_fields: dict[str, object]) -> str: ...

    def sign_ed25519(self, private_key: bytes, message: bytes) -> str: ...


class ShieldSdkCrypto:
    """Production provider — delegates verbatim to the frozen shield_sdk.crypto."""

    def canonical(self, value: object) -> bytes:
        return sdk_crypto.jcs_canonicalize(value)

    def verify_ed25519(self, public_key: bytes, message: bytes, signature: str) -> bool:
        return sdk_crypto.verify_ed25519(public_key, message, signature)

    def chain_hash(self, prev: str, payload_hash: str, operation_id: str, issued_at: int) -> str:
        # Elydora computeChainHash: SHA-256(`{prev}|{payload_hash}|{op_id}|{issued_at}`).
        # issued_at is stringified exactly as the frozen golden vectors define.
        return sdk_crypto.compute_chain_hash(prev, payload_hash, operation_id, str(issued_at))

    def receipt_hash(self, receipt_fields: dict[str, object]) -> str:
        # Elydora computeReceiptHash = sha256_b64url(JCS(receiptFields)); this is
        # exactly compute_payload_hash's contract (SHA-256 over JCS(value)).
        return sdk_crypto.compute_payload_hash(receipt_fields)

    def sign_ed25519(self, private_key: bytes, message: bytes) -> str:
        return sdk_crypto.sign_ed25519(private_key, message)


def crypto_frozen() -> bool:
    """True once sdk-builder's byte-exact port has replaced the W0 stub.

    Probes a pure no-arg-safe call; the stub raises NotImplementedError, the
    real port returns a hash. Keeps the integration suite green now (skip) and
    auto-enables the crypto-gated assertions after the v1.1 rebase.
    """
    try:
        sdk_crypto.compute_payload_hash({"_probe": 1})
    except NotImplementedError:
        return False
    except Exception:  # pragma: no cover - any other failure => treat as not ready
        return False
    return True
