// Carry-in #1 — demo-fidelity per-call identity (CONSOLE-W3).
//
// On the mock / pre-recorded demo path, eval's MockedLLM emits
// `tool_call.id = None`; the SDK then assigns the synthetic fallback id
// `__shield_idx_{n}` and (per EVAL-W3 §5b) the collapse symptom is every
// call sharing a single key (`__shield_idx_0`) on `correlation_id`. That
// would render the verdict-tab / decision granularity as `{BLOCK:1}`
// instead of the true `[PASS, PASS, BLOCK]`.
//
// The server assigns a UNIQUE `verdict_id` per gate decision REGARDLESS of
// `tool_call.id`, so `verdict_id` is the correct stable per-call identity.
// We key the live monitor / selection / verdict-tab by `verdict_id`, and
// on a collapsed `correlation_id` we render the verdict tab from the
// stream-embedded signed §4 verdict (per `verdict_id`) instead of a
// `/verdicts/{correlation_id}` refetch that would collapse. PRODUCTION IS
// UNAFFECTED (real worker LLMs supply real tool_call ids) and the MEASURED
// $30k env-diff-oracle headline is unaffected — purely demo fidelity.

import type { GovernanceVerdict } from '@elydora/shared';
import type { ShieldVerdictEvent, TimelineRow, VerdictDetail } from '@/types/governance';

/** The SDK's synthetic fallback id when tool_call.id was None. */
const SHIELD_IDX_RE = /^__shield_idx_\d+$/;

export function isCollapsedCorrelation(id: string | null | undefined): boolean {
  return !!id && SHIELD_IDX_RE.test(id);
}

/**
 * Stable, unique per-call identity for React keys + row selection +
 * verdict-tab scoping. `verdict_id` is server-unique per decision even
 * when `correlation_id` collapses on the mock path.
 */
export function stableRowKey(row: TimelineRow): string {
  return row.verdict_id;
}

function toNum(v: unknown): number {
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
}

/**
 * Adapt a LOCKED FLAT-8 shield:verdicts SSE envelope → TimelineRow.
 * `risk_score` arrives as a string ("0.0"); `created_at` is not in the
 * envelope so receipt time is used (display-only ordering). Honest-UI:
 * decision/risk are rendered from the envelope, never fabricated.
 */
export function streamEventToRow(ev: ShieldVerdictEvent, receivedAt: number): TimelineRow {
  let latency: number | null = null;
  let createdAt = receivedAt;
  try {
    const v = JSON.parse(ev.verdict) as GovernanceVerdict;
    latency = v.latency_ms ?? null;
    const servedAt = Number((v as { served_at?: unknown }).served_at);
    if (Number.isFinite(servedAt) && servedAt > 0) {
      createdAt = servedAt;
    }
  } catch {
    latency = null;
  }
  return {
    verdict_id: ev.verdict_id,
    record_id: ev.record_id,
    correlation_id: ev.correlation_id,
    run_id: ev.run_id,
    decision: ev.decision,
    risk_score: toNum(ev.risk_score),
    latency_ms: latency,
    created_at: createdAt,
  };
}

/**
 * Build a VerdictDetail from the stream-embedded signed §4 verdict, scoped
 * by `verdict_id`. Used on collapsed-correlation_id rows so the verdict
 * tab keeps per-call fidelity without a colliding /verdicts refetch.
 */
export function streamEventToDetail(ev: ShieldVerdictEvent): VerdictDetail | null {
  try {
    const verdict = JSON.parse(ev.verdict) as GovernanceVerdict;
    return { correlation_id: ev.correlation_id, verdict, pre_exec: null, post_exec: null };
  } catch {
    return null;
  }
}
