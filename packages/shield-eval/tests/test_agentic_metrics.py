"""Fixture-only agentic metric shell for Track C/D.

These tests define the local fixture contract. They do not create measured,
provider-backed benchmark evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

from shield_eval.agentic_metrics import (
    AgenticCaseRow,
    ArbitrationTrace,
    ReasonGroundingTrace,
    SelfCorrectionTrace,
    ToolSelectionTrace,
    compute_agentic_metric_report,
)


def test_agentic_metrics_compute_fixture_gain_and_trace_quality() -> None:
    report = compute_agentic_metric_report(
        case_rows=[
            AgenticCaseRow(case_id="semantic-split", arm="A3", attack_succeeded=True),
            AgenticCaseRow(case_id="semantic-split", arm="A2", attack_succeeded=False),
            AgenticCaseRow(case_id="benign-context", arm="A3", attack_succeeded=False),
            AgenticCaseRow(case_id="benign-context", arm="A2", attack_succeeded=False),
            AgenticCaseRow(case_id="regression", arm="A3", attack_succeeded=False),
            AgenticCaseRow(case_id="regression", arm="A2", attack_succeeded=True),
        ],
        tool_traces=[
            ToolSelectionTrace(
                case_id="semantic-split",
                expected_tools={"eval_invariant_policies", "behavior_drift"},
                tools_called={"eval_invariant_policies"},
            ),
            ToolSelectionTrace(
                case_id="benign-context",
                expected_tools={"inspect_provenance"},
                tools_called={"inspect_provenance", "behavior_drift"},
            ),
        ],
        arbitration_traces=[
            ArbitrationTrace(
                case_id="semantic-split",
                expected_decision="BLOCK",
                supervisor_decision="BLOCK",
            ),
            ArbitrationTrace(
                case_id="benign-context",
                expected_decision="PASS",
                supervisor_decision="BLOCK",
            ),
            ArbitrationTrace(
                case_id="regression",
                expected_decision="BLOCK",
                supervisor_decision="PASS",
            ),
        ],
        self_correction_traces=[
            SelfCorrectionTrace(case_id="semantic-split", before_correct=False, after_correct=True),
            SelfCorrectionTrace(case_id="regression", before_correct=True, after_correct=False),
        ],
        reason_grounding_traces=[
            ReasonGroundingTrace(case_id="semantic-split", grounded_reasons=2, total_reasons=3),
            ReasonGroundingTrace(case_id="benign-context", grounded_reasons=1, total_reasons=1),
        ],
    )

    assert report["schema_version"] == "agentic-metrics-fixture.v1"
    assert report["evidence_label"] == "FIXTURE"
    assert report["measured_provider_evidence"] is False
    assert report["metrics"]["AGD"]["value"] == 0.0
    assert report["metrics"]["DRC"]["value"] == 1.0
    assert report["metrics"]["TSA"]["precision"] == 2 / 3
    assert report["metrics"]["TSA"]["recall"] == 2 / 3
    assert report["metrics"]["ARQ"]["accuracy"] == 1 / 3
    assert report["metrics"]["ARQ"]["over_conservative_errors"] == 1
    assert report["metrics"]["ARQ"]["permissive_errors"] == 1
    assert report["metrics"]["SCE"]["wrong_to_right_rate"] == 0.5
    assert report["metrics"]["SCE"]["right_to_wrong_regression_rate"] == 0.5
    assert report["metrics"]["RGF"]["value"] == 0.75


def test_agentic_delta_scenarios_are_supplementary_and_schema_valid() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "shield_eval"
        / "scenarios"
        / "agentic_delta.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    scenarios = payload["scenarios"]

    assert payload["schema_version"] == "agentic-delta-scenarios.v1"
    assert payload["evidence_label"] == "SUPPLEMENTARY_FIXTURE"
    assert payload["standard_benchmark"] is False
    assert 15 <= len(scenarios) <= 30

    required = {
        "scenario_id",
        "benign_task_context",
        "injected_or_malicious_behavior",
        "deterministic_rules_may_miss_because",
        "expected_guardian_signals",
        "expected_outcome",
        "attack_category",
        "tsa_expected_tools",
    }
    categories = {scenario["attack_category"] for scenario in scenarios}
    assert {
        "semantic_structuring",
        "long_window_distribution",
        "account_takeover_chain",
        "context_dependent",
        "unseen_pattern",
    }.issubset(categories)

    for scenario in scenarios:
        assert required.issubset(scenario)
        assert scenario["scenario_id"].startswith("agentic_delta_")
        assert scenario["expected_outcome"] in {"BLOCK", "ESCALATE", "PASS"}
        assert scenario["tsa_expected_tools"]
        text = json.dumps(scenario).lower()
        assert "api_key" not in text
        assert "password" not in text
