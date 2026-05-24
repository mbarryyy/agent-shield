"""Router-backed construction for Evaluator, Supervisor, and Auditor."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
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
from shield_governance.memory.tools import build_recall_similar_incidents_tool
from shield_governance.model_router import ShieldModelRouter
from shield_governance.router_runtime import (
    RouterCallMeasurement,
    RouterCallResult,
    RouterTextClient,
)
from shield_governance.supervisor import (
    ArbitrationResult,
    GuardianSignals,
    Supervisor,
)
from shield_governance.verdicts import AsyncVerdictHandoff

if TYPE_CHECKING:
    from shield_governance.defender.scanners import LocalPolicyStructuringAnalyzer


@dataclass(frozen=True, slots=True)
class RouterBackedGuardians:
    evaluator: Evaluator
    supervisor: Supervisor
    auditor: Auditor
    evidence_recorder: GuardianEvidenceRecorder


class RouterHallucinationChecker:
    """Evaluator hallucination / value-sanity seam.

    Phase B upgrades the internal implementation from a single prompt → single
    completion (``RouterTextClient.acomplete``) to a real
    :func:`langchain.agents.create_agent` LLM agent that plans, calls bound
    tools, and can self-correct before producing a verdict. **The class
    signature is unchanged** — :class:`Evaluator` still injects a
    :class:`HallucinationChecker` and awaits ``check(record, trace)``; only
    the inside changes. See :mod:`shield_governance.evaluator_agent` for the
    agent, its bound tools, and the honest downgrade note re. G-4 / Chroma.
    """

    def __init__(
        self,
        router: ShieldModelRouter,
        evidence_recorder: GuardianEvidenceRecorder,
        *,
        memory: object | None = None,
        analyzer: LocalPolicyStructuringAnalyzer | None = None,
    ) -> None:
        # Lazy imports so the module's existing import graph isn't perturbed
        # for callers that never construct a Phase-B Evaluator agent.
        from shield_governance.defender.scanners import LocalPolicyStructuringAnalyzer
        from shield_governance.evaluator_agent import EvaluatorAgentMemory

        self._router = router
        self._evidence = evidence_recorder
        self._memory = memory or EvaluatorAgentMemory()
        self._analyzer = analyzer or LocalPolicyStructuringAnalyzer()
        # Spy hook for the discriminative tests; production leaves it None.
        self.last_tool_calls: list[str] = []

    async def check(
        self, record: ShieldActionRecord, trace: list[dict[str, object]]
    ) -> VerdictReason | None:
        import time

        from shield_governance.evaluator_agent import (
            _summarize,
            make_evaluator_agent,
            parse_evaluator_decision,
        )

        started = time.perf_counter()
        tool_call_log: list[str] = []
        memory_evidence_log: list[dict[str, object]] = []
        agent = make_evaluator_agent(
            self._router,
            record=record,
            trace=trace,
            analyzer=self._analyzer,
            memory=self._memory,
            tool_call_log=tool_call_log,
            memory_evidence_log=memory_evidence_log,
        )

        user_prompt = (
            "Tool-call record under review:\n"
            f"  tool={record.payload.tool_name}\n"
            f"  args={dict(record.payload.tool_args)}\n"
            f"  run_id={record.run_id}\n"
            f"  step_index={record.step_index}\n"
            "Use the tools and then answer in the DECISION/REASON format."
        )
        result = await agent.ainvoke({"messages": [{"role": "user", "content": user_prompt}]})

        messages = result.get("messages", []) if isinstance(result, dict) else []
        self.last_tool_calls = list(tool_call_log)

        # Find the final AIMessage (no tool_calls) — the model's decision.
        final_text = ""
        prompt_tokens = 0
        completion_tokens = 0
        model_id: str | None = None
        served_via = None
        for msg in messages:
            usage = getattr(msg, "usage_metadata", None)
            if isinstance(usage, dict):
                prompt_tokens += int(usage.get("input_tokens", 0) or 0)
                completion_tokens += int(usage.get("output_tokens", 0) or 0)
            content = getattr(msg, "content", None)
            tool_calls = getattr(msg, "tool_calls", None)
            if (
                content is not None
                and not (isinstance(content, str) and not content.strip())
                and not tool_calls
            ):
                final_text = (
                    content
                    if isinstance(content, str)
                    else getattr(content[0], "text", str(content))
                )

        resolved = self._router.for_role("evaluator")
        model_id = resolved.model
        served_via = resolved.served_via

        hallucinated, reason_text = parse_evaluator_decision(final_text)
        decision = Decision.BLOCK if hallucinated else Decision.PASS
        label = "evaluator.hallucination" if hallucinated else "evaluator.grounded"
        # Remember this record for future recall queries — done after the
        # agent runs so the current call cannot recall itself.
        remember_record = getattr(self._memory, "remember_record", None)
        if callable(remember_record):
            remember_record(record, decision=decision, reasons=(label,))
        else:
            remember = getattr(self._memory, "remember", None)
            if callable(remember):
                remember(_summarize(record))
        latency_ms = (time.perf_counter() - started) * 1000.0
        self._evidence.record_for_record(
            record,
            guardian=Guardian.EVALUATOR,
            decision=decision,
            reasons=(label,),
            model_id=model_id,
            served_via=served_via,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            cost_usd=0.0,
            memory=memory_evidence_log[-1] if memory_evidence_log else None,
            tool_calls=tuple(tool_call_log),
        )
        if not hallucinated:
            return None
        return VerdictReason(
            agent=Guardian.EVALUATOR,
            label=label,
            detail=reason_text[:240],
            score=0.7,
            model_id=model_id,
            served_via=served_via,
        )


class RouterSupervisorArbiter:
    """Conflict-only Supervisor arbiter backed by a bounded tool loop."""

    def __init__(
        self,
        router: ShieldModelRouter,
        evidence_recorder: GuardianEvidenceRecorder,
        *,
        memory: object | None = None,
        max_iterations: int = 6,
    ):
        self._router = router
        self._evidence = evidence_recorder
        self._last_measurement: RouterCallMeasurement | None = None
        self._last_tool_calls: tuple[str, ...] = ()
        self._last_memory: dict[str, object] | None = None
        self._memory = memory
        self._max_iterations = max(2, max_iterations)

    def __call__(self, signals: GuardianSignals) -> ArbitrationResult:
        return self.decide(signals, record=None)

    def decide(
        self,
        signals: GuardianSignals,
        *,
        record: ShieldActionRecord | None,
    ) -> ArbitrationResult:
        import time

        started = time.perf_counter()
        resolved = self._router.for_role("supervisor")
        tool_call_log: list[str] = []
        memory_evidence_log: list[dict[str, object]] = []
        tools = self._build_tools(
            signals,
            record=record,
            tool_call_log=tool_call_log,
            memory_evidence_log=memory_evidence_log,
        )
        agent = create_agent(
            model=cast(BaseChatModel, self._router.model_factory("supervisor")({}, object())),
            tools=tools,
            system_prompt=(
                "You are the Agent Shield Supervisor. Use tools before resolving "
                "guardian conflicts. Reply with one of PASS, ALERT, ESCALATE, "
                "BLOCK, or ROLLBACK followed by a short reason."
            ),
        )
        prompt = (
            "Resolve this Defender/Evaluator conflict. "
            f"defender={signals.defender_decision.value} "
            f"evaluator_anomaly={signals.evaluator_anomaly:.3f}. "
            "Use tools, then answer PASS, ALERT, ESCALATE, BLOCK, or ROLLBACK."
        )
        try:
            result = agent.invoke(
                {"messages": [{"role": "user", "content": prompt}]},
                config={"recursion_limit": self._max_iterations + 2},
            )
            parsed = _extract_agent_text_and_usage(result)
        except Exception as exc:
            parsed = _AgentRunSummary(
                text=f"ESCALATE: supervisor tool loop failed ({exc.__class__.__name__})",
                prompt_tokens=0,
                completion_tokens=0,
            )
            tool_call_log.append("supervisor_tool_loop_error")
        measurement = RouterCallMeasurement(
            role="supervisor",
            model_id=resolved.model,
            served_via=resolved.served_via,
            result=parsed.to_router_result(),
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )
        self._last_measurement = measurement
        self._last_tool_calls = tuple(tool_call_log)
        self._last_memory = memory_evidence_log[-1] if memory_evidence_log else None
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

    def _build_tools(
        self,
        signals: GuardianSignals,
        *,
        record: ShieldActionRecord | None,
        tool_call_log: list[str],
        memory_evidence_log: list[dict[str, object]],
    ) -> list[Any]:
        @tool
        def inspect_guardian_signals(_hint: str = "") -> dict[str, object]:
            """Inspect Defender, Evaluator, and Auditor signals for this conflict."""
            tool_call_log.append("inspect_guardian_signals")
            return {
                "defender_decision": signals.defender_decision.value,
                "evaluator_anomaly": signals.evaluator_anomaly,
                "evaluator_ran": signals.evaluator_ran,
                "auditor_integrity": signals.auditor_integrity,
                "structuring_or_exfil": signals.structuring_or_exfil,
                "chain_broken": signals.chain_broken,
                "post_exec": signals.post_exec,
                "defender_reasons": [reason.label for reason in signals.defender_reasons],
                "evaluator_reasons": [reason.label for reason in signals.evaluator_reasons],
                "auditor_reasons": [reason.label for reason in signals.auditor_reasons],
            }

        tools: list[Any] = [inspect_guardian_signals]
        if self._memory is not None and record is not None:
            tools.append(
                build_recall_similar_incidents_tool(
                    record=record,
                    memory=self._memory,
                    tool_call_log=tool_call_log,
                    memory_evidence_log=memory_evidence_log,
                )
            )
        return tools

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
            memory=self._last_memory,
            tool_calls=self._last_tool_calls,
        )


class RouterBackedAuditor(Auditor):
    """Auditor with router-backed bounded tool loop plus report narrative."""

    def __init__(
        self,
        router: ShieldModelRouter,
        evidence_recorder: GuardianEvidenceRecorder,
        *,
        memory: object | None = None,
        max_iterations: int = 6,
    ):
        super().__init__()
        self._router = router
        self._caller = RouterTextClient(router, "auditor")
        self._evidence = evidence_recorder
        self._memory = memory
        self._max_iterations = max(2, max_iterations)

    def audit(
        self, records: list[ShieldActionRecord], *, agent_pubkey_b64url: str | None
    ) -> AuditResult:
        result = super().audit(records, agent_pubkey_b64url=agent_pubkey_b64url)
        if records:
            self._record_tool_loop_evidence(records, result)
        return result

    def _record_tool_loop_evidence(
        self,
        records: list[ShieldActionRecord],
        audit_result: AuditResult,
    ) -> None:
        import time

        record = records[0]
        started = time.perf_counter()
        resolved = self._router.for_role("auditor")
        tool_call_log: list[str] = []
        memory_evidence_log: list[dict[str, object]] = []
        tools = self._build_tools(
            records,
            audit_result,
            tool_call_log=tool_call_log,
            memory_evidence_log=memory_evidence_log,
        )
        agent = create_agent(
            model=cast(BaseChatModel, self._router.model_factory("auditor")({}, object())),
            tools=tools,
            system_prompt=(
                "You are the Agent Shield Auditor. Use tools to inspect chain, "
                "provenance, and memory evidence before emitting a concise audit finding."
            ),
        )
        try:
            run = agent.invoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": "Audit this Channel-2 record batch with tools.",
                        }
                    ]
                },
                config={"recursion_limit": self._max_iterations + 2},
            )
            parsed = _extract_agent_text_and_usage(run)
        except Exception as exc:
            parsed = _AgentRunSummary(
                text=f"AUDIT: tool loop failed ({exc.__class__.__name__})",
                prompt_tokens=0,
                completion_tokens=0,
            )
            tool_call_log.append("auditor_tool_loop_error")
        self._evidence.record_for_record(
            record,
            guardian=Guardian.AUDITOR,
            decision=Decision.BLOCK if audit_result.chain_broken else Decision.PASS,
            reasons=tuple(reason.label for reason in audit_result.reasons)
            or ("auditor.tool_loop",),
            model_id=resolved.model,
            served_via=resolved.served_via,
            prompt_tokens=parsed.prompt_tokens,
            completion_tokens=parsed.completion_tokens,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            cost_usd=0.0,
            memory=memory_evidence_log[-1] if memory_evidence_log else None,
            tool_calls=tuple(tool_call_log),
        )

    def _build_tools(
        self,
        records: list[ShieldActionRecord],
        audit_result: AuditResult,
        *,
        tool_call_log: list[str],
        memory_evidence_log: list[dict[str, object]],
    ) -> list[Any]:
        @tool
        def inspect_chain_state(_hint: str = "") -> dict[str, object]:
            """Inspect signature/chain/Merkle integrity for the audited batch."""
            tool_call_log.append("inspect_chain_state")
            return {
                "record_count": len(records),
                "integrity": audit_result.integrity,
                "chain_broken": audit_result.chain_broken,
                "self_report_mismatch": audit_result.self_report_mismatch,
                "reason_labels": [reason.label for reason in audit_result.reasons],
            }

        @tool
        def inspect_provenance_summary(_hint: str = "") -> dict[str, object]:
            """Inspect trace-safe provenance summary for the audited batch."""
            tool_call_log.append("inspect_provenance_summary")
            return {
                "record_ids": [record.record_id for record in records[:8]],
                "correlation_ids": sorted({record.correlation_id for record in records}),
                "phases": [record.phase.value for record in records],
            }

        tools: list[Any] = [inspect_chain_state, inspect_provenance_summary]
        if self._memory is not None and records:
            tools.append(
                build_recall_similar_incidents_tool(
                    record=records[0],
                    memory=self._memory,
                    tool_call_log=tool_call_log,
                    memory_evidence_log=memory_evidence_log,
                )
            )
        return tools

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
    memory: object | None = None,
) -> RouterBackedGuardians:
    evidence = evidence_recorder or GuardianEvidenceRecorder()
    evaluator = Evaluator(
        evaluator_config or EvaluatorConfig(),
        hallucination=RouterHallucinationChecker(router, evidence, memory=memory),
    )
    supervisor = Supervisor(arbiter=RouterSupervisorArbiter(router, evidence, memory=memory))
    auditor = RouterBackedAuditor(router, evidence, memory=memory)
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
    memory: object | None = None,
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
        memory=memory,
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


@dataclass(frozen=True, slots=True)
class _AgentRunSummary:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def to_router_result(self) -> RouterCallResult:
        return RouterCallResult(
            text=self.text,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            cost_usd=0.0,
        )


def _extract_agent_text_and_usage(result: object) -> _AgentRunSummary:
    messages = result.get("messages", []) if isinstance(result, dict) else []
    final_text = ""
    prompt_tokens = 0
    completion_tokens = 0
    for msg in messages:
        usage = getattr(msg, "usage_metadata", None)
        if isinstance(usage, dict):
            prompt_tokens += int(usage.get("input_tokens", 0) or 0)
            completion_tokens += int(usage.get("output_tokens", 0) or 0)
        content = getattr(msg, "content", None)
        tool_calls = getattr(msg, "tool_calls", None)
        if (
            content is not None
            and not (isinstance(content, str) and not content.strip())
            and not tool_calls
        ):
            final_text = (
                content if isinstance(content, str) else getattr(content[0], "text", str(content))
            )
    return _AgentRunSummary(
        text=final_text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def _decision_from_text(text: str, *, default: Decision) -> Decision:
    upper = text.strip().upper()
    for decision in Decision:
        if upper.startswith(decision.value):
            return decision
    return default
