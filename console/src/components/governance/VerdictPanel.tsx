'use client';

import { useTranslation } from 'react-i18next';
import type {
  Guardian,
  GovernanceVerdict,
  ShieldActionRecord,
  VerdictReason,
} from '@elydora/shared';
import { DecisionBadge, RiskBadge } from './badges';

// The four guardian lanes are a fixed, ordered set (master §3.3 / demo
// L77 — the audience must learn these four names). Always render all four,
// even with no signal, so a BLOCK reads as "the team caught it".
const GUARDIANS: Guardian[] = ['defender', 'evaluator', 'supervisor', 'auditor'];

function GuardianLane({
  guardian,
  reasons,
  noSignal,
}: {
  guardian: Guardian;
  reasons: VerdictReason[];
  noSignal: string;
}) {
  return (
    <div className="border border-border p-3">
      <div className="font-mono text-[10px] uppercase tracking-wider text-ink-dim mb-2">
        {guardian}
      </div>
      {reasons.length === 0 ? (
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
              {r.detail && (
                <div className="text-ink-dim normal-case mt-0.5 break-words">
                  {r.detail}
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
}: {
  verdict: GovernanceVerdict;
  preExec?: ShieldActionRecord | null;
  postExec?: ShieldActionRecord | null;
}) {
  const { t } = useTranslation();
  const reasons = verdict.reasons ?? [];
  const ob = verdict.obligations;

  return (
    <div className="border border-border">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <DecisionBadge decision={verdict.decision} />
          <RiskBadge score={verdict.risk_score} />
        </div>
        <span className="font-mono text-[11px] text-ink-dim break-all">
          {verdict.correlation_id}
        </span>
      </div>

      <div className="p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {GUARDIANS.map((g) => (
          <GuardianLane
            key={g}
            guardian={g}
            reasons={reasons.filter((r) => r.agent === g)}
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
        </div>
      )}
    </div>
  );
}
