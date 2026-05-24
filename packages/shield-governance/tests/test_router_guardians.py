"""Router-backed Evaluator/Supervisor/Auditor evidence path (Phase B)."""

from __future__ import annotations

import pytest
import shield_sdk.canonical as canonical
import shield_sdk.crypto as crypto
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from shield_governance.evaluator import EvaluatorConfig
from shield_governance.evidence import GuardianEvidenceRecorder
from shield_governance.memory import ChromaIncidentMemory, ChromaMemoryConfig
from shield_governance.model_router import GUARDIAN_ROLES, ResolvedModel, ShieldModelRouter
from shield_governance.router_guardians import (
    build_router_backed_guardians,
    make_router_backed_async_channel2_handler,
)
from shield_governance.supervisor import GuardianSignals
from shield_governance.verdicts import AsyncVerdictHandoff
from shield_sdk.schema import ActionPayload, Decision, Guardian, Phase, ShieldActionRecord

PRIV = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
PUB = crypto.get_public_key_base64url(PRIV)


class _ToolableFakeChatModel(FakeMessagesListChatModel):
    """``FakeMessagesListChatModel`` + no-op ``bind_tools`` so
    :func:`langchain.agents.create_agent` accepts it.

    LangChain's default ``BaseChatModel.bind_tools`` raises
    ``NotImplementedError``; ``create_agent`` always calls it. We don't
    actually need to honor the bound-tools list (the responses are pre-
    canned in ``responses``), so a no-op suffices for unit tests.
    """

    def bind_tools(self, tools, **kwargs):  # type: ignore[override,no-untyped-def]  # noqa: ARG002
        return self


def _evaluator_tool_call_sequence(
    decision: str,
    *,
    tool_name: str = "eval_invariant_policies",
    tool_id: str = "tc-1",
    final_reason: str = "see tool evidence",
    turn1_usage: tuple[int, int] = (8, 2),
    turn2_usage: tuple[int, int] = (3, 1),
) -> list[AIMessage]:
    """A 2-turn evaluator response: tool_call → final DECISION/REASON.

    Token totals across the two turns map directly onto the evidence
    recorder's ``prompt_tokens`` / ``completion_tokens`` columns (the
    checker sums them across the agent loop).
    """
    return [
        AIMessage(
            content="",
            tool_calls=[{"name": tool_name, "args": {}, "id": tool_id}],
            usage_metadata={
                "input_tokens": turn1_usage[0],
                "output_tokens": turn1_usage[1],
                "total_tokens": turn1_usage[0] + turn1_usage[1],
            },
        ),
        AIMessage(
            content=f"DECISION: {decision}\nREASON: {final_reason}",
            usage_metadata={
                "input_tokens": turn2_usage[0],
                "output_tokens": turn2_usage[1],
                "total_tokens": turn2_usage[0] + turn2_usage[1],
            },
        ),
    ]


def _single_message(text: str, *, prompt: int = 0, completion: int = 0) -> AIMessage:
    return AIMessage(
        content=text,
        usage_metadata={
            "input_tokens": prompt,
            "output_tokens": completion,
            "total_tokens": prompt + completion,
        },
    )


