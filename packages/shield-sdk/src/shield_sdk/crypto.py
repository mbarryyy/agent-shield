"""Ed25519 / JCS-RFC8785 / chain-hash crypto.

W0 STUB. At W1 sdk-builder ports Elydora `sdks/python/elydora/crypto.py` +
`utils.py` BYTE-EXACT (verified first-hand) and freezes golden vectors.
"""

from __future__ import annotations

# 43-char, NO trailing '=' padding. Verified byte-identical in Elydora
# client.py:40 and operation-service.ts:47. The README's trailing-'=' is wrong.
GENESIS_CHAIN_HASH = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def jcs_canonicalize(value: object) -> bytes:
    """RFC-8785 JSON Canonicalization. W1: byte-exact Elydora port."""
    raise NotImplementedError("W1: port from Elydora crypto.py")  # pragma: no cover


def compute_payload_hash(payload: object) -> str:
    raise NotImplementedError("W1: SHA-256 over JCS(signable projection)")  # pragma: no cover


def compute_chain_hash(prev: str, payload_hash: str, operation_id: str, issued_at: str) -> str:
    raise NotImplementedError(
        "W1: SHA-256(prev|payload_hash|operation_id|issued_at)"
    )  # pragma: no cover


def sign_ed25519(private_key: bytes, message: bytes) -> str:
    raise NotImplementedError("W1: Ed25519 sign, base64url no-pad")  # pragma: no cover


def verify_ed25519(public_key: bytes, message: bytes, signature: str) -> bool:
    raise NotImplementedError("W1: Ed25519 verify")  # pragma: no cover
