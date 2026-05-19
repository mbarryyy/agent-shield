"""Cross-impl crypto golden vectors — FROZEN at W1 (C11 / ADR-0007).

``contracts/golden/vectors.json`` was captured byte-exact from Elydora's
reference Python SDK at generation time (see
``packages/shield-sdk/tests/_tools/gen_golden_vectors.py``). This test
re-derives every value with the ``shield_sdk`` port and the frozen §4
signable projection and asserts equality — the cross-impl green gate that
shield-server's 12-step ingest must also satisfy.

Part of the ADR-0007 ritual branch: green only against the v1.1
``shield_sdk`` (lands with / after the SDK feature freeze). The identical
vectors also ship as a self-contained shield-sdk fixture
(``packages/shield-sdk/tests/unit/crypto/golden_vectors.json``); this file
re-verifies the contracts-level copy so the firewall owns a frozen artifact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shield_sdk import canonical, crypto
from shield_sdk.schema import GovernanceVerdict, ShieldActionRecord

_V: dict[str, Any] = json.loads((Path(__file__).parent / "golden" / "vectors.json").read_text())
_PRIV = _V["keypair"]["private_key_b64url"]
_PUB = _V["keypair"]["public_key_b64url"]


def test_golden_vectors_present() -> None:
    assert _V["jcs"] and _V["payload_hash"] and _V["chain_hash"]
    assert _V["x-genesis-chain-hash"] == "A" * 43


def test_keypair_and_genesis() -> None:
    assert crypto.get_public_key_base64url(_PRIV) == _PUB
    assert _V["x-genesis-chain-hash"] == crypto.GENESIS_CHAIN_HASH


def test_jcs_payload_chain_vectors_byte_exact() -> None:
    for vec in _V["jcs"]:
        assert crypto.jcs_canonicalize(vec["input"]) == vec["canonical"]
    for vec in _V["payload_hash"]:
        assert crypto.compute_payload_hash(vec["payload"]) == vec["payload_hash"]
    for vec in _V["chain_hash"]:
        assert (
            crypto.compute_chain_hash(
                vec["prev"], vec["payload_hash"], vec["operation_id"], vec["issued_at"]
            )
            == vec["chain_hash"]
        )


def test_ed25519_and_sign_eor_vectors_byte_exact() -> None:
    e = _V["ed25519"]
    msg = crypto.base64url_decode(e["message_b64url"])
    assert crypto.sign_ed25519(_PRIV, msg) == e["signature"]
    assert crypto.verify_ed25519(_PUB, msg, e["signature"]) is True
    s = _V["sign_eor"]
    assert crypto.sign_eor(s["eor"], _PRIV) == s["signature"]


def test_record_and_verdict_vectors_roundtrip() -> None:
    rv = _V["record"]
    rec = ShieldActionRecord.model_validate(rv["model"])
    assert canonical.record_signing_string(rec) == rv["signable_string"]
    assert rec.payload_hash == rv["payload_hash"]
    assert rec.signature == rv["signature"]
    assert canonical.verify_record(rec, _PUB) is True
    assert canonical.derive_chain_hash(crypto.GENESIS_CHAIN_HASH, rec) == rv["derived_chain_hash"]

    vv = _V["verdict"]
    verdict = GovernanceVerdict.model_validate(vv["model"])
    assert canonical.verdict_signing_string(verdict) == vv["signable_string"]
    assert verdict.signature_by_shield == vv["signature_by_shield"]
    assert canonical.verify_verdict(verdict, _PUB) is True
