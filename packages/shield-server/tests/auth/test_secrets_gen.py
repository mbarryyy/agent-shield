"""Unit tests for `infra/secrets/gen.py` (ADR-0013).

Covers all 4 subcommands (session / pepper / fernet / jwt-ed25519) via
subprocess so the test exercises the actual CLI surface CI uses to bootstrap
ephemeral secrets. Deterministic via `--seed`; format invariants asserted.
"""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

pytestmark = pytest.mark.unit_auth

_REPO_ROOT = Path(__file__).resolve().parents[4]
_GEN = _REPO_ROOT / "infra" / "secrets" / "gen.py"


def _run(*args: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(_GEN), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    out = proc.stdout
    # Exactly one line of output, no trailing whitespace (shell-substitution safe).
    assert out.endswith("\n")
    assert out.count("\n") == 1
    return out.rstrip("\n")


def test_session_format_and_length() -> None:
    out = _run("session", "--seed", "1")
    # base64url(32B) with no padding = 43 chars; URL-safe alphabet only.
    assert len(out) == 43
    assert all(c.isalnum() or c in "-_" for c in out)
    # base64url-decodable back to 32 bytes.
    assert len(base64.urlsafe_b64decode(out + "=")) == 32


def test_session_deterministic_under_seed() -> None:
    assert _run("session", "--seed", "42") == _run("session", "--seed", "42")
    assert _run("session", "--seed", "42") != _run("session", "--seed", "43")


def test_pepper_same_shape_as_session() -> None:
    out = _run("pepper", "--seed", "7")
    assert len(out) == 43
    assert len(base64.urlsafe_b64decode(out + "=")) == 32


def test_fernet_is_loadable_by_fernet() -> None:
    out = _run("fernet", "--seed", "9")
    # cryptography.fernet.Fernet must accept the key (44-char base64 with padding).
    fernet = Fernet(out.encode("ascii"))
    token = fernet.encrypt(b"hello")
    assert fernet.decrypt(token) == b"hello"


def test_jwt_ed25519_pair_is_loadable() -> None:
    out = _run("jwt-ed25519", "--seed", "13")
    priv_b64, pub_b64 = out.split(".")
    # Add base64 padding back for decoding.
    priv_pem = base64.urlsafe_b64decode(priv_b64 + "=" * (-len(priv_b64) % 4))
    pub_pem = base64.urlsafe_b64decode(pub_b64 + "=" * (-len(pub_b64) % 4))
    priv = serialization.load_pem_private_key(priv_pem, password=None)
    pub = serialization.load_pem_public_key(pub_pem)
    assert isinstance(priv, Ed25519PrivateKey)
    # Sign-and-verify roundtrip proves the keypair is consistent.
    sig = priv.sign(b"adr-0013")
    pub.verify(sig, b"adr-0013")


def test_random_mode_differs_each_run() -> None:
    # No --seed → random; two consecutive runs must differ with overwhelming probability.
    assert _run("session") != _run("session")


def test_unknown_subcommand_rejected() -> None:
    proc = subprocess.run(
        [sys.executable, str(_GEN), "bogus"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
