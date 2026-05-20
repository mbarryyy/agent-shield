"""ADR-0013 — auth-package utility primitives (uuidv7, time, opaque tokens).

Import-cycle-free: depends only on stdlib. Other auth submodules import from
here without inversion risk.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
import uuid

# Opaque token byte-length for sessions / invites / reset / verify tokens.
# 48 random bytes → 64-char base64url (no padding) = 384 bits entropy.
_TOKEN_BYTES = 48


def now_ms() -> int:
    """Current epoch milliseconds (matches the BIGINT schema column convention)."""
    return int(time.time() * 1000)


def uuidv7() -> str:
    """Generate a UUIDv7 string (time-ordered, lexicographically sortable).

    The repo allows uuidv7 as TEXT PK across new auth tables (ADR-0013 §A8
    schema). CPython's stdlib ``uuid`` doesn't ship a v7 helper as of 3.11
    so we implement it inline per RFC 9562 §5.7:

      48-bit unix millis | 4-bit version (7) | 12-bit rand_a |
      2-bit variant (10) | 62-bit rand_b

    The output ``str(uuid)`` is 36-char canonical 8-4-4-4-12 dashed form.
    """
    unix_ms = now_ms() & 0xFFFFFFFFFFFF  # 48 bits
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    # Compose the 128-bit integer per RFC 9562 §5.7 layout.
    val = (unix_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=val))


def generate_opaque_token(num_bytes: int = _TOKEN_BYTES) -> str:
    """Cryptographically random URL-safe base64 token (no padding).

    Used for session cookie values, password-reset tokens, email-verify
    tokens, invite tokens. The raw string is shown to the user ONCE
    (printed in email or returned in JSON for api-keys); the server stores
    only the SHA-256 hash for constant-time lookup.
    """
    return secrets.token_urlsafe(num_bytes)


def sha256_hex(value: str) -> str:
    """Hex-encoded SHA-256 of the input string (utf-8 encoded)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def constant_time_equal(a: str, b: str) -> bool:
    """``hmac.compare_digest`` wrapper — constant-time string comparison.

    Used for CSRF token comparison (§A10) and session-token-hash lookup so
    no timing side-channel leaks valid vs. invalid token prefixes. Returns
    False on any type mismatch instead of raising — the caller never wants
    a None-input to crash a header-validation path.
    """
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def redact_argv() -> list[str]:
    """Return a redacted ``sys.argv`` for the §A3 STARTED_IN_OPEN_MODE audit row.

    Strips any token-shaped arguments (anything ≥ 32 chars matching the
    base64url alphabet) so credentials accidentally passed on the CLI do not
    end up in ``audit_log_auth.detail``.
    """
    import sys as _sys

    redacted: list[str] = []
    for arg in _sys.argv:
        if len(arg) >= 32 and all(c.isalnum() or c in "-_=" for c in arg):
            redacted.append("***REDACTED***")
        else:
            redacted.append(arg)
    return redacted


def client_ip(headers: dict[str, str] | None, fallback: str | None = None) -> str | None:
    """Resolve the client IP from request headers (X-Forwarded-For or X-Real-IP).

    Used by sessions/audit to record source IP. Returns ``None`` if no
    forwarded-IP header is present and no fallback supplied.
    """
    if headers is None:
        return fallback
    for key in ("x-forwarded-for", "x-real-ip", "forwarded"):
        raw = headers.get(key) or headers.get(key.title())
        if raw:
            # X-Forwarded-For may be a comma-separated chain; first is original.
            return raw.split(",")[0].strip()
    return fallback


# Re-export for tests / direct consumption.
TOKEN_BYTES = _TOKEN_BYTES


# Suppress "os import is unused" — kept available for future utils that need
# environment access; cheap and harmless.
_ = os
