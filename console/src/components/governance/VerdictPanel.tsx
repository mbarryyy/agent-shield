'use client';

import { useTranslation } from 'react-i18next';
import type {
  Guardian,
  GovernanceVerdict,
  ShieldActionRecord,
  VerdictReason,
} from '@elydora/shared';
import type { GuardianEvidenceRow } from '@/types/governance';
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
    <div className="border border-border p-3">
      <div className="font-mono text-[10px] uppercase tracking-wider text-ink-dim mb-2">
        {guardian}
      </div>
      {!hasSignal ? (
        <div className="font-mono text-[12px] text-ink-dim italic">{noSignal}</div>
      ) : (
        <ul className="space-y-1.5">
          {reasons.map((r, i) => (
            <li key={`${guardian}-${i}`} className="font-mono text-[12px] text-ink">
              <span className="uppercase tracking-wider">{r.label}</span>
              {r.score != null && (
                <span className="text-ink-dim"> · {r.score.toFixed(2)}</span>
              )}
              {r.served_via && (
                <span className="text-ink-dim"> · {r.served_via}</span>
              )}
              {r.model_id && (
                <div className="text-ink-dim normal-case mt-0.5 break-words">
                  model {r.model_id}
                </div>
              )}
              {r.detail && (
                <div className="text-ink-dim normal-case mt-0.5 break-words">
                  {r.detail}
                </div>
              )}
            </li>
          ))}
          {evidenceRows.map((row, i) => (
            <li
              key={`${guardian}-evidence-${i}`}
              className="font-mono text-[12px] text-ink"
            >
              <span className="uppercase tracking-wider">{row.decision}</span>
              {row.reasons.map((reason) => (
                <div key={reason} className="text-ink-dim normal-case mt-0.5 break-words">
                  {reason}
                </div>
              ))}
              <div className="text-ink-dim normal-case mt-0.5 break-words">
                {row.prompt_tokens} prompt / {row.completion_tokens} completion
                <span> · {row.latency_ms} ms</span>
                {row.served_via && <span> · {row.served_via}</span>}
                <span> · cost {formatGuardianCost(row.cost_usd)}</span>
              </div>
              {row.model_id && (
                <div className="text-ink-dim normal-case mt-0.5 break-words">
                  model {row.model_id}
                </div>
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
          {verdict.latency_ms != null && <div>latency {verdict.latency_ms} ms</div>}
          <div className="break-all">{verdict.correlation_id}</div>
        </div>
      </div>

      <div className="p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
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
