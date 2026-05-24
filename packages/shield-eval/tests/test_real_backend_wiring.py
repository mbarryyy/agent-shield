"""F2 (Phase F, EM-3) — ``--backend real`` wiring coverage.

The tests substitute via ``monkeypatch`` on ``_real_llm_for_worker`` so
the call chain through ``_score_real_cell`` →
``benchmark_suite_with_injections`` → ``decide.real_server_transport()``
is exercised end-to-end WITHOUT any provider call. F2 = wiring only;
M3 (AndyHu / W5 infra) is what flips ``--execute-real-run`` ON in a
protected env where ``ANTHROPIC_API_KEY`` is provisioned and budgeted.

HG#6 framing: these tests assert the **call chain is correctly wired**,
NOT that a real model achieved any ASR. The artifact label
``MEASURED-REAL-MODEL`` only becomes quotable after AndyHu's M3 run with
a real key; pre-M3 these tests merely confirm F2's plumbing is sound.
"""

from __future__ import annotations

import json
from typing import Any

from shield_eval import run_ab
from shield_eval.mock_llm import MockedLLM


def test_backend_real_default_path_stays_skipped_without_execute_flag(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """Regression: ``--backend real`` without ``--execute-real-run`` MUST
    stay on the keyless budget-only path (existing eval.yml CI step
    invariant). Even with the env key present and the budget cap fine,
    the absence of the explicit flag keeps the path SKIPPED.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-irrelevant-no-call-will-happen")
    budget_path = tmp_path / "budget.json"
    slice_path = tmp_path / "slice.json"

    rc = run_ab.main(
        [
            "--full",
            "--suite",
            "banking",
            "--backend",
            "real",
            "--arms",
            "A0,A2",
            "--user-task",
            "user_task_2",
            "--injection-task",
            "injection_task_6",
            "--samples",
            "1",
            "--serialized-prompt-chars",
            "3000",
            "--max-output-tokens",
            "1000",
            "--budget-out",
            str(budget_path),
            "--metrics-out",
            str(slice_path),
        ]
    )

    assert rc == 0
    # Existing path: budget estimator + SKIPPED slice artifact.
    slice_artifact = json.loads(slice_path.read_text(encoding="utf-8"))
    assert slice_artifact["api_call_status"] == "SKIPPED"
    assert slice_artifact["evidence_label"] == "SKIPPED"
    assert slice_artifact["skip_reason"] == "ESTIMATE_ONLY_AWAITING_USER_APPROVAL"
    budget = json.loads(budget_path.read_text(encoding="utf-8"))
    assert budget["api_call_status"] == "SKIPPED"


def test_backend_real_execute_flag_without_key_skips_honestly(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """``--execute-real-run`` without ``ANTHROPIC_API_KEY`` → budget guard
    short-circuits to ``status_label='SKIPPED'`` (MISSING_ANTHROPIC_API_KEY),
    so the F2 execution branch SHORT-CIRCUITS too and the existing
    keyless slice artifact is emitted. NEVER fabricates a measured result.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    budget_path = tmp_path / "budget.json"
    slice_path = tmp_path / "slice.json"

    rc = run_ab.main(
        [
            "--full",
            "--suite",
            "banking",
            "--backend",
            "real",
            "--execute-real-run",
            "--arms",
            "A0,A2",
            "--user-task",
            "user_task_2",
            "--injection-task",
            "injection_task_6",
            "--samples",
            "1",
            "--budget-out",
            str(budget_path),
            "--metrics-out",
            str(slice_path),
        ]
    )

    assert rc == 0
    budget = json.loads(budget_path.read_text(encoding="utf-8"))
    assert budget["status_label"] == "SKIPPED"
    assert budget["skip_reason"] == "MISSING_ANTHROPIC_API_KEY"
    # The F2 branch did not fire (budget guard short-circuited); the
    # default slice artifact carrying SKIPPED is what was written.
    slice_artifact = json.loads(slice_path.read_text(encoding="utf-8"))
    assert slice_artifact["api_call_status"] == "SKIPPED"


def test_backend_real_execute_flag_wires_real_llm_for_worker(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """F2 (EM-3) wiring assertion: with ``--execute-real-run`` + key + budget
    OK, ``_dispatch_full --backend real`` routes through
    ``_score_real_cell``, which calls ``_real_llm_for_worker(worker)`` for
    the worker LLM. We monkeypatch ``_real_llm_for_worker`` to return a
    ``MockedLLM`` (NO real provider call) and assert:

    1. The patched function was called (call chain wired correctly).
    2. The patched function received the configured ``worker`` argument.
    3. The resulting artifact carries ``run_label='MEASURED-REAL-MODEL'``
       and per-case rows tagged ``backend='real'`` — proving F2's branch
       fired (not the SKIPPED fallback).

    This validates the wiring. M3 (AndyHu) is what flips the patch off and
    lets the real ``_real_llm_for_worker`` return a real ``AnthropicLLM``;
    nothing else in the code path changes.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-mocked")
    calls: list[str] = []

    def fake_real_llm(worker: str) -> Any:
        calls.append(worker)
        # MockedLLM stand-in — same interface, no provider call. The name
        # must contain one of AgentDojo's ``MODEL_NAMES`` keys so the
        # ImportantInstructionsAttack's ``get_model_name_from_pipeline``
        # accepts the pipeline — matching the real ``_real_llm_for_worker``
        # convention (it always tags the LLM ``claude-3-haiku-20240307
        # (<worker>)``).
        llm = MockedLLM(name="placeholder", user_task=None, injection_task=None)
        llm.name = f"claude-3-haiku-20240307 (mock-as-{worker})"
        return llm

    monkeypatch.setattr(run_ab, "_real_llm_for_worker", fake_real_llm)

    summary_path = tmp_path / "real_grid_summary.json"
    cases_path = tmp_path / "real_grid_cases.json"

    rc = run_ab.main(
        [
            "--full",
            "--suite",
            "banking",
            "--backend",
            "real",
            "--execute-real-run",
            "--arms",
            "A0,A2",
            "--user-task",
            "user_task_2",
            "--injection-task",
            "injection_task_6",
            "--samples",
            "1",
            "--serialized-prompt-chars",
            "3000",
            "--max-output-tokens",
            "1000",
            "--model",
            "claude-haiku-4-5-20251001",
            "--metrics-out",
            str(summary_path),
            "--cases-out",
            str(cases_path),
        ]
    )

    assert rc == 0
    # (1) + (2): _real_llm_for_worker was actually called with the configured
    # worker name — proves the F2 dispatch routes through the wiring point.
    assert len(calls) >= 1, (
        "_real_llm_for_worker was not invoked — F2 dispatch did not "
        f"reach _score_real_cell. calls={calls!r}"
    )
    assert all(name == "claude-haiku-4-5-20251001" for name in calls)

    # (3): MEASURED-REAL-MODEL label + backend='real' on per-case rows.
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    assert summary["run_label"] == "MEASURED-REAL-MODEL"
    assert summary["backend"] == "real"
    assert {row["backend"] for row in cases} == {"real"}
    assert {row["evidence_label"] for row in cases} == {"MEASURED-REAL-MODEL"}


def test_backend_real_execute_flag_skips_when_real_gov_unavailable(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """F2: when ``decide.real_server_transport()`` raises
    ``RealGovUnavailable`` (in-process server setup blocked), the F2 path
    emits SKIPPED rows with the upstream reason — same honesty discipline
    as F1's keyless http path. NEVER fabricates.
    """
    from shield_eval import decide

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-mocked")

    def _boom():  # type: ignore[no-untyped-def]
        raise decide.RealGovUnavailable("simulated real-gov unavailable for F2 fallback test")

    monkeypatch.setattr(decide, "real_server_transport", _boom)

    summary_path = tmp_path / "real_skipped_summary.json"
    cases_path = tmp_path / "real_skipped_cases.json"

    rc = run_ab.main(
        [
            "--full",
            "--suite",
            "banking",
            "--backend",
            "real",
            "--execute-real-run",
            "--arms",
            "A0,A2",
            "--user-task",
            "user_task_2",
            "--injection-task",
            "injection_task_6",
            "--samples",
            "1",
            "--metrics-out",
            str(summary_path),
            "--cases-out",
            str(cases_path),
        ]
    )

    assert rc == 0
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    assert summary["run_label"] == "SKIPPED"
    assert "REAL_GOV_UNAVAILABLE" in summary["skip_reason"]
    assert {row["evidence_label"] for row in cases} == {"SKIPPED"}
    assert {row["backend"] for row in cases} == {"real"}
