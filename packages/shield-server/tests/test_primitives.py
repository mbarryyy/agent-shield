"""base64url + UUIDv7 + crypto-seam probe + error builder."""

from __future__ import annotations

import os
import time

from shield_server._b64 import b64url_decode, b64url_encode
from shield_server._crypto import GENESIS_CHAIN_HASH, ShieldSdkCrypto, crypto_frozen
from shield_server._ids import generate_uuid7
from shield_server.errors import AppError, build_error_response


def test_b64url_round_trip_no_padding() -> None:
    for raw in (b"", b"\x00" * 32, os.urandom(31), b"abc"):
        enc = b64url_encode(raw)
        assert "=" not in enc
        assert b64url_decode(enc) == raw


def test_uuid7_shape_and_time_ordered() -> None:
    a = generate_uuid7()
    time.sleep(0.002)  # advance the 48-bit ms prefix
    b = generate_uuid7()
    for u in (a, b):
        assert len(u) == 36 and u[14] == "7" and u.count("-") == 4
    assert a != b
    assert a[:8] <= b[:8]  # high 32 timestamp bits are monotonic across the sleep


def test_genesis_is_frozen_no_pad() -> None:
    assert GENESIS_CHAIN_HASH == "A" * 43 and "=" not in GENESIS_CHAIN_HASH


def test_crypto_frozen_and_chain_hash_matches_golden() -> None:
    # POST-v1.1 rebase: shield_sdk.crypto is byte-exact on main -> frozen True,
    # and chain_hash takes issued_at as INT unix-ms (no str() coercion). Pinned
    # to contracts/golden/vectors.json chain_hash[0].
    assert crypto_frozen() is True
    sdk = ShieldSdkCrypto()
    got = sdk.chain_hash(
        "A" * 43,
        "u7j9Bqiba5NFxcGzpHlri1IGIF2lnl6kVlgn4nMhsgU",
        "0193aaaa-bbbb-7ccc-8ddd-eeeeeeeeeeee",
        1747526400000,
    )
    assert got == "2OxyLR10CXKdX5fWpRI_ELMjw9BP4xkTYgnnmk_3sQ4"


def test_error_response_shape() -> None:
    body = build_error_response("NOT_FOUND", "req-1")
    assert body["error"]["code"] == "NOT_FOUND"  # type: ignore[index]
    err = AppError(404, "NOT_FOUND")
    assert err.status_code == 404 and err.error_code == "NOT_FOUND"
    detailed = build_error_response("VALIDATION_ERROR", "r", "msg", {"k": "v"})
    assert detailed["error"]["details"] == {"k": "v"}  # type: ignore[index]
