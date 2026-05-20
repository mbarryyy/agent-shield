"""ADR-0013 §A6 — TOTP (RFC 6238) + 10 recovery codes, MultiFernet-wrapped secrets.

Architecture:
  * Secret = 20 random bytes, base32-encoded (the canonical pyotp input).
  * Persisted as ``secret_encrypted`` = Fernet token via MultiFernet over
    ``SHIELD_AUTH_FERNET_KEYS``; the ``active_kid`` column records the kid
    that LAST wrote the row. Decryption tries every key in order; the row
    is lazily re-encrypted with the active kid on the next setup-or-verify
    cycle (§A6 rotation pattern).
  * 10 recovery codes (256-bit entropy each, URL-safe base64); stored
    sha256-hashed; consumed one-at-a-time on use.
  * Constant-time comparison (``hmac.compare_digest``) for TOTP verification
    AND recovery-code consumption.

This module is import-cycle-free: depends only on stdlib + ``cryptography`` +
``pyotp`` + the typed ``Settings``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

import pyotp
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from ..config import Settings

_TOTP_SECRET_BYTES = 20  # → 32 base32 chars (RFC 4226 minimum 128 bits, RFC 6238 §5.1)
_RECOVERY_CODE_BYTES = 32  # 256-bit entropy → ~43-char URL-safe b64 (no padding)
_RECOVERY_CODE_COUNT = 10


@dataclass(frozen=True, slots=True)
class TotpSetup:
    """The ``POST /v1/auth/totp/setup`` response shape (minus the QR PNG).

    The plaintext ``secret`` is returned ONCE so the user's authenticator
    app can be provisioned; the server stores only the encrypted form.
    ``provisioning_uri`` is the otpauth:// URL suitable for QR encoding.
    """

    secret: str
    provisioning_uri: str


@dataclass(frozen=True, slots=True)
class TotpDecrypt:
    """``decrypt`` outcome — secret plus whether the row needs re-encryption."""

    secret: str
    needs_rewrap: bool
    new_active_kid: str


def _decode_fernet_key(secret: str) -> bytes:
    """Tolerate both 44-char-with-padding and 43-char-no-padding fernet keys.

    ``cryptography.fernet.Fernet`` requires the with-padding form. The
    secrets/gen.py random branch outputs the canonical 44-char form, but
    the seed branch outputs base64url(32B) which is 44 chars WITH padding
    in our generator — both shapes accepted defensively.
    """
    raw = secret.encode("ascii")
    # If missing padding, add it back (urlsafe_b64 is padding-permissive when
    # the original byte length is exactly 32: 4 chars × 8 = 32 bytes → no
    # padding shortfall, but mass paranoid normalisation is cheap).
    padding = -len(raw) % 4
    if padding:
        raw = raw + b"=" * padding
    return raw


class TotpService:
    """Owns MultiFernet over ``SHIELD_AUTH_FERNET_KEYS`` + the pyotp wrapper."""

    def __init__(
        self,
        *,
        fernet_keys: tuple[tuple[str, str], ...],
        issuer: str = "Agent Shield",
    ) -> None:
        if not fernet_keys:
            raise RuntimeError(
                "ADR-0013 §A6 requires SHIELD_AUTH_FERNET_KEYS to be non-empty "
                "in enterprise mode; TOTP setup refuses unwrapped secrets."
            )
        # Order matters: first = active (encryption); all keys accept decrypt.
        self._key_order: tuple[str, ...] = tuple(k for k, _ in fernet_keys)
        self._kid_to_fernet: dict[str, Fernet] = {
            kid: Fernet(_decode_fernet_key(secret)) for kid, secret in fernet_keys
        }
        self._multi = MultiFernet([self._kid_to_fernet[kid] for kid in self._key_order])
        self._issuer = issuer

    @classmethod
    def from_settings(cls, settings: Settings) -> TotpService:
        return cls(fernet_keys=settings.fernet_keys)

    @property
    def active_kid(self) -> str:
        return self._key_order[0]

    # ---- secret lifecycle ------------------------------------------------ #

    def generate_secret(self) -> str:
        """Return a fresh base32 secret (20 random bytes → 32 base32 chars)."""
        raw = secrets.token_bytes(_TOTP_SECRET_BYTES)
        return base64.b32encode(raw).decode("ascii").rstrip("=")

    def provisioning_uri(self, *, secret: str, email: str) -> str:
        return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=self._issuer)

    def setup_for(self, email: str) -> TotpSetup:
        secret = self.generate_secret()
        return TotpSetup(
            secret=secret, provisioning_uri=self.provisioning_uri(secret=secret, email=email)
        )

    # ---- wrap / unwrap --------------------------------------------------- #

    def encrypt(self, secret: str) -> str:
        """Encrypt a plaintext secret with the active Fernet key."""
        return self._multi.encrypt(secret.encode("ascii")).decode("ascii")

    def decrypt(self, ciphertext: str, *, stored_kid: str) -> TotpDecrypt:
        """Decrypt a stored secret; flag rewrap if not encrypted under active kid.

        ``MultiFernet.decrypt`` tries every key in declaration order. Raises
        ``InvalidToken`` (re-raised) if none match — the caller surfaces this
        as a §A7-uniform 500 ("internal error", no detail) and emits an
        audit row; a lost Fernet key is an operations incident, not a user-
        facing error.
        """
        plain = self._multi.decrypt(ciphertext.encode("ascii"))
        return TotpDecrypt(
            secret=plain.decode("ascii"),
            needs_rewrap=(stored_kid != self.active_kid),
            new_active_kid=self.active_kid,
        )

    # ---- TOTP verify ----------------------------------------------------- #

    def verify(self, secret: str, code: str, *, valid_window: int = 1) -> bool:
        """RFC 6238 verification with ±1 step (30 s) tolerance.

        ``pyotp.TOTP.verify`` uses ``hmac.compare_digest`` internally so the
        comparison is constant-time. The ±1 window absorbs clock-drift but
        bounds the replay window to 90 s; tighten with valid_window=0 for
        admin-sensitive paths if desired.
        """
        if not code or not code.isdigit() or len(code) not in (6, 7, 8):
            return False
        return pyotp.TOTP(secret).verify(code, valid_window=valid_window)

    # ---- recovery codes -------------------------------------------------- #

    @staticmethod
    def generate_recovery_codes() -> tuple[list[str], list[str]]:
        """Return ``(plaintext_codes, hashed_codes)``.

        Plaintext is shown to the user ONCE; hashes are persisted in
        ``totp_credentials.recovery_codes_hash``. Each code is 256 bits of
        entropy (URL-safe base64, no padding) so guessing is computationally
        infeasible regardless of the user picking it.
        """
        plain = [secrets.token_urlsafe(_RECOVERY_CODE_BYTES) for _ in range(_RECOVERY_CODE_COUNT)]
        hashed = [hashlib.sha256(c.encode("utf-8")).hexdigest() for c in plain]
        return plain, hashed

    @staticmethod
    def hash_recovery_code(code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    @staticmethod
    def consume_recovery_code(
        candidate: str, *, stored_hashes: list[str]
    ) -> tuple[bool, list[str]]:
        """Constant-time lookup + single-use pop.

        Returns ``(ok, new_hashes_list)``. On match the matched hash is
        REMOVED from the list — the caller persists ``new_hashes_list`` so
        the code cannot be reused. On miss the list is returned unchanged.
        Comparison is constant-time across all stored codes to avoid timing
        side-channels.
        """
        candidate_hash = TotpService.hash_recovery_code(candidate)
        matched_index = -1
        # Walk every entry — do NOT short-circuit (timing channel).
        for idx, stored in enumerate(stored_hashes):
            if hmac.compare_digest(stored, candidate_hash) and matched_index < 0:
                matched_index = idx
        if matched_index < 0:
            return False, stored_hashes
        return True, [h for i, h in enumerate(stored_hashes) if i != matched_index]


# --- module-level helpers used by routes/tests --------------------------- #


def now_unix_seconds() -> int:
    return int(time.time())


# Catch the import to keep ``InvalidToken`` referenced (callers catch it via
# the module path); the explicit re-export documents the failure mode.
__all__ = [
    "InvalidToken",
    "TotpDecrypt",
    "TotpService",
    "TotpSetup",
    "now_unix_seconds",
]
