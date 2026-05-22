"""Real-provider slice artifact schema without live provider calls."""

from __future__ import annotations

from shield_eval import metrics


def test_provider_slice_skipped_artifact_matches_required_schema() -> None:
    artifact = metrics.build_provider_slice_artifact(
        user_task_id="user_task_2",
        injection_task_id="injection_task_6",
        attack_variant="important_instructions",
        provider="anthropic",
        model_router_profile="cloud",
        hard_cap_usd=5.0,
        estimated_cost_usd=5.25,
        api_call_status="SKIPPED",
        skip_reason="REAL_EVAL_SKIPPED_BUDGET_GUARD",
    )

    assert artifact["schema_version"] == "eval-slice-v1"
    assert artifact["slice_id"] == "user_task_2_x_injection_task_6"
    assert artifact["backend"] == "real"
    assert artifact["provider"] == "anthropic"
    assert artifact["model_router_profile"] == "cloud"
    assert artifact["api_call_status"] == "SKIPPED"
    assert artifact["evidence_label"] == "SKIPPED"
    assert artifact["skip_reason"] == "REAL_EVAL_SKIPPED_BUDGET_GUARD"
    assert artifact["budget"]["hard_cap_usd"] == 5.0
    assert artifact["budget"]["estimated_cost_usd"] == 5.25
    assert artifact["budget"]["actual_cost_usd"] == 0.0
    assert artifact["arms"]["A0"]["per_guardian"] == []
    guardians = artifact["arms"]["A2"]["per_guardian"]
    assert [g["guardian"] for g in guardians] == [
        "defender",
        "evaluator",
        "supervisor",
        "auditor",
    ]
    assert all(g["cost_usd"] == 0.0 for g in guardians)


def test_provider_slice_provider_backed_fixture_schema_records_usage() -> None:
    artifact = metrics.build_provider_slice_artifact(
        user_task_id="user_task_2",
        injection_task_id="injection_task_6",
        attack_variant="important_instructions",
        provider="anthropic",
        model_router_profile="cloud",
        hard_cap_usd=5.0,
        estimated_cost_usd=0.04,
        actual_cost_usd=0.03,
        api_call_status="EXECUTED",
        a0_latency_ms=1200.0,
        a2_latency_ms=1800.0,
        prevented_loss_usd=30_000.0,
        per_guardian=[
            {
                "guardian": "defender",
                "decision": "PASS",
                "model_id": "local-deterministic",
                "served_via": "local",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "latency_ms": 2.0,
                "cost_usd": 0.0,
                "reasons": [],
            },
            {
                "guardian": "evaluator",
                "decision": "BLOCK",
                "model_id": "claude-haiku-4-5-20251001",
                "served_via": "cloud",
                "prompt_tokens": 1000,
                "completion_tokens": 200,
                "latency_ms": 600.0,
                "cost_usd": 0.002,
                "reasons": ["fixture only"],
            },
        ],
    )

    assert artifact["api_call_status"] == "EXECUTED"
    assert artifact["evidence_label"] == "PROVIDER_BACKED"
    assert "skip_reason" not in artifact
    assert artifact["arms"]["A2"]["latency_ms"] == 1800.0
    assert artifact["totals"]["prompt_tokens"] == 1000
    assert artifact["totals"]["completion_tokens"] == 200
    assert artifact["totals"]["latency_ms"] == 3000.0
    assert artifact["totals"]["cost_usd"] == 0.03
    assert artifact["totals"]["prevented_loss_usd"] == 30_000.0
