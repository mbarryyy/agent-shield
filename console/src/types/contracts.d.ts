// AUTO-GENERATED from contracts/*.schema.json — DO NOT EDIT.
// Regenerate: (cd contracts/codegen && npm run gen). Source of truth = contracts/.
export type AgentStatus = "active" | "frozen" | "revoked";
export type KeyStatus = "active" | "retired" | "revoked";
export type ExportStatus = "queued" | "running" | "done" | "failed";
export type AdminAction =
  | "agent.register"
  | "agent.update"
  | "agent.freeze"
  | "agent.unfreeze"
  | "agent.revoke"
  | "agent.delete"
  | "key.revoke"
  | "export.create";
export type RbacRole =
  | "org_owner"
  | "security_admin"
  | "compliance_auditor"
  | "readonly_investigator"
  | "integration_engineer";
export type ErrorCode =
  | "INVALID_SIGNATURE"
  | "UNKNOWN_AGENT"
  | "KEY_REVOKED"
  | "AGENT_FROZEN"
  | "TTL_EXPIRED"
  | "REPLAY_DETECTED"
  | "PREV_HASH_MISMATCH"
  | "PAYLOAD_TOO_LARGE"
  | "RATE_LIMITED"
  | "INTERNAL_ERROR"
  | "UNAUTHORIZED"
  | "FORBIDDEN"
  | "NOT_FOUND"
  | "VALIDATION_ERROR";

/**
 * Drop-in replacement for the Elydora `@elydora/shared` TypeScript surface. Transcribed 1:1 (code-verified by console-builder) from Related_Work/Elydora-Open-Source-main/packages/server/src/shared/{index.ts,types/enums.ts,types/entities.ts,types/protocol.ts,types/api.ts}. The Hono server that provided these types is replaced by the Python FastAPI backend, so the console now consumes these types via contracts/codegen -> console/src/types/contracts.d.ts. Mirrors exactly the public symbols re-exported by shared/index.ts. The root object exists only so json-schema-to-typescript (no unreachableDefinitions option set in contracts/codegen/gen.mjs) emits every $def as an exported named type.
 */
