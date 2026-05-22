"""Router-backed Evaluator/Supervisor/Auditor evidence path."""

from __future__ import annotations

import pytest
import shield_sdk.canonical as canonical
import shield_sdk.crypto as crypto
from shield_governance.evaluator import EvaluatorConfig
from shield_governance.evidence import GuardianEvidenceRecorder
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


class _FakeRouterClient:
    def __init__(self, role: str, calls: list[tuple[str, str]]) -> None:
        self._role = role
        self._calls = calls

    def complete(self, prompt: str, **kwargs: object) -> dict[str, object]:
        self._calls.append((self._role, prompt))
        if self._role == "evaluator":
            return {
                "text": "HALLUCINATED: claimed effect does not match arguments",
                "prompt_tokens": 11,
                "completion_tokens": 3,
                "cost_usd": 0.0011,
            }
        if self._role == "supervisor":
            return {
                "text": "BLOCK: evaluator evidence is credible",
                "prompt_tokens": 7,
                "completion_tokens": 2,
                "cost_usd": 0.0022,
            }
        if self._role == "auditor":
            return {
                "text": "Audit narrative: chain intact and evidence preserved.",
                "prompt_tokens": 5,
                "completion_tokens": 4,
                "cost_usd": 0.0005,
            }
        return {"text": "PASS", "prompt_tokens": 1, "completion_tokens": 1, "cost_usd": 0.0}


def _router(calls: list[tuple[str, str]]) -> ShieldModelRouter:
    def fake_builder(resolved: ResolvedModel, api_key: str | None) -> object:
        return _FakeRouterClient(resolved.role, calls)

    guardians = {
        role: {"provider": "local", "model": f"{role}-model", "served_via": "local"}
        for role in GUARDIAN_ROLES
    }
    return ShieldModelRouter(
        {"profile": "test", "guardians": guardians},
        client_builders={"local": fake_builder},
    )


def _record(*, phase: Phase = Phase.POST_EXEC, run_id: str = "router-run") -> ShieldActionRecord:
    rec = ShieldActionRecord(
        run_id=run_id,
        phase=phase,
        agent_pubkey_kid=PUB,
        payload=ActionPayload(
            tool_name="send_money",
            tool_args={"recipient": "attacker", "amount": 10_000.0},
        ),
    )
    return canonical.finalize_record(rec, PRIV)


@pytest.mark.asyncio
async def test_router_backed_guardians_call_router_and_record_evidence() -> None:
    calls: list[tuple[str, str]] = []
    recorder = GuardianEvidenceRecorder()
    guardians = build_router_backed_guardians(
        _router(calls),
        evidence_recorder=recorder,
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
    assert [role for role, _prompt in calls] == ["evaluator", "supervisor", "auditor"]
    assert any(
        reason.agent is Guardian.SUPERVISOR
        and reason.label == "supervisor.arbitrated"
        and reason.model_id == "supervisor-model"
        for reason in verdict.reasons
    )

    evidence = recorder.for_record(record.record_id)
    by_guardian = {row.guardian: row for row in evidence}
    assert by_guardian[Guardian.EVALUATOR].model_id == "evaluator-model"
    assert by_guardian[Guardian.EVALUATOR].prompt_tokens == 11
    assert by_guardian[Guardian.EVALUATOR].completion_tokens == 3
    assert by_guardian[Guardian.EVALUATOR].decision is Decision.BLOCK
    assert by_guardian[Guardian.SUPERVISOR].cost_usd == pytest.approx(0.0022)
    assert by_guardian[Guardian.AUDITOR].reasons == ("auditor.narrative",)


@pytest.mark.asyncio
async def test_router_backed_async_handler_attaches_guardian_evidence_to_handoff() -> None:
    calls: list[tuple[str, str]] = []
    recorder = GuardianEvidenceRecorder()
    seen: list[AsyncVerdictHandoff] = []

    async def sink(handoff: AsyncVerdictHandoff) -> None:
        seen.append(handoff)

    handler = make_router_backed_async_channel2_handler(
        router=_router(calls),
        evidence_recorder=recorder,
        evaluator_config=EvaluatorConfig(run_invariant=False, run_hallucination=True),
        on_verdict=sink,
    )
    await handler(_record(run_id="async-router-run"))

    assert len(seen) == 1
    assert seen[0].verdict.signature_by_shield is None
    assert seen[0].guardian_evidence
    by_guardian = {row.guardian: row for row in seen[0].guardian_evidence}
    assert by_guardian[Guardian.EVALUATOR].model_id == "evaluator-model"
    assert by_guardian[Guardian.SUPERVISOR].model_id == "supervisor-model"
    assert by_guardian[Guardian.AUDITOR].decision is Decision.PASS
    assert by_guardian[Guardian.AUDITOR].prompt_tokens == 0
