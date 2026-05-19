"""Unit fixtures: a deterministic FakeCrypto + memory storage + TestClient.

FakeCrypto lets every one of the 12 ingest steps (incl. signature verify, chain
derivation, EAR signing) be exercised deterministically WITHOUT docker and
WITHOUT the sdk-builder crypto freeze (the W1 hard dependency). The production
path still goes through shield_sdk.crypto via ShieldSdkCrypto.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from shield_server.app import create_app
from shield_server.config import Settings
from shield_server.storage import Storage, build_memory_storage


def _h(*parts: bytes) -> str:
    d = hashlib.sha256()
    for p in parts:
        d.update(p)
    return d.hexdigest()


class FakeCrypto:
    """Deterministic stand-in (NOT the byte-exact Elydora port — that is
    sdk-builder's shield_sdk.crypto). Linkage/derivation are stable so the
    full ingest + verify round-trips."""

    def canonical(self, value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    def chain_hash(self, prev: str, payload_hash: str, operation_id: str, issued_at: int) -> str:
        return "ch_" + _h(f"{prev}|{payload_hash}|{operation_id}|{issued_at}".encode())

    def receipt_hash(self, receipt_fields: dict[str, object]) -> str:
        return "rh_" + _h(self.canonical(receipt_fields).encode())

    def sign_ed25519(self, private_key_b64url: str, message: bytes) -> str:
        return "sig_" + _h(private_key_b64url.encode(), message)

    def verify_ed25519(self, public_key_b64url: str, message: bytes, signature: str) -> bool:
        return signature == fake_signature(public_key_b64url, message)


def fake_signature(public_key_b64url: str, message: bytes) -> str:
    """Produce a signature FakeCrypto.verify_ed25519 accepts (test-side signer)."""
    return "ok_" + _h(public_key_b64url.encode(), message)


@pytest.fixture
def storage() -> Storage:
    return build_memory_storage()


@pytest.fixture
def crypto() -> FakeCrypto:
    return FakeCrypto()


@pytest.fixture
def settings() -> Settings:
    return Settings.from_env()


@pytest.fixture
def client(storage: Storage, crypto: FakeCrypto, settings: Settings) -> Iterator[TestClient]:
    app = create_app(storage=storage, crypto=crypto, settings=settings)
    with TestClient(app) as c:
        yield c
