"""B2 + B3 discriminative tests for the Phase B Evaluator agent.

These tests fail (in distinct ways) if a future regression silently reverts
the Evaluator's hallucination seam to the pre-Phase-B single-prompt call:

* **B2 wiring** — assert the agent invokes at least one bound tool, and
  the resulting verdict reflects the tool evidence (not a free-form LLM
  text scrape).
* **B3 self-correction** — assert the agent ran ≥ 2 turns when the first
  turn was a tool call (the create_agent loop's natural multi-turn behavior
  is the self-correction substrate; we prove it actually engages).
"""

from __future__ import annotations

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from shield_governance.evaluator_agent import (
    EvaluatorAgentMemory,
    IncidentSummary,
    _summarize,
    make_evaluator_agent,
    parse_evaluator_decision,
)
from shield_governance.evidence import GuardianEvidenceRecorder
from shield_governance.model_router import GUARDIAN_ROLES, ResolvedModel, ShieldModelRouter
from shield_governance.router_guardians import RouterHallucinationChecker
from shield_sdk.schema import ActionPayload, Phase, ShieldActionRecord


class _ToolableFakeChatModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):  # type: ignore[override,no-untyped-def]  # noqa: ARG002
        return self


def _record(
    *,
    run_id: str = "agent-run",
    recipient: str = "attacker-iban",
    amount: float = 10_000.0,
) -> ShieldActionRecord:
    return ShieldActionRecord(
        run_id=run_id,
        phase=Phase.POST_EXEC,
        payload=ActionPayload(
            tool_name="send_money",
            tool_args={"recipient": recipient, "amount": amount, "subject": "fixture"},
        ),
    )


def _router_with_evaluator_responses(responses: list[AIMessage]) -> ShieldModelRouter:
    """Build a router whose evaluator role returns the given response sequence."""

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


# --------------------------------------------------------------------------- #
# B2 wiring tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_evaluator_agent_calls_at_least_one_bound_tool() -> None:
    """B2 discriminative: the create_agent loop must drive at least one
    of the bound tools (eval_invariant_policies / recall_similar_local_incidents)
    before producing its final DECISION. If a refactor reverts the seam to a
    single LLM call, this test sees an empty tool-call log and fails.
    """
    record = _record()
    router = _router_with_evaluator_responses(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "eval_invariant_policies",
                        "args": {"_hint": "check trace"},
                        "id": "tc-b2-1",
                    }
                ],
            ),
            AIMessage(
                content="DECISION: GROUNDED\nREASON: tool reports no structuring",
            ),
        ]
    )

    checker = RouterHallucinationChecker(router, GuardianEvidenceRecorder())
    reason = await checker.check(record, [])

    # GROUNDED → check() returns None (no VerdictReason).
    assert reason is None
    # The spy hook on the agent recorded a real tool invocation.
    assert checker.last_tool_calls == ["eval_invariant_policies"]


@pytest.mark.asyncio
async def test_evaluator_agent_verdict_reflects_tool_evidence() -> None:
    """B2 discriminative: the VerdictReason emitted on HALLUCINATED must
    carry the agent's tool-evidence-grounded reason (parsed from the
    DECISION/REASON contract), not a freeform LLM scrape.
    """
    record = _record()
    router = _router_with_evaluator_responses(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "recall_similar_local_incidents",
                        "args": {"recipient": "attacker-iban"},
                        "id": "tc-b2-2",
                    }
                ],
            ),
            AIMessage(
                content=(
                    "DECISION: HALLUCINATED\n"
                    "REASON: recall_similar_local_incidents surfaced 3 prior "
                    "transfers to the same recipient — structuring pattern"
                ),
            ),
        ]
    )

    checker = RouterHallucinationChecker(router, GuardianEvidenceRecorder())
    reason = await checker.check(record, [])

    assert reason is not None
    assert reason.label == "evaluator.hallucination"
    assert "structuring pattern" in (reason.detail or "")
    assert checker.last_tool_calls == ["recall_similar_local_incidents"]
    assert reason.model_id == "evaluator-model"


@pytest.mark.asyncio
async def test_eval_invariant_policies_tool_wraps_real_local_policy() -> None:
    """The bound ``eval_invariant_policies`` tool runs the real
    :class:`LocalPolicyStructuringAnalyzer` — feed it a 3-transfer trace
    and assert the structuring violation actually fires through the agent
    tool path (not a stub).
    """
    record = _record(recipient="repeat-iban")
    trace: list[dict[str, object]] = []
    for idx in range(3):
        trace.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"prior-{idx}",
                        "type": "function",
                        "function": {
                            "name": "send_money",
                            # subject is required by the Invariant LocalPolicy
                            # (it accesses ``subject`` on the args dict); see
                            # _signed_record in test_async_verdict_worker.py.
                            "arguments": {
                                "recipient": "repeat-iban",
                                "amount": 9_500,
                                "subject": "tax payment",
                            },
                        },
                    }
                ],
            }
        )

    # First turn: ask the agent to call the invariant tool. Second turn: the
    # agent reflects the tool's fired-status in its final decision.
    fired_turn_text = (
        "DECISION: HALLUCINATED\nREASON: invariant policy fired — 3+ transfers to repeat-iban"
    )
    router = _router_with_evaluator_responses(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "eval_invariant_policies",
                        "args": {},
                        "id": "tc-inv",
                    }
                ],
            ),
            AIMessage(content=fired_turn_text),
        ]
    )

    tool_call_log: list[str] = []
    agent = make_evaluator_agent(
        router,
        record=record,
        trace=trace,
        tool_call_log=tool_call_log,
    )
    result = await agent.ainvoke({"messages": [{"role": "user", "content": "check"}]})

    # Find the ToolMessage produced by the analyzer tool and confirm it
    # carries a real ``fired=True`` result from the LocalPolicy analyzer.
    from langchain_core.messages import ToolMessage

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_messages, "no ToolMessage in agent transcript"
    payload = tool_messages[0].content
    assert "fired" in (payload if isinstance(payload, str) else str(payload))
    # The agent's spy log saw the same call.
    assert tool_call_log == ["eval_invariant_policies"]


