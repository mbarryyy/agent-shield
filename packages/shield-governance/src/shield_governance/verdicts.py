"""Async verdict handoff helpers.

Governance computes unsigned async verdicts. The shield server owns signing,
storage, and `shield:verdicts:{workflow_id}` publication, so this module only
builds the server-ready handoff/envelope and contains no Redis publisher.
"""

from __future__ import annotations

from dataclasses import dataclass

from shield_sdk.schema import GovernanceVerdict, ShieldActionRecord

from shield_governance.evidence import GuardianEvidence

DEFAULT_VERDICTS_PREFIX = "shield:verdicts"


def verdict_stream_key(workflow_id: str, *, prefix: str = DEFAULT_VERDICTS_PREFIX) -> str:
    """Return the server-owned verdict stream key for callers that need labels."""
    return f"{prefix}:{workflow_id}"


def verdict_fields(verdict: GovernanceVerdict, *, phase: str) -> dict[str, str]:
    """Server PR-S3 flat 8-field envelope with string values.

    This is a pure serialization helper. It does not sign, store, or publish.
    """
    return {
        "verdict_id": verdict.verdict_id,
        "record_id": verdict.record_id or "",
        "correlation_id": verdict.correlation_id,
        "run_id": verdict.run_id or "",
        "decision": verdict.decision.value,
        "risk_score": str(verdict.risk_score),
        "phase": phase,
        "verdict": verdict.model_dump_json(),
    }


@dataclass(frozen=True, slots=True)
class AsyncVerdictHandoff:
    """Unsigned async verdict plus the record context the server needs to sign."""

    workflow_id: str
    phase: str
    record: ShieldActionRecord
    verdict: GovernanceVerdict
    guardian_evidence: tuple[GuardianEvidence, ...] = ()

    @classmethod
    def from_record(
        cls,
        record: ShieldActionRecord,
        verdict: GovernanceVerdict,
        *,
        guardian_evidence: tuple[GuardianEvidence, ...] = (),
    ) -> AsyncVerdictHandoff:
        normalized = verdict.model_copy(
            update={
                "record_id": record.record_id,
                "correlation_id": record.correlation_id,
                "run_id": record.run_id,
                "signature_by_shield": None,
                "shield_kid": None,
            }
        )
        return cls(
            workflow_id=record.workflow_id,
            phase=record.phase.value,
            record=record,
            verdict=normalized,
            guardian_evidence=guardian_evidence,
        )

    def server_fields(self) -> dict[str, str]:
        return verdict_fields(self.verdict, phase=self.phase)
