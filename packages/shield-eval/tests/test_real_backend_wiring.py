"""F2 (Phase F, EM-3) — ``--backend real`` wiring coverage.

The tests substitute via ``monkeypatch`` on ``_real_llm_for_worker`` so
the call chain through ``_score_real_cell`` →
``benchmark_suite_with_injections`` → ``decide.real_server_harness()``
is exercised end-to-end WITHOUT any provider call. F2 = wiring only;
M3 (AndyHu / W5 infra) is what flips ``--execute-real-run`` ON in a
protected env where ``ANTHROPIC_API_KEY`` is provisioned and budgeted.

HG#6 framing: these tests assert the **call chain is correctly wired**,
NOT that a real model achieved any ASR. The artifact label
``MEASURED-REAL-MODEL`` only becomes quotable after AndyHu's M3 run with
a real key; pre-M3 these tests merely confirm F2's plumbing is sound.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from shield_eval import run_ab
from shield_eval.mock_llm import MockedLLM
from shield_governance.model_router import ResolvedModel, ShieldModelRouter
from shield_sdk.canonical import finalize_record
from shield_sdk.crypto import GENESIS_CHAIN_HASH
from shield_sdk.schema import ActionPayload, ActionRef, Phase, ShieldActionRecord
from shield_server.async_verdict_worker import AsyncVerdictWorker, CacheChannel2Transport


class _ToolableFakeChatModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: object, **kwargs: object) -> object:  # noqa: ARG002
        return self


def _message(text: str, *, prompt: int = 0, completion: int = 0) -> AIMessage:
    return AIMessage(
        content=text,
        usage_metadata={
            "input_tokens": prompt,
            "output_tokens": completion,
            "total_tokens": prompt + completion,
        },
    )


def _tool_call_sequence() -> list[AIMessage]:
    return [
        AIMessage(
            content="",
            tool_calls=[{"name": "eval_invariant_policies", "args": {}, "id": "tc-1"}],
            usage_metadata={"input_tokens": 8, "output_tokens": 2, "total_tokens": 10},
        ),
        _message("DECISION: HALLUCINATED\nREASON: fixture", prompt=3, completion=1),
    ]


def _fake_cloud_router() -> ShieldModelRouter:
    def fake_builder(resolved: ResolvedModel, api_key: str | None) -> object:  # noqa: ARG001
        if resolved.role == "evaluator":
            return _ToolableFakeChatModel(responses=_tool_call_sequence() * 8)
        if resolved.role == "supervisor":
            return _ToolableFakeChatModel(
                responses=[_message("BLOCK: fixture", prompt=7, completion=2)] * 8
            )
        if resolved.role == "auditor":
            return _ToolableFakeChatModel(
                responses=[_message("Audit narrative", prompt=5, completion=4)] * 8
            )
        return _ToolableFakeChatModel(responses=[_message("PASS")] * 8)

    return ShieldModelRouter.from_profile(
        "cloud",
        client_builders={"anthropic": fake_builder},
        environ={"ANTHROPIC_API_KEY": "test-router-key"},
    )


def _post_async_smoke_records(harness: object) -> None:
    async def latest_chain_hash() -> str:
        row = await harness.storage.db.fetchrow(
            "SELECT chain_hash, seq_no FROM operations WHERE agent_id = $1 "
            "ORDER BY seq_no DESC LIMIT 1",
            "agentdojo-banking-v1",
        )
        assert row is not None
        return str(row["chain_hash"])

    pre = ShieldActionRecord(
        run_id="sidecar-smoke",
        phase=Phase.PRE_EXEC,
        step_index=0,
        prev_chain_hash=GENESIS_CHAIN_HASH,
        subject={"fixture": "async-sidecar-smoke"},
        action=ActionRef(tool="send_money", args_digest="sha256:sidecar-smoke"),
        payload=ActionPayload(
            tool_args={"recipient": "fixture-recipient", "amount": 1.0},
            tool_result={"ok": True},
        ),
    )
    signed_pre = finalize_record(pre, harness.agent_private_key_b64url)
    resp = httpx.post(
        f"{harness.base_url}/v1/governance/decide",
        json=signed_pre.model_dump(mode="json"),
        timeout=2.0,
    )
    resp.raise_for_status()

    post = ShieldActionRecord(
        run_id=pre.run_id,
        correlation_id=pre.correlation_id,
        phase=Phase.POST_EXEC,
        step_index=1,
        prev_chain_hash=asyncio.run(latest_chain_hash()),
        subject={"fixture": "async-sidecar-smoke"},
        action=ActionRef(tool="send_money", args_digest="sha256:sidecar-smoke"),
        payload=ActionPayload(
            tool_args={"recipient": "fixture-recipient", "amount": 1.0},
            tool_result={"ok": True},
        ),
    )
    signed_post = finalize_record(post, harness.agent_private_key_b64url)
    resp = httpx.post(
        f"{harness.base_url}/v1/governance/record",
        json=signed_post.model_dump(mode="json"),
        timeout=2.0,
    )
    resp.raise_for_status()


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


@pytest.mark.filterwarnings("ignore:Not all injection tasks were solved as user tasks")
def test_real_server_mock_worker_publishes_async_guardian_evidence_sidecar() -> None:
    from shield_eval.decide import real_server_harness

    with real_server_harness() as harness:
        _post_async_smoke_records(harness)

        worker = AsyncVerdictWorker(
            storage=harness.storage,
            settings=harness.settings,
            transport=CacheChannel2Transport(harness.storage.cache),
            router=_fake_cloud_router(),
        )
        handled = 0
        sidecars = []
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            handled += asyncio.run(worker.run_once("banking", count=16, block_ms=1))
            sidecars = [
                body
                for key, body in harness.storage.objects._objects.items()
                if key.endswith(".guardian_evidence")
            ]
            if handled >= 1 and sidecars:
                break
            time.sleep(0.05)
        guardian_rows = [json.loads(body.decode("utf-8")) for body in sidecars]

    assert handled >= 1
    assert sidecars
    assert sum(len(rows) for rows in guardian_rows) >= 1


def test_backend_real_execute_flag_skips_when_real_gov_unavailable(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """F2: when ``decide.real_server_harness()`` raises
    ``RealGovUnavailable`` (in-process server setup blocked), the F2 path
    emits SKIPPED rows with the upstream reason — same honesty discipline
    as F1's keyless http path. NEVER fabricates.
    """
    from shield_eval import decide

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-mocked")

    def _boom():  # type: ignore[no-untyped-def]
        raise decide.RealGovUnavailable("simulated real-gov unavailable for F2 fallback test")

    monkeypatch.setattr(decide, "real_server_harness", _boom)

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
