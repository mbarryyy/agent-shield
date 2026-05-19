"""shield_sdk.schema — the SINGLE source of truth for the FROZEN §4 contract.

This is the W1 FREEZE at ``shield_version`` **1.1**: the §4 baseline of
``sdk_layer_design.md`` (read first-hand by sdk-builder) *including* the three
optional cost fields that are the planned 1.0 -> 1.1 MINOR evolution
(C11 / ADR-0007):

  * ``GovernanceVerdict.reasons[].model_id``
  * ``GovernanceVerdict.reasons[].served_via``
  * ``GovernanceVerdict.obligations.prevented_loss``

server / governance / eval / console **import these models and never
re-declare them** — drift is impossible by construction. The JSON-Schema
snapshots in ``contracts/`` are regenerated from these models; that snapshot
regen + the 1.0 -> 1.1 bump land via the dedicated all-owner ADR-0007
contract-ritual PR (team-lead), NOT inside the SDK feature PR.

All closed models set ``extra="forbid"`` so the generated JSON Schema is
``additionalProperties: false`` (O5 — the snapshot-diff firewall must bite).
Genuinely open maps (``subject``, ``payload.tool_args``) are typed
``dict[str, Any]`` and remain open by design (tool arguments vary per tool).

Stub corrections applied at the W1 freeze (vs the W0 compile-unblock stub),
all to match §4 which is the sole source of truth — reported to team-lead for
the ADR-0007 ritual:
  * ``ShieldActionRecord.issued_at``: ``str`` -> ``int`` unix-epoch-ms
    (§4 line 129; required for byte-exact chain_hash with Elydora/server).
  * ``GovernanceVerdict.reasons[]``: ``code/message/guardian`` ->
    ``label/detail/agent`` + ``score`` (§4.2 field names).
  * ``GovernanceVerdict``: dropped speculative ``confidence`` (not in §4.2);
    added §4.2 ``verdict_id/record_id/run_id/served_at/shield_kid/
    signature_by_shield``.
  * Full §4.1 record field set modelled (record_id, org/agent/workflow ids,
    ttl_ms, action_type, subject, action, agent_pubkey_kid, ...).
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .crypto import GENESIS_CHAIN_HASH, generate_nonce, generate_uuidv7

SHIELD_VERSION = "1.1"


def _now_ms() -> int:
    return int(time.time() * 1000)


# --------------------------------------------------------------------------- #
# Enumerations (§4.1 / §4.2)
# --------------------------------------------------------------------------- #


class Phase(StrEnum):
    PRE_EXEC = "pre_exec"
    POST_EXEC = "post_exec"


class ActionType(StrEnum):
    TOOL_CALL = "tool_call"
    LLM_INFERENCE = "llm_inference"
    DECISION = "decision"
    CHECKPOINT = "checkpoint"
    ESCALATION = "escalation"


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


# --------------------------------------------------------------------------- #
# ShieldActionRecord (§4.1) — one per-agent hash chain, two phases
# --------------------------------------------------------------------------- #


class LLMUsage(BaseModel):
    """Per-action LLM token attribution (commercial cost hook #1; eval TO)."""

    model_config = ConfigDict(extra="forbid")

    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ActionContext(BaseModel):
    """Dual-substrate rollback keys (C2 resolution, first-class in §4.1)."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str | None = None
    langgraph_thread_id: str | None = None
    env_snapshot_ref: str | None = None


class ActionRef(BaseModel):
    """``action`` (§4.1): the tool + a digest of its args."""

    model_config = ConfigDict(extra="forbid")

    tool: str | None = None
    args_digest: str | None = None


class ActionPayload(BaseModel):
    """``payload`` (§4.1): JCS-hashed, object-stored. ``tool_args`` is open."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str | None = None
    tool_args: dict[str, Any] = Field(default_factory=dict)
    tool_result: Any | None = None
    tool_error: str | None = None
    llm: LLMUsage | None = None
    confidence: float | None = None


class ShieldActionRecord(BaseModel):
    """Two-phase tamper-evident action record. FROZEN §4.1 baseline, v1.1.

    ``chain_hash`` is server-derived and never trusted from / signed by the
    client; it is excluded from the signable projection (see
    ``shield_sdk.canonical``).
    """

    model_config = ConfigDict(extra="forbid")

    shield_version: str = SHIELD_VERSION

    record_id: str = Field(default_factory=generate_uuidv7)  # == Elydora operation_id
    correlation_id: str = Field(default_factory=generate_uuidv7)
    org_id: str = "demo-org"
    agent_id: str = "agentdojo-banking-v1"
    workflow_id: str = "banking"
    run_id: str
    step_index: int = Field(default=0, ge=0)

    issued_at: int = Field(default_factory=_now_ms)  # unix epoch ms (§4 line 129)
    ttl_ms: int = 30000
    nonce: str = Field(default_factory=generate_nonce)

    phase: Phase
    action_type: ActionType = ActionType.TOOL_CALL
    operation_type: str = "tool_call"  # Elydora-compat mirror

    subject: dict[str, Any] = Field(default_factory=dict)  # open (scenario-specific)
    action: ActionRef = Field(default_factory=ActionRef)
    payload: ActionPayload = Field(default_factory=ActionPayload)
    context: ActionContext = Field(default_factory=ActionContext)

    payload_hash: str = ""
    prev_chain_hash: str = GENESIS_CHAIN_HASH
    chain_hash: str | None = None  # server-derived ONLY; never signed/trusted

    agent_pubkey_kid: str = "agentdojo-banking-v1-key-v1"
    verdict_ref: str | None = None  # post_exec: verdict_id of the matching gate
    signature: str | None = None  # b64url Ed25519 over JCS(record − sig − chain_hash)


# --------------------------------------------------------------------------- #
# GovernanceVerdict (§4.2) — Layer-2 -> Layer-1, signed by the shield server
# --------------------------------------------------------------------------- #


class VerdictReason(BaseModel):
    """One per-guardian reason. ``model_id``/``served_via`` are v1.1 cost
    fields (C11 / ADR-0007)."""

    model_config = ConfigDict(extra="forbid")

    agent: Guardian | None = None
    label: str
    detail: str | None = None
    score: float | None = None
    model_id: str | None = None  # v1.1 cost field
    served_via: ServedVia | None = None  # v1.1 cost field


class RollbackObligation(BaseModel):
    """Dual-substrate rollback target (C2): BOTH fire on a ROLLBACK verdict."""

    model_config = ConfigDict(extra="forbid")

    langgraph_checkpoint_id: str | None = None
    env_snapshot_ref: str | None = None


class Obligations(BaseModel):
    """Locally-enforced obligations. ``prevented_loss`` is a v1.1 cost field."""

    model_config = ConfigDict(extra="forbid")

    mask_args: list[str] | None = None
    rewrite_args: dict[str, Any] | None = None
    require_human: bool | None = None
    rollback: RollbackObligation | None = None
    prevented_loss: float | None = None  # v1.1 cost field ($ value prevented)


class GovernanceVerdict(BaseModel):
    """Synchronous verdict returned by ``POST /v1/governance/decide``.

    FROZEN §4.2 baseline, v1.1. Signed by the shield server key
    (``signature_by_shield``), offline-verifiable like an Elydora EAR; the
    signable projection excludes ``signature_by_shield`` only.
    """

    model_config = ConfigDict(extra="forbid")

    shield_version: str = SHIELD_VERSION

    verdict_id: str = Field(default_factory=generate_uuidv7)
    record_id: str | None = None  # the pre_exec record this judges
    correlation_id: str
    run_id: str | None = None

    decision: Decision
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    reasons: list[VerdictReason] = Field(default_factory=list)
    obligations: Obligations = Field(default_factory=Obligations)

    latency_ms: float | None = None
    served_at: int | None = None  # unix epoch ms
    shield_kid: str | None = None
    signature_by_shield: str | None = None  # b64url Ed25519 over JCS(verdict − sig)
