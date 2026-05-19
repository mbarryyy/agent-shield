"""Ed25519 / JCS-RFC8785 / chain-hash crypto — byte-exact port of Elydora.

Ported verbatim (byte-for-byte algorithm-faithful) from the Elydora Open Source
reference Python SDK, MIT-licensed:

  * ``sdks/python/elydora/crypto.py``  -> the JCS/SHA-256/Ed25519 primitives
  * ``sdks/python/elydora/utils.py``   -> base64url + nonce + UUIDv7 helpers

The port is intentionally line-faithful so that the on-the-wire bytes (the
JCS canonical string, the SHA-256 ``payload_hash``/``chain_hash``, and the
Ed25519 signature) are *identical* to what Elydora's reference SDK and its
server produce. The frozen ``contracts/golden/vectors.json`` cross-impl
vectors and the byte-exact regression tests pin this guarantee.

``verify_ed25519`` is the one **addition** over the upstream Python SDK: the
Elydora Python SDK only signs (the server verifies in TypeScript). The §4
two-phase contract needs a Python verifier for the server-side 12-step
ingest, so it is provided here as the exact inverse of ``sign_ed25519`` and is
clearly marked below.

Genesis constant: ``GENESIS_CHAIN_HASH`` is the 43-char, NO-padding base64url
value verified byte-identical in Elydora ``sdks/python/elydora/client.py`` and
``packages/server/src/services/operation-service.ts``. The upstream README's
trailing ``=`` is wrong; the code value is authoritative and frozen here.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import struct
import time
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

# 43-char, NO trailing '=' padding. Verified byte-identical in Elydora
# client.py:40 and operation-service.ts:47. The README's trailing-'=' is wrong.
GENESIS_CHAIN_HASH = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


# ---------------------------------------------------------------------------
# base64url (Elydora utils.py — verbatim)
# ---------------------------------------------------------------------------


def base64url_encode(data: bytes) -> str:
    """Encode bytes to base64url string with no padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def base64url_decode(s: str) -> bytes:
    """Decode a base64url string (with or without padding) to bytes."""
    s = s.replace("-", "+").replace("_", "/")
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.b64decode(s)


def generate_nonce() -> str:
    """Generate a 16-byte random nonce, base64url encoded."""
    return base64url_encode(os.urandom(16))


def generate_uuidv7() -> str:
    """Generate a UUIDv7 (time-ordered, random) as a string (RFC 9562)."""
    timestamp_ms = int(time.time() * 1000)

    # 48-bit timestamp
    ts_bytes = struct.pack(">Q", timestamp_ms)[2:]  # last 6 bytes of 8-byte big-endian

    # 2 bytes: version (4 bits = 0x7) + 12 random bits
    rand_a = struct.unpack(">H", os.urandom(2))[0]
    rand_a = (rand_a & 0x0FFF) | 0x7000  # set version nibble

    # 8 bytes: variant (2 bits = 0b10) + 62 random bits
    rand_b = bytearray(os.urandom(8))
    rand_b[0] = (rand_b[0] & 0x3F) | 0x80  # set variant bits

    uuid_bytes = ts_bytes + struct.pack(">H", rand_a) + bytes(rand_b)

    hex_str = uuid_bytes.hex()
    return f"{hex_str[0:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:32]}"


# ---------------------------------------------------------------------------
# SHA-256 (Elydora crypto.py — verbatim)
# ---------------------------------------------------------------------------