def _router_with_fakes(
    *,
    evaluator_responses: list[AIMessage] | None = None,
    supervisor_responses: list[AIMessage] | None = None,
    auditor_responses: list[AIMessage] | None = None,
    role_calls: list[str] | None = None,
) -> ShieldModelRouter:
    """Build a ShieldModelRouter whose per-role clients are toolable fake
    BaseChatModels (LangChain ``BaseChatModel`` shape, post-Phase-B).
    """
    eval_resp = evaluator_responses or _evaluator_tool_call_sequence("HALLUCINATED")
    sup_resp = supervisor_responses or [
        _single_message("BLOCK: evaluator evidence is credible", prompt=7, completion=2),
    ]
    aud_resp = auditor_responses or [
        _single_message(
            "Audit narrative: chain intact and evidence preserved.",
            prompt=5,
            completion=4,
        ),
    ]

    def fake_builder(resolved: ResolvedModel, api_key: str | None) -> object:  # noqa: ARG001
        if role_calls is not None:
            role_calls.append(resolved.role)
        if resolved.role == "evaluator":
            return _ToolableFakeChatModel(responses=list(eval_resp))
        if resolved.role == "supervisor":
            return _ToolableFakeChatModel(responses=list(sup_resp))
        if resolved.role == "auditor":
            return _ToolableFakeChatModel(responses=list(aud_resp))
        return _ToolableFakeChatModel(responses=[_single_message("PASS")])

    guardians = {
        role: {"provider": "local", "model": f"{role}-model", "served_via": "local"}
        for role in GUARDIAN_ROLES
    }
    return ShieldModelRouter(
        {"profile": "test", "guardians": guardians},
        client_builders={"local": fake_builder},
    )


def _record(
    *,
    phase: Phase = Phase.POST_EXEC,
    run_id: str = "router-run",
    recipient: str = "attacker",
) -> ShieldActionRecord:
    rec = ShieldActionRecord(
        run_id=run_id,
        phase=phase,
        agent_pubkey_kid=PUB,
        payload=ActionPayload(
            tool_name="send_money",
            tool_args={"recipient": recipient, "amount": 10_000.0, "subject": "fixture"},
        ),
    )
    return canonical.finalize_record(rec, PRIV)


@pytest.mark.asyncio
async def test_router_backed_guardians_call_router_and_record_evidence() -> None:
    """End-to-end: Evaluator agent (tool-call → decision) → Supervisor
    arbitrate → Auditor narrative. Phase B replaces the Evaluator single-
    prompt scaffold with a real ``create_agent`` agent loop, so the role
    call list now sees the evaluator twice (one agent turn per LLM call).
    """
    role_calls: list[str] = []
    recorder = GuardianEvidenceRecorder()
    guardians = build_router_backed_guardians(
        _router_with_fakes(role_calls=role_calls),
        evidence_recorder=recorder,
        # ``run_invariant`` off so the deterministic invariant analyzer
        # does not also fire on the fixture (it does not provide a
        # subject field the invariant policy expects); the agent's
        # ``eval_invariant_policies`` tool exercises the real analyzer
        # via the agent path instead.
        evaluator_config=EvaluatorConfig(run_invariant=False, run_hallucination=True),
    )
    record = _record()

    eval_result = await guardians.evaluator.evaluate(record)
    verdict = guardians.supervisor.decide(
        GuardianSignals(
            evaluator_anomaly=eval_result.anomaly,
            evaluator_reasons=eval_result.reasons,
            evaluator_ran=True,
        ),
        record=record,
    )
    report = await guardians.auditor.generate_compliance_report([verdict])

    assert verdict.decision is Decision.BLOCK
    assert report["narrative"].startswith("Audit narrative")
    # role_calls is the unique-instantiation log (model_factory builds the
    # underlying client once per role and caches it). What matters for the
    # discriminative wiring intent is that the evaluator role IS exercised.
    assert "evaluator" in role_calls
    assert "supervisor" in role_calls
    assert "auditor" in role_calls
    assert any(
        reason.agent is Guardian.SUPERVISOR
        and reason.label == "supervisor.arbitrated"
        and reason.model_id == "supervisor-model"
        for reason in verdict.reasons
    )

    evidence = recorder.for_record(record.record_id)
    by_guardian = {row.guardian: row for row in evidence}
    assert by_guardian[Guardian.EVALUATOR].model_id == "evaluator-model"
    # Phase B sums tokens across the agent's two turns.
    assert by_guardian[Guardian.EVALUATOR].prompt_tokens == 11
    assert by_guardian[Guardian.EVALUATOR].completion_tokens == 3
    assert by_guardian[Guardian.EVALUATOR].decision is Decision.BLOCK
    assert by_guardian[Guardian.SUPERVISOR].reasons == ("supervisor.arbitrated",)
    assert by_guardian[Guardian.AUDITOR].reasons == ("auditor.narrative",)


