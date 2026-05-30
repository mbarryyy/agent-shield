"""Deterministic core of ``reflect_recent_memory`` (governance_design §3.2).

AgentSafe ``ReviewMemory`` re-implemented, fixing its three gaps: a real
scheduler-driven window re-scan (the caller schedules), QUARANTINE (a structured
label) rather than ``.replace()``-delete, and a STRUCTURED reason match rather
than a ``"unreasonable" in text`` substring heuristic.

This module is the model-free core: re-scan a recent window of stored incidents
and flag (quarantine) the ones that slipped through (decided PASS/ALERT) yet
carry a late-surfacing poison signal in their recorded reasons. The optional
per-item LLM re-judge is a clean injectable seam (``llm_rejudge=``) that is
DEFERRED to the keyed sub-wave — it is accepted but NEVER called here (no stub,
no fake; just not invoked).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

#: Recorded guardian-reason prefixes that indicate a late-surfacing poison
#: signal (anomaly/drift/hallucination/exfil/structuring). A record that was
#: nonetheless let through (PASS/ALERT) and carries one of these is the
#: AgentSafe "review memory" target — quarantine it for human/LLM re-review.
LATE_POISON_REASON_PREFIXES: tuple[str, ...] = (
    "evaluator.behavior_drift",
    "evaluator.hallucination",
    "evaluator.peer_relative_anomaly",
    "invariant.",
    "subject.secret",
    "cumulative.structuring",
)

#: Decisions that mean the record was NOT hard-stopped — i.e. it slipped
#: through and a late poison signal makes it a re-review candidate.
_SLIPPED_THROUGH = frozenset({"PASS", "ALERT"})


@runtime_checkable
class _RecentRecordSource(Protocol):
    def recent_records(self, *, limit: int) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class QuarantinedIncident:
    record_id: str
    decision: str
    label: str
    matched_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReflectionResult:
    scanned: int
    quarantined: tuple[QuarantinedIncident, ...]


def _matched_late_poison(reasons: list[str]) -> tuple[str, ...]:
    return tuple(r for r in reasons if any(r.startswith(p) for p in LATE_POISON_REASON_PREFIXES))


def reflect_recent_memory(
    memory: _RecentRecordSource,
    *,
    window: int = 50,
    llm_rejudge: Callable[[QuarantinedIncident], bool] | None = None,
) -> ReflectionResult:
    """Deterministically re-scan the most recent ``window`` incidents and
    quarantine slipped-through records carrying a late poison signal.

    ``llm_rejudge`` is a deferred seam (keyed sub-wave): when provided it is the
    per-item LLM re-judge callable, but the deterministic core does NOT call it
    — it is accepted for forward-compatible wiring only. No model, no network.
    """
    _ = llm_rejudge  # deferred LLM re-judge seam — intentionally NOT invoked.
    rows = memory.recent_records(limit=window)
    quarantined: list[QuarantinedIncident] = []
    for row in rows:
        decision = str(row.get("decision", ""))
        reasons = [r for r in str(row.get("reasons", "")).split(",") if r]
        if decision not in _SLIPPED_THROUGH:
            continue
        matched = _matched_late_poison(reasons)
        if matched:
            quarantined.append(
                QuarantinedIncident(
                    record_id=str(row.get("record_id", "")),
                    decision=decision,
                    label="reflect.late_poison",
                    matched_reasons=matched,
                )
            )
    return ReflectionResult(scanned=len(rows), quarantined=tuple(quarantined))
