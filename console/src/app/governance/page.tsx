'use client';

import { useTranslation } from 'react-i18next';
import PageHeader from '@/components/ui/PageHeader';
import type { GovernanceVerdict, Decision } from '@elydora/shared';

// W2 STUB verdicts — typed against the FROZEN v1.1 §4 GovernanceVerdict
// (codegen-owned: console/src/types/contracts.d.ts). W3 (G3) replaces this
// with the live shield:verdicts stream + the GET /v1/governance/runs/{id}/cost
// rollup. The $30k BLOCK previews the InjectionTask6 money-shot.
const STUB_VERDICTS: GovernanceVerdict[] = [
  {
    correlation_id: 'corr-stub-0001',
    decision: 'BLOCK',
    risk_score: 0.92,
    obligations: { prevented_loss: 30000 },
  },
  {
    correlation_id: 'corr-stub-0002',
    decision: 'ESCALATE',
    risk_score: 0.41,
    obligations: { prevented_loss: null },
  },
  {
    correlation_id: 'corr-stub-0003',
    decision: 'PASS',
    risk_score: 0.03,
    obligations: { prevented_loss: null },
  },
];

const DECISION_STYLE: Record<Decision, string> = {
  PASS: 'text-ink-dim border-border',
  ALERT: 'text-amber-700 border-amber-300',
  BLOCK: 'text-red-700 border-red-300',
  ESCALATE: 'text-amber-700 border-amber-300',
  ROLLBACK: 'text-red-700 border-red-300',
  REWRITE: 'text-ink border-border',
};

const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

function KpiCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-border p-5">
      <div className="font-mono text-[10px] uppercase tracking-wider text-ink-dim">
        {label}
      </div>
      <div className="mt-2 font-sans text-2xl font-semibold text-ink">{value}</div>
    </div>
  );
}

export default function GovernancePage() {
  const { t } = useTranslation();

  const verdicts = STUB_VERDICTS;
  const blocked = verdicts.filter((v) => v.decision === 'BLOCK').length;
  const escalated = verdicts.filter((v) => v.decision === 'ESCALATE').length;
  const preventedLoss = verdicts.reduce(
    (sum, v) => sum + (v.obligations?.prevented_loss ?? 0),
    0,
  );
  const meanRisk = verdicts.length
    ? verdicts.reduce((s, v) => s + (v.risk_score ?? 0), 0) / verdicts.length
    : 0;

  return (
    <div className="fade-in">
      <PageHeader
        title={t('governance.title')}
        subtitle={t('governance.subtitle')}
        breadcrumbs={[
          { label: t('common.dashboard'), href: '/' },
          { label: t('governance.title') },
        ]}
      />

      <div className="mb-6 px-4 py-3 border border-border bg-surface font-mono text-[12px] text-ink-dim">
        {t('governance.stubNotice')}
      </div>

      <div className="mb-8 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard label={t('governance.kpiBlocked')} value={String(blocked)} />
        <KpiCard label={t('governance.kpiSaved')} value={usd.format(preventedLoss)} />
        <KpiCard label={t('governance.kpiEscalated')} value={String(escalated)} />
        <KpiCard label={t('governance.kpiMeanRisk')} value={meanRisk.toFixed(2)} />
      </div>

      <div className="border border-border">
        <div className="px-4 py-3 border-b border-border font-mono text-[11px] uppercase tracking-wider text-ink-dim">
          {t('governance.verdictsTitle')}
        </div>
        {verdicts.length === 0 ? (
          <div className="px-4 py-8 text-center font-mono text-[12px] text-ink-dim">
            {t('governance.emptyVerdicts')}
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-border">
                <th className="px-4 py-2 text-left font-mono text-[10px] uppercase tracking-wider text-ink-dim">
                  {t('governance.colCorrelation')}
                </th>
                <th className="px-4 py-2 text-left font-mono text-[10px] uppercase tracking-wider text-ink-dim">
                  {t('governance.colDecision')}
                </th>
                <th className="px-4 py-2 text-left font-mono text-[10px] uppercase tracking-wider text-ink-dim">
                  {t('governance.colRisk')}
                </th>
                <th className="px-4 py-2 text-left font-mono text-[10px] uppercase tracking-wider text-ink-dim">
                  {t('governance.colPrevented')}
                </th>
              </tr>
            </thead>
            <tbody>
              {verdicts.map((v) => (
                <tr key={v.correlation_id} className="border-b border-border last:border-0">
                  <td className="px-4 py-3 font-mono text-[13px] text-ink">
                    {v.correlation_id}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`font-mono text-[11px] uppercase tracking-wider px-2 py-1 border ${DECISION_STYLE[v.decision]}`}
                    >
                      {v.decision}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-[13px] text-ink-dim">
                    {(v.risk_score ?? 0).toFixed(2)}
                  </td>
                  <td className="px-4 py-3 font-mono text-[13px] text-ink-dim">
                    {v.obligations?.prevented_loss != null
                      ? usd.format(v.obligations.prevented_loss)
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
