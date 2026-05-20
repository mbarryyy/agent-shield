"""ADR-0013 §A1 — argon2id password hashing with peppered HMAC + caps.

Architecture:
  1. The plaintext password is HMAC-SHA256-peppered with the *active* pepper
     (first entry of ``SHIELD_PASSWORD_PEPPERS``) BEFORE argon2id sees it.
     The argon2id hash binds the password+pepper composite, not the raw
     password — so a database leak alone is insufficient to mount offline
     attacks (the attacker would additionally need the env-held pepper).
  2. argon2id parameters are env-tunable (``SHIELD_ARGON2_*``) but capped by
     the §A1 hardcoded ceilings. Cap validation runs at ``Settings.from_env()``;
     this module additionally re-validates at hasher construction time.
  3. ``password_pepper_kid`` is persisted on each user row. On login the
     stored kid drives which pepper rotates the verify-hash; if the stored
     kid is NOT the active kid, the password is LAZILY RE-HASHED with the
     active pepper after a successful verify (rotation pattern).

This module is import-cycle-free: depends on stdlib + ``argon2`` + the typed
``Settings``. Tests at ``tests/auth/test_passwords.py`` validate caps,
peppered HMAC, lazy re-hash, and ``needs_rehash``.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError

from ..config import (
    ARGON2_MEMORY_KIB_CAP,
    ARGON2_PARALLELISM_CAP,
    ARGON2_TIME_COST_CAP,
    Settings,
)


@dataclass(frozen=True, slots=True)
class VerifyResult:
    """Outcome of ``verify_password``.

    ``ok`` is the binary accept/reject. ``needs_rehash`` is True when the
    stored hash used a pepper that is no longer the active kid OR when the
    argon2 parameters have advanced (``PasswordHasher.check_needs_rehash``);
    the caller (login flow) re-hashes with the active pepper + current
    parameters and persists, on a successful verify only.
    """

    ok: bool
    needs_rehash: bool = False


def _pepper_password(password: str, pepper_secret: str) -> str:
    """HMAC-SHA256 the password with the pepper; return hex.

    HMAC (not simple concat) is used so a leaked password_hash cannot be
    "un-peppered" by trial-decryption: the pepper is the HMAC key and is
    never present in the database. Hex output keeps argon2's input ascii
    so the C library never sees raw bytes that might trip its length
    handling.
    """
    digest = hmac.new(
        pepper_secret.encode("utf-8"),
        password.encode("utf-8"),
        hashlib.sha256,
    )
    return digest.hexdigest()


class PasswordHasherService:
    """Owns the argon2id hasher and the active pepper rotation logic.

    Constructed once per app via ``PasswordHasherService.from_settings(settings)``
    so the parameters are validated against §A1 caps at construction; tests
    can construct with explicit values to exercise edge cases. Stateless
    apart from the configured hasher + the pepper list (frozen via tuple).
    """

    def __init__(
        self,
        *,
        memory_kib: int,
        time_cost: int,
        parallelism: int,
        peppers: tuple[tuple[str, str], ...],
    ) -> None:
        # Re-validate caps at construction so a hand-rolled service (tests,
        # CLI seed-admin) still raises if it tries to exceed §A1.
        if memory_kib > ARGON2_MEMORY_KIB_CAP:
            raise RuntimeError(
                f"argon2 memory_kib={memory_kib} exceeds §A1 cap {ARGON2_MEMORY_KIB_CAP}"
            )
        if time_cost > ARGON2_TIME_COST_CAP:
            raise RuntimeError(
                f"argon2 time_cost={time_cost} exceeds §A1 cap {ARGON2_TIME_COST_CAP}"
            )
        if parallelism > ARGON2_PARALLELISM_CAP:
            raise RuntimeError(
                f"argon2 parallelism={parallelism} exceeds §A1 cap {ARGON2_PARALLELISM_CAP}"
            )
        if memory_kib <= 0 or time_cost <= 0 or parallelism <= 0:
            raise RuntimeError(
                "argon2 parameters must be positive: "
                f"memory_kib={memory_kib} time_cost={time_cost} parallelism={parallelism}"
            )
        if not peppers:
            raise RuntimeError(
                "ADR-0013 §A1 requires SHIELD_PASSWORD_PEPPERS to be non-empty in "
                "enterprise mode; password hashing refuses unpeppered input."
            )
        self._hasher = PasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_kib,
            parallelism=parallelism,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )
        self._peppers: dict[str, str] = dict(peppers)
        # Tuple order preserves rotation order: first = active.
        self._active_kid: str = peppers[0][0]
        self._active_secret: str = peppers[0][1]

    @classmethod
    def from_settings(cls, settings: Settings) -> PasswordHasherService:
        return cls(
            memory_kib=settings.argon2_memory_kib,
            time_cost=settings.argon2_time_cost,
            parallelism=settings.argon2_parallelism,
            peppers=settings.password_peppers,
        )

    @property
    def active_pepper_kid(self) -> str:
        return self._active_kid

    def known_pepper_kid(self, kid: str) -> bool:
        return kid in self._peppers

    def hash(self, password: str) -> tuple[str, str]:
        """Hash a fresh password with the active pepper.

        Returns ``(password_hash, pepper_kid)`` for persistence; the caller
        stores both columns. The hash itself is the argon2id-encoded string
        (includes algorithm/parameter prefix → forwards-compatible).
        """
        peppered = _pepper_password(password, self._active_secret)
        return self._hasher.hash(peppered), self._active_kid

    def verify(self, password: str, stored_hash: str, stored_kid: str) -> VerifyResult:
        """Constant-time verify; returns ``(ok, needs_rehash)``.

        The stored kid determines which pepper rotates the verify HMAC. An
        unknown kid (rotated out before the user logged in again) is an
        ``ok=False`` — the caller emits ``SIGN_IN_FAIL`` without leaking the
        kid-rotation reason in the response (uniform 401, §A7).
        """
        if not self.known_pepper_kid(stored_kid):
            return VerifyResult(ok=False, needs_rehash=False)
        peppered = _pepper_password(password, self._peppers[stored_kid])
        try:
            self._hasher.verify(stored_hash, peppered)
        except VerifyMismatchError:
            return VerifyResult(ok=False, needs_rehash=False)
        # Successful verify — should we re-hash?
        needs_rehash = stored_kid != self._active_kid or self._hasher.check_needs_rehash(
            stored_hash
        )
        return VerifyResult(ok=True, needs_rehash=needs_rehash)