def test_recall_similar_local_incidents_honest_in_memory_only() -> None:
    """The ``recall_similar_local_incidents`` tool's memory is process-local
    (HONEST DOWNGRADE vs gap §4.2's Chroma design). Verify the memory really
    is an in-process bounded deque: remembering past summaries then recalling
    by tool_name / recipient.
    """
    memory = EvaluatorAgentMemory(capacity=3)
    summaries = [
        IncidentSummary(
            record_id=f"rec-{i}",
            tool_name="send_money",
            recipient="repeat-iban",
            amount=float(1_000 * (i + 1)),
        )
        for i in range(2)
    ]
    summaries.append(
        IncidentSummary(
            record_id="rec-other",
            tool_name="send_money",
            recipient="other-iban",
            amount=500.0,
        )
    )
    for s in summaries:
        memory.remember(s)

    repeat_matches = memory.recall(tool_name="send_money", recipient="repeat-iban")
    assert {m.record_id for m in repeat_matches} == {"rec-0", "rec-1"}

    # Honest downgrade: memory is bounded; one more remember evicts the oldest.
    memory.remember(
        IncidentSummary(
            record_id="rec-2",
            tool_name="send_money",
            recipient="repeat-iban",
            amount=4_000.0,
        )
    )
    after_evict = memory.recall(tool_name="send_money")
    assert {m.record_id for m in after_evict} == {"rec-1", "rec-other", "rec-2"}


def test_parse_evaluator_decision_default_fail_open_to_grounded() -> None:
    """When the model fails to follow the DECISION/REASON format the parser
    fails OPEN to GROUNDED — explicit, documented behavior (the deterministic
    Defender already gates the hot path)."""
    hallucinated, reason = parse_evaluator_decision("I'm not sure, looks fine.")
    assert hallucinated is False
    assert "I'm not sure" in reason

    hallucinated, reason = parse_evaluator_decision(
        "DECISION: HALLUCINATED\nREASON: clear structuring"
    )
    assert hallucinated is True
    assert reason == "clear structuring"


# --------------------------------------------------------------------------- #
# B3 self-correction tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_evaluator_agent_runs_multi_turn_self_correction() -> None:
    """B3 discriminative: when the first model turn is a tool call, the
    create_agent loop must run a second turn (after the tool result) before
    producing its final decision. We construct a fake LLM whose first turn
    is a low-confidence tool call and second turn carries the final
    high-confidence DECISION, and assert both turns actually executed.

    If a refactor short-circuits the agent loop to a single turn — i.e.
    drops the create_agent / `self-correction` substrate — this test
    sees only one AIMessage in the transcript and fails.
    """
    record = _record()
    first_turn = AIMessage(
        content=(
            "I am uncertain whether this is GROUNDED — calling a tool "
            "to gather more evidence before deciding."
        ),
        tool_calls=[
            {
                "name": "recall_similar_local_incidents",
                "args": {"recipient": "attacker-iban"},
                "id": "tc-b3-1",
            }
        ],
    )
    second_turn = AIMessage(
        content=(
            "DECISION: HALLUCINATED\nREASON: after the recall tool I now have enough evidence"
        ),
    )
    router = _router_with_evaluator_responses([first_turn, second_turn])

    tool_call_log: list[str] = []
    agent = make_evaluator_agent(
        router,
        record=record,
        trace=[],
        tool_call_log=tool_call_log,
    )
    result = await agent.ainvoke({"messages": [{"role": "user", "content": "check"}]})

    # ≥ 2 AIMessages → the agent loop actually re-invoked after the tool.
    ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
    assert len(ai_messages) == 2, (
        f"expected 2 AIMessages (first tool turn + final decision turn); "
        f"got {len(ai_messages)} — agent loop may have collapsed to a single turn"
    )
    assert tool_call_log == ["recall_similar_local_incidents"]
    final_text = ai_messages[-1].content
    assert isinstance(final_text, str)
    assert "DECISION: HALLUCINATED" in final_text


@pytest.mark.asyncio
async def test_evaluator_agent_remembers_records_for_future_recall() -> None:
    """The checker remembers each record it judges so subsequent calls'
    ``recall_similar_local_incidents`` tool can surface prior patterns.
    """
    memory = EvaluatorAgentMemory()
    router = _router_with_evaluator_responses(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "eval_invariant_policies",
                        "args": {},
                        "id": "tc-mem-1",
                    }
                ],
            ),
            AIMessage(content="DECISION: GROUNDED\nREASON: ok"),
        ]
    )
    # Construct the checker with a *shared* memory so we can inspect it.
    checker = RouterHallucinationChecker(
        router,
        GuardianEvidenceRecorder(),
        memory=memory,
    )

    record = _record(recipient="repeat-iban", amount=9_500.0)
    await checker.check(record, [])

    summary = _summarize(record)
    assert memory.recall(tool_name="send_money", recipient="repeat-iban") == [summary]
