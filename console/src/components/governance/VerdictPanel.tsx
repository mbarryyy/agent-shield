'use client';

import { useTranslation } from 'react-i18next';
import type {
  Guardian,
  GovernanceVerdict,
  ShieldActionRecord,
  VerdictReason,
} from '@elydora/shared';
import type { GuardianEvidenceRow, GuardianMemoryHit } from '@/types/governance';
import { evidenceLabelFrom } from '@/types/governance';
import { DecisionBadge, EvidenceBadge, RiskBadge } from './badges';

// The four guardian lanes are a fixed, ordered set (master §3.3 / demo
// L77 — the audience must learn these four names). Always render all four,
// even with no signal, so a BLOCK reads as "the team caught it".
const GUARDIANS: Guardian[] = ['defender', 'evaluator', 'supervisor', 'auditor'];

function formatGuardianCost(value: number): string {
  if (value > 0 && value < 0.01) {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 4,
      maximumFractionDigits: 4,
    }).format(value);
  }
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  }).format(value);
}

function formatEvidenceNumber(value: number): string {
  return new Intl.NumberFormat('en-US', {
    maximumFractionDigits: 4,
  }).format(value);
}

function formatLatencyMs(value: number): string {
  return new Intl.NumberFormat('en-US', {
    maximumFractionDigits: 2,
  }).format(value);
}

function visibleServedVia(servedVia: string | null | undefined): string | null {
  if (!servedVia || servedVia === 'local') return null;
  return servedVia;
}

function formatMemorySummary(row: GuardianEvidenceRow): string | null {
  const memoryBackend = row.memory_backend ?? row.memory?.memory_backend;
  if (!memoryBackend) return null;
  const collection = row.collection ?? row.memory?.collection;
  const hitCount = row.hit_count ?? row.memory?.hit_count;
  const latencyMs = row.memory_latency_ms ?? row.memory?.latency_ms;
  const parts = [`memory ${memoryBackend}`];
  if (collection) parts.push(collection);
  if (hitCount != null) {
    parts.push(`${hitCount} ${hitCount === 1 ? 'hit' : 'hits'}`);
  }
  if (latencyMs != null) {
    parts.push(`${formatEvidenceNumber(latencyMs)} ms`);
  }
  return parts.join(' · ');
}

function formatMemoryHit(hit: GuardianMemoryHit): string {
  const parts = [hit.id];
  if (hit.score != null) parts.push(`score ${formatEvidenceNumber(hit.score)}`);
  if (hit.distance != null) parts.push(`distance ${formatEvidenceNumber(hit.distance)}`);
  return parts.join(' · ');
}

function memoryHits(row: GuardianEvidenceRow): GuardianMemoryHit[] {
  if (row.top_hit_id) {
    return [{ id: row.top_hit_id, score: row.score, distance: row.distance }];
  }
  return row.memory?.top_hits ?? [];
}

