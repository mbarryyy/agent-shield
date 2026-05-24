"""Guardian-evidence adapter tests without live provider calls."""

from __future__ import annotations

from shield_eval import evidence_adapter


def test_guardian_evidence_adapter_preserves_fields_and_marks_missing_agentic_metrics() -> None:
    report = evidence_adapter.adapt_guardian_evidence_rows(
        [
            {
                "record_id": "r-provider",
                "correlation_id": "c-provider",
                "guardian": "evaluator",
                "decision": "BLOCK",
                "reasons": ["evaluator.hallucination"],
                "model_id": "claude-haiku-4-5-20251001",
                "served_via": "cloud",
                "prompt_tokens": 120,
                "completion_tokens": 40,
                "latency_ms": 87.5,
                "cost_usd": 0.0012,
            }
        ],
        evidence_label="PROVIDER_BACKED",
    )

    assert report["schema_version"] == "guardian-evidence-adapter.v1"
    assert report["source_evidence_label"] == "PROVIDER_BACKED"
    assert report["agentic_metric_label"] == "SKIPPED"
    assert report["rows"][0]["model_id"] == "claude-haiku-4-5-20251001"
    assert report["rows"][0]["prompt_tokens"] == 120
    assert report["rows"][0]["completion_tokens"] == 40
    assert report["rows"][0]["cost_usd"] == 0.0012
    assert "trace_id" in report["missing_fields"]
    assert "tools_called" in report["missing_fields"]
    assert "self_correction_state" in report["missing_fields"]
    assert "grounded_reason_count" in report["missing_fields"]


def test_guardian_evidence_adapter_marks_measured_when_required_trace_fields_exist() -> None:
    report = evidence_adapter.adapt_guardian_evidence_rows(
        [
            {
                "record_id": "r-provider",
                "correlation_id": "c-provider",
                "guardian": "supervisor",
                "decision": "BLOCK",
                "reasons": ["supervisor.arbitrated"],
                "model_id": "claude-haiku-4-5-20251001",
                "served_via": "cloud",
                "prompt_tokens": 200,
                "completion_tokens": 60,
                "latency_ms": 95.0,
                "cost_usd": 0.0018,
                "trace_id": "trace-provider",
                "case_id": "user_task_2_x_injection_task_6",
                "arm": "A2",
                "attack_succeeded": False,
                "expected_tools": ["query_policy"],
                "tools_called": ["query_policy"],
                "expected_decision": "BLOCK",
                "supervisor_decision": "BLOCK",
                "self_correction_state": "not_needed",
                "grounded_reason_count": 1,
                "total_reason_count": 1,
            }
        ],
        evidence_label="PROVIDER_BACKED",
    )

    assert report["agentic_metric_label"] == "MEASURED"
    assert report["missing_fields"] == []
    assert report["rows"][0]["trace_id"] == "trace-provider"
