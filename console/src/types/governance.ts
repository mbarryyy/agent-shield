// Console-owned VIEW-MODEL for the W3 governance surface.
//
// NOT a contract: the FROZEN §4 v1.1 types (GovernanceVerdict /
// ShieldActionRecord / Decision / Phase / VerdictReason / Obligations) are
// codegen-owned in console/src/types/contracts.d.ts (alias
// `@elydora/shared`) and consumed as-is. This file is the thin console
// layer over the LOCKED server console-READ contract (server PR-S2 @PR#18 /
// PR-S3 shield:verdicts / PR-S4 hook#5 /cost) — relayed & pinned by
// team-lead. These shapes are FINAL; live-wiring (gated on
// server+gov+eval merged) is then a pure stub→live swap (one adapter spot
// per view model). The console RENDERS server-authoritative values and
// never recomputes $prevented / tokens / risk (honest-UI).

import type {
  Decision,
  GovernanceVerdict,
  Guardian,
  Phase,
  ServedVia,
  ShieldActionRecord,
} from '@elydora/shared';

export const EVIDENCE_LABELS = [
  'MOCKED',
  'MEASURED',
  'ESTIMATED',
  'SKIPPED',
  'PROVIDER_BACKED',
] as const;
export type EvidenceLabel = (typeof EVIDENCE_LABELS)[number];

export interface EvidenceMetadata {
  evidence_label?: EvidenceLabel | null;
  evidence_note?: string | null;
  backend?: string | null;
  arm?: string | null;
  api_call_status?: string | null;
  cost_usd?: number | null;
}

export function evidenceLabelFrom(value: unknown): EvidenceLabel | null {
  if (!value || typeof value !== 'object') return null;
  const label = (value as { evidence_label?: unknown }).evidence_label;
  return typeof label === 'string' && EVIDENCE_LABELS.includes(label as EvidenceLabel)
    ? (label as EvidenceLabel)
    : null;
}

// --- GET /v1/governance/runs/{run_id}/timeline?cursor=&limit= -------------
// LOCKED: { rows:[{...}], cursor, total_count } (keyset-paginated,
// org-scoped) — the live-monitor feed. Flat lightweight rows; the full
// verdict + paired records come from /verdicts/{correlation_id}.
export interface TimelineRow extends EvidenceMetadata {
  verdict_id: string;
  record_id: string; // server: required str
  correlation_id: string;
  run_id: string | null;
  decision: Decision;
  /** Normalized to number in the view model; the SSE shield:verdicts
   *  envelope carries it as a string ("0.0") — the adapter coerces. */
  risk_score: number;
  latency_ms: number | null;
  created_at: number;
}
export interface TimelinePage {
  rows: TimelineRow[];
  cursor?: string | null;
  total_count: number;
}

export interface GuardianEvidenceRow {
  record_id: string;
  correlation_id: string;
  guardian: Guardian;
  decision: Decision;
  reasons: string[];
  model_id: string | null;
  served_via: ServedVia | null;
  prompt_tokens: number;
  completion_tokens: number;
  latency_ms: number;
  cost_usd: number;
  tool_calls?: string[];
  memory_backend?: string | null;
  collection?: string | null;
  query_id?: string | null;
  hit_count?: number | null;
  memory_latency_ms?: number | null;
  missing_reason?: string | null;
  top_hit_id?: string | null;
  score?: number | null;
  distance?: number | null;
  memory?: GuardianMemoryEvidence | null;
}

export interface GuardianMemoryHit {
  id: string;
  score?: number | null;
  distance?: number | null;
}

export interface GuardianMemoryEvidence {
  memory_backend?: string | null;
  collection?: string | null;
  query_id?: string | null;
  hit_count?: number | null;
  latency_ms?: number | null;
  missing_reason?: string | null;
  top_hits?: GuardianMemoryHit[];
}

// --- GET /v1/governance/verdicts/{correlation_id} ------------------------
// LOCKED: { correlation_id, verdict:<SIGNED §4 GovernanceVerdict JSON>,
// pre_exec:<§4 record JSON>, post_exec:<§4 record JSON>,
// guardian_evidence:[server-owned per-guardian rows] } (404 if unknown).
// Server VerdictView: verdict / pre_exec / post_exec are each dict|null
// (opaque frozen §4 envelopes; null when not yet present / 404-adjacent).
// Callers guard `verdict` before rendering VerdictPanel.
export interface VerdictDetail extends EvidenceMetadata {
  correlation_id: string;
  verdict: GovernanceVerdict | null;
  pre_exec: ShieldActionRecord | null;
  post_exec: ShieldActionRecord | null;
  guardian_evidence?: GuardianEvidenceRow[];
}

