from __future__ import annotations

import pytest
from shield_governance.memory import (
    ChromaIncidentMemory,
    ChromaMemoryConfig,
    MemoryBackendUnavailable,
)
from shield_sdk.schema import ActionPayload, Decision, Phase, ShieldActionRecord


def _record(
    record_id: str,
    *,
    recipient: str = "attacker-iban",
    amount: float = 10_000.0,
) -> ShieldActionRecord:
    return ShieldActionRecord(
        record_id=record_id,
        correlation_id=f"corr-{record_id}",
        run_id="memory-test-run",
        phase=Phase.POST_EXEC,
        payload=ActionPayload(
            tool_name="send_money",
            tool_args={"recipient": recipient, "amount": amount, "subject": "fixture"},
        ),
    )


def test_chroma_memory_creates_collection_writes_and_queries_hits(tmp_path) -> None:
    memory = ChromaIncidentMemory(
        ChromaMemoryConfig(
            persist_directory=tmp_path,
            collection_name="agent_shield_incidents_test",
        )
    )
    prior = _record("rec-prior")
    current = _record("rec-current")

    memory.remember_record(
        prior,
        decision=Decision.BLOCK,
        reasons=("defender.single_transfer_cap", "evaluator.hallucination"),
    )
    result = memory.query_record(current, top_k=3)

    assert result.memory_backend == "chroma"
    assert result.collection == "agent_shield_incidents_test"
    assert result.hit_count == 1
    assert result.latency_ms >= 0
    assert result.hits[0].id == "rec-prior"
    assert 0.0 <= result.hits[0].score <= 1.0
    assert result.hits[0].distance >= 0.0


def test_chroma_memory_persists_collection_across_instances(tmp_path) -> None:
    config = ChromaMemoryConfig(
        persist_directory=tmp_path,
        collection_name="agent_shield_incidents_persistent_test",
    )
    first = ChromaIncidentMemory(config)
    first.remember_record(
        _record("rec-persisted", recipient="repeat-iban"),
        decision=Decision.ALERT,
        reasons=("evaluator.behavior_drift",),
    )

    second = ChromaIncidentMemory(config)
    result = second.query_record(_record("rec-query", recipient="repeat-iban"), top_k=1)

    assert result.memory_backend == "chroma"
    assert result.collection == "agent_shield_incidents_persistent_test"
    assert [hit.id for hit in result.hits] == ["rec-persisted"]


def test_chroma_memory_mode_fails_fast_without_persistent_directory() -> None:
    with pytest.raises(MemoryBackendUnavailable, match="persist_directory"):
        ChromaIncidentMemory(
            ChromaMemoryConfig(
                persist_directory=None,
                collection_name="agent_shield_incidents_missing_path_test",
            )
        )
