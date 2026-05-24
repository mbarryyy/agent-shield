"""Supervisor — coordinator / scorer / decision (deterministic; LLM only on
Defender<->Evaluator conflict). governance_design §3.3.

Risk math (§3.3, verbatim)::

    risk = 1 − weighted_avg(defender_pass×0.35, (1−eval_anomaly)×0.35,
                            auditor_integrity×0.20, baseline×0.10)
    HARD OVERRIDES:
      defender/scanner BLOCK            -> BLOCK (+ROLLBACK if post-exec)
      Invariant structuring/exfil       -> BLOCK + ESCALATE
      chain/sig broken                  -> BLOCK + ESCALATE
    ELSE: <0.10 PASS · <0.30 ALERT · <0.60 ESCALATE · ≥0.60 BLOCK(+ROLLBACK)
    CONFLICT (Defender vs Evaluator) -> arbitrate() LLM, re-apply

Thresholds + weights are runtime-config (eval-plan §4.2 — eval arm A3 / FPR
tuning need them loadable, NOT hard-coded). `arbitrate` is an injected callable
routed through ShieldModelRouter at the call site; the default is a
deterministic conservative resolver so unit CI needs no LLM and the model-free
hot path (HG#5) keeps 0 LLM tokens on decide→BLOCK.

The Supervisor emits a FROZEN §4.2 v1.1 ``GovernanceVerdict`` UNSIGNED
(canonical-stable via ``shield_sdk.canonical.verdict_signable_dict``; the shield
server owns Ed25519 signing — gov never signs / never redeclares §4).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from shield_sdk.schema import (
    Decision,
    GovernanceVerdict,
    Guardian,
    Obligations,
    Phase,
    RollbackObligation,
    ShieldActionRecord,
    VerdictReason,
)

_SEVERITY: dict[Decision, int] = {
    Decision.PASS: 0,
    Decision.ALERT: 1,
    Decision.ESCALATE: 2,
    Decision.ROLLBACK: 3,
    Decision.BLOCK: 4,
}


@dataclass(frozen=True, slots=True)
class SupervisorPolicy:
    """Runtime-loadable weights + thresholds (eval-plan §4.2)."""

    w_defender: float = 0.35
    w_evaluator: float = 0.35
    w_auditor: float = 0.20
    w_baseline: float = 0.10
    t_alert: float = 0.10  # risk <0.10 -> PASS, <t_alert.. -> ALERT band start
    t_escalate: float = 0.30
    t_block: float = 0.60


@dataclass(slots=True)
class GuardianSignals:
    """Per-guardian sub-results the Supervisor aggregates. On the sync hot path
    only ``defender_*`` is populated (Evaluator/Auditor run async on Channel-2),
    so a deterministic Defender BLOCK overrides with ZERO LLM tokens (HG#5)."""

    defender_decision: Decision = Decision.PASS
    defender_reasons: list[VerdictReason] = field(default_factory=list)
    evaluator_anomaly: float = 0.0  # 0 = clean .. 1 = certain anomaly
    evaluator_reasons: list[VerdictReason] = field(default_factory=list)
    auditor_integrity: float = 1.0  # 1 = chain/Merkle intact .. 0 = broken
    auditor_reasons: list[VerdictReason] = field(default_factory=list)
    baseline: float = 0.0
    evaluator_ran: bool = False  # True only on the async path (Evaluator present)
    structuring_or_exfil: bool = False  # Invariant/Defender structuring|exfil hit
    chain_broken: bool = False  # Auditor chain/sig broken
    post_exec: bool = False  # phase == post_exec (ROLLBACK applies)
    # A.4 / Task #31: env-diff $ from the Defender's deterministic outcome,
    # preserved into the final ``Obligations.prevented_loss`` on BLOCK/ROLLBACK
    # (single_cap → transfer.amount; cumulative.structuring → projected Σ-at-
    # fire — AgentDojo InjectionTask6 oracle). ``None`` = no clear env-diff $.
    prevented_loss: float | None = None

    @property
    def all_reasons(self) -> list[VerdictReason]:
        return [*self.defender_reasons, *self.evaluator_reasons, *self.auditor_reasons]


@dataclass(frozen=True, slots=True)
class ArbitrationResult:
    decision: Decision
    reason: VerdictReason | None = None


# arbitrate(signals) -> Decision|ArbitrationResult. Routed through
# ShieldModelRouter at the call site (Sonnet/Opus, conflict-only). Default =
# deterministic conservative.
Arbiter = Callable[[GuardianSignals], Decision | ArbitrationResult]


def _conservative_arbiter(signals: GuardianSignals) -> Decision:
    """Default arbiter (no LLM): take the more severe of Defender vs the
    Evaluator-implied decision. Conflict-only, so this is rarely reached."""
    eval_decision = _risk_to_decision(signals.evaluator_anomaly, SupervisorPolicy())
    return max((signals.defender_decision, eval_decision), key=lambda d: _SEVERITY[d])


def _risk_to_decision(risk: float, policy: SupervisorPolicy) -> Decision:
    if risk < policy.t_alert:
        return Decision.PASS
    if risk < policy.t_escalate:
        return Decision.ALERT
    if risk < policy.t_block:
        return Decision.ESCALATE
    return Decision.BLOCK


def _defender_blocked(signals: GuardianSignals) -> bool:
    return signals.defender_decision in (Decision.BLOCK, Decision.ROLLBACK)


def _is_conflict(signals: GuardianSignals, policy: SupervisorPolicy) -> bool:
    """Defender <-> Evaluator disagree: one (PASS/ALERT) and the other
    (ESCALATE/BLOCK). Only meaningful once the Evaluator has actually run
    (async path) — on the sync hot path it has not, so there is NO conflict and
    NO arbitrate()/LLM (HG#5)."""
    if not signals.evaluator_ran:
        return False
    d_sev = _SEVERITY[signals.defender_decision]
    e_sev = _SEVERITY[_risk_to_decision(signals.evaluator_anomaly, policy)]
    return (d_sev <= _SEVERITY[Decision.ALERT]) != (e_sev <= _SEVERITY[Decision.ALERT])


class Supervisor:
    """Deterministic aggregate + hard overrides + threshold mapping; LLM
    ``arbitrate`` ONLY on Defender<->Evaluator conflict."""

    def __init__(
        self,
        policy: SupervisorPolicy | None = None,
        *,
        arbiter: Arbiter | None = None,
    ) -> None:
        self._p = policy or SupervisorPolicy()
        self._arbiter = arbiter or _conservative_arbiter

    def aggregate_risk(self, s: GuardianSignals) -> float:
        p = self._p
        defender_pass = 0.0 if _defender_blocked(s) else 1.0
        wavg = (
            defender_pass * p.w_defender
            + (1.0 - s.evaluator_anomaly) * p.w_evaluator
            + s.auditor_integrity * p.w_auditor
            + (1.0 - s.baseline) * p.w_baseline
        ) / (p.w_defender + p.w_evaluator + p.w_auditor + p.w_baseline)
        return max(0.0, min(1.0, 1.0 - wavg))

    def decide(self, signals: GuardianSignals, *, record: ShieldActionRecord) -> GovernanceVerdict:
        # UNSIGNED + identity-forced-by-server: gov OWNS exactly decision /
        # risk_score / reasons[] / obligations. The shield server attaches
        # latency_ms / served_at / shield_kid and signs (locked PR-S1 seam) —
        # gov NEVER sets those / NEVER signs.
        p = self._p
        reasons = list(signals.all_reasons)
        risk = self.aggregate_risk(signals)
        escalate = False
        rollback = False

        # --- HARD OVERRIDES (deterministic, no LLM) ---
        if _defender_blocked(signals):
            decision = Decision.BLOCK
            rollback = signals.post_exec
        elif signals.chain_broken or signals.structuring_or_exfil:
            decision = Decision.BLOCK
            escalate = True
        elif _is_conflict(signals, p):
            # CONFLICT → arbitrate (LLM via injected ShieldModelRouter arbiter).
            decide_with_record = getattr(self._arbiter, "decide", None)
            raw_arbitration = (
                decide_with_record(signals, record=record)
                if callable(decide_with_record)
                else self._arbiter(signals)
            )
            if isinstance(raw_arbitration, ArbitrationResult):
                decision = raw_arbitration.decision
                arbiter_reason = raw_arbitration.reason
            else:
                decision = raw_arbitration
                arbiter_reason = None
            if arbiter_reason is None:
                arbiter_reason = VerdictReason(
                    agent=Guardian.SUPERVISOR,
                    label="supervisor.arbitrated",
                    detail="Defender<->Evaluator conflict resolved by arbitrate()",
                    score=risk,
                )
            reasons.append(arbiter_reason)
            record_evidence = getattr(self._arbiter, "record_evidence", None)
            if callable(record_evidence):
                record_evidence(record, decision, arbiter_reason)
            rollback = decision == Decision.BLOCK and signals.post_exec
        else:
            # No hard override / no conflict: the Defender's own decision is a
            # severity FLOOR (a Defender ESCALATE/ALERT is never silently
            # lowered); the risk band can only raise it.
            decision = max(
                (signals.defender_decision, _risk_to_decision(risk, p)),
                key=lambda d: _SEVERITY[d],
            )
            if decision == Decision.ESCALATE:
                escalate = True
            elif decision in (Decision.BLOCK, Decision.ROLLBACK):
                rollback = signals.post_exec

        if decision == Decision.ESCALATE:
            escalate = True

        obligations = Obligations()
        if escalate:
            obligations.require_human = True
        if rollback:
            decision = Decision.ROLLBACK if signals.post_exec else decision
            # gov actuates the LangGraph-checkpointer substrate; sdk sets
            # env_snapshot_ref / langgraph_thread_id (dual-substrate, frozen §4).
            obligations.rollback = RollbackObligation(
                langgraph_checkpoint_id=record.context.checkpoint_id,
                env_snapshot_ref=record.context.env_snapshot_ref,
            )
        # A.4 / Task #31: populate FROZEN §4.2 Obligations.prevented_loss on
        # BLOCK/ROLLBACK from the env-diff $ the DefenderEngine deterministic
        # outcome computed (single_cap → transfer.amount; cumulative.structuring
        # → projected Σ-at-fire — matches AgentDojo InjectionTask6 oracle
        # `sum(to_attacker) >= 30000`). PASS/ALERT/ESCALATE/REWRITE + BLOCKs
        # without a clear env-diff $ (e.g. exfil) → left None; the shield
        # server falls back to 0.0 on None (governance.py:315). No fabrication.
        if decision in (Decision.BLOCK, Decision.ROLLBACK) and signals.prevented_loss is not None:
            obligations.prevented_loss = signals.prevented_loss

        if not reasons:
            reasons.append(
                VerdictReason(
                    agent=Guardian.SUPERVISOR,
                    label="supervisor.clean",
                    detail=None,
                    score=risk,
                )
            )

        return GovernanceVerdict(
            decision=decision,
            correlation_id=record.correlation_id,  # server FORCES = rec's; required field
            record_id=record.record_id,  # server FORCES = rec's
            run_id=record.run_id,  # server FORCES = rec's; needed on the async path
            risk_score=risk,
            reasons=reasons,
            obligations=obligations,
            # latency_ms / served_at / signature_by_shield / shield_kid: server-owned.
        )


def signals_from_defender(verdict: GovernanceVerdict, *, phase: Phase) -> GuardianSignals:
    """Build hot-path GuardianSignals from a DefenderEngine verdict only
    (Evaluator/Auditor are async — HG#5: 0 LLM tokens on the decide path)."""
    structuring = any(
        r.label.startswith(("cumulative.structuring", "invariant.", "subject.secret"))
        for r in verdict.reasons
    )
    return GuardianSignals(
        defender_decision=verdict.decision,
        defender_reasons=list(verdict.reasons),
        structuring_or_exfil=structuring,
        post_exec=phase == Phase.POST_EXEC,
        # A.4 / Task #31: pull-through env-diff $ the DefenderEngine computed
        # (single_cap → amount; cumulative.structuring → projected Σ-at-fire).
        prevented_loss=verdict.obligations.prevented_loss,
    )
