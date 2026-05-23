"""Router-backed construction for Evaluator, Supervisor, and Auditor."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from shield_sdk.schema import (
    Decision,
    GovernanceVerdict,
    Guardian,
    Phase,
    ShieldActionRecord,
    VerdictReason,
)

from shield_governance.auditor import Auditor, AuditResult
from shield_governance.evaluator import Evaluator, EvaluatorConfig
from shield_governance.evidence import GuardianEvidenceRecorder
from shield_governance.graph import _resolve_pubkey
from shield_governance.model_router import ShieldModelRouter
from shield_governance.router_runtime import RouterCallMeasurement, RouterTextClient
from shield_governance.supervisor import (
    ArbitrationResult,
    GuardianSignals,
    Supervisor,
)
from shield_governance.verdicts import AsyncVerdictHandoff


@dataclass(frozen=True, slots=True)
class RouterBackedGuardians:
    evaluator: Evaluator
    supervisor: Supervisor
    auditor: Auditor
    evidence_recorder: GuardianEvidenceRecorder


class RouterHallucinationChecker:
    """Evaluator hallucination/value-sanity seam backed by the model router."""

    def __init__(self, router: ShieldModelRouter, evidence_recorder: GuardianEvidenceRecorder):
        self._caller = RouterTextClient(router, "evaluator")
        self._evidence = evidence_recorder

    async def check(
        self, record: ShieldActionRecord, trace: list[dict[str, object]]
    ) -> VerdictReason | None:
        prompt = (
            "Does this tool call's claimed effect match its arguments? "
            f"tool={record.payload.tool_name} args={dict(record.payload.tool_args)}. "
            "Answer GROUNDED or HALLUCINATED with a one-line reason."
        )
        measurement = await self._caller.acomplete(prompt)
        text = measurement.result.text.strip()
        hallucinated = text.upper().startswith("HALLUCINATED")
        decision = Decision.BLOCK if hallucinated else Decision.PASS
        label = "evaluator.hallucination" if hallucinated else "evaluator.grounded"
        self._record_measurement(record, measurement, decision=decision, reasons=(label,))
        if not hallucinated:
            return None
        return VerdictReason(
            agent=Guardian.EVALUATOR,
            label=label,
            detail=text[:240],
            score=0.7,
            model_id=measurement.model_id,
            served_via=measurement.served_via,
        )

    def _record_measurement(
        self,
        record: ShieldActionRecord,
        measurement: RouterCallMeasurement,
        *,
        decision: Decision,
        reasons: tuple[str, ...],
    ) -> None:
        self._evidence.record_for_record(
            record,
            guardian=Guardian.EVALUATOR,
            decision=decision,
            reasons=reasons,
            model_id=measurement.model_id,
            served_via=measurement.served_via,
            prompt_tokens=measurement.result.prompt_tokens,
            completion_tokens=measurement.result.completion_tokens,
            latency_ms=measurement.latency_ms,
            cost_usd=measurement.result.cost_usd,
        )


class RouterSupervisorArbiter:
    """Conflict-only Supervisor arbiter backed by the model router."""

    def __init__(self, router: ShieldModelRouter, evidence_recorder: GuardianEvidenceRecorder):
        self._caller = RouterTextClient(router, "supervisor")
        self._evidence = evidence_recorder
        self._last_measurement: RouterCallMeasurement | None = None

    def __call__(self, signals: GuardianSignals) -> ArbitrationResult:
        prompt = (
            "Resolve this Defender/Evaluator conflict. "
            f"defender={signals.defender_decision.value} "
            f"evaluator_anomaly={signals.evaluator_anomaly:.3f}. "
            "Answer PASS, ALERT, ESCALATE, BLOCK, or ROLLBACK with a short reason."
        )
        measurement = self._caller.complete(prompt)
        self._last_measurement = measurement
        decision = _decision_from_text(measurement.result.text, default=Decision.ESCALATE)
        reason = VerdictReason(
            agent=Guardian.SUPERVISOR,
            label="supervisor.arbitrated",
            detail=measurement.result.text.strip()[:240],
            score=signals.evaluator_anomaly,
            model_id=measurement.model_id,
            served_via=measurement.served_via,
        )
        return ArbitrationResult(decision=decision, reason=reason)

    def record_evidence(
        self, record: ShieldActionRecord, decision: Decision, reason: VerdictReason
    ) -> None:
        if self._last_measurement is None:
            return
        measurement = self._last_measurement
        self._evidence.record_for_record(
            record,
            guardian=Guardian.SUPERVISOR,
            decision=decision,
            reasons=(reason.label,),
            model_id=measurement.model_id,
            served_via=measurement.served_via,
            prompt_tokens=measurement.result.prompt_tokens,
            completion_tokens=measurement.result.completion_tokens,
            latency_ms=measurement.latency_ms,
            cost_usd=measurement.result.cost_usd,
        )


class RouterBackedAuditor(Auditor):
    """Auditor with router-backed narrative/reporting path."""

    def __init__(self, router: ShieldModelRouter, evidence_recorder: GuardianEvidenceRecorder):
        super().__init__()
        self._caller = RouterTextClient(router, "auditor")
        self._evidence = evidence_recorder

    async def generate_compliance_report(
        self, verdicts: list[GovernanceVerdict]
    ) -> dict[str, object]:
        report = await super().generate_compliance_report(verdicts)
        measurement = await self._caller.acomplete(
            f"Summarize this governance audit in 2 sentences: {report}"
        )
        report["narrative"] = measurement.result.text.strip()
        if verdicts:
            record_stub = _record_stub_from_verdict(verdicts[0])
            self._evidence.record_for_record(
                record_stub,
                guardian=Guardian.AUDITOR,
                decision=Decision.PASS,
                reasons=("auditor.narrative",),
                model_id=measurement.model_id,
                served_via=measurement.served_via,
                prompt_tokens=measurement.result.prompt_tokens,
                completion_tokens=measurement.result.completion_tokens,
                latency_ms=measurement.latency_ms,
                cost_usd=measurement.result.cost_usd,
            )
        return report


def build_router_backed_guardians(
    router: ShieldModelRouter,
    *,
    evidence_recorder: GuardianEvidenceRecorder | None = None,
    evaluator_config: EvaluatorConfig | None = None,
) -> RouterBackedGuardians:
    evidence = evidence_recorder or GuardianEvidenceRecorder()
    evaluator = Evaluator(
        evaluator_config or EvaluatorConfig(),
        hallucination=RouterHallucinationChecker(router, evidence),
    )
    supervisor = Supervisor(arbiter=RouterSupervisorArbiter(router, evidence))
    auditor = RouterBackedAuditor(router, evidence)
    return RouterBackedGuardians(
        evaluator=evaluator,
        supervisor=supervisor,
        auditor=auditor,
        evidence_recorder=evidence,
    )


def make_router_backed_async_channel2_handler(
    *,
    router: ShieldModelRouter,
    evidence_recorder: GuardianEvidenceRecorder | None = None,
    evaluator_config: EvaluatorConfig | None = None,
    on_verdict: Callable[[AsyncVerdictHandoff], Awaitable[None]] | None = None,
    key_resolver: Callable[[str], Awaitable[str | None] | str | None] | None = None,
) -> Callable[[ShieldActionRecord], Awaitable[None]]:
    """Build the router-backed async Channel-2 handler.

    ``key_resolver`` resolves ``record.agent_pubkey_kid`` to the base64url
    Ed25519 public key required by Auditor chain verification. Production
    callers MUST inject a resolver wired to the server's ``agent_keys``
    registry (see ``shield_server.governance`` for the sync ingest precedent
    that already uses ``agent_keys`` lookup). When no resolver is provided the
    audit step skips signature verification rather than pass the kid as a key.
    May be sync or async.
    """
    guardians = build_router_backed_guardians(
        router,
        evidence_recorder=evidence_recorder,
        evaluator_config=evaluator_config,
    )

    async def handle(record: ShieldActionRecord) -> None:
        eval_result = await guardians.evaluator.evaluate(record)
        public_key = await _resolve_pubkey(key_resolver, record)
        audit_result = guardians.auditor.audit([record], agent_pubkey_b64url=public_key)
        _record_auditor_if_absent(guardians.evidence_recorder, record, audit_result)
        signals = GuardianSignals(
            defender_decision=Decision.PASS,
            evaluator_anomaly=eval_result.anomaly,
            evaluator_reasons=eval_result.reasons,
            evaluator_ran=True,
            auditor_integrity=audit_result.integrity,
            auditor_reasons=audit_result.reasons,
            structuring_or_exfil=eval_result.structuring_or_exfil,
            chain_broken=audit_result.chain_broken,
            post_exec=record.phase == Phase.POST_EXEC,
        )
        verdict = guardians.supervisor.decide(signals, record=record)
        _record_supervisor_if_absent(guardians.evidence_recorder, record, verdict)
        if on_verdict is not None:
            await on_verdict(
                AsyncVerdictHandoff.from_record(
                    record,
                    verdict,
                    guardian_evidence=guardians.evidence_recorder.for_record(record.record_id),
                )
            )

    return handle


def _record_auditor_if_absent(
    recorder: GuardianEvidenceRecorder, record: ShieldActionRecord, audit_result: AuditResult
) -> None:
    if recorder.has_guardian(record.record_id, Guardian.AUDITOR):
        return
    recorder.record_for_record(
        record,
        guardian=Guardian.AUDITOR,
        decision=Decision.BLOCK if audit_result.chain_broken else Decision.PASS,
        reasons=tuple(reason.label for reason in audit_result.reasons) or ("auditor.integrity",),
        model_id=None,
        served_via=None,
    )


def _record_supervisor_if_absent(
    recorder: GuardianEvidenceRecorder, record: ShieldActionRecord, verdict: GovernanceVerdict
) -> None:
    if recorder.has_guardian(record.record_id, Guardian.SUPERVISOR):
        return
    recorder.record_for_record(
        record,
        guardian=Guardian.SUPERVISOR,
        decision=verdict.decision,
        reasons=tuple(
            reason.label for reason in verdict.reasons if reason.agent is Guardian.SUPERVISOR
        )
        or ("supervisor.aggregate",),
        model_id=None,
        served_via=None,
    )


def _record_stub_from_verdict(verdict: GovernanceVerdict) -> ShieldActionRecord:
    return ShieldActionRecord(
        run_id=verdict.run_id or "audit-report",
        record_id=verdict.record_id or verdict.verdict_id,
        correlation_id=verdict.correlation_id,
        phase=Phase.POST_EXEC,
    )


def _decision_from_text(text: str, *, default: Decision) -> Decision:
    upper = text.strip().upper()
    for decision in Decision:
        if upper.startswith(decision.value):
            return decision
    return default
