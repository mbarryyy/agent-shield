from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
_ATTACK_MANIFEST = (
    _ROOT
    / "packages"
    / "shield-eval"
    / "src"
    / "shield_eval"
    / "scenarios"
    / "benchmark_20pct_20260525.json"
)
_BENIGN_MANIFEST = _ATTACK_MANIFEST.with_name("benchmark_20pct_benign_20260525.json")
_SCRIPT = _ROOT / "scripts" / "benchmark" / "run_20pct_provider.py"

assert _SCRIPT.exists(), "Phase 4 provider runner script is missing"
_SPEC = importlib.util.spec_from_file_location("run_20pct_provider", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

CostGuard = _MODULE.CostGuard
ProviderErrorTracker = _MODULE.ProviderErrorTracker
build_benign_case_row = _MODULE.build_benign_case_row
expand_attack_manifest_cases = _MODULE.expand_attack_manifest_cases
normalize_reused_case_row = _MODULE.normalize_reused_case_row
summarize_attack = _MODULE._summarize_attack
summarize_benign = _MODULE._summarize_benign


class _FakeOutcome:
    decisions = {"corr-1": "BLOCK"}
    decision_sources = {"corr-1": "governance"}
    latencies_ms = [12.5]
    per_guardian = [
        {
            "guardian": "evaluator",
            "served_via": "cloud",
            "model_id": "claude-sonnet-4-6",
            "prompt_tokens": 10,
            "completion_tokens": 4,
            "cost_usd": 0.001,
        }
    ]
    prompt_tokens = 20
    completion_tokens = 5
    cost_usd = 0.002
    model_id = "claude-haiku-4-5-20251001"
    utility = {("user_task_0", ""): True}


def test_attack_manifest_expansion_excludes_reused_rows_from_execution() -> None:
    manifest = json.loads(_ATTACK_MANIFEST.read_text(encoding="utf-8"))

    executable, reused = expand_attack_manifest_cases(manifest)

    assert len(executable) == 288
    assert len(reused) == 2
    assert {row["sample_index"] for row in executable} == {0, 1}
    assert {
        (row["user_task_id"], row["injection_task_id"], row["arm"], row["sample_index"])
        for row in reused
    } == {
        ("user_task_2", "injection_task_4", "A2", 0),
        ("user_task_2", "injection_task_6", "A2", 0),
    }
    assert all(row.get("reused_from") for row in reused)
    assert not any(
        row["user_task_id"] == "user_task_2"
        and row["injection_task_id"] == "injection_task_4"
        and row["arm"] == "A2"
        and row["sample_index"] == 0
        for row in executable
    )


def test_normalized_reused_rows_are_not_counted_as_new_provider_cost() -> None:
    manifest = json.loads(_ATTACK_MANIFEST.read_text(encoding="utf-8"))
    _, reused = expand_attack_manifest_cases(manifest)

    pass_row = normalize_reused_case_row(reused[0])
    block_row = normalize_reused_case_row(reused[1])

    assert pass_row["api_call_status"] == "REUSED"
    assert pass_row["new_actual_cost_usd"] == 0.0
    assert pass_row["reused_from"].startswith("/private/tmp/")
    assert pass_row["errors"] == []
    assert pass_row["sample_index"] == 0
    assert pass_row["per_guardian"] == []
    assert pass_row["security"] is False
    assert block_row["security"] is True


def test_benign_case_row_marks_false_positive_without_injection_id() -> None:
    manifest = json.loads(_BENIGN_MANIFEST.read_text(encoding="utf-8"))
    case = manifest["cases"][0]

    row = build_benign_case_row(
        suite=manifest["suite"],
        case=case,
        evidence_label="MEASURED-REAL-MODEL",
        outcome=_FakeOutcome(),
        backend="real",
        errors=[],
    )

    assert row["suite"] == "agentdojo_banking_without_injections"
    assert row["benign_marker"] is True
    assert "injection_task_id" not in row
    assert row["api_call_status"] == "EXECUTED"
    assert row["decision"] == "BLOCK"
    assert row["false_positive"] is True
    assert row["utility"] is True
    assert row["prompt_tokens"] == 30
    assert row["completion_tokens"] == 9
    assert row["cost_usd"] == pytest.approx(0.003)
    assert row["errors"] == []


def test_cost_guard_ignores_reused_cost_and_stops_on_budget_or_spike() -> None:
    guard = CostGuard(cap_usd=0.25, per_case_estimate_usd=0.05)

    guard.record_row({"api_call_status": "REUSED", "cost_usd": 2.0})
    assert guard.actual_cost_usd == 0.0

    guard.record_row({"api_call_status": "EXECUTED", "cost_usd": 0.04})
    assert guard.actual_cost_usd == pytest.approx(0.04)
    assert guard.stop_reason is None

    guard.record_row({"api_call_status": "EXECUTED", "cost_usd": 0.16})
    assert guard.stop_reason == "SINGLE_SCENARIO_COST_SPIKE"

    capped = CostGuard(cap_usd=0.10, per_case_estimate_usd=0.05)
    capped.record_row({"api_call_status": "EXECUTED", "cost_usd": 0.11})
    assert capped.stop_reason == "APPROVED_CAP_EXCEEDED"


def test_provider_error_tracker_stops_on_repeated_provider_errors() -> None:
    tracker = ProviderErrorTracker(max_errors=3)

    assert tracker.record_errors([]) is None
    assert tracker.record_errors([{"error_class": "RateLimitError"}]) is None
    assert tracker.record_errors([{"error_class": "RateLimitError"}]) is None
    assert tracker.record_errors([{"error_class": "APIConnectionError"}]) == (
        "REPEATED_PROVIDER_ERRORS"
    )


def test_subrun_summaries_use_subrun_cost_not_global_guard_total() -> None:
    guard = CostGuard(cap_usd=25.0, per_case_estimate_usd=0.056)
    guard.actual_cost_usd = 0.30
    benign_summary = summarize_benign(
        manifest={"manifest_id": "benign", "suite": "agentdojo_banking_without_injections"},
        cases=[
            {
                "api_call_status": "EXECUTED",
                "false_positive": False,
                "utility": True,
                "prompt_tokens": 1,
                "completion_tokens": 2,
                "new_actual_cost_usd": 0.10,
            }
        ],
        guard=guard,
        stop_reason=None,
    )
    attack_summary = summarize_attack(
        manifest={
            "manifest_id": "attack",
            "suite": "agentdojo_banking_security",
            "arms": ["A2"],
        },
        cases=[
            {
                "suite": "agentdojo_banking_security",
                "user_task_id": "user_task_0",
                "injection_task_id": "injection_task_0",
                "arm": "A2",
                "security": True,
                "utility": True,
                "decision": "PASS",
                "latency_ms": 1.0,
                "prompt_tokens": 3,
                "completion_tokens": 4,
                "cost_usd": 0.20,
                "new_actual_cost_usd": 0.20,
                "api_call_status": "EXECUTED",
                "evidence_label": "MEASURED-REAL-MODEL",
                "errors": [],
            }
        ],
        guard=guard,
        stop_reason=None,
    )

    assert benign_summary["actual_cost_usd"] == pytest.approx(0.10)
    assert benign_summary["cost_guard"]["actual_cost_usd"] == pytest.approx(0.30)
    assert attack_summary["new_actual_cost_usd"] == pytest.approx(0.20)
    assert attack_summary["cost_guard"]["actual_cost_usd"] == pytest.approx(0.30)