@pytest.mark.asyncio
async def test_router_backed_async_handler_attaches_guardian_evidence_to_handoff() -> None:
    role_calls: list[str] = []
    recorder = GuardianEvidenceRecorder()
    seen: list[AsyncVerdictHandoff] = []

    async def sink(handoff: AsyncVerdictHandoff) -> None:
        seen.append(handoff)

    handler = make_router_backed_async_channel2_handler(
        router=_router_with_fakes(role_calls=role_calls),
        evidence_recorder=recorder,
        evaluator_config=EvaluatorConfig(run_invariant=False, run_hallucination=True),
        on_verdict=sink,
        # _record() sets ``agent_pubkey_kid = PUB`` (i.e. the kid string IS the
        # base64url public key in this fixture) — give the audit step the
        # matching public key via an identity resolver so chain verification
        # succeeds. Production wiring resolves the kid via the server's
        # ``agent_keys`` registry instead (see AsyncVerdictWorker).
        key_resolver=lambda kid: kid,
    )
    await handler(_record(run_id="async-router-run"))

    assert len(seen) == 1
    assert seen[0].verdict.signature_by_shield is None
    assert seen[0].guardian_evidence
    by_guardian = {row.guardian: row for row in seen[0].guardian_evidence}
    assert by_guardian[Guardian.EVALUATOR].model_id == "evaluator-model"
    assert by_guardian[Guardian.SUPERVISOR].model_id == "supervisor-model"
    # Auditor narrative is only produced by ``generate_compliance_report``
    # (which the async handler does not call); the recorder only logs the
    # auditor's deterministic integrity row here. That row is PASS (the
    # record verifies cleanly) and carries zero LLM tokens by design.
    assert by_guardian[Guardian.AUDITOR].decision is Decision.PASS
    assert by_guardian[Guardian.AUDITOR].prompt_tokens == 0


@pytest.mark.asyncio
async def test_router_backed_async_handler_emits_chroma_memory_evidence(tmp_path) -> None:
    recorder = GuardianEvidenceRecorder()
    seen: list[AsyncVerdictHandoff] = []
    memory = ChromaIncidentMemory(
        ChromaMemoryConfig(
            persist_directory=tmp_path,
            collection_name="agent_shield_async_handler_memory_test",
        )
    )
    memory.remember_record(
        _record(run_id="prior-memory-run", recipient="repeat-iban"),
        decision=Decision.ALERT,
        reasons=("evaluator.behavior_drift",),
    )

    async def sink(handoff: AsyncVerdictHandoff) -> None:
        seen.append(handoff)

    handler = make_router_backed_async_channel2_handler(
        router=_router_with_fakes(
            evaluator_responses=_evaluator_tool_call_sequence(
                "GROUNDED",
                tool_name="recall_similar_incidents",
                final_reason="memory evidence reviewed",
            ),
        ),
        evidence_recorder=recorder,
        evaluator_config=EvaluatorConfig(run_invariant=False, run_hallucination=True),
        memory=memory,
        on_verdict=sink,
        key_resolver=lambda kid: kid,
    )
    await handler(_record(run_id="async-memory-run", recipient="repeat-iban"))

    assert len(seen) == 1
    by_guardian = {row.guardian: row for row in seen[0].guardian_evidence}
    evaluator_row = by_guardian[Guardian.EVALUATOR]
    assert evaluator_row.memory is not None
    assert evaluator_row.memory["memory_backend"] == "chroma"
    assert evaluator_row.memory["collection"] == "agent_shield_async_handler_memory_test"
    assert evaluator_row.memory["hit_count"] >= 1
    assert evaluator_row.tool_calls == ("recall_similar_incidents",)
