"""base64url primitives (RFC 4648 §5, no-padding) — encoding only.

This is *not* the §4 crypto (JCS / Ed25519 / chain-hash) — that single source of
truth lives in `shield_sdk.crypto` and is never redeclared here. base64url is a
stateless RFC-4648 transport primitive used for opaque audit cursors and for
decoding a stored agent public key into raw bytes before handing it to
`shield_sdk.crypto.verify_ed25519`. Behaviour mirrors Elydora
`packages/server/src/utils/crypto.ts:13-38` exactly (pad-on-decode,
strip-pad-on-encode) so cursors/keys are byte-compatible with the ported chain.
"""

from __future__ import annotations

import base64


def b64url_encode(data: bytes) -> str:
    """Encode bytes as base64url with padding stripped (Elydora crypto.ts:29-38)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    """Decode a base64url string, re-padding to a multiple of 4 (crypto.ts:13-26)."""
    pad = (-len(value)) % 4
    return base64.urlsafe_b64decode(value + ("=" * pad))
