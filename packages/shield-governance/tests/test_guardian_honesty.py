"""Wave-1 honesty fixes (charter R1/R6): guardian model failures must RAISE,
never fabricate a verdict; cost_usd must be REAL, never a hardcoded 0.0.

Reference impl that already does it right: ``RouterHallucinationChecker.check``
raises :class:`GuardianModelInvocationError` on a model exception. These tests
pin the Supervisor-arbiter and Auditor tool loops to the SAME contract, plus
the real-cost computation.
"""

from __future__ import annotations

import pytest
import shield_sdk.canonical as canonical
import shield_sdk.crypto as crypto
from langchain_core.language_models import BaseChatModel
from shield_governance.evaluator import EvaluatorConfig
from shield_governance.evidence import GuardianEvidenceRecorder
from shield_governance.model_router import GUARDIAN_ROLES, ResolvedModel, ShieldModelRouter
from shield_governance.pricing import (
    UnknownModelPriceError,
    cost_usd,
)
from shield_governance.router_guardians import (
    GuardianModelInvocationError,
    RouterBackedAuditor,
    RouterSupervisorArbiter,
    make_router_backed_async_channel2_handler,
)
from shield_governance.supervisor import GuardianSignals, Supervisor
from shield_governance.verdicts import AsyncVerdictHandoff
from shield_sdk.schema import (
    ActionPayload,
    Decision,
    Guardian,
    Phase,
    ServedVia,
    ShieldActionRecord,
)

PRIV = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
PUB = crypto.get_public_key_base64url(PRIV)


class _RaisingChatModel(BaseChatModel):
    """A real ``BaseChatModel`` whose every invocation raises — simulates a
    provider outage / auth failure without any network call."""

    @property
    def _llm_type(self) -> str:  # pragma: no cover - identity only
        return "raising-fake"

    def bind_tools(self, tools, **kwargs):  # type: ignore[override,no-untyped-def]  # noqa: ARG002
        return self

    def _generate(self, *args, **kwargs):  # type: ignore[no-untyped-def]  # noqa: ARG002
        raise RuntimeError("simulated provider failure")

    def invoke(self, *args, **kwargs):  # type: ignore[override,no-untyped-def]  # noqa: ARG002
        raise RuntimeError("simulated provider failure")

    async def ainvoke(self, *args, **kwargs):  # type: ignore[override,no-untyped-def]  # noqa: ARG002
        raise RuntimeError("simulated provider failure")


def _router_raising() -> ShieldModelRouter:
    def builder(resolved: ResolvedModel, api_key: str | None) -> object:  # noqa: ARG001
        return _RaisingChatModel()

    guardians = {
        role: {"provider": "local", "model": f"{role}-model", "served_via": "local"}
        for role in GUARDIAN_ROLES
    }
    return ShieldModelRouter(
        {"profile": "test", "guardians": guardians},
        client_builders={"local": builder},
    )


def _record(*, run_id: str = "honesty-run") -> ShieldActionRecord:
    rec = ShieldActionRecord(
        run_id=run_id,
        phase=Phase.POST_EXEC,
        agent_pubkey_kid=PUB,
        payload=ActionPayload(
            tool_name="send_money",
            tool_args={"recipient": "attacker", "amount": 10_000.0, "subject": "fixture"},
        ),
    )
    return canonical.finalize_record(rec, PRIV)


# --------------------------------------------------------------------------- #
# T1 — model failure RAISES (no fabricated verdict / evidence)
# --------------------------------------------------------------------------- #


def test_supervisor_arbiter_raises_on_model_failure_no_fabrication() -> None:
    recorder = GuardianEvidenceRecorder()
    arbiter = RouterSupervisorArbiter(_router_raising(), recorder)
    record = _record()

    with pytest.raises(GuardianModelInvocationError) as excinfo:
        arbiter.decide(
            GuardianSignals(
                defender_decision=Decision.PASS,
                evaluator_anomaly=0.95,
                evaluator_ran=True,
            ),
            record=record,
        )

    assert excinfo.value.guardian_name == Guardian.SUPERVISOR.value
    # NO fabricated "ESCALATE: tool loop failed" evidence row was written.
    rows = recorder.for_record(record.record_id)
    assert all("supervisor_tool_loop_error" not in row.tool_calls for row in rows)
    assert all(
        not (isinstance(d := row.reasons, tuple) and any("tool loop failed" in r for r in d))
        for row in rows
    )


def test_auditor_tool_loop_raises_on_model_failure_no_fabrication() -> None:
    recorder = GuardianEvidenceRecorder()
    auditor = RouterBackedAuditor(_router_raising(), recorder)
    record = _record()

    with pytest.raises(GuardianModelInvocationError) as excinfo:
        auditor.audit([record], agent_pubkey_b64url=PUB)

    assert excinfo.value.guardian_name == Guardian.AUDITOR.value
    rows = recorder.for_record(record.record_id)
    assert all("auditor_tool_loop_error" not in row.tool_calls for row in rows)


