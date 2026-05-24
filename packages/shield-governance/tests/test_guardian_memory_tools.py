from __future__ import annotations

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from shield_governance.evidence import GuardianEvidenceRecorder
from shield_governance.memory import ChromaIncidentMemory, ChromaMemoryConfig
from shield_governance.memory.tools import build_recall_similar_incidents_tool
from shield_governance.model_router import GUARDIAN_ROLES, ResolvedModel, ShieldModelRouter
from shield_governance.router_guardians import RouterHallucinationChecker
from shield_sdk.schema import ActionPayload, Decision, Phase, ShieldActionRecord


class _ToolableFakeChatModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):  # type: ignore[override,no-untyped-def]  # noqa: ARG002
        return self


def _record(
    record_id: str,
    *,
    run_id: str = "guardian-memory-run",
    recipient: str = "attacker-iban",
    amount: float = 10_000.0,
) -> ShieldActionRecord:
    return ShieldActionRecord(
        record_id=record_id,
        correlation_id=f"corr-{record_id}",
        run_id=run_id,
        phase=Phase.POST_EXEC,
        payload=ActionPayload(
            tool_name="send_money",
            tool_args={"recipient": recipient, "amount": amount, "subject": "fixture"},
        ),
    )


def _router_with_evaluator_responses(responses: list[AIMessage]) -> ShieldModelRouter:
    def fake_builder(resolved: ResolvedModel, api_key: str | None) -> object:  # noqa: ARG001
        return _ToolableFakeChatModel(responses=list(responses))

    guardians = {
        role: {"provider": "local", "model": f"{role}-model", "served_via": "local"}
        for role in GUARDIAN_ROLES
    }
    return ShieldModelRouter(
        {"profile": "test", "guardians": guardians},
        client_builders={"local": fake_builder},
    )


def test_recall_similar_incidents_tool_returns_chroma_evidence(tmp_path) -> None:
    memory = ChromaIncidentMemory(
        ChromaMemoryConfig(
            persist_directory=tmp_path,
            collection_name="agent_shield_guardian_tool_test",
        )
    )
    prior = _record("rec-tool-prior")
    current = _record("rec-tool-current")
    memory.remember_record(
        prior,
        decision=Decision.BLOCK,
        reasons=("defender.single_transfer_cap",),
    )
    tool_call_log: list[str] = []
    tool = build_recall_similar_incidents_tool(
        record=current,
        memory=memory,
        tool_call_log=tool_call_log,
    )

    result = tool.invoke({"tool_name": "send_money", "recipient": "attacker-iban"})

    assert tool_call_log == ["recall_similar_incidents"]
    assert result["memory_backend"] == "chroma"
    assert result["collection"] == "agent_shield_guardian_tool_test"
    assert result["hit_count"] == 1
    assert result["top_hits"][0]["id"] == "rec-tool-prior"
    assert 0.0 <= result["top_hits"][0]["score"] <= 1.0
    assert result["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_router_hallucination_checker_records_chroma_memory_evidence(tmp_path) -> None:
    memory = ChromaIncidentMemory(
        ChromaMemoryConfig(
            persist_directory=tmp_path,
            collection_name="agent_shield_checker_memory_test",
        )
    )
    memory.remember_record(
        _record("rec-checker-prior", recipient="repeat-iban"),
        decision=Decision.ALERT,
        reasons=("evaluator.behavior_drift",),
    )
    router = _router_with_evaluator_responses(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "recall_similar_incidents",
                        "args": {"recipient": "repeat-iban"},
                        "id": "tc-memory",
                    }
                ],
            ),
            AIMessage(content="DECISION: GROUNDED\nREASON: memory evidence reviewed"),
        ]
    )
    recorder = GuardianEvidenceRecorder()
    checker = RouterHallucinationChecker(router, recorder, memory=memory)

    reason = await checker.check(_record("rec-checker-current", recipient="repeat-iban"), [])

    assert reason is None
    evidence = recorder.for_record("rec-checker-current")
    assert len(evidence) == 1
    assert evidence[0].memory is not None
    assert evidence[0].memory["memory_backend"] == "chroma"
    assert evidence[0].memory["collection"] == "agent_shield_checker_memory_test"
    assert evidence[0].memory["hit_count"] >= 1
    assert evidence[0].tool_calls == ("recall_similar_incidents",)