def sha256_base64url(data: str | bytes) -> str:
    """Compute SHA-256 of data and return base64url-encoded hash."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    digest = hashlib.sha256(data).digest()
    return base64url_encode(digest)


# ---------------------------------------------------------------------------
# JCS Canonicalization, RFC 8785 (Elydora crypto.py — verbatim)
# ---------------------------------------------------------------------------


def _jcs_serialize_number(value: int | float) -> str:
    """Serialize a number per JCS / ES2015 Number serialization rules."""
    if isinstance(value, bool):
        # bool is a subclass of int in Python; handle before int check
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    # float
    if math.isnan(value) or math.isinf(value):
        return "null"
    if value == 0.0:
        # Handle -0.0 -> "0"
        return "0"
    # Use Python's repr which matches ES2015 for normal floats,
    # but we need to ensure no trailing zeros beyond what's needed.
    # json.dumps handles this correctly per the JSON spec.
    return json.dumps(value)


def jcs_canonicalize(value: Any) -> str:
    """Canonicalize a value according to JCS (RFC 8785).

    - Object keys sorted lexicographically
    - No whitespace
    - Numbers serialized using ES2015 rules
    - Strings serialized with minimal JSON escaping
    - ``None``/null-valued keys present in the mapping ARE emitted as ``null``
      (this is the exact Elydora behavior; the Shield signable projection in
      ``shield_sdk.canonical`` strips ``None`` *before* canonicalization so
      present-null vs absent can never diverge — see that module's docstring)
    """
    if value is None:
        return "null"

    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, (int, float)):
        return _jcs_serialize_number(value)

    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)

    if isinstance(value, list):
        elements = [jcs_canonicalize(v) for v in value]
        return "[" + ",".join(elements) + "]"

    if isinstance(value, dict):
        keys = sorted(value.keys())
        pairs = []
        for key in keys:
            v = value[key]
            if v is not None or key in value:
                # Include keys with None values (maps to JSON null), but skip
                # keys that don't exist (cannot happen while iterating
                # dict keys). Behavior preserved byte-for-byte from Elydora.
                pairs.append(json.dumps(key, ensure_ascii=False) + ":" + jcs_canonicalize(v))
        return "{" + ",".join(pairs) + "}"

    return json.dumps(value)


# ---------------------------------------------------------------------------
# Payload hash (Elydora crypto.py — verbatim)
# ---------------------------------------------------------------------------


def compute_payload_hash(payload: Any) -> str:
    """Compute SHA-256 hash of JCS-canonicalized payload, base64url encoded."""
    canonical = jcs_canonicalize(payload)
    return sha256_base64url(canonical)


# ---------------------------------------------------------------------------
# Chain hash (Elydora crypto.py — verbatim)
# ---------------------------------------------------------------------------


def compute_chain_hash(
    prev_chain_hash: str,
    payload_hash: str,
    operation_id: str,
    issued_at: int,
) -> str:
    """Compute chain hash: SHA-256(prev|payload_hash|op_id|issued_at) base64url.

    Matches the Elydora backend formula exactly:
      chain_hash = SHA-256(prev + "|" + payload_hash + "|" + operation_id
                           + "|" + str(issued_at))
    ``issued_at`` is the unix-epoch-milliseconds integer (§4 line 129); it is
    f-string-formatted exactly as Elydora formats its ``int`` issued_at.
    """
    input_str = f"{prev_chain_hash}|{payload_hash}|{operation_id}|{issued_at}"
    return sha256_base64url(input_str)


# ---------------------------------------------------------------------------
# Ed25519 signing (Elydora crypto.py — verbatim)
# ---------------------------------------------------------------------------


def sign_ed25519(private_key_base64url: str, data: bytes) -> str:
    """Sign data with Ed25519 private key (32-byte seed, base64url encoded).

    Returns a base64url-encoded 64-byte signature.
    """
    seed = base64url_decode(private_key_base64url)
    key = Ed25519PrivateKey.from_private_bytes(seed)
    signature = key.sign(data)
    return base64url_encode(signature)


def get_public_key_base64url(private_key_base64url: str) -> str:
    """Derive the Ed25519 public key from the private key seed.

    Returns base64url-encoded 32-byte public key.
    """
    seed = base64url_decode(private_key_base64url)
    key = Ed25519PrivateKey.from_private_bytes(seed)
    pub = key.public_key()
    raw_bytes = pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64url_encode(raw_bytes)


# ---------------------------------------------------------------------------
# Ed25519 verification — Shield ADDITION (exact inverse of sign_ed25519).
# Not present in the Elydora Python SDK (Elydora verifies server-side in TS);
# required by the §4 server-side 12-step ingest. Byte-compatible: a signature
# produced by sign_ed25519 over `data` with a given key MUST verify here with
# that key's public half, and any tamper of data/signature/key MUST fail.
# ---------------------------------------------------------------------------


def verify_ed25519(public_key_base64url: str, data: bytes, signature_base64url: str) -> bool:
    """Verify an Ed25519 signature. Returns True iff valid; never raises."""
    try:
        pub_bytes = base64url_decode(public_key_base64url)
        sig = base64url_decode(signature_base64url)
        key = Ed25519PublicKey.from_public_bytes(pub_bytes)
        key.verify(sig, data)
        return True
    except (InvalidSignature, ValueError):
        return False


# ---------------------------------------------------------------------------
# Record/EOR signing (Elydora crypto.py — verbatim low-level signer)
# ---------------------------------------------------------------------------


def sign_eor(eor_dict: dict[str, Any], private_key_base64url: str) -> str:
    """Sign a dict by canonicalizing all fields except 'signature'.

    Low-level signer, byte-identical to Elydora ``sign_eor``. The Shield §4
    record/verdict signers in ``shield_sdk.canonical`` build the typed
    signable projection and delegate the actual signing to this primitive.
    """
    signable = {k: v for k, v in eor_dict.items() if k != "signature"}
    canonical = jcs_canonicalize(signable)
    return sign_ed25519(private_key_base64url, canonical.encode("utf-8"))
