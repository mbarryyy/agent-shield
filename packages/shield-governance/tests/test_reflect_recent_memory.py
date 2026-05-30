"""Wave-2 chunk #3c: deterministic core of ``reflect_recent_memory`` (no LLM).

governance_design §3.2 (AgentSafe ReviewMemory re-impl): periodically re-scan a
recent-incident window for late-surfacing poison, with a scheduler + quarantine
+ structured label (fixing AgentSafe's 3 gaps: real scheduler, quarantine not
delete, structured label not substring match). This builds the DETERMINISTIC
core: window-rescan over the incidents Chroma collection + structured
quarantine result. The optional per-item LLM re-judge is a clean seam
(``llm_rejudge=`` param) that is DEFERRED to the keyed sub-wave and never called
here. All against a real local Chroma (tmp dir, no key, no spend).
"""

from __future__ import annotations

from shield_governance.memory import (
    ChromaVectorStore,
    ChromaVectorStoreConfig,
)
from shield_governance.memory.reflect import (
    ReflectionResult,
    reflect_recent_memory,
)
from shield_sdk.schema import ActionPayload, Decision, Phase, ShieldActionRecord


def _record(record_id: str, *, recipient: str = "a", amount: float = 100.0) -> ShieldActionRecord:
    return ShieldActionRecord(
        record_id=record_id,
        correlation_id=f"corr-{record_id}",
        run_id="reflect-run",
        phase=Phase.POST_EXEC,
        payload=ActionPayload(
            tool_name="send_money",
            tool_args={"recipient": recipient, "amount": amount, "subject": "x"},
        ),
    )


def _memory(tmp_path):
    return ChromaVectorStore(ChromaVectorStoreConfig(persist_directory=tmp_path)).incident_memory()


def test_reflect_empty_collection_quarantines_nothing(tmp_path) -> None:
    result = reflect_recent_memory(_memory(tmp_path), window=10)
    assert isinstance(result, ReflectionResult)
    assert result.scanned == 0
    assert result.quarantined == ()


def test_reflect_quarantines_late_poison_signal(tmp_path) -> None:
    mem = _memory(tmp_path)
    # A record that was let through (ALERT) but carries a late drift/halluc
    # signal in its reasons → should be quarantined on re-scan.
    mem.remember_record(
        _record("poison-1", recipient="attacker"),
        decision=Decision.ALERT,
        reasons=("evaluator.behavior_drift",),
    )
    # A clean record that passed → not quarantined.
    mem.remember_record(
        _record("clean-1"),
        decision=Decision.PASS,
        reasons=("supervisor.clean",),
    )
    result = reflect_recent_memory(mem, window=10)
    assert result.scanned == 2
    quarantined_ids = {item.record_id for item in result.quarantined}
    assert "poison-1" in quarantined_ids
    assert "clean-1" not in quarantined_ids
    poison = next(i for i in result.quarantined if i.record_id == "poison-1")
    assert poison.label == "reflect.late_poison"
    assert "evaluator.behavior_drift" in poison.matched_reasons


def test_reflect_blocked_record_not_re_quarantined(tmp_path) -> None:
    mem = _memory(tmp_path)
    # Already BLOCKed with a poison reason → it was handled, not a LATE signal,
    # so it is not re-quarantined (we quarantine slipped-through PASS/ALERT only).
    mem.remember_record(
        _record("blocked-1", recipient="attacker"),
        decision=Decision.BLOCK,
        reasons=("evaluator.behavior_drift",),
    )
    result = reflect_recent_memory(mem, window=10)
    assert result.scanned == 1
    assert result.quarantined == ()


def test_reflect_respects_window_size(tmp_path) -> None:
    mem = _memory(tmp_path)
    for i in range(5):
        mem.remember_record(
            _record(f"rec-{i}", recipient="attacker"),
            decision=Decision.ALERT,
            reasons=("evaluator.hallucination",),
        )
    result = reflect_recent_memory(mem, window=3)
    assert result.scanned == 3


def test_reflect_llm_rejudge_seam_present_but_not_called(tmp_path) -> None:
    mem = _memory(tmp_path)
    mem.remember_record(
        _record("p"),
        decision=Decision.ALERT,
        reasons=("evaluator.behavior_drift",),
    )
    calls: list[object] = []

    def _rejudge(item: object) -> bool:  # pragma: no cover - must NOT be called
        calls.append(item)
        return True

    # The seam EXISTS (accepted as a param) but the deterministic core does not
    # invoke it — the LLM re-judge is deferred to the keyed sub-wave.
    result = reflect_recent_memory(mem, window=10, llm_rejudge=_rejudge)
    assert calls == []
    assert any(i.record_id == "p" for i in result.quarantined)
