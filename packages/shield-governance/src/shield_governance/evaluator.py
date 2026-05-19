"""Evaluator — async, latency-tolerant semantic guardian. governance_design
§3.2. Runs on the Channel-2 path (NOT the sync hot path), so it never adds
latency or tokens to decide→BLOCK (HG#5).

W3 scope (team-lead-accepted cut):
* **REAL**: Invariant ``LocalPolicy`` cross-step (verified ``count(min=3)``
  idiom — ADR-0010; reuses :class:`LocalPolicyStructuringAnalyzer`) + secret
  exfil + ``hallucination_check`` / ``value_sanity`` (LLM via
  ``ShieldModelRouter`` — injected; a fake/null is used in unit CI).
* **WIRED + behind a sub-flag** (``EvaluatorConfig.drift_enabled``, default
  off): GUARDIAN/XG-Guard behaviour-drift *idea*, training-free — Sentence-BERT
  ``all-MiniLM-L6-v2`` (XG-Guard ``MA/Ours.py:238``) vs a per-(agent,workflow,
  tool) Chroma centroid + parameter-free fusion (``Ours.py:395-399,428-459``).
  GUARDIAN/XG-Guard repos are training-bound / unlicensed (governance_design
  §1) → the IDEA only, never their weights. Full benign-staging baseline =
  DEFERRED W4.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from shield_sdk.schema import Guardian, ServedVia, ShieldActionRecord, VerdictReason

from shield_governance.defender.scanners import (
    LocalPolicyStructuringAnalyzer,
    StructuringAnalyzer,
)


@dataclass(frozen=True, slots=True)
class EvaluatorResult:
    """Feeds the Supervisor's async GuardianSignals."""

    anomaly: float  # 0 = clean .. 1 = certain anomaly
    reasons: list[VerdictReason]
    structuring_or_exfil: bool


@runtime_checkable
class HallucinationChecker(Protocol):
    async def check(
        self, record: ShieldActionRecord, trace: list[dict[str, Any]]
    ) -> VerdictReason | None: ...


class NullHallucinationChecker:
    """Default — no LLM (unit CI / cloud-disabled profile)."""

    async def check(
        self, record: ShieldActionRecord, trace: list[dict[str, Any]]
    ) -> VerdictReason | None:
        return None


@dataclass(slots=True)
class RouterHallucinationChecker:
    """Real grounding/value-sanity check via ShieldModelRouter (Sonnet|in-VPC).

    ``call`` is the only LLM seam — it MUST be produced through
    ``ShieldModelRouter`` by the caller (kept injected so unit CI stays
    model-free and the air-gap profile swaps cloud→local by one YAML)."""

    call: Callable[[str], Awaitable[str]]
    model_id: str
    served_via: ServedVia

    async def check(
        self, record: ShieldActionRecord, trace: list[dict[str, Any]]
    ) -> VerdictReason | None:
        prompt = (
            "Does this tool call's claimed effect match its arguments? "
            f"tool={record.payload.tool_name} args={dict(record.payload.tool_args)}. "
            "Answer GROUNDED or HALLUCINATED with a one-line reason."
        )
        verdict_text = (await self.call(prompt)).strip()
        if verdict_text.upper().startswith("HALLUCINATED"):
            return VerdictReason(
                agent=Guardian.EVALUATOR,
                label="evaluator.hallucination",
                detail=verdict_text[:240],
                score=0.7,
                model_id=self.model_id,
                served_via=self.served_via,
            )
        return None


@runtime_checkable
class DriftDetector(Protocol):
    def score(self, record: ShieldActionRecord) -> float: ...


class NullDriftDetector:
    """Default when ``drift_enabled`` is off (W3). Always 0.0 (no drift)."""

    def score(self, record: ShieldActionRecord) -> float:
        return 0.0


class SbertChromaDriftDetector:
    """WIRED seam for the GUARDIAN/XG-Guard training-free drift idea. Full
    benign-staging centroid baseline is DEFERRED to W4 — constructing/scoring
    raises until then so it can never silently no-op into a false ``PASS``."""

    def __init__(self) -> None:  # pragma: no cover - W4
        raise NotImplementedError(
            "W4: SBERT all-MiniLM-L6-v2 + Chroma benign-staging centroid "
            "(idea from XG-Guard Ours.py:238/395-399; training-free, no weights)"
        )

    def score(self, record: ShieldActionRecord) -> float:  # pragma: no cover - W4
        raise NotImplementedError("W4: behaviour-drift scoring")


@dataclass(frozen=True, slots=True)
class EvaluatorConfig:
    run_invariant: bool = True
    run_hallucination: bool = True
    drift_enabled: bool = False  # sub-flag — full benign-staging is W4


class Evaluator:
    """Async semantic guardian. ``analyzer`` defaults to the real verified
    Invariant ``LocalPolicy`` (ADR-0010); injectable for unit CI."""

    def __init__(
        self,
        config: EvaluatorConfig | None = None,
        *,
        analyzer: StructuringAnalyzer | None = None,
        hallucination: HallucinationChecker | None = None,
        drift: DriftDetector | None = None,
    ) -> None:
        self._cfg = config or EvaluatorConfig()
        self._analyzer = analyzer or LocalPolicyStructuringAnalyzer()
        self._hallucination = hallucination or NullHallucinationChecker()
        self._drift = drift or NullDriftDetector()
        self._traces: dict[str, list[dict[str, Any]]] = {}

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

    async def evaluate(self, record: ShieldActionRecord) -> EvaluatorResult:
        import asyncio

        reasons: list[VerdictReason] = []
        structuring_or_exfil = False
        scores: list[float] = []

        if self._cfg.run_invariant and (record.payload.tool_name or ""):
            trace = self._append_trace(record)
            analyzer = self._analyzer
            # LocalPolicy.analyze() uses asyncio.run() internally (policy.py:90)
            # — offload so it gets its own loop (ADR-0010).
            violations = await asyncio.to_thread(analyzer.analyze, trace)
            for v in violations:
                structuring_or_exfil = True
                scores.append(1.0)
                reasons.append(
                    VerdictReason(
                        agent=Guardian.EVALUATOR,
                        label=v.label,
                        detail=v.detail or None,
                        score=1.0,
                        served_via=ServedVia.LOCAL,  # Invariant = pure-local, no model
                    )
                )

        if self._cfg.run_hallucination:
            hr = await self._hallucination.check(record, self._traces.get(record.run_id, []))
            if hr is not None:
                reasons.append(hr)
                scores.append(hr.score or 0.0)

        if self._cfg.drift_enabled:
            d = self._drift.score(record)
            if d > 0.0:
                scores.append(d)
                reasons.append(
                    VerdictReason(
                        agent=Guardian.EVALUATOR,
                        label="evaluator.behavior_drift",
                        detail=f"drift score {d:.3f} vs benign baseline",
                        score=d,
                        served_via=ServedVia.LOCAL,
                    )
                )

        return EvaluatorResult(
            anomaly=max(scores) if scores else 0.0,
            reasons=reasons,
            structuring_or_exfil=structuring_or_exfil,
        )
