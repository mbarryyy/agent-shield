"""shield_sdk.schema — the SINGLE source of truth for the FROZEN §4 contract.

W0 STATUS: importable STUB so server/governance/eval/console compile day 1.
Field set is sourced from `Research/02_sdk_layer/sdk_layer_design.md` §4 (read
first-hand by sdk-builder). sdk-builder FINALIZES and FREEZES this at W1 as
`shield_version` 1.1 — the §4 baseline INCLUDING the three optional cost fields
(`GovernanceVerdict.reasons[].model_id`, `.served_via`, `obligations.prevented_loss`)
— and regenerates `contracts/*.schema.json`. The 1.0→1.1 MINOR bump is the one
planned all-owner contract ritual (ADR-0007), executed once at W1 BEFORE any
consumer builds. Do NOT treat this stub as the frozen contract.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

SHIELD_VERSION = "1.1"


class Phase(StrEnum):
    PRE_EXEC = "pre_exec"
    POST_EXEC = "post_exec"


class Decision(StrEnum):
    PASS = "PASS"
    ALERT = "ALERT"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"
    ROLLBACK = "ROLLBACK"
    REWRITE = "REWRITE"


class ServedVia(StrEnum):
    CLOUD = "cloud"
    LOCAL = "local"


class Guardian(StrEnum):
    DEFENDER = "defender"
    EVALUATOR = "evaluator"
    SUPERVISOR = "supervisor"
    AUDITOR = "auditor"


class LLMUsage(BaseModel):
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ActionContext(BaseModel):
    checkpoint_id: str | None = None
    langgraph_thread_id: str | None = None
    env_snapshot_ref: str | None = None


class ActionPayload(BaseModel):
    llm: LLMUsage = Field(default_factory=LLMUsage)


class ShieldActionRecord(BaseModel):
    """Two-phase tamper-evident action record. STUB — frozen at W1 v1.1."""

    shield_version: str = SHIELD_VERSION
    phase: Phase
    correlation_id: str
    run_id: str
    step_index: int = 0
    issued_at: str | None = None
    nonce: str | None = None
    tool_name: str | None = None
    args_digest: str | None = None
    payload: ActionPayload = Field(default_factory=ActionPayload)
    payload_hash: str
    prev_chain_hash: str | None = None
    chain_hash: str | None = None  # server-derived; never trusted from client
    tool_result: object | None = None
    verdict_ref: str | None = None
    context: ActionContext = Field(default_factory=ActionContext)
    signature: str | None = None


class VerdictReason(BaseModel):
    code: str
    message: str | None = None
    guardian: Guardian | None = None
    model_id: str | None = None  # v1.1 cost field
    served_via: ServedVia | None = None  # v1.1 cost field


class RollbackObligation(BaseModel):
    langgraph_checkpoint_id: str | None = None
    env_snapshot_ref: str | None = None


class Obligations(BaseModel):
    rewrite_args: dict[str, object] | None = None
    mask_args: list[str] | None = None
    require_human: bool | None = None
    rollback: RollbackObligation | None = None
    prevented_loss: float | None = None  # v1.1 cost field ($ prevented)


class GovernanceVerdict(BaseModel):
    """Synchronous verdict returned by POST /v1/governance/decide. STUB — frozen W1 v1.1."""

    shield_version: str = SHIELD_VERSION
    decision: Decision
    correlation_id: str
    risk_score: float = 0.0
    confidence: float | None = None
    reasons: list[VerdictReason] = Field(default_factory=list)
    obligations: Obligations = Field(default_factory=Obligations)
    latency_ms: float | None = None
