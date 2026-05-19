"""Property-based crypto invariants (hypothesis).

JCS idempotence / key-order-independence, payload-hash determinism &
sensitivity, the exact chain-hash formula, Ed25519 sign/verify roundtrip and
tamper-rejection, base64url roundtrip.
"""

from __future__ import annotations

import json
from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from shield_sdk import crypto

# JSON-ish values: JCS handles None/bool/int/float/str/list/dict(str keys).
_json = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(min_value=-(10**12), max_value=10**12)
    | st.floats(allow_nan=False, allow_infinity=False, width=64)
    | st.text(max_size=40),
    lambda children: (
        st.lists(children, max_size=5) | st.dictionaries(st.text(max_size=12), children, max_size=5)
    ),
    max_leaves=25,
)


@given(_json)
def test_jcs_is_idempotent(value: Any) -> None:
    once = crypto.jcs_canonicalize(value)
    # Re-parsing the canonical form and re-canonicalizing is a fixpoint.
    assert crypto.jcs_canonicalize(json.loads(once)) == once


@given(st.dictionaries(st.text(min_size=1, max_size=10), st.integers(), max_size=8))
def test_jcs_key_order_independent(d: dict[str, int]) -> None:
    shuffled = dict(reversed(list(d.items())))
    assert crypto.jcs_canonicalize(d) == crypto.jcs_canonicalize(shuffled)


@given(_json)
def test_payload_hash_deterministic(value: Any) -> None:
    assert crypto.compute_payload_hash(value) == crypto.compute_payload_hash(value)
    h = crypto.compute_payload_hash(value)
    assert len(h) == 43 and "=" not in h  # base64url SHA-256, no padding


@given(st.dictionaries(st.text(min_size=1, max_size=8), st.integers(), min_size=1, max_size=6))
def test_payload_hash_sensitive_to_change(d: dict[str, int]) -> None:
    mutated = dict(d)
    k = next(iter(mutated))
    mutated[k] = mutated[k] + 1
    assert crypto.compute_payload_hash(d) != crypto.compute_payload_hash(mutated)


@given(
    st.text(max_size=30),
    st.text(max_size=30),
    st.text(max_size=30),
    st.integers(min_value=0, max_value=2**60),
)
def test_chain_hash_matches_formula(prev: str, ph: str, op: str, ts: int) -> None:
    expected = crypto.sha256_base64url(f"{prev}|{ph}|{op}|{ts}")
    assert crypto.compute_chain_hash(prev, ph, op, ts) == expected


@given(st.binary(max_size=256))
def test_ed25519_sign_verify_roundtrip(msg: bytes) -> None:
    seed = bytes(range(32))
    priv = crypto.base64url_encode(seed)
    pub = crypto.get_public_key_base64url(priv)
    sig = crypto.sign_ed25519(priv, msg)
    assert crypto.verify_ed25519(pub, msg, sig) is True


@given(st.binary(min_size=1, max_size=128))
def test_ed25519_tamper_fails(msg: bytes) -> None:
    priv = crypto.base64url_encode(bytes(range(32)))
    pub = crypto.get_public_key_base64url(priv)
    sig = crypto.sign_ed25519(priv, msg)
    assert crypto.verify_ed25519(pub, msg + b"\x00", sig) is False
    # Wrong key must also fail.
    other_pub = crypto.get_public_key_base64url(crypto.base64url_encode(bytes(range(1, 33))))
    assert crypto.verify_ed25519(other_pub, msg, sig) is False


@given(st.binary(max_size=300))
def test_base64url_roundtrip_no_padding(data: bytes) -> None:
    enc = crypto.base64url_encode(data)
    assert "=" not in enc
    assert crypto.base64url_decode(enc) == data


def test_nonce_and_uuidv7_shape() -> None:
    n = crypto.generate_nonce()
    assert "=" not in n and len(crypto.base64url_decode(n)) == 16
    u = crypto.generate_uuidv7()
    parts = u.split("-")
    assert [len(p) for p in parts] == [8, 4, 4, 4, 12]
    assert u[14] == "7"  # version nibble


def test_jcs_number_serialization_edge_cases() -> None:
    """ES2015/JCS number rules — exactly where cross-impl signatures break."""
    assert crypto.jcs_canonicalize(12345) == "12345"
    assert crypto.jcs_canonicalize(-7) == "-7"
    assert crypto.jcs_canonicalize(0.0) == "0"
    assert crypto.jcs_canonicalize(-0.0) == "0"
    assert crypto.jcs_canonicalize(2.5) == "2.5"
    assert crypto.jcs_canonicalize(True) == "true"
    assert crypto.jcs_canonicalize(False) == "false"
    # NaN / +Inf / -Inf -> JSON null (Elydora-verbatim behavior).
    assert crypto.jcs_canonicalize(float("nan")) == "null"
    assert crypto.jcs_canonicalize(float("inf")) == "null"
    assert crypto.jcs_canonicalize(float("-inf")) == "null"


def test_jcs_non_json_type_fallback() -> None:
    """The verbatim Elydora fallback: a non-list iterable hits json.dumps."""
    assert crypto.jcs_canonicalize((1, 2)) == "[1, 2]"