@pytest.mark.asyncio
async def test_async_handler_records_guardian_error_and_reraises() -> None:
    """When a guardian's model raises, the async handler records an HONEST
    guardian_error evidence row (truthful, not a faked decision) and re-raises
    so the at-least-once consumer does NOT ACK / publish a fabricated verdict."""
    recorder = GuardianEvidenceRecorder()
    published: list[AsyncVerdictHandoff] = []

    async def sink(handoff: AsyncVerdictHandoff) -> None:
        published.append(handoff)

    handler = make_router_backed_async_channel2_handler(
        router=_router_raising(),
        evidence_recorder=recorder,
        evaluator_config=EvaluatorConfig(run_invariant=False, run_hallucination=True),
        on_verdict=sink,
        key_resolver=lambda kid: kid,
    )
    record = _record(run_id="async-honesty-run")

    with pytest.raises(GuardianModelInvocationError):
        await handler(record)

    # No verdict was published (no fabricated decision escaped).
    assert published == []
    # An honest guardian_error row was recorded for the failed guardian.
    rows = recorder.for_record(record.record_id)
    error_rows = [row for row in rows if "guardian.model_error" in row.reasons]
    assert error_rows, "expected an honest guardian.model_error evidence row"
    # The error row carries NO fabricated risk decision token in reasons.
    assert all("tool loop failed" not in " ".join(row.reasons) for row in error_rows)


# --------------------------------------------------------------------------- #
# T3 — real cost_usd (no hardcoded 0.0 when a cloud model was called)
# --------------------------------------------------------------------------- #


def test_cost_usd_cloud_haiku_from_tokens() -> None:
    # 1000 input @ $1/MTok + 500 output @ $5/MTok = 0.001 + 0.0025 = 0.0035
    assert cost_usd(
        model_id="claude-haiku-4-5-20251001",
        served_via=ServedVia.CLOUD,
        prompt_tokens=1000,
        completion_tokens=500,
    ) == pytest.approx(0.0035)


def test_cost_usd_cloud_opus_from_tokens() -> None:
    # 1_000_000 input @ $15 + 1_000_000 output @ $75 = 90.0
    assert cost_usd(
        model_id="claude-opus-4-7",
        served_via=ServedVia.CLOUD,
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
    ) == pytest.approx(90.0)


def test_cost_usd_local_is_zero_marginal() -> None:
    # In-VPC open-weight serving: real marginal cost is $0 regardless of tokens.
    assert (
        cost_usd(
            model_id="Qwen2.5-32B-Instruct",
            served_via=ServedVia.LOCAL,
            prompt_tokens=999_999,
            completion_tokens=999_999,
        )
        == 0.0
    )


def test_cost_usd_unknown_cloud_model_raises_not_zero() -> None:
    with pytest.raises(UnknownModelPriceError):
        cost_usd(
            model_id="totally-unknown-model",
            served_via=ServedVia.CLOUD,
            prompt_tokens=10,
            completion_tokens=10,
        )


def test_supervisor_evidence_cost_is_real_for_cloud() -> None:
    """A cloud supervisor call with real tokens records a NON-zero cost_usd
    (not the old hardcoded 0.0)."""
    from langchain_core.messages import AIMessage
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

    class _ToolableFake(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):  # type: ignore[override,no-untyped-def]  # noqa: ARG002
            return self

    def builder(resolved: ResolvedModel, api_key: str | None) -> object:  # noqa: ARG001
        return _ToolableFake(
            responses=[
                AIMessage(
                    content="BLOCK: evaluator anomaly credible",
                    usage_metadata={
                        "input_tokens": 1000,
                        "output_tokens": 500,
                        "total_tokens": 1500,
                    },
                )
            ]
        )

    # supervisor role priced as cloud opus so the cost is non-zero + checkable.
    guardians = {
        role: {"provider": "local", "model": f"{role}-model", "served_via": "local"}
        for role in GUARDIAN_ROLES
    }
    guardians["supervisor"] = {
        "provider": "anthropic",
        "model": "claude-opus-4-7",
        "served_via": "cloud",
        "api_key_env": "SHIELD_TEST_NO_KEY",
    }
    router = ShieldModelRouter(
        {"profile": "test", "guardians": guardians},
        client_builders={"local": builder, "anthropic": builder},
        environ={"SHIELD_TEST_NO_KEY": "x"},
    )
    recorder = GuardianEvidenceRecorder()
    record = _record()
    Supervisor(arbiter=RouterSupervisorArbiter(router, recorder)).decide(
        GuardianSignals(
            defender_decision=Decision.PASS,
            evaluator_anomaly=0.95,
            evaluator_ran=True,
        ),
        record=record,
    )
    row = next(
        r for r in recorder.for_record(record.record_id) if r.guardian is Guardian.SUPERVISOR
    )
    # opus: 1000/1e6*15 + 500/1e6*75 = 0.015 + 0.0375 = 0.0525
    assert row.cost_usd == pytest.approx(0.0525)