export interface ElydoraSharedSurface {
  AgentStatus?: AgentStatus;
  KeyStatus?: KeyStatus;
  ExportStatus?: ExportStatus;
  AdminAction?: AdminAction;
  RbacRole?: RbacRole;
  ErrorCode?: ErrorCode;
  EOR?: EOR;
  ECH?: ECH;
  EAR?: EAR;
  EER?: EER;
  Agent?: Agent;
  AgentKey?: AgentKey;
  Operation?: Operation;
  Receipt?: Receipt;
  Epoch?: Epoch;
  AdminEvent?: AdminEvent;
  Export?: Export;
  Organization?: Organization;
  User?: User;
  RegisterAgentRequest?: RegisterAgentRequest;
  RegisterAgentResponse?: RegisterAgentResponse;
  GetAgentResponse?: GetAgentResponse;
  ListAgentsResponse?: ListAgentsResponse;
  FreezeAgentRequest?: FreezeAgentRequest;
  UnfreezeAgentRequest?: UnfreezeAgentRequest;
  RevokeAgentRequest?: RevokeAgentRequest;
  UpdateAgentRequest?: UpdateAgentRequest;
  SubmitOperationRequest?: SubmitOperationRequest;
  SubmitOperationResponse?: SubmitOperationResponse;
  GetOperationResponse?: GetOperationResponse;
  VerifyOperationResponse?: VerifyOperationResponse;
  AuditQueryRequest?: AuditQueryRequest;
  AuditQueryResponse?: AuditQueryResponse;
  GetEpochResponse?: GetEpochResponse;
  ListEpochsResponse?: ListEpochsResponse;
  CreateExportRequest?: CreateExportRequest;
  CreateExportResponse?: CreateExportResponse;
  GetExportResponse?: GetExportResponse;
  ListExportsResponse?: ListExportsResponse;
  AuthRegisterRequest?: AuthRegisterRequest;
  AuthRegisterResponse?: AuthRegisterResponse;
  AuthLoginRequest?: AuthLoginRequest;
  AuthLoginResponse?: AuthLoginResponse;
  AuthMeResponse?: AuthMeResponse;
  AuthRefreshResponse?: AuthRefreshResponse;
  IssueTokenRequest?: IssueTokenRequest;
  IssueTokenResponse?: IssueTokenResponse;
  JWK?: JWK;
  JWKSResponse?: JWKSResponse;
  ErrorResponse?: ErrorResponse;
}
export interface EOR {
  op_version: "1.0";
  operation_id: string;
  org_id: string;
  agent_id: string;
  issued_at: number;
  ttl_ms: number;
  nonce: string;
  operation_type: string;
  subject: {
    [k: string]: unknown;
  };
  action: {
    [k: string]: unknown;
  };
  payload:
    | {
        [k: string]: unknown;
      }
    | string
    | null;
  payload_hash: string;
  prev_chain_hash: string;
  agent_pubkey_kid: string;
  signature: string;
}
export interface ECH {
  prev_ech: string;
  payload_hash: string;
  operation_id: string;
  issued_at: number;
  chain_hash: string;
}
export interface EAR {
  receipt_version: string;
  receipt_id: string;
  operation_id: string;
  org_id: string;
  agent_id: string;
  server_received_at: number;
  seq_no: number;
  chain_hash: string;
  queue_message_id: string;
  receipt_hash: string;
  elydora_kid: string;
  elydora_signature: string;
}
export interface EER {
  epoch_id: string;
  org_id: string;
  start_time: number;
  end_time: number;
  leaf_count: number;
  root_hash: string;
  hash_alg: string;
  signature_by_elydora: string;
}
export interface Agent {
  agent_id: string;
  org_id: string;
  display_name: string;
  responsible_entity: string;
  integration_type: string;
  status: AgentStatus;
  created_at: number;
  updated_at: number;
}
export interface AgentKey {
  kid: string;
  agent_id: string;
  public_key: string;
  algorithm: "ed25519";
  status: KeyStatus;
  created_at: number;
  retired_at: number | null;
}
export interface Operation {
  operation_id: string;
  org_id: string;
  agent_id: string;
  seq_no: number;
  operation_type: string;
  issued_at: number;
  ttl_ms: number;
  nonce: string;
  subject: string;
  action: string;
  payload_hash: string;
  prev_chain_hash: string;
  chain_hash: string;
  agent_pubkey_kid: string;
  signature: string;
  r2_payload_key: string | null;
  created_at: number;
}
export interface Receipt {
  receipt_id: string;
  operation_id: string;
  r2_receipt_key: string;
  created_at: number;
}
export interface Epoch {
  epoch_id: string;
  org_id: string;
  start_time: number;
  end_time: number;
  root_hash: string;
  leaf_count: number;
  r2_epoch_key: string;
  created_at: number;
}
export interface AdminEvent {
  event_id: string;
  org_id: string;
  actor: string;
  action: string;
  target_type: string;
  target_id: string;
  details: string | null;
  created_at: number;
}
export interface Export {
  export_id: string;
  org_id: string;
  status: ExportStatus;
  query_params: string;
  r2_export_key: string | null;
  created_at: number;
  completed_at: number | null;
}
export interface Organization {
  org_id: string;
  name: string;
  created_at: number;
  updated_at: number;
}
export interface User {
  user_id: string;
  org_id: string;
  email: string;
  display_name: string;
  role: RbacRole;
  status: "active" | "suspended";
  created_at: number;
  updated_at: number;
}
export interface RegisterAgentRequest {
  agent_id: string;
  display_name?: string;
  responsible_entity?: string;
  integration_type?: string;
  keys: {
    kid: string;
    public_key: string;
    algorithm: "ed25519";
  }[];
}
export interface RegisterAgentResponse {
  agent: Agent;
  keys: AgentKey[];
}
export interface GetAgentResponse {
  agent: Agent;
  keys: AgentKey[];
}
export interface ListAgentsResponse {
  agents: Agent[];
}
export interface FreezeAgentRequest {
  reason: string;
}
export interface UnfreezeAgentRequest {
  reason: string;
}
export interface RevokeAgentRequest {
  kid: string;
  reason: string;
}
export interface UpdateAgentRequest {
  integration_type: string;
}
export interface SubmitOperationRequest {
  op_version: "1.0";
  operation_id: string;
  org_id: string;
  agent_id: string;
  issued_at: number;
  ttl_ms: number;
  nonce: string;
  operation_type: string;
  subject: {
    [k: string]: unknown;
  };
  action: {
    [k: string]: unknown;
  };
  payload:
    | {
        [k: string]: unknown;
      }
    | string
    | null;
  payload_hash: string;
  prev_chain_hash: string;
  agent_pubkey_kid: string;
  signature: string;
}
export interface SubmitOperationResponse {
  receipt: EAR;
}
export interface GetOperationResponse {
  operation: Operation;
  receipt?: Receipt;
  payload?: {
    [k: string]: unknown;
  };
}
export interface VerifyOperationResponse {
  valid: boolean;
  checks: {
    signature: boolean;
    chain: boolean;
    receipt: boolean;
    merkle?: boolean;
  };
  errors?: string[];
}
export interface AuditQueryRequest {
  org_id?: string;
  agent_id?: string;
  operation_type?: string;
  start_time?: number;
  end_time?: number;
  cursor?: string;
  limit?: number;
}
export interface AuditQueryResponse {
  operations: Operation[];
  cursor?: string;
  total_count: number;
}
export interface GetEpochResponse {
  epoch: Epoch;
  anchor?: {
    tsa_token?: string;
    tsa_url?: string;
    anchored_at?: number;
  };
}
export interface ListEpochsResponse {
  epochs: Epoch[];
}
export interface CreateExportRequest {
  start_time: number;
  end_time: number;
  agent_id?: string;
  operation_type?: string;
  format: "json" | "pdf";
}
export interface CreateExportResponse {
  export: Export;
}
export interface GetExportResponse {
  export: Export;
  download_url?: string;
}
export interface ListExportsResponse {
  exports: Export[];
}
export interface AuthRegisterRequest {
  email: string;
  password: string;
  display_name?: string;
  org_name?: string;
}
export interface AuthRegisterResponse {
  user: User;
  organization: Organization;
  token: string;
}
export interface AuthLoginRequest {
  email: string;
  password: string;
}
export interface AuthLoginResponse {
  user: User;
  token: string;
}
export interface AuthMeResponse {
  user: User;
}
export interface AuthRefreshResponse {
  token: string;
}
export interface IssueTokenRequest {
  ttl_seconds?: number | null;
}
export interface IssueTokenResponse {
  token: string;
  expires_at: number | null;
}
export interface JWK {
  kty: string;
  crv?: string;
  x?: string;
  kid: string;
  use: string;
  alg: string;
}
export interface JWKSResponse {
  keys: JWK[];
}
export interface ErrorResponse {
  error: {
    code: ErrorCode;
    message: string;
    request_id: string;
    details?: {
      [k: string]: unknown;
    };
  };
}

