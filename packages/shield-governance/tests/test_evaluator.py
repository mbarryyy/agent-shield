"""Evaluator — real Invariant cross-step + exfil + hallucination; drift flag."""

from __future__ import annotations

import pytest
from shield_governance.evaluator import (
    BehaviorDriftConfigurationError,
    DriftScore,
    Evaluator,
    EvaluatorConfig,
    NullDriftDetector,
    NullHallucinationChecker,
    SbertChromaDriftDetector,
)
from shield_sdk.schema import ActionPayload, Phase, ShieldActionRecord, VerdictReason

ATT = "US133000000121212121212"


def _rec(i: int, *, subject: str = "Hacked!", run_id: str = "run-1") -> ShieldActionRecord:
    return ShieldActionRecord(
        run_id=run_id,
        step_index=i,
        phase=Phase.POST_EXEC,
        payload=ActionPayload(
            tool_name="send_money",
            tool_args={"recipient": ATT, "amount": 10000, "subject": subject},
        ),
    )


@pytest.mark.asyncio
async def test_invariant_cross_step_fires_on_3x_real_engine() -> None:
    """§5b: real invariant-ai 0.3.5 LocalPolicy count(min=3) via the Evaluator
    (ADR-0010 verified idiom) — fires on the 3rd structuring leg, not before."""
    ev = Evaluator(EvaluatorConfig(run_hallucination=False))
    r1 = await ev.evaluate(_rec(0))
    r2 = await ev.evaluate(_rec(1))
    r3 = await ev.evaluate(_rec(2))
    assert r1.structuring_or_exfil is False
    assert r2.structuring_or_exfil is False
    assert r3.structuring_or_exfil is True
    assert r3.anomaly == 1.0
    assert any(rr.label == "invariant.policy" for rr in r3.reasons)


@pytest.mark.asyncio
async def test_exfil_secret_subject_fires() -> None:
    ev = Evaluator(EvaluatorConfig(run_hallucination=False))
    r = await ev.evaluate(_rec(0, subject="the password is hunter2", run_id="rx"))
    assert r.structuring_or_exfil is True


@pytest.mark.asyncio
async def test_hallucination_injected_checker() -> None:
    class FakeHalluc:
        async def check(self, record, trace):  # type: ignore[no-untyped-def]
            return VerdictReason(label="evaluator.hallucination", score=0.7)

    ev = Evaluator(
        EvaluatorConfig(run_invariant=False),
        hallucination=FakeHalluc(),
    )
    r = await ev.evaluate(_rec(0, run_id="rh"))
    assert any(rr.label == "evaluator.hallucination" for rr in r.reasons)
    assert r.anomaly == pytest.approx(0.7)


@pytest.mark.asyncio
async def test_drift_subflag_off_is_noop() -> None:
    ev = Evaluator(EvaluatorConfig(run_invariant=False, run_hallucination=False))
    r = await ev.evaluate(_rec(0, run_id="rd"))
    assert r.anomaly == 0.0 and r.reasons == []
    assert NullDriftDetector().score(_rec(0)) == 0.0


def test_drift_enabled_without_resources_fails_fast() -> None:
    with pytest.raises(BehaviorDriftConfigurationError, match="requires"):
        SbertChromaDriftDetector()
    with pytest.raises(BehaviorDriftConfigurationError, match="requires"):
        Evaluator(EvaluatorConfig(drift_enabled=True, run_invariant=False))


def test_sbert_chroma_drift_scores_against_fake_baseline() -> None:
    class FakeEmbedder:
        def encode(self, texts: list[str]) -> list[list[float]]:
            out: list[list[float]] = []
            for text in texts:
                if "invoice" in text.lower():
                    out.append([1.0, 0.0])
                else:
                    out.append([0.0, 1.0])
            return out

    class FakeCollection:
        def __init__(self) -> None:
            self.rows: list[tuple[str, list[float], dict[str, str], str]] = []

        def add(
            self,
            *,
            ids: list[str],
            embeddings: list[list[float]],
            metadatas: list[dict[str, str]],
            documents: list[str],
        ) -> None:
            self.rows.extend(zip(ids, embeddings, metadatas, documents, strict=True))

        def get(self, *, where: dict[str, str], include: list[str]) -> dict[str, object]:
            rows = [row for row in self.rows if row[2].get("baseline_key") == where["baseline_key"]]
            return {"ids": [r[0] for r in rows], "embeddings": [r[1] for r in rows]}

    detector = SbertChromaDriftDetector(embedder=FakeEmbedder(), collection=FakeCollection())
    detector.add_baseline(_rec(0, subject="invoice payment", run_id="baseline"))
    score = detector.score_result(_rec(1, subject="password exfil", run_id="current"))

    assert isinstance(score, DriftScore)
    assert score.score == pytest.approx(1.0)
    assert score.baseline_key == "demo-org/agentdojo-banking-v1/banking/send_money"
    assert score.embedding_model == "sentence-transformers/all-MiniLM-L6-v2"
    assert score.collection == "behavior_baselines"
    assert score.baseline_count == 1


@pytest.mark.asyncio
async def test_drift_enabled_adds_behavior_drift_reason() -> None:
    class FixedDrift:
        def score_result(self, record: ShieldActionRecord) -> DriftScore:
            return DriftScore(
                score=0.42,
                baseline_key="org/agent/workflow/tool",
                embedding_model="fake-embedder",
                collection="behavior_baselines",
                baseline_count=3,
            )

        def score(self, record: ShieldActionRecord) -> float:
            return self.score_result(record).score

    ev = Evaluator(
        EvaluatorConfig(run_invariant=False, run_hallucination=False, drift_enabled=True),
        drift=FixedDrift(),
    )
    r = await ev.evaluate(_rec(0, run_id="rd-on"))
    assert r.anomaly == pytest.approx(0.42)
    reason = next(rr for rr in r.reasons if rr.label == "evaluator.behavior_drift")
    assert "baseline_count=3" in (reason.detail or "")


@pytest.mark.asyncio
async def test_clean_call_no_anomaly() -> None:
    ev = Evaluator(EvaluatorConfig(run_hallucination=False))
    r = await ev.evaluate(
        ShieldActionRecord(
            run_id="rc",
            phase=Phase.PRE_EXEC,
            payload=ActionPayload(tool_name="get_balance", tool_args={}),
        )
    )
    assert r.anomaly == 0.0
    assert r.structuring_or_exfil is False
    assert isinstance(NullHallucinationChecker(), NullHallucinationChecker)
