"""W0 smoke: the §4 schema stub is importable and the models instantiate.

This proves server/governance/eval/console can compile against shield_sdk.schema
on day 1. Real crypto/schema property tests arrive at W1 (≥90% coverage gate).
"""

from __future__ import annotations

import shield_sdk.crypto as crypto
from shield_sdk import schema
from shield_sdk.sdk import ShieldClient


def test_genesis_chain_hash_is_43_char_no_pad() -> None:
    assert crypto.GENESIS_CHAIN_HASH == "A" * 43
    assert "=" not in crypto.GENESIS_CHAIN_HASH


def test_action_record_roundtrip() -> None:
    rec = schema.ShieldActionRecord(
        phase=schema.Phase.PRE_EXEC,
        correlation_id="c1",
        run_id="r1",
        payload_hash="h",
    )
    assert rec.shield_version == "1.1"
    assert rec.phase is schema.Phase.PRE_EXEC
    assert schema.ShieldActionRecord.model_validate(rec.model_dump()).run_id == "r1"


def test_verdict_has_v11_cost_fields() -> None:
    v = schema.GovernanceVerdict(
        decision=schema.Decision.REWRITE,
        correlation_id="c1",
        reasons=[schema.VerdictReason(code="X", served_via=schema.ServedVia.LOCAL)],
    )
    assert v.decision is schema.Decision.REWRITE
    assert v.reasons[0].served_via is schema.ServedVia.LOCAL
    assert v.obligations.prevented_loss is None  # present in v1.1 baseline


def test_client_constructs() -> None:
    assert ShieldClient("http://localhost:8000").base_url == "http://localhost:8000"
