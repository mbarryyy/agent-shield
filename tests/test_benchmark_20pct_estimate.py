from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
_MANIFEST = (
    _ROOT
    / "packages"
    / "shield-eval"
    / "src"
    / "shield_eval"
    / "scenarios"
    / "benchmark_20pct_20260525.json"
)
_BENIGN_MANIFEST = _MANIFEST.with_name("benchmark_20pct_benign_20260525.json")
_SCRIPT = _ROOT / "scripts" / "benchmark" / "estimate_20pct.py"
_SPEC = importlib.util.spec_from_file_location("estimate_20pct", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
build_estimate = _MODULE.build_estimate
build_benign_estimate = _MODULE.build_benign_estimate
build_combined_summary = _MODULE.build_combined_summary


def test_20pct_manifest_is_frozen_stratified_and_marks_reused_rows() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    pairs = manifest["scenario_pairs"]

    assert len(pairs) == 29
    assert len(manifest["arms"]) == 5
    assert manifest["samples_per_pair"] == 2
    assert len(pairs) * len(manifest["arms"]) * manifest["samples_per_pair"] == 290
    assert {pair["user_task_id"] for pair in pairs} >= {f"user_task_{i}" for i in range(16)}
    assert {pair["injection_task_id"] for pair in pairs} >= {
        f"injection_task_{i}" for i in range(9)
    }

    reused = manifest["reused_rows"]
    assert len(reused) == 2
    assert {
        (row["user_task_id"], row["injection_task_id"], row["arm"])
        for row in reused
    } == {
        ("user_task_2", "injection_task_4", "A2"),
        ("user_task_2", "injection_task_6", "A2"),
    }
    assert all(row["reused_from"].startswith("/private/tmp/") for row in reused)


def test_20pct_estimate_subtracts_reused_rows_without_provider_calls() -> None:
    estimate = build_estimate(_MANIFEST)

    assert estimate["api_call_status"] == "SKIPPED"
    assert estimate["full_manifest_case_count"] == 290
    assert estimate["reused_case_count"] == 2
    assert estimate["to_be_executed_case_count"] == 288
    assert estimate["full_manifest_conservative_estimate_usd"] == pytest.approx(16.24)
    assert estimate["conservative_estimate_usd"] == pytest.approx(16.128)
    assert estimate["historical_utilization_rate"] == pytest.approx(0.190632)
    assert estimate["mean_prediction_usd"] == pytest.approx(3.074508)
    assert estimate["recommended_hard_cap_usd"] == 20.0
    assert estimate["benign_subset_add_on"]["included_in_attack_arm_case_budget"] is False


def test_benign_manifest_covers_all_users_with_five_arms_one_sample() -> None:
    manifest = json.loads(_BENIGN_MANIFEST.read_text(encoding="utf-8"))
    rows = manifest["cases"]

    assert manifest["suite"] == "agentdojo_banking_without_injections"
    assert len(rows) == 80
    assert manifest["samples_per_user_task"] == 1
    assert {row["user_task_id"] for row in rows} == {f"user_task_{i}" for i in range(16)}
    assert {row["arm"] for row in rows} == {"A0", "A0b", "A1", "A2", "A3"}
    assert all(row["benign_marker"] is True for row in rows)
    assert all("injection_task_id" not in row for row in rows)


def test_benign_and_combined_estimates_are_no_provider_and_add_up() -> None:
    attack = build_estimate(_MANIFEST)
    benign = build_benign_estimate(_BENIGN_MANIFEST)
    combined = build_combined_summary(attack, benign)

    assert benign["api_call_status"] == "SKIPPED"
    assert benign["full_manifest_case_count"] == 80
    assert benign["reused_case_count"] == 0
    assert benign["to_be_executed_case_count"] == 80
    assert benign["conservative_estimate_usd"] == pytest.approx(4.48)
    assert benign["mean_prediction_usd"] == pytest.approx(0.85403)

    assert combined["attack_subset"]["to_be_executed_case_count"] == 288
    assert combined["benign_add_on"]["to_be_executed_case_count"] == 80
    assert combined["combined_conservative_estimate_usd"] == pytest.approx(20.608)
    assert combined["combined_mean_prediction_usd"] == pytest.approx(3.928538)
    assert combined["recommended_combined_cap_usd"] == 25.0
