"""Defender hot path — produces a REAL frozen §4 ``GovernanceVerdict``,
BEHIND A FLAG (``DefenderConfig.enabled``). NOT swapped into
``POST /v1/governance/decide`` — that wiring is W3 (server still stub->PASS).

Composition (governance_design §3.1/§3.3, model-free hot path):

1. **Deterministic** (W1, no LLM): :func:`evaluate_send_money` +
   per-``run_id`` :class:`CumulativeRecipientTracker` — the authoritative
   cumulative-amount structuring catcher (InjectionTask6 thesis, audited).
2. **LlamaFirewall** ``scan_async`` on free-text (``subject``) — injection /
   secret / hidden-ASCII (local classifier + model-free regex; §5b-cited in
   :mod:`~shield_governance.defender.scanners`).
3. **Invariant ``LocalPolicy``** cross-call DSL cross-check (verified
   ``count(min=3)`` structuring + exfil; air-gap-safe LocalPolicy only).

The worst outcome wins. Every reason is a FROZEN §4.2 v1.1 ``VerdictReason``
(``label``/``detail``/``agent``/``score`` + ``served_via``/``model_id``).
Defender is model-free, so reasons carry ``served_via=local`` /
``model_id=None`` — it contributes ZERO LLM tokens (a correct, asserted
cost-hook-#1 data point).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from shield_sdk.schema import (
    Decision,
    GovernanceVerdict,
    Guardian,
    Obligations,
    ServedVia,
    ShieldActionRecord,
    VerdictReason,
)

from shield_governance.defender.rules import (
    CumulativeRecipientTracker,
    DefenderPolicy,
    evaluate_send_money,
)
from shield_governance.defender.scanners import (
    InjectionScanner,
    NullInjectionScanner,
    StructuringAnalyzer,
)

# Decision severity (mirrors rules._SEVERITY; ROLLBACK/REWRITE are W3 Supervisor
# compositions, never emitted by the deterministic Defender pre-exec path).
_SEVERITY: dict[Decision, int] = {
    Decision.PASS: 0,
    Decision.ALERT: 1,
    Decision.ESCALATE: 2,
    Decision.BLOCK: 3,
}


@dataclass(frozen=True, slots=True)
class DefenderConfig:
    """Runtime-loadable, flag-gated (eval arm A3 / FPR tuning need these
    runtime-configurable — master design §3.3)."""

    enabled: bool = False  # the FLAG — W2 builds it; W3 swaps it into /decide
    policy: DefenderPolicy = field(
        default_factory=lambda: DefenderPolicy(amount_cap=10_000, cumulative_cap=20_000)
    )
    run_scanner: bool = True
    run_invariant: bool = True


def _defender_reason(
    label: str, detail: str, score: float, agent: Guardian = Guardian.DEFENDER
) -> VerdictReason:
    # Defender is model-free -> no LLM token spend attributable to this reason.
    return VerdictReason(
        agent=agent,
        label=label,
        detail=detail or None,
        score=score,
        model_id=None,
        served_via=ServedVia.LOCAL,
    )


class DefenderEngine:
    """Stateful per-process Defender. Keeps a per-``run_id`` cumulative tracker
    and Invariant trace so cross-call structuring is detectable."""

    def __init__(
        self,
        config: DefenderConfig | None = None,
        *,
        scanner: InjectionScanner | None = None,
        structuring: StructuringAnalyzer | None = None,
    ) -> None:
        self._cfg = config or DefenderConfig()
        self._scanner: InjectionScanner = scanner or NullInjectionScanner()
        self._structuring = structuring  # None -> Invariant cross-check skipped
        self._trackers: dict[str, CumulativeRecipientTracker] = {}
        self._traces: dict[str, list[dict[str, Any]]] = {}

    @property
    def enabled(self) -> bool:
        return self._cfg.enabled

    def _tracker(self, run_id: str) -> CumulativeRecipientTracker:
        return self._trackers.setdefault(run_id, CumulativeRecipientTracker())

    def _append_trace(self, record: ShieldActionRecord) -> list[dict[str, Any]]:
        trace = self._traces.setdefault(record.run_id, [])
        trace.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": record.record_id,
                        "type": "function",
                        "function": {
                            "name": record.payload.tool_name or "",
                            "arguments": dict(record.payload.tool_args),
                        },
                    }
                ],
            }
        )
        return trace

    async def assess(self, record: ShieldActionRecord) -> GovernanceVerdict:
        t0 = time.perf_counter()

        def _verdict(
            decision: Decision,
            reasons: list[VerdictReason],
            risk: float,
            *,
            prevented_loss: float | None = None,
        ) -> GovernanceVerdict:
            # A.4 / Task #31: populate FROZEN §4.2 Obligations.prevented_loss
            # when the deterministic outcome carries an env-diff $ (single_cap
            # or cumulative.structuring BLOCK). Only when this verdict's own
            # decision is BLOCK/ROLLBACK — never on PASS/ALERT (no fabrication).
            obligations = Obligations()
            if prevented_loss is not None and decision in (
                Decision.BLOCK,
                Decision.ROLLBACK,
            ):
                obligations.prevented_loss = prevented_loss
            return GovernanceVerdict(
                decision=decision,
                correlation_id=record.correlation_id,
                record_id=record.record_id,
                run_id=record.run_id,
                risk_score=max(0.0, min(1.0, risk)),
                reasons=reasons,
                obligations=obligations,
                latency_ms=(time.perf_counter() - t0) * 1000.0,
            )

        if not self._cfg.enabled:
            # Truly behind a flag — emits an explicit disabled PASS so callers
            # can see the flag state without affecting /decide (server stub).
            return _verdict(
                Decision.PASS,
                [_defender_reason("defender.disabled", "Defender flag is off (W2)", 0.0)],
                0.0,
            )

        reasons: list[VerdictReason] = []
        tool_name = record.payload.tool_name or ""
        args = dict(record.payload.tool_args)
        # A.4 / Task #31: env-diff $ from the deterministic outcome (single_cap
        # → transfer.amount; cumulative.structuring → projected Σ-at-fire).
        # None for non-enumerated BLOCKs (scanner/invariant/exfil) — no
        # fabrication; server falls back to 0.0 on None.
        det_prev_loss: float | None = None

        # 1. Deterministic, model-free (the authoritative structuring catcher).
        if tool_name == "send_money":
            tracker = self._tracker(record.run_id)
            outcome = evaluate_send_money(args, policy=self._cfg.policy, tracker=tracker)
            reasons.append(outcome.to_verdict_reason())
            if outcome.decision in (Decision.PASS, Decision.ALERT):
                tracker.commit(str(args.get("recipient", "")), _amount(args))
            elif outcome.decision in (Decision.BLOCK, Decision.ROLLBACK):
                det_prev_loss = outcome.prevented_loss

        # 2. LlamaFirewall scan on the free-text subject (model-free/local).
        if self._cfg.run_scanner:
            subject = str(args.get("subject", ""))
            if subject:
                f = await self._scanner.scan_text(subject, kind="subject")
                if f.blocked or f.escalate:
                    reasons.append(_defender_reason(f.label, f.detail, f.score))

        # 3. Invariant LocalPolicy cross-call cross-check (verified count(min=3)).
        #    Invariant's sync LocalPolicy.analyze() calls asyncio.run()
        #    internally (verified policy.py:90); offload to a worker thread so it
        #    gets its own loop and never collides with our running event loop.
        if self._cfg.run_invariant and self._structuring is not None and tool_name:
            trace = self._append_trace(record)
            structuring = self._structuring
            violations = await asyncio.to_thread(structuring.analyze, trace)
            for v in violations:
                reasons.append(_defender_reason(v.label, v.detail, 1.0))

        # Compose: worst decision across all reasons.
        decision = Decision.PASS
        for r in reasons:
            d = _decision_for(r.label)
            if _SEVERITY[d] > _SEVERITY[decision]:
                decision = d
        risk = max((r.score or 0.0) for r in reasons) if reasons else 0.0
        return _verdict(decision, reasons, risk, prevented_loss=det_prev_loss)


def _amount(args: dict[str, Any]) -> float:
    try:
        return float(args.get("amount", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _decision_for(label: str) -> Decision:
    """Map a reason label to its Decision (deterministic, no LLM)."""
    if label in (
        "amount.ok",
        "iban.format_ok",
        "iban.allowlist_ok",
        "subject.clean",
        "cumulative.ok",
        "cumulative.disabled",
        "scanner.clean",
        "scanner.disabled",
        "defender.disabled",
    ):
        return Decision.PASS
    if label.startswith("scanner.review"):
        return Decision.ESCALATE
    # Every other emitted label is a deterministic / scanner / invariant BLOCK
    # (amount.over_cap, cumulative.structuring, iban.invalid, iban.not_allowlisted,
    #  subject.secret.*, amount.unparseable, scanner.injection.*, invariant.*).
    return Decision.BLOCK
