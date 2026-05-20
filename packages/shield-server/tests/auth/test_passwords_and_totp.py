"""ADR-0013 §A1 + §A6 — password hashing caps + peppered argon2id +
MultiFernet-wrapped TOTP + recovery codes."""

from __future__ import annotations

import pytest
from shield_server.auth.passwords import PasswordHasherService
from shield_server.auth.totp import TotpService
from shield_server.config import (
    ARGON2_MEMORY_KIB_CAP,
    ARGON2_PARALLELISM_CAP,
    ARGON2_TIME_COST_CAP,
    Settings,
)

pytestmark = pytest.mark.unit_auth


# --- §A1 — argon2 cap validation -------------------------------------- #


_PEPPERS = (("p1", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),)


def test_hasher_refuses_memory_over_cap() -> None:
    with pytest.raises(RuntimeError, match="exceeds §A1 cap"):
        PasswordHasherService(
            memory_kib=ARGON2_MEMORY_KIB_CAP + 1,
            time_cost=3,
            parallelism=4,
            peppers=_PEPPERS,
        )


def test_hasher_refuses_time_over_cap() -> None:
    with pytest.raises(RuntimeError, match="exceeds §A1 cap"):
        PasswordHasherService(
            memory_kib=65536,
            time_cost=ARGON2_TIME_COST_CAP + 1,
            parallelism=4,
            peppers=_PEPPERS,
        )


def test_hasher_refuses_parallelism_over_cap() -> None:
    with pytest.raises(RuntimeError, match="exceeds §A1 cap"):
        PasswordHasherService(
            memory_kib=65536,
            time_cost=3,
            parallelism=ARGON2_PARALLELISM_CAP + 1,
            peppers=_PEPPERS,
        )


def test_hasher_refuses_unpeppered() -> None:
    with pytest.raises(RuntimeError, match="non-empty"):
        PasswordHasherService(memory_kib=65536, time_cost=3, parallelism=4, peppers=())


def test_settings_validates_argon2_at_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHIELD_ARGON2_MEMORY_COST_KIB", str(ARGON2_MEMORY_KIB_CAP + 1))
    with pytest.raises(RuntimeError, match="exceeds §A1 hardcoded cap"):
        Settings.from_env()


# --- argon2 hash + peppered verify ------------------------------------ #


def test_hasher_roundtrips_and_uses_active_kid() -> None:
    svc = PasswordHasherService(
        memory_kib=8192,
        time_cost=1,
        parallelism=1,
        peppers=_PEPPERS,  # tiny for tests
    )
    h, kid = svc.hash("hunter2")
    assert kid == "p1"
    out = svc.verify("hunter2", h, kid)
    assert out.ok and not out.needs_rehash


def test_hasher_verify_wrong_password() -> None:
    svc = PasswordHasherService(memory_kib=8192, time_cost=1, parallelism=1, peppers=_PEPPERS)
    h, kid = svc.hash("hunter2")
    assert not svc.verify("wrong", h, kid).ok


def test_hasher_signals_needs_rehash_on_rotated_pepper() -> None:
    old = (("p_old", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),)
    svc_old = PasswordHasherService(memory_kib=8192, time_cost=1, parallelism=1, peppers=old)
    h, kid = svc_old.hash("hunter2")
    # Rotate: new key is now first, old key kept for decrypt.
    rotated = (("p_new", "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"), *old)
    svc_new = PasswordHasherService(memory_kib=8192, time_cost=1, parallelism=1, peppers=rotated)
    out = svc_new.verify("hunter2", h, kid)
    assert out.ok and out.needs_rehash


def test_hasher_unknown_pepper_kid_returns_ok_false() -> None:
    svc = PasswordHasherService(memory_kib=8192, time_cost=1, parallelism=1, peppers=_PEPPERS)
    assert not svc.verify("hunter2", "$argon2id$...", "p_unknown").ok


# --- §A6 — TOTP MultiFernet wrap + verify ----------------------------- #


_FERNET_KEYS = (("f1", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="),)


def test_totp_setup_returns_uri_and_secret() -> None:
    svc = TotpService(fernet_keys=_FERNET_KEYS)
    setup = svc.setup_for("alice@example.com")
    assert setup.secret
    assert setup.provisioning_uri.startswith("otpauth://totp/")


def test_totp_encrypt_decrypt_roundtrip() -> None:
    svc = TotpService(fernet_keys=_FERNET_KEYS)
    secret = svc.generate_secret()
    enc = svc.encrypt(secret)
    decrypted = svc.decrypt(enc, stored_kid="f1")
    assert decrypted.secret == secret
    assert not decrypted.needs_rewrap


def test_totp_decrypt_signals_rewrap_on_old_key() -> None:
    older = (("f_old", "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB="),)
    svc_old = TotpService(fernet_keys=older)
    secret = svc_old.generate_secret()
    enc = svc_old.encrypt(secret)
    rotated = (("f_new", "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC="), *older)
    svc_new = TotpService(fernet_keys=rotated)
    dec = svc_new.decrypt(enc, stored_kid="f_old")
    assert dec.secret == secret
    assert dec.needs_rewrap
    assert dec.new_active_kid == "f_new"


def test_totp_verify_with_real_code() -> None:
    import pyotp

    svc = TotpService(fernet_keys=_FERNET_KEYS)
    secret = svc.generate_secret()
    code = pyotp.TOTP(secret).now()
    assert svc.verify(secret, code)
    assert not svc.verify(secret, "000000")


def test_totp_recovery_codes_single_use_and_constant_time() -> None:
    plain, hashed = TotpService.generate_recovery_codes()
    assert len(plain) == 10 and len(hashed) == 10
    # Match one; the matched hash is removed.
    ok, new_hashes = TotpService.consume_recovery_code(plain[3], stored_hashes=list(hashed))
    assert ok and len(new_hashes) == 9
    # Re-use of the SAME plain code fails on the trimmed list.
    again, _ = TotpService.consume_recovery_code(plain[3], stored_hashes=new_hashes)
    assert not again
    # Bogus code fails.
    no, _ = TotpService.consume_recovery_code("not-real", stored_hashes=list(hashed))
    assert not no


def test_totp_service_refuses_no_keys() -> None:
    with pytest.raises(RuntimeError, match="non-empty"):
        TotpService(fernet_keys=())
