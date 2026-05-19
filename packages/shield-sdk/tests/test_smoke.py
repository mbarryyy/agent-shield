"""Smoke: the frozen §4 v1.1 schema imports, instantiates, and round-trips.

Proves server / governance / eval / console can build against
``shield_sdk.schema`` (the single source of truth). Deep crypto/schema
property + golden-vector coverage lives in ``tests/unit/crypto/``.
"""

from __future__ import annotations

import shield_sdk.crypto as crypto
from shield_sdk import schema
from shield_sdk.sdk import ShieldClient


def test_genesis_chain_hash_is_43_char_no_pad() -> None:
    assert crypto.GENESIS_CHAIN_HASH == "A" * 43
    assert "=" not in crypto.GENESIS_CHAIN_HASH


def test_action_record_roundtrip() -> None:
    rec = schema.ShieldActionRecord(phase=schema.Phase.PRE_EXEC, run_id="r1")
    assert rec.shield_version == "1.1"
    assert rec.phase is schema.Phase.PRE_EXEC
    again = schema.ShieldActionRecord.model_validate(rec.model_dump())
    assert again.run_id == "r1"
    assert again.prev_chain_hash == crypto.GENESIS_CHAIN_HASH


def test_verdict_has_v11_cost_fields() -> None:
    v = schema.GovernanceVerdict(
        decision=schema.Decision.REWRITE,
        correlation_id="c1",
        reasons=[
            schema.VerdictReason(
                agent=schema.Guardian.DEFENDER,
                label="X",
                served_via=schema.ServedVia.LOCAL,
            )
        ],
    )
    assert v.decision is schema.Decision.REWRITE
    assert v.reasons[0].served_via is schema.ServedVia.LOCAL
    assert v.reasons[0].model_id is None  # v1.1 cost field, present + optional
    assert v.obligations.prevented_loss is None  # v1.1 cost field


def test_client_constructs() -> None:
    assert ShieldClient("http://localhost:8000").base_url == "http://localhost:8000"
