"""Real-provider slice artifact schema without live provider calls."""

from __future__ import annotations

import pytest
from shield_eval import metrics, provider_slice


def test_haiku_slice_profile_records_model_backed_guardians() -> None:
    profile = provider_slice.build_haiku_provider_slice_profile()

    assert profile["model_router_profile"] == "provider-slice-haiku"
    assert profile["worker_model"] == "claude-haiku-4-5-20251001"
    guardians = {row["guardian"]: row for row in profile["guardian_models"]}
    assert guardians["defender"]["model_id"] == "local-deterministic"
    assert guardians["defender"]["served_via"] == "local"
    for guardian in ("evaluator", "supervisor", "auditor"):
        assert guardians[guardian]["model_id"] == "claude-haiku-4-5-20251001"
        assert guardians[guardian]["served_via"] == "cloud"

    artifact = metrics.build_provider_slice_artifact(
        user_task_id="user_task_2",
        injection_task_id="injection_task_6",
        attack_variant="important_instructions",
        provider="anthropic",
        model_router_profile=profile["model_router_profile"],
        hard_cap_usd=3.0,
        estimated_cost_usd=0.03,
        api_call_status="SKIPPED",
        skip_reason="ESTIMATE_ONLY_AWAITING_USER_APPROVAL",
    )
    artifact_guardians = {
        row["guardian"]: row for row in artifact["arms"]["A2"]["per_guardian"]
    }
    for guardian in ("evaluator", "supervisor", "auditor"):
        assert artifact_guardians[guardian]["model_id"] == "claude-haiku-4-5-20251001"


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
    required_guardian_fields = {
        "guardian",
        "decision",
        "model_id",
        "served_via",
        "prompt_tokens",
        "completion_tokens",
        "latency_ms",
        "cost_usd",
        "reasons",
    }
    assert all(set(g) == required_guardian_fields for g in guardians)


def test_provider_slice_skipped_artifact_drops_measured_totals() -> None:
    artifact = metrics.build_provider_slice_artifact(
        user_task_id="user_task_2",
        injection_task_id="injection_task_6",
        attack_variant="important_instructions",
        provider="anthropic",
        model_router_profile="cloud",
        hard_cap_usd=5.0,
        estimated_cost_usd=5.25,
        api_call_status="SKIPPED",
        actual_cost_usd=0.03,
        a0_latency_ms=1200.0,
        a2_latency_ms=1800.0,
        prevented_loss_usd=30_000.0,
        skip_reason="REAL_EVAL_SKIPPED_BUDGET_GUARD",
    )

    assert artifact["evidence_label"] == "SKIPPED"
    assert artifact["budget"]["actual_cost_usd"] == 0.0
    assert artifact["arms"]["A0"]["latency_ms"] == 0.0
    assert artifact["arms"]["A2"]["latency_ms"] == 0.0
    assert artifact["totals"]["latency_ms"] == 0.0
    assert artifact["totals"]["cost_usd"] == 0.0
    assert artifact["totals"]["prevented_loss_usd"] == 0.0


def test_provider_slice_executed_requires_explicit_guardian_rows() -> None:
    with pytest.raises(ValueError, match="explicit per_guardian"):
        metrics.build_provider_slice_artifact(
            user_task_id="user_task_2",
            injection_task_id="injection_task_6",
            attack_variant="important_instructions",
            provider="anthropic",
            model_router_profile="cloud",
            hard_cap_usd=5.0,
            estimated_cost_usd=0.04,
            actual_cost_usd=0.03,
            api_call_status="EXECUTED",
        )


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
    assert all(
        set(g)
        == {
            "guardian",
            "decision",
            "model_id",
            "served_via",
            "prompt_tokens",
            "completion_tokens",
            "latency_ms",
            "cost_usd",
            "reasons",
        }
        for g in artifact["arms"]["A2"]["per_guardian"]
    )
