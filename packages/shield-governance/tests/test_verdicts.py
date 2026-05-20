"""Async verdict handoff seam; server owns signing and stream publication."""

from __future__ import annotations

import json

from shield_governance.verdicts import (
    AsyncVerdictHandoff,
    verdict_fields,
    verdict_stream_key,
)
from shield_sdk.schema import ActionPayload, Decision, GovernanceVerdict, Phase, ShieldActionRecord


def _rec() -> ShieldActionRecord:
    return ShieldActionRecord(
        run_id="run-1",
        phase=Phase.POST_EXEC,
        payload=ActionPayload(tool_name="send_money", tool_args={"recipient": "A", "amount": 1}),
    )


def test_server_verdict_stream_key_helper() -> None:
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


def test_async_verdict_handoff_is_unsigned_and_server_ready() -> None:
    rec = _rec()
    verdict = GovernanceVerdict(
        decision=Decision.ALERT,
        correlation_id=rec.correlation_id,
        record_id=rec.record_id,
        run_id=rec.run_id,
        risk_score=0.2,
    )
    handoff = AsyncVerdictHandoff.from_record(rec, verdict)
    assert handoff.workflow_id == rec.workflow_id
    assert handoff.phase == "post_exec"
    assert handoff.verdict.signature_by_shield is None
    fields = handoff.server_fields()
    assert fields["record_id"] == rec.record_id
    assert fields["run_id"] == rec.run_id
    assert fields["phase"] == "post_exec"
    assert json.loads(fields["verdict"])["signature_by_shield"] is None


def test_governance_verdict_module_has_no_direct_stream_publisher() -> None:
    import shield_governance.verdicts as verdicts

    assert not hasattr(verdicts, "RedisVerdictTransport")
    assert not hasattr(verdicts, "VerdictPublisher")
