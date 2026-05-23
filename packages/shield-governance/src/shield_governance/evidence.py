"""Governance-owned per-guardian evidence rows.

The server owns persistence. This module owns the in-process evidence structure
that router-backed guardians can hand across the async verdict seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from shield_sdk.schema import Decision, Guardian, ServedVia, ShieldActionRecord


@dataclass(frozen=True, slots=True)
class GuardianEvidence:
    """One guardian decision row for eval/console/server sinks."""

    record_id: str
    correlation_id: str
    guardian: Guardian
    decision: Decision
    reasons: tuple[str, ...]
    model_id: str | None
    served_via: ServedVia | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0


class GuardianEvidenceRecorder:
    """Thread-safe accumulator keyed by ShieldActionRecord identity."""

    def __init__(self) -> None:
        self._rows: list[GuardianEvidence] = []
        self._lock = Lock()

    def record(self, row: GuardianEvidence) -> GuardianEvidence:
        with self._lock:
            self._rows.append(row)
        return row

    def record_for_record(
        self,
        record: ShieldActionRecord,
        *,
        guardian: Guardian,
        decision: Decision,
        reasons: tuple[str, ...] | list[str],
        model_id: str | None,
        served_via: ServedVia | None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: float = 0.0,
        cost_usd: float = 0.0,
    ) -> GuardianEvidence:
        return self.record(
            GuardianEvidence(
                record_id=record.record_id,
                correlation_id=record.correlation_id,
                guardian=guardian,
                decision=decision,
                reasons=tuple(reasons),
                model_id=model_id,
                served_via=served_via,
                prompt_tokens=max(0, int(prompt_tokens)),
                completion_tokens=max(0, int(completion_tokens)),
                latency_ms=max(0.0, float(latency_ms)),
                cost_usd=max(0.0, float(cost_usd)),
            )
        )

    def for_record(self, record_id: str) -> tuple[GuardianEvidence, ...]:
        with self._lock:
            return tuple(row for row in self._rows if row.record_id == record_id)

    def has_guardian(self, record_id: str, guardian: Guardian) -> bool:
        with self._lock:
            return any(
                row.record_id == record_id and row.guardian is guardian for row in self._rows
            )

    def reset(self) -> None:
        with self._lock:
            self._rows.clear()
