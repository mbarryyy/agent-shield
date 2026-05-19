"""Cross-impl golden vectors — the byte-exact regression freeze.

``golden_vectors.json`` was captured FROM Elydora's reference Python SDK at
generation time (every primitive cross-verified byte-exact then; see
``tests/_tools/gen_golden_vectors.py``). This test re-derives every value with
our port and asserts equality, so the port can never silently drift from
Elydora — and it runs green in CI on py3.11+3.12 without needing Elydora on
the runner. (A live Elydora cross-check also exists in
``test_elydora_reference.py`` and runs when the upstream tree is present.)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shield_sdk import canonical, crypto
from shield_sdk.schema import GovernanceVerdict, ShieldActionRecord

_V: dict[str, Any] = json.loads((Path(__file__).parent / "golden_vectors.json").read_text())
_PRIV = _V["keypair"]["private_key_b64url"]
_PUB = _V["keypair"]["public_key_b64url"]


def test_keypair_derivation() -> None:
    assert crypto.get_public_key_base64url(_PRIV) == _PUB
    assert _V["keypair"]["seed_hex"] == bytes(range(32)).hex()


def test_genesis_matches_vectors() -> None:
    assert crypto.GENESIS_CHAIN_HASH == _V["x-genesis-chain-hash"] == "A" * 43


def test_jcs_vectors_byte_exact() -> None:
    for vec in _V["jcs"]:
        assert crypto.jcs_canonicalize(vec["input"]) == vec["canonical"]


def test_jcs_emits_present_null() -> None:
    """The verbatim Elydora port emits present-null keys (the projection,
    not the primitive, is what strips None — proven in test_canonical)."""
    pn = next(v for v in _V["jcs"] if "present_null" in str(v["input"]))
    assert crypto.jcs_canonicalize(pn["input"]) == '{"kept":0,"present_null":null}'


def test_payload_hash_vectors_byte_exact() -> None:
    for vec in _V["payload_hash"]:
        assert crypto.compute_payload_hash(vec["payload"]) == vec["payload_hash"]


def test_chain_hash_vectors_byte_exact() -> None:
    for vec in _V["chain_hash"]:
        assert (
            crypto.compute_chain_hash(
                vec["prev"], vec["payload_hash"], vec["operation_id"], vec["issued_at"]
            )
            == vec["chain_hash"]
        )


def test_ed25519_vector_byte_exact() -> None:
    e = _V["ed25519"]
    msg = crypto.base64url_decode(e["message_b64url"])
    assert crypto.sign_ed25519(_PRIV, msg) == e["signature"]
    assert crypto.verify_ed25519(_PUB, msg, e["signature"]) is True
    assert crypto.verify_ed25519(_PUB, msg + b"x", e["signature"]) is False


def test_sign_eor_vector_byte_exact() -> None:
    s = _V["sign_eor"]
    assert crypto.sign_eor(s["eor"], _PRIV) == s["signature"]


def test_record_vector_roundtrips() -> None:
    rv = _V["record"]
    rec = ShieldActionRecord.model_validate(rv["model"])
    assert canonical.record_signing_string(rec) == rv["signable_string"]
    assert canonical.compute_record_payload_hash(rec) == rv["payload_hash"]
    assert rec.signature == rv["signature"]
    assert canonical.verify_record(rec, _PUB) is True
    assert canonical.derive_chain_hash(crypto.GENESIS_CHAIN_HASH, rec) == rv["derived_chain_hash"]


def test_verdict_vector_roundtrips() -> None:
    vv = _V["verdict"]
    verdict = GovernanceVerdict.model_validate(vv["model"])
    assert canonical.verdict_signing_string(verdict) == vv["signable_string"]
    assert verdict.signature_by_shield == vv["signature_by_shield"]
    assert canonical.verify_verdict(verdict, _PUB) is True