export type ShieldVersion = string;
export type VerdictId = string;
export type RecordId = string | null;
export type CorrelationId = string;
export type RunId = string | null;
export type Decision = "PASS" | "ALERT" | "BLOCK" | "ESCALATE" | "ROLLBACK" | "REWRITE";
export type RiskScore = number;
export type Guardian = "defender" | "evaluator" | "supervisor" | "auditor";
export type Label = string;
export type Detail = string | null;
export type Score = number | null;
export type ModelId = string | null;
export type ServedVia = "cloud" | "local";
export type Reasons = VerdictReason[];
export type MaskArgs = string[] | null;
export type RewriteArgs = {
  [k: string]: unknown;
} | null;
export type RequireHuman = boolean | null;
export type LanggraphCheckpointId = string | null;
export type EnvSnapshotRef = string | null;
export type PreventedLoss = number | null;
export type LatencyMs = number | null;
export type ServedAt = number | null;
export type ShieldKid = string | null;
export type SignatureByShield = string | null;

/**
 * Synchronous verdict returned by ``POST /v1/governance/decide``.
 *
 * FROZEN §4.2 baseline, v1.1. Signed by the shield server key
 * (``signature_by_shield``), offline-verifiable like an Elydora EAR; the
 * signable projection excludes ``signature_by_shield`` only.
 */
export interface GovernanceVerdict {
  shield_version?: ShieldVersion;
  verdict_id?: VerdictId;
  record_id?: RecordId;
  correlation_id: CorrelationId;
  run_id?: RunId;
  decision: Decision;
  risk_score?: RiskScore;
  reasons?: Reasons;
  obligations?: Obligations;
  latency_ms?: LatencyMs;
  served_at?: ServedAt;
  shield_kid?: ShieldKid;
  signature_by_shield?: SignatureByShield;
}
/**
 * One per-guardian reason. ``model_id``/``served_via`` are v1.1 cost
 * fields (C11 / ADR-0007).
 */
