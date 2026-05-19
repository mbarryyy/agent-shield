"""Per-tool fail-open / fail-CLOSED policy table — runtime config.

Ratified (00_integration_conflicts closure rule; master_design §6
"Fail-open vs fail-CLOSED"): on a 500 ms `/decide` timeout / Layer-2-down,
the **default is fail-open → synthetic `ALERT` (WARN)** so the demo stays
live, but the money/credential tools are **fail-CLOSED → synthetic `BLOCK`**
(a slow/silent Layer-2 must NOT silently allow the malicious transfer).

`FailPolicy` is a pydantic model ⇒ loadable from runtime config (dict / JSON /
env) and parametrized contract-tested. `FailPolicy.ratified()` is the locked
default table.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .schema import Decision, GovernanceVerdict, Guardian, ShieldActionRecord, VerdictReason


class FailMode(StrEnum):
    OPEN = "open"  # degraded -> synthetic ALERT(WARN); the call proceeds, flagged
    CLOSED = "closed"  # degraded -> synthetic BLOCK; the call is stopped


# The ratified fail-CLOSED tools (master_design §6 / closure rule).
FAIL_CLOSED_TOOLS: tuple[str, ...] = (
    "send_money",
    "update_password",
    "update_scheduled_transaction",
)


class FailPolicy(BaseModel):
    """Runtime-loadable per-tool fail policy table."""

    model_config = ConfigDict(extra="forbid")

    default: FailMode = FailMode.OPEN
    overrides: dict[str, FailMode] = Field(default_factory=dict)

    @classmethod
    def ratified(cls) -> FailPolicy:
        """The locked default: fail-open everywhere, fail-CLOSED for the 3
        money/credential tools."""
        return cls(
            default=FailMode.OPEN,
            overrides={t: FailMode.CLOSED for t in FAIL_CLOSED_TOOLS},
        )

    def fail_mode_for(self, tool_name: str) -> FailMode:
        return self.overrides.get(tool_name, self.default)


def synthetic_degraded_verdict(
    record: ShieldActionRecord, mode: FailMode, *, detail: str
) -> GovernanceVerdict:
    """The local degraded verdict synthesized when the gate budget is blown.

    It is NOT server-signed (`signature_by_shield` stays None) — it is a local
    Layer-1 degradation, intentionally distinguishable from a real signed
    Layer-2 verdict on the audit stream.
    """
    if mode is FailMode.OPEN:
        decision, label, risk = Decision.ALERT, "shield-degraded-warn", 0.0
    else:
        decision, label, risk = Decision.BLOCK, "shield-degraded-fail-closed", 1.0
    return GovernanceVerdict(
        record_id=record.record_id,
        correlation_id=record.correlation_id,
        run_id=record.run_id,
        decision=decision,
        risk_score=risk,
        reasons=[VerdictReason(agent=Guardian.DEFENDER, label=label, detail=detail)],
    )
