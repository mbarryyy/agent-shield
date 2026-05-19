"""shield:verdicts producer (PR-S3 tolerant seam)."""

from __future__ import annotations

import json

import pytest
from shield_governance.verdicts import (
    InMemoryVerdictTransport,
    VerdictPublisher,
    verdict_fields,
    verdict_stream_key,
)
from shield_sdk.schema import Decision, GovernanceVerdict


def test_stream_key() -> None:
    assert verdict_stream_key("banking") == "shield:verdicts:banking"
    assert verdict_stream_key("banking", prefix="x") == "x:banking"


def test_verdict_fields_locked_8_field_envelope() -> None:
    v = GovernanceVerdict(
        decision=Decision.BLOCK,
        correlation_id="c9",
        record_id="r9",
        run_id="run-9",
        risk_score=0.8,
    )
    f = verdict_fields(v, phase="pre_exec")
    # server PR-S3 LOCKED FLAT 8-field envelope, all str values.
    assert set(f) == {
        "verdict_id",
        "record_id",
        "correlation_id",
        "run_id",
        "decision",
        "risk_score",
        "phase",
        "verdict",
    }
    assert all(isinstance(val, str) for val in f.values())
    assert f["decision"] == "BLOCK"
    assert f["correlation_id"] == "c9"
    assert f["record_id"] == "r9"
    assert f["run_id"] == "run-9"
    assert f["risk_score"] == "0.8"
    assert f["phase"] == "pre_exec"
    back = GovernanceVerdict.model_validate_json(f["verdict"])
    assert back.decision is Decision.BLOCK and back.correlation_id == "c9"


@pytest.mark.asyncio
async def test_publisher_inmemory() -> None:
    t = InMemoryVerdictTransport()
    pub = VerdictPublisher(t)
    v = GovernanceVerdict(decision=Decision.PASS, correlation_id="c1", run_id="r1")
    mid = await pub.publish("banking", v, phase="post_exec")
    assert mid == "1-0"
    assert len(t.published) == 1
    stream, fields = t.published[0]
    assert stream == "shield:verdicts:banking"
    assert fields["phase"] == "post_exec"
    assert fields["run_id"] == "r1"
    assert json.loads(fields["verdict"])["correlation_id"] == "c1"
