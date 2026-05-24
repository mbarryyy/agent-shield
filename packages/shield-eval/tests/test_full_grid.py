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


def test_full_mock_a2_cases_emit_profile_aware_guardian_rows(tmp_path) -> None:  # type: ignore[no-untyped-def]
    summary_path = tmp_path / "mock_cloud_summary.json"
    cases_path = tmp_path / "mock_cloud_cases.json"

    rc = run_ab.main(
        [
            "--full",
            "--backend",
            "mock",
            "--suite",
            "banking",
            "--arms",
            "A0,A2",
            "--user-task",
            "user_task_2",
            "--injection-task",
            "injection_task_6",
            "--attack",
            "important_instructions",
            "--model-router-profile",
            "cloud",
            "--metrics-out",
            str(summary_path),
            "--cases-out",
            str(cases_path),
        ]
    )

    assert rc == 0
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    a2 = next(row for row in cases if row["arm"] == "A2")
    guardians = {row["guardian"]: row for row in a2["per_guardian"]}

    assert guardians["defender"]["model_id"] == "local-deterministic"
    assert guardians["defender"]["served_via"] == "local"
    assert guardians["defender"]["decision"] == "BLOCK"
    assert guardians["evaluator"]["model_id"] == "claude-sonnet-4"
    assert guardians["evaluator"]["served_via"] == "cloud"
    assert guardians["evaluator"]["decision"] == "BLOCK"
    assert all(
        {
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
        == set(row)
        for row in a2["per_guardian"]
    )


def test_full_mock_guardian_rows_follow_haiku_profile(tmp_path) -> None:  # type: ignore[no-untyped-def]
    cases_path = tmp_path / "mock_haiku_cases.json"

    rc = run_ab.main(
        [
            "--full",
            "--backend",
            "mock",
            "--suite",
            "banking",
            "--arms",
            "A2",
            "--user-task",
            "user_task_2",
            "--injection-task",
            "injection_task_6",
            "--model-router-profile",
            "provider-slice-haiku",
            "--cases-out",
            str(cases_path),
        ]
    )

    assert rc == 0
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    a2 = cases[0]
    model_backed = [
        row
        for row in a2["per_guardian"]
        if row["guardian"] in {"evaluator", "supervisor", "auditor"}
    ]
    assert model_backed
    assert {row["model_id"] for row in model_backed} == {"claude-haiku-4-5-20251001"}


def test_full_grid_http_backend_runs_measured_via_real_server_transport(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """F1 (Phase F, EM-2): the http backend drives the real shield decide()
    in-process via decide.real_server_transport() and produces MEASURED
    per-case rows from the AgentDojo oracle — NOT a fabricated template.

    Scope-capped to one user_task × one injection_task × two arms so the
    test stays under a few seconds while still exercising the real ASGI
    transport + sdk ShieldClient round-trip end-to-end.
    """
    summary_path = tmp_path / "http_grid_summary.json"
    cases_path = tmp_path / "http_grid_cases.json"

    rc = run_ab.main(
        [
            "--full",
            "--suite",
            "banking",
            "--backend",
            "http",
            "--arms",
            "A0,A2",
            "--user-task",
            "user_task_2",
            "--injection-task",
            "injection_task_6",
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
    assert summary["run_label"] == "MEASURED-INLINE-DECIDE"
    assert "skip_reason" not in summary  # measured path, not skipped
    assert {row["backend"] for row in cases} == {"http"}
    assert {row["evidence_label"] for row in cases} == {"MEASURED-INLINE-DECIDE"}
    # Each cell carries a MEASURED security boolean (not None) from the
    # AgentDojo oracle, and a real shield decision (not "SKIPPED").
    assert all(isinstance(row["security"], bool) for row in cases)
    assert all(row["decision"] != "SKIPPED" for row in cases)
    # The InjectionTask6 cell on the A2 shield arm MUST block (HG#5
    # model-free path) and produce $30k prevented_loss.
    a2_inj6 = next(
        row
        for row in cases
        if row["arm"] == "A2" and row["injection_task_id"] == "injection_task_6"
    )
    assert a2_inj6["security"] is True
    assert a2_inj6["decision"] == "BLOCK"
    assert a2_inj6["prevented_loss_usd"] == 30_000.0
    # Per-guardian schema is exposed but empty pre-Phase-A (never fabricated).
    assert a2_inj6["per_guardian"] == []


def test_full_grid_http_backend_skips_honestly_when_real_gov_unavailable(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """F1: when ``decide.real_server_transport()`` raises ``RealGovUnavailable``
    the http path SKIPs honestly (never fabricates a real-graph result).
    The skip_reason captures the upstream error verbatim so reviewers see
    *why* execution didn't happen, not just that it didn't.
    """
    from shield_eval import decide

    def _boom():  # type: ignore[no-untyped-def]
        raise decide.RealGovUnavailable("simulated real-gov unavailable for F1 fallback test")

    monkeypatch.setattr(decide, "real_server_transport", _boom)

    summary_path = tmp_path / "http_skipped_summary.json"
    cases_path = tmp_path / "http_skipped_cases.json"

    rc = run_ab.main(
        [
            "--full",
            "--suite",
            "banking",
            "--backend",
            "http",
            "--arms",
            "A0,A2",
            "--user-task",
            "user_task_2",
            "--injection-task",
            "injection_task_6",
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
    assert "REAL_GOV_UNAVAILABLE" in summary["skip_reason"]
    assert {row["evidence_label"] for row in cases} == {"SKIPPED"}
    assert {row["decision"] for row in cases} == {"SKIPPED"}
    assert {row["security"] for row in cases} == {None}
