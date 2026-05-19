"""REST DTOs — pydantic mirrors of Elydora
`packages/server/src/shared/types/{protocol,entities,enums,api}.ts`.

These are the server-internal representation; their JSON serialization must
byte-match the console's `@elydora/shared` types. The canonical JSON-Schema for
those console types is generated into `contracts/elydora/` by sdk-builder +
console-builder (CODEOWNERS-gated; NOT edited here) from the SAME upstream
`shared/types/*.ts`, so both sides derive from one source and stay aligned.
Field names/types/optionality are kept verbatim with upstream.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --- enums.ts ---
AgentStatus = Literal["active", "frozen", "revoked"]
KeyStatus = Literal["active", "retired", "revoked"]
ExportStatus = Literal["queued", "running", "done", "failed"]


# --- protocol.ts: EOR (the submitted, signed operation record) ---
class OperationRecord(BaseModel):
    """Elydora EOR. Lenient typing so the *Elydora* semantic validator (not
    pydantic) emits the canonical VALIDATION_ERROR codes the console expects."""

    model_config = ConfigDict(extra="ignore")

    op_version: str = ""
    operation_id: str = ""
    org_id: str = ""
    agent_id: str = ""
    issued_at: int = 0
    ttl_ms: int = -1
    nonce: str = ""
    operation_type: str = ""
    subject: dict[str, Any] = Field(default_factory=dict)
    action: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] | str | None = None
    payload_hash: str = ""
    prev_chain_hash: str = ""
    agent_pubkey_kid: str = ""
    signature: str = ""


# --- protocol.ts: EAR (server receipt) ---
class EAR(BaseModel):
    receipt_version: str
    receipt_id: str
    operation_id: str
    org_id: str
    agent_id: str
    server_received_at: int
    seq_no: int
    chain_hash: str
    queue_message_id: str
    receipt_hash: str
    elydora_kid: str
    elydora_signature: str


# --- entities.ts ---
class Agent(BaseModel):
    agent_id: str
    org_id: str
    display_name: str
    responsible_entity: str
    integration_type: str
    status: AgentStatus
    created_at: int
    updated_at: int


class AgentKey(BaseModel):
    kid: str
    agent_id: str
    public_key: str
    algorithm: Literal["ed25519"] = "ed25519"
    status: KeyStatus
    created_at: int
    retired_at: int | None = None


class Operation(BaseModel):
    operation_id: str
    org_id: str
    agent_id: str
    seq_no: int
    operation_type: str
    issued_at: int
    ttl_ms: int
    nonce: str
    subject: str
    action: str
    payload_hash: str
    prev_chain_hash: str
    chain_hash: str
    agent_pubkey_kid: str
    signature: str
    r2_payload_key: str | None = None
    created_at: int


class Receipt(BaseModel):
    receipt_id: str
    operation_id: str
    r2_receipt_key: str
    created_at: int


# --- api.ts request/response ---
class RegisterAgentKey(BaseModel):
    kid: str
    public_key: str
    algorithm: Literal["ed25519"] = "ed25519"


class RegisterAgentRequest(BaseModel):
    agent_id: str
    display_name: str | None = None
    responsible_entity: str | None = None
    integration_type: str | None = None
    keys: list[RegisterAgentKey] = Field(default_factory=list)


class RegisterAgentResponse(BaseModel):
    agent: Agent
    keys: list[AgentKey]


class GetAgentResponse(BaseModel):
    agent: Agent
    keys: list[AgentKey]


class ListAgentsResponse(BaseModel):
    agents: list[Agent]


class UpdateAgentRequest(BaseModel):
    integration_type: str


class FreezeAgentRequest(BaseModel):
    reason: str


class UnfreezeAgentRequest(BaseModel):
    reason: str


class RevokeAgentRequest(BaseModel):
    kid: str
    reason: str


class SubmitOperationResponse(BaseModel):
    receipt: EAR


class GetOperationResponse(BaseModel):
    operation: Operation
    receipt: Receipt | None = None
    payload: dict[str, Any] | None = None


class VerifyChecks(BaseModel):
    signature: bool
    chain: bool
    receipt: bool
    merkle: bool | None = None


class VerifyOperationResponse(BaseModel):
    valid: bool
    checks: VerifyChecks
    errors: list[str] | None = None


class AuditQueryRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    org_id: str | None = None
    agent_id: str | None = None
    operation_type: str | None = None
    start_time: int | None = None
    end_time: int | None = None
    cursor: str | None = None
    limit: int | None = None


class AuditQueryResponse(BaseModel):
    operations: list[Operation]
    cursor: str | None = None
    total_count: int


# --- entities.ts: Epoch / Export + their api.ts envelopes ---
class Epoch(BaseModel):
    epoch_id: str
    org_id: str
    start_time: int
    end_time: int
    root_hash: str
    leaf_count: int
    r2_epoch_key: str
    created_at: int


class ListEpochsResponse(BaseModel):
    epochs: list[Epoch]


class ExportModel(BaseModel):
    export_id: str
    org_id: str
    status: ExportStatus
    query_params: str
    r2_export_key: str | None = None
    created_at: int
    completed_at: int | None = None


class ListExportsResponse(BaseModel):
    exports: list[ExportModel]


class CreateExportResponseModel(BaseModel):
    export: ExportModel


class GetExportResponseModel(BaseModel):
    export: ExportModel
    download_url: str | None = None


# --- api.ts: JWKS + auth ---
class JWK(BaseModel):
    kty: str
    crv: str | None = None
    x: str | None = None
    kid: str
    use: str
    alg: str


class JWKSResponse(BaseModel):
    keys: list[JWK]


class IssueTokenResponseModel(BaseModel):
    token: str
    expires_at: int | None = None


# --- W3 PR-S2: console governance READ contract (additive /v1/governance/*).
# console-pact typed; NOT a frozen-§4 contracts/*.schema.json change. The
# verdict/record bodies are the FROZEN §4 types (shield_sdk.schema), carried
# opaque (dict) so this module never duplicates/redefines a §4 type.


class TimelineRow(BaseModel):
    """One gate decision in a run's live-monitor feed."""

    verdict_id: str
    record_id: str
    correlation_id: str
    run_id: str | None = None
    decision: str
    risk_score: float
    latency_ms: float | None = None
    created_at: int


class TimelineResponse(BaseModel):
    rows: list[TimelineRow]
    cursor: str | None = None
    total_count: int


class VerdictView(BaseModel):
    """Verdict tab: the signed §4 GovernanceVerdict + the paired pre/post §4
    ShieldActionRecord envelopes — all opaque (frozen §4, not redefined)."""

    correlation_id: str
    verdict: dict[str, Any] | None = None
    pre_exec: dict[str, Any] | None = None
    post_exec: dict[str, Any] | None = None


class ProvenanceNode(BaseModel):
    record_id: str
    phase: str | None = None
    correlation_id: str | None = None
    decision: str | None = None
    seq_no: int
    chain_hash: str


class ProvenanceEdge(BaseModel):
    src: str
    dst: str
    kind: Literal["chain", "correlation"]


class ProvenanceGraph(BaseModel):
    run_id: str
    nodes: list[ProvenanceNode]
    edges: list[ProvenanceEdge]