// --- GET /v1/governance/runs/{run_id}/provenance ------------------------
// LOCKED: { run_id, nodes:[{record_id, phase, correlation_id, decision,
// seq_no, chain_hash}], edges:[{src, dst, kind}] }. Server returns DATA;
// the console renders it. `blocked_intent` is DERIVED (not a server field):
// a pre-execution BLOCK is a permanent-evidence node, NOT a rollback
// (Act-3 GATE-ARCH L6/124/128) — derived, never fabricated.
export interface ProvenanceNode {
  record_id: string;
  phase: Phase | null;
  correlation_id: string | null;
  decision: Decision | null;
  seq_no: number;
  chain_hash: string; // server: required str
}
export interface ProvenanceEdge {
  src: string;
  dst: string;
  kind: 'chain' | 'correlation';
}
export interface ProvenanceGraph {
  run_id: string;
  nodes: ProvenanceNode[];
  edges: ProvenanceEdge[];
}
/** A pre-exec BLOCK = blocked-intent permanent evidence (GATE-ARCH). */
export function isBlockedIntent(n: ProvenanceNode): boolean {
  return n.decision === 'BLOCK';
}

// --- GET /v1/governance/stream?workflow_id= (SSE) ------------------------
// LOCKED shield:verdicts envelope (PR-S3) carried by `event: verdict`:
// FLAT 8 string fields. The adapter JSON.parses `verdict` -> §4
// GovernanceVerdict and coerces `risk_score`/`phase`.
export interface ShieldVerdictEvent {
  verdict_id: string;
  record_id: string;
  correlation_id: string;
  run_id: string;
  decision: Decision;
  /** string e.g. "0.0" per the locked envelope. */
  risk_score: string;
  phase: Phase;
  /** SIGNED §4 GovernanceVerdict, JSON string. */
  verdict: string;
}

// --- GET /v1/governance/runs/{run_id}/cost (hook #5, PR-S4) -------------
// LOCKED body — bound VERBATIM by KpiCards; the console RENDERS, never
// recomputes. `$cost`/BCR are intentionally NOT here (eval/commercial
// ESTIMATED, off the console). `prevented_loss_total` is the MEASURED
// AgentDojo env-diff oracle ($30k on the money-shot).
export interface CostRollup extends EvidenceMetadata {
  tokens: { prompt: number; completion: number; total: number };
  decision_mix: Record<Decision, number>;
  prevented_loss_total: number;
  latency_p50_ms: number;
  latency_p95_ms: number;
}

// --- Incidents (U6) ------------------------------------------------------
// RULING (b): the incidents list is SERVER-AUTHORITATIVE — server owns
// GET /v1/governance/incidents?run_id=&status=&cursor=&limit= (companion
// to its PR-S5 resume; same incident_id key; additive, console-pact, no
// §4). The console does NOT derive incidents client-side (status is
// server-owned via the resume processing). Shape below is PROVISIONAL —
// team-lead relays server's FINAL in-code shape with the trigger ping;
// this is the single isolated adapter spot. The full verdict + paired
// records load from /verdicts/{correlation_id} (VerdictDetail) when an
// incident is opened (same pattern as the live monitor). Approve/Reject
// round-trips POST /v1/governance/incidents/{incident_id}/resume (the one
// console WRITE; server/LangGraph owns the resume + resulting status).
// LOCKED & byte-confirmed from server PR#18. Incidents are ESCALATE-ONLY:
// an HITL incident IS a pending ESCALATE. BLOCK is NOT an incident
// (terminal — rendered in the provenance DAG blocked-intent node +
// verdict tab, GATE-ARCH). `incident_id` == the ESCALATE gate verdict_id
// and is the SAME id the PR-S5 resume route consumes. `status` is
// server-authoritative (flips pending→resolved after the resume WRITE
// persists server-side) — the console renders it verbatim and holds NO
// resolution state of its own. Full verdict loads from
// /verdicts/{correlation_id} (VerdictDetail) on open.
export type IncidentStatus = 'pending' | 'resolved';
export type IncidentResolution = 'accept' | 'edit' | 'response' | 'ignore';
export interface Incident {
  incident_id: string;
  correlation_id: string;
  run_id: string | null;
  decision: 'ESCALATE';
  risk_score: number;
  status: IncidentStatus;
  resolution: IncidentResolution | null;
  created_at: number;
}
export interface IncidentList {
  incidents: Incident[];
  cursor: string | null;
  total_count: number;
}

// §3.3 LOCKED decision bands (master_design §3.3 / demo L29). The console
// renders the live risk_score against these — the score is a runtime
// output (never fabricated); only the band label is derived.
export type RiskBand = 'PASS' | 'ALERT' | 'ESCALATE' | 'BLOCK';
export function riskBand(score: number | null | undefined): RiskBand {
  const s = score ?? 0;
  if (s < 0.1) return 'PASS';
  if (s < 0.3) return 'ALERT';
  if (s < 0.6) return 'ESCALATE';
  return 'BLOCK';
}

// --- GET /v1/governance/dashboard/kpi (Task #31.b) -----------------------
// Org-wide rollup for the console Dashboard local-demo prevented-loss stat
// card. Server NEVER recomputes — `prevented_loss_total` is Σ over
// signed verdicts' `obligations.prevented_loss` (the MEASURED env-diff
// stored at /decide time). Shape mirrors `shield_server.models.DashboardKpi`
// byte-for-byte (§5b vs models.py:365).
export interface DashboardKpi {
  prevented_loss_total: number;
  decision_mix: Record<string, number>;
  total_verdicts: number;
}
