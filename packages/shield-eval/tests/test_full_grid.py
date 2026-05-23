"""Full banking grid artifact coverage for Research #4."""

from __future__ import annotations

import json

from shield_eval import run_ab


def test_run_ab_full_mock_writes_144_cell_summary_and_case_rows(tmp_path) -> None:  # type: ignore[no-untyped-def]
    summary_path = tmp_path / "full_grid_summary.json"
    cases_path = tmp_path / "full_grid_cases.json"

    rc = run_ab.main(
        [
            "--full",
            "--suite",
            "banking",
            "--attack",
            "important_instructions",
            "--metrics-out",
            str(summary_path),
            "--cases-out",
            str(cases_path),
        ]
    )

    assert rc == 0
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    assert summary["schema_version"] == "eval-full-grid.v1"
    assert summary["run_label"] == "MOCKED"
    assert summary["backend"] == "mock"
    assert summary["grid"]["user_task_count"] == 16
    assert summary["grid"]["injection_task_count"] == 9
    assert summary["grid"]["security_cell_count"] == 144
    assert summary["grid"]["case_row_count"] == 144 * 5
    assert set(summary["arms"]) == {"A0", "A0b", "A1", "A2", "A3"}
    assert summary["values"]["asr"]["label"] == "MOCKED"
    assert summary["values"]["utility_retention"]["label"] == "MOCKED"
    assert summary["values"]["detection_rate"]["label"] == "MOCKED"

    assert len(cases) == 144 * 5
    first = cases[0]
    assert {
        "user_task_id",
        "injection_task_id",
        "attack_variant",
        "arm",
        "backend",
        "evidence_label",
        "security",
        "utility",
        "decision",
    }.issubset(first)
    assert {row["backend"] for row in cases} == {"mock"}
    assert {row["evidence_label"] for row in cases} == {"MOCKED"}
    assert {row["arm"] for row in cases} == {"A0", "A0b", "A1", "A2", "A3"}


def test_full_grid_http_backend_is_separated_and_unexecuted(tmp_path) -> None:  # type: ignore[no-untyped-def]
    summary_path = tmp_path / "http_grid_summary.json"
    cases_path = tmp_path / "http_grid_cases.json"

    rc = run_ab.main(
        [
            "--full",
            "--suite",
            "banking",
            "--backend",
            "http",
            "--metrics-out",
            str(summary_path),
            "--cases-out",
            str(cases_path),
        ]
    )

    assert rc == 0
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    assert summary["backend"] == "http"
    assert summary["run_label"] == "SKIPPED"
    assert summary["skip_reason"] == "HTTP_FULL_GRID_NOT_EXECUTED_IN_CI"
    assert {row["backend"] for row in cases} == {"http"}
    assert {row["evidence_label"] for row in cases} == {"SKIPPED"}
