'use client';

import { useTranslation } from 'react-i18next';
import type { CostRollup, RiskBand } from '@/types/governance';

const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

function KpiCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="border border-border p-5">
      <div className="font-mono text-[10px] uppercase tracking-wider text-ink-dim">
        {label}
      </div>
      <div className="mt-2 font-sans text-2xl font-semibold text-ink">{value}</div>
      {sub && <div className="mt-1 font-mono text-[11px] text-ink-dim">{sub}</div>}
    </div>
  );
}

/**
 * Money-shot KPI cards bound VERBATIM to the LOCKED hook #5 /cost body
 * (server PR-S4): { tokens:{prompt,completion,total}, decision_mix (all 6),
 * prevented_loss_total, latency_p50_ms, latency_p95_ms }. The console
 * RENDERS server-authoritative values — `prevented_loss_total` is the
 * MEASURED AgentDojo env-diff oracle ($30k on the money-shot) and is NEVER
 * recomputed (honest-UI: demo L77/125/140). `$cost`/BCR are intentionally
 * absent from the contract (eval/commercial ESTIMATED) — not shown.
 * `meanRiskBand` comes from the verdict feed (not /cost); "—" until wired
 * rather than a fabricated number.
 */
export default function KpiCards({
  rollup,
  meanRiskBand,
}: {
  rollup: CostRollup | null;
  meanRiskBand?: RiskBand | null;
}) {
  const { t } = useTranslation();
  const blocked = rollup?.decision_mix.BLOCK ?? 0;
  const escalated = rollup?.decision_mix.ESCALATE ?? 0;
  const saved = rollup ? usd.format(rollup.prevented_loss_total) : '—';
  const tokensSub = rollup
    ? `${rollup.tokens.total} ${t('governance.tokens')} · p95 ${rollup.latency_p95_ms} ms`
    : undefined;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <KpiCard label={t('governance.kpiBlocked')} value={String(blocked)} />
      <KpiCard label={t('governance.kpiSaved')} value={saved} sub={tokensSub} />
      <KpiCard label={t('governance.kpiEscalated')} value={String(escalated)} />
      <KpiCard label={t('governance.kpiMeanRisk')} value={meanRiskBand ?? '—'} />
    </div>
  );
}