function GuardianLane({
  guardian,
  reasons,
  evidenceRows,
  noSignal,
}: {
  guardian: Guardian;
  reasons: VerdictReason[];
  evidenceRows: GuardianEvidenceRow[];
  noSignal: string;
}) {
  const hasSignal = reasons.length > 0 || evidenceRows.length > 0;
  return (
    <div className="border border-border p-3 min-w-0 overflow-hidden">
      <div className="font-mono text-[10px] uppercase tracking-wider text-ink-dim mb-2">
        {guardian}
      </div>
      {!hasSignal ? (
        <div className="font-mono text-[12px] text-ink-dim italic">{noSignal}</div>
      ) : (
        <ul className="space-y-1.5">
          {reasons.map((r, i) => (
            <li key={`${guardian}-${i}`} className="font-mono text-[12px] text-ink min-w-0">
              <span className="uppercase tracking-wider break-words [overflow-wrap:anywhere]">
                {r.label}
              </span>
              {r.score != null && (
                <span className="text-ink-dim"> · {r.score.toFixed(2)}</span>
              )}
              {visibleServedVia(r.served_via) && (
                <span className="text-ink-dim"> · {visibleServedVia(r.served_via)}</span>
              )}
              {r.model_id && (
                <div className="text-ink-dim normal-case mt-0.5 break-words [overflow-wrap:anywhere]">
                  model {r.model_id}
                </div>
              )}
              {r.detail && (
                <div className="text-ink-dim normal-case mt-0.5 break-words [overflow-wrap:anywhere]">
                  {r.detail}
                </div>
              )}
            </li>
          ))}
          {evidenceRows.map((row, i) => (
            <li
              key={`${guardian}-evidence-${i}`}
              className="font-mono text-[12px] text-ink min-w-0"
            >
              <span className="uppercase tracking-wider break-words [overflow-wrap:anywhere]">
                {row.decision}
              </span>
              {row.reasons.map((reason) => (
                <div
                  key={reason}
                  className="text-ink-dim normal-case mt-0.5 break-words [overflow-wrap:anywhere]"
                >
                  {reason}
                </div>
              ))}
              <div className="text-ink-dim normal-case mt-0.5 break-words [overflow-wrap:anywhere]">
                {row.prompt_tokens} prompt / {row.completion_tokens} completion
                <span> · {formatLatencyMs(row.latency_ms)} ms</span>
                {visibleServedVia(row.served_via) && (
                  <span> · {visibleServedVia(row.served_via)}</span>
                )}
                <span> · cost {formatGuardianCost(row.cost_usd)}</span>
              </div>
              {row.model_id && (
                <div className="text-ink-dim normal-case mt-0.5 break-words [overflow-wrap:anywhere]">
                  model {row.model_id}
                </div>
              )}
              {row.tool_calls && row.tool_calls.length > 0 && (
                <div className="text-ink-dim normal-case mt-0.5 break-words [overflow-wrap:anywhere]">
                  tools {row.tool_calls.join(', ')}
                </div>
              )}
              {(formatMemorySummary(row) || row.query_id || row.missing_reason || memoryHits(row).length > 0) && (
                <>
                  {formatMemorySummary(row) && (
                    <div className="text-ink-dim normal-case mt-0.5 break-words [overflow-wrap:anywhere]">
                      {formatMemorySummary(row)}
                    </div>
                  )}
                  {(row.query_id ?? row.memory?.query_id) && (
                    <div className="text-ink-dim normal-case mt-0.5 break-words [overflow-wrap:anywhere]">
                      query {row.query_id ?? row.memory?.query_id}
                    </div>
                  )}
                  {(row.missing_reason ?? row.memory?.missing_reason) && (
                    <div className="text-ink-dim normal-case mt-0.5 break-words [overflow-wrap:anywhere]">
                      missing {row.missing_reason ?? row.memory?.missing_reason}
                    </div>
                  )}
                  {memoryHits(row).slice(0, 3).map((hit) => (
                    <div
                      key={`${row.record_id}-${hit.id}`}
                      className="text-ink-dim normal-case mt-0.5 break-words [overflow-wrap:anywhere]"
                    >
                      {formatMemoryHit(hit)}
                    </div>
                  ))}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function VerdictPanel({
  verdict,
  preExec,
  postExec,
  guardianEvidence = [],
}: {
  verdict: GovernanceVerdict;
  preExec?: ShieldActionRecord | null;
  postExec?: ShieldActionRecord | null;
  guardianEvidence?: GuardianEvidenceRow[];
}) {
  const { t } = useTranslation();
  const reasons = verdict.reasons ?? [];
  const ob = verdict.obligations;
  const evidenceLabel = evidenceLabelFrom(verdict);
  const usageRows = [
    { label: 'pre_exec llm', llm: preExec?.payload?.llm },
    { label: 'post_exec llm', llm: postExec?.payload?.llm },
  ].filter((row) => row.llm);

  return (
    <div className="border border-border">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <DecisionBadge decision={verdict.decision} />
          <RiskBadge score={verdict.risk_score} />
          {evidenceLabel && <EvidenceBadge label={evidenceLabel} />}
        </div>
        <div className="font-mono text-[11px] text-ink-dim text-right">
          {verdict.latency_ms != null && <div>latency {formatLatencyMs(verdict.latency_ms)} ms</div>}
          <div className="break-all">{verdict.correlation_id}</div>
        </div>
      </div>

      <div className="p-4 grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-4 gap-3">
        {GUARDIANS.map((g) => (
          <GuardianLane
            key={g}
            guardian={g}
            reasons={reasons.filter((r) => r.agent === g)}
            evidenceRows={guardianEvidence.filter((row) => row.guardian === g)}
            noSignal={t('governance.noSignal')}
          />
        ))}
      </div>

      {ob && (ob.require_human || ob.prevented_loss != null || ob.rollback) && (
        <div className="px-4 py-3 border-t border-border font-mono text-[12px] text-ink-dim space-y-1">
          {ob.require_human && <div>{t('governance.obRequireHuman')}</div>}
          {ob.prevented_loss != null && (
            <div>
              {t('governance.obPreventedLoss')}:{' '}
              <span className="text-ink">
                {new Intl.NumberFormat('en-US', {
                  style: 'currency',
                  currency: 'USD',
                  maximumFractionDigits: 0,
                }).format(ob.prevented_loss)}
              </span>
            </div>
          )}
          {ob.rollback && <div>{t('governance.obRollback')}</div>}
        </div>
      )}

      {(preExec || postExec) && (
        <div className="px-4 py-3 border-t border-border font-mono text-[11px] text-ink-dim flex flex-wrap gap-x-6 gap-y-1">
          <span>
            {t('governance.preExec')}:{' '}
            {preExec ? (preExec.record_id ?? '—') : t('governance.pending')}
          </span>
          <span>
            {t('governance.postExec')}:{' '}
            {postExec ? (postExec.record_id ?? '—') : t('governance.pending')}
          </span>
          {usageRows.map((row) => (
            <span key={row.label}>
              {row.label}:{' '}
              <span className="text-ink">
                {row.llm?.prompt_tokens ?? 0} prompt / {row.llm?.completion_tokens ?? 0}{' '}
                completion
              </span>
              {row.llm?.model && <span> · {row.llm.model}</span>}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
