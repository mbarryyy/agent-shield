"""Phase E (M2) — eval-side discriminative test on the agentic substance.

Mirrors Phase B's gov-side coverage of ``make_evaluator_agent`` /
``RouterHallucinationChecker.check`` from the eval boundary so the
property eval relies on is pinned here too. The agentic substance
that the F1 ``MEASURED-INLINE-DECIDE`` and F3 ``per_guardian_rollup``
labels implicitly depend on is **"the evaluator agent invokes ≥1 of
its bound tools per record"**. If a future refactor regresses the
``create_agent`` seam to a single LLM call (no tool use, verdict
read off the prompt alone), this test fails — preventing a quiet
regression from masquerading as a present-but-degraded "agentic
eval" in eval artifacts.

These are eval's defence-in-depth duplicates of Phase B's
discriminative pair (positive: tool-call path; inverse: single-prompt
path). Gov-side tests churn faster than eval-side artifacts; this
file's job is to keep the eval-quoted property locked.

HG#6 framing: this is NOT a "measured agentic eval" — it is a
discriminative property test using a deterministic fake ChatModel.
No provider call. No model ASR. Purely an agentic-scope contract.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from shield_governance.evidence import GuardianEvidenceRecorder
from shield_governance.model_router import GUARDIAN_ROLES, ResolvedModel, ShieldModelRouter
from shield_governance.router_guardians import RouterHallucinationChecker
from shield_sdk.schema import ActionPayload, Phase, ShieldActionRecord


class _ToolingFakeChatModel(FakeMessagesListChatModel):
    """Local fake supporting ``bind_tools`` — mirrors Phase B's
    ``_ToolableFakeChatModel`` fixture pattern (re-implemented in eval-tests
    rather than imported across packages so eval's discriminative property
    is self-contained and survives gov-side test churn).
    """

    def bind_tools(self, tools: Any, **kwargs: Any) -> _ToolingFakeChatModel:  # type: ignore[override,no-untyped-def]  # noqa: ARG002
        return self


def _record(
    *,
    run_id: str = "eval-phase-e-run",
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
    """Build a router whose ``evaluator`` role returns a deterministic
    response sequence (no provider call). Matches the gov-side pattern
    so the seam exercised is the same; reasons differ to keep tests
    decoupled if the gov fixture drifts.
    """

    def fake_builder(resolved: ResolvedModel, api_key: str | None) -> object:  # noqa: ARG001
        return _ToolingFakeChatModel(responses=list(responses))

    guardians = {
        role: {"provider": "local", "model": f"{role}-model", "served_via": "local"}
        for role in GUARDIAN_ROLES
    }
    return ShieldModelRouter(
        {"profile": "test", "guardians": guardians},
        client_builders={"local": fake_builder},
    )


# ─────────────────────────────────────────────────────────────────────────
# Phase E discriminative positive: ≥1 bound tool invoked per record.
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluator_agent_invokes_at_least_one_bound_tool() -> None:
    """If the create_agent loop regresses to a single LLM call (no tool
    invocation before final answer), ``last_tool_calls`` stays empty and
    this assertion fails — pinning the agentic substance.
    """
    router = _router_with_evaluator_responses(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "eval_invariant_policies",
                        "args": {"_hint": "check trace"},
                        "id": "phase-e-tc-1",
                    }
                ],
            ),
            AIMessage(
                content="DECISION: GROUNDED\nREASON: invariant policies did not fire",
            ),
        ]
    )
    checker = RouterHallucinationChecker(router, GuardianEvidenceRecorder())

    reason = await checker.check(_record(), [])

    # GROUNDED branch → ``check()`` returns None (no VerdictReason).
    assert reason is None
    # ≥1 tool actually invoked — the agentic property eval depends on.
    assert len(checker.last_tool_calls) >= 1, (
        "evaluator agent did not invoke any bound tool — "
        "regression to single-prompt? "
        f"last_tool_calls={checker.last_tool_calls!r}"
    )
    assert checker.last_tool_calls[0] in {
        "eval_invariant_policies",
        "recall_similar_local_incidents",
    }


@pytest.mark.asyncio
async def test_evaluator_hallucinated_verdict_carries_tool_evidence_in_detail() -> None:
    """F13 routing: when the agent decides HALLUCINATED, the emitted
    ``VerdictReason.detail`` must carry the tool-evidence-grounded reason
    from the agent's REASON: line. eval's per_guardian_rollup + the
    F3 passthrough rely on that detail string staying tool-evidence-y;
    a regression to freeform/empty detail would silently weaken the
    rollup's downstream usefulness.

    Schema discipline per F13: NO new ``evidence`` field added; the
    existing ``reasons[].detail`` carries the witness verbatim.
    """
    router = _router_with_evaluator_responses(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "recall_similar_local_incidents",
                        "args": {"recipient": "attacker-iban"},
                        "id": "phase-e-tc-2",
                    }
                ],
            ),
            AIMessage(
                content=(
                    "DECISION: HALLUCINATED\n"
                    "REASON: recall_similar_local_incidents surfaced repeat "
                    "transfers to the same recipient — structuring pattern"
                ),
            ),
        ]
    )
    checker = RouterHallucinationChecker(router, GuardianEvidenceRecorder())

    reason = await checker.check(_record(), [])

    assert reason is not None
    # The verdict's reason detail is the tool-evidence-grounded one-liner,
    # not a freeform LLM scrape.
    assert "structuring pattern" in (reason.detail or "")
    assert checker.last_tool_calls == ["recall_similar_local_incidents"]
    # Evidence-route discipline: detail field carries the witness; no
    # ad-hoc evidence field on VerdictReason.
    assert not hasattr(reason, "evidence")


# ─────────────────────────────────────────────────────────────────────────
# Phase E discriminative inverse: a non-tool-calling LLM produces 0
# tool invocations — explicit failure-mode pin so we know exactly what a
# regression looks like.
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluator_no_tool_calls_when_model_skips_them_is_visible() -> None:
    """Inverse pin: a model response with no ``tool_calls`` (single-prompt
    answer) produces an empty ``last_tool_calls`` list — confirming that
    *if* the agent regressed in that direction, the positive test above
    would fail. Together they form a discriminative pair: present-and-
    correct vs absent-and-detected.

    NOTE: this case represents the FAIL-OPEN-to-GROUNDED path
    documented in ``parse_evaluator_decision`` — appropriate because
    the deterministic Defender + Invariant LocalPolicy already gate
    the hot path; the LLM agent is the late path's second opinion.
    """
    router = _router_with_evaluator_responses(
        [
            AIMessage(
                content="DECISION: GROUNDED\nREASON: looks fine from the prompt alone",
            ),
        ]
    )
    checker = RouterHallucinationChecker(router, GuardianEvidenceRecorder())

    reason = await checker.check(_record(), [])

    # The model never called a tool; ``last_tool_calls`` stays empty.
    assert checker.last_tool_calls == [], (
        "expected an empty tool-call log when the model returns no "
        f"tool_calls; got {checker.last_tool_calls!r}"
    )
    # And the agent falls open to GROUNDED (None) — documented behaviour.
    assert reason is None
