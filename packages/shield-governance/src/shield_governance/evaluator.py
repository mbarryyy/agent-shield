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

import json
import math
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


class BehaviorDriftConfigurationError(RuntimeError):
    """Raised when drift is enabled without local baseline resources."""


@dataclass(frozen=True, slots=True)
class DriftScore:
    score: float
    baseline_key: str
    embedding_model: str
    collection: str
    baseline_count: int
    served_via: ServedVia = ServedVia.LOCAL


class NullDriftDetector:
    """Default when ``drift_enabled`` is off (W3). Always 0.0 (no drift)."""

    def score(self, record: ShieldActionRecord) -> float:
        return 0.0

    def score_result(self, record: ShieldActionRecord) -> DriftScore:
        return DriftScore(
            score=0.0,
            baseline_key=behavior_baseline_key(record),
            embedding_model="disabled",
            collection="disabled",
            baseline_count=0,
        )


class SbertChromaDriftDetector:
    """SBERT/Chroma drift seam with injectable local resources.

    The class deliberately fails fast unless both an embedder and a Chroma-like
    collection are supplied. That keeps drift disabled by default and prevents
    a missing local baseline from silently producing a clean score.
    """

    def __init__(
        self,
        *,
        embedder: object | None = None,
        collection: object | None = None,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        collection_name: str = "behavior_baselines",
    ) -> None:
        if embedder is None or collection is None:
            raise BehaviorDriftConfigurationError(
                "behavior drift requires local SBERT embedder and Chroma collection resources"
            )
        self._embedder = embedder
        self._collection = collection
        self._embedding_model = embedding_model
        self._collection_name = collection_name

    def add_baseline(self, record: ShieldActionRecord) -> None:
        key = behavior_baseline_key(record)
        document = _record_text(record)
        embedding = self._embed(document)
        add = getattr(self._collection, "add", None)
        if add is None:
            raise BehaviorDriftConfigurationError("behavior drift collection lacks add()")
        add(
            ids=[f"{key}:{record.record_id}"],
            embeddings=[embedding],
            metadatas=[{"baseline_key": key}],
            documents=[document],
        )

    def score_result(self, record: ShieldActionRecord) -> DriftScore:
        key = behavior_baseline_key(record)
        embeddings = self._baseline_embeddings(key)
        if not embeddings:
            raise BehaviorDriftConfigurationError(
                f"behavior drift enabled but no benign baseline exists for {key!r}"
            )
        current = self._embed(_record_text(record))
        centroid = _centroid(embeddings)
        score = max(0.0, min(1.0, 1.0 - _cosine(current, centroid)))
        return DriftScore(
            score=score,
            baseline_key=key,
            embedding_model=self._embedding_model,
            collection=self._collection_name,
            baseline_count=len(embeddings),
        )

    def score(self, record: ShieldActionRecord) -> float:
        return self.score_result(record).score

    def _baseline_embeddings(self, key: str) -> list[list[float]]:
        get = getattr(self._collection, "get", None)
        if get is None:
            raise BehaviorDriftConfigurationError("behavior drift collection lacks get()")
        result = get(where={"baseline_key": key}, include=["embeddings"])
        if not isinstance(result, dict):
            raise BehaviorDriftConfigurationError("behavior drift collection returned invalid data")
        raw = result.get("embeddings", [])
        return [[float(x) for x in row] for row in raw or []]

    def _embed(self, text: str) -> list[float]:
        encode = getattr(self._embedder, "encode", None)
        raw = encode([text]) if encode is not None else self._embedder([text])  # type: ignore[operator]
        first = raw[0]
        return [float(x) for x in first]


def behavior_baseline_key(record: ShieldActionRecord) -> str:
    tool = record.payload.tool_name or "<unknown>"
    return f"{record.org_id}/{record.agent_id}/{record.workflow_id}/{tool}"


def _record_text(record: ShieldActionRecord) -> str:
    args = json.dumps(dict(record.payload.tool_args), sort_keys=True, separators=(",", ":"))
    return f"{record.payload.tool_name or ''} {args}"


def _centroid(vectors: list[list[float]]) -> list[float]:
    width = len(vectors[0])
    return [sum(v[i] for v in vectors) / len(vectors) for i in range(width)]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


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
        if self._cfg.drift_enabled and drift is None:
            drift = SbertChromaDriftDetector()
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
            if hasattr(self._drift, "score_result"):
                drift_result = self._drift.score_result(record)
            else:
                d_score = self._drift.score(record)
                drift_result = DriftScore(
                    score=d_score,
                    baseline_key=behavior_baseline_key(record),
                    embedding_model="unknown",
                    collection="unknown",
                    baseline_count=0,
                )
            d = drift_result.score
            if d > 0.0:
                scores.append(d)
                reasons.append(
                    VerdictReason(
                        agent=Guardian.EVALUATOR,
                        label="evaluator.behavior_drift",
                        detail=(
                            f"drift score {d:.3f} vs benign baseline "
                            f"baseline_key={drift_result.baseline_key} "
                            f"embedding_model={drift_result.embedding_model} "
                            f"collection={drift_result.collection} "
                            f"baseline_count={drift_result.baseline_count}"
                        ),
                        score=d,
                        served_via=drift_result.served_via,
                    )
                )

        return EvaluatorResult(
            anomaly=max(scores) if scores else 0.0,
            reasons=reasons,
            structuring_or_exfil=structuring_or_exfil,
        )