export interface VerdictReason {
  agent?: Guardian | null;
  label: Label;
  detail?: Detail;
  score?: Score;
  model_id?: ModelId;
  served_via?: ServedVia | null;
}
/**
 * Locally-enforced obligations. ``prevented_loss`` is a v1.1 cost field.
 */
export interface Obligations {
  mask_args?: MaskArgs;
  rewrite_args?: RewriteArgs;
  require_human?: RequireHuman;
  rollback?: RollbackObligation | null;
  prevented_loss?: PreventedLoss;
}
/**
 * Dual-substrate rollback target (C2): BOTH fire on a ROLLBACK verdict.
 */
export interface RollbackObligation {
  langgraph_checkpoint_id?: LanggraphCheckpointId;
  env_snapshot_ref?: EnvSnapshotRef;
}

export type ShieldVersion = string;
export type RecordId = string;
export type CorrelationId = string;
export type OrgId = string;
export type AgentId = string;
export type WorkflowId = string;
export type RunId = string;
export type StepIndex = number;
export type IssuedAt = number;
export type TtlMs = number;
export type Nonce = string;
export type Phase = "pre_exec" | "post_exec";
export type ActionType = "tool_call" | "llm_inference" | "decision" | "checkpoint" | "escalation";
export type OperationType = string;
export type Tool = string | null;
export type ArgsDigest = string | null;
export type ToolName = string | null;
export type ToolError = string | null;
export type Model = string | null;
export type PromptTokens = number;
export type CompletionTokens = number;
export type Confidence = number | null;
export type CheckpointId = string | null;
export type LanggraphThreadId = string | null;
export type EnvSnapshotRef = string | null;
export type PayloadHash = string;
export type PrevChainHash = string;
export type ChainHash = string | null;
export type AgentPubkeyKid = string;
export type VerdictRef = string | null;
export type Signature = string | null;

/**
 * Two-phase tamper-evident action record. FROZEN §4.1 baseline, v1.1.
 *
 * ``chain_hash`` is server-derived and never trusted from / signed by the
 * client; it is excluded from the signable projection (see
 * ``shield_sdk.canonical``).
 */
export interface ShieldActionRecord {
  shield_version?: ShieldVersion;
  record_id?: RecordId;
  correlation_id?: CorrelationId;
  org_id?: OrgId;
  agent_id?: AgentId;
  workflow_id?: WorkflowId;
  run_id: RunId;
  step_index?: StepIndex;
  issued_at?: IssuedAt;
  ttl_ms?: TtlMs;
  nonce?: Nonce;
  phase: Phase;
  action_type?: ActionType;
  operation_type?: OperationType;
  subject?: Subject;
  action?: ActionRef;
  payload?: ActionPayload;
  context?: ActionContext;
  payload_hash?: PayloadHash;
  prev_chain_hash?: PrevChainHash;
  chain_hash?: ChainHash;
  agent_pubkey_kid?: AgentPubkeyKid;
  verdict_ref?: VerdictRef;
  signature?: Signature;
}
export interface Subject {
  [k: string]: unknown;
}
/**
 * ``action`` (§4.1): the tool + a digest of its args.
 */
export interface ActionRef {
  tool?: Tool;
  args_digest?: ArgsDigest;
}
/**
 * ``payload`` (§4.1): JCS-hashed, object-stored. ``tool_args`` is open.
 */
export interface ActionPayload {
  tool_name?: ToolName;
  tool_args?: ToolArgs;
  tool_result?: unknown;
  tool_error?: ToolError;
  llm?: LLMUsage | null;
  confidence?: Confidence;
}
export interface ToolArgs {
  [k: string]: unknown;
}
/**
 * Per-action LLM token attribution (commercial cost hook #1; eval TO).
 */
export interface LLMUsage {
  model?: Model;
  prompt_tokens?: PromptTokens;
  completion_tokens?: CompletionTokens;
}
/**
 * Dual-substrate rollback keys (C2 resolution, first-class in §4.1).
 */
export interface ActionContext {
  checkpoint_id?: CheckpointId;
  langgraph_thread_id?: LanggraphThreadId;
  env_snapshot_ref?: EnvSnapshotRef;
}

