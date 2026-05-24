'use client';

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import PageHeader from '@/components/ui/PageHeader';
import KpiCards from '@/components/governance/KpiCards';
import LiveMonitor from '@/components/governance/LiveMonitor';
import VerdictPanel from '@/components/governance/VerdictPanel';
import { useCost } from '@/lib/hooks';
import { useLiveGovernance } from '@/lib/useLiveGovernance';
import { stableRowKey } from '@/lib/governanceKeys';
import type { CostRollup, TimelineRow, VerdictDetail } from '@/types/governance';
import { evidenceLabelFrom, riskBand } from '@/types/governance';

const WORKFLOW_ID = process.env.NEXT_PUBLIC_GOV_WORKFLOW_ID ?? 'banking';
const RUN_ID = process.env.NEXT_PUBLIC_GOV_RUN_ID ?? 'banking';

// PRE-RECORDED-DEMO FALLBACK fixtures (data-layer resilience ONLY — used
// solely if BOTH the SSE stream and the /timeline poll yield nothing; the
// auth gate stays server-backed, this is NOT a zero-backend mode). Typed
// against the LOCKED server shapes. The $30k BLOCK previews the
// InjectionTask6 money-shot; tokens=0 = the model-free decisive block.
const NOW = 1_716_000_000_000;
const FALLBACK_ROWS: TimelineRow[] = [
  { verdict_id: 'v-0001', record_id: 'r-0001', correlation_id: 'corr-0001', run_id: RUN_ID, decision: 'PASS', risk_score: 0.03, latency_ms: 4, created_at: NOW - 9000, evidence_label: 'MOCKED' },
  { verdict_id: 'v-0002', record_id: 'r-0002', correlation_id: 'corr-0002', run_id: RUN_ID, decision: 'ESCALATE', risk_score: 0.41, latency_ms: 7, created_at: NOW - 6000, evidence_label: 'MOCKED' },
  { verdict_id: 'v-0003', record_id: 'r-0003', correlation_id: 'corr-0003', run_id: RUN_ID, decision: 'BLOCK', risk_score: 0.92, latency_ms: 6, created_at: NOW - 3000, evidence_label: 'MOCKED' },
];
const FALLBACK_DETAIL: Record<string, VerdictDetail> = {
  'v-0001': { correlation_id: 'corr-0001', verdict: { correlation_id: 'corr-0001', decision: 'PASS', risk_score: 0.03, latency_ms: 4, reasons: [{ agent: 'defender', label: 'DETERMINISTIC_CLEAR', score: 0.0 }] }, pre_exec: null, post_exec: null, evidence_label: 'MOCKED' },
  'v-0002': { correlation_id: 'corr-0002', verdict: { correlation_id: 'corr-0002', decision: 'ESCALATE', risk_score: 0.41, reasons: [{ agent: 'defender', label: 'AMOUNT_ABOVE_BASELINE', score: 0.4 }, { agent: 'supervisor', label: 'HUMAN_REVIEW' }], obligations: { require_human: true } }, pre_exec: null, post_exec: null, evidence_label: 'MOCKED' },
  'v-0003': { correlation_id: 'corr-0003', verdict: { correlation_id: 'corr-0003', decision: 'BLOCK', risk_score: 0.92, reasons: [{ agent: 'defender', label: 'RECIPIENT_NOT_ALLOWLISTED', score: 0.8 }, { agent: 'evaluator', label: 'STRUCTURING', detail: '$30k pattern across run (InjectionTask6).', score: 0.95 }, { agent: 'supervisor', label: 'HARD_OVERRIDE_BLOCK', score: 0.92 }, { agent: 'auditor', label: 'PROVENANCE_RECORDED' }], obligations: { prevented_loss: 30000, require_human: true } }, pre_exec: null, post_exec: null, evidence_label: 'MOCKED' },
};
const FALLBACK_ROLLUP: CostRollup = {
  tokens: { prompt: 0, completion: 0, total: 0 },
  decision_mix: { PASS: 1, ALERT: 0, BLOCK: 1, ESCALATE: 1, ROLLBACK: 0, REWRITE: 0 },
  prevented_loss_total: 30000,
  latency_p50_ms: 5,
  latency_p95_ms: 7,
  evidence_label: 'MOCKED',
};

export default function GovernancePage() {
  const { t } = useTranslation();
  const live = useLiveGovernance(WORKFLOW_ID, RUN_ID, FALLBACK_ROWS);
  const cost = useCost(RUN_ID);
  const rollup = cost.data ?? (live.source === 'offline' ? FALLBACK_ROLLUP : null);

  const rows = live.rows;
  const [selKey, setSelKey] = useState<string>('');
  const selectedRow =
    rows.find((r) => stableRowKey(r) === selKey) ?? rows[rows.length - 1] ?? null;

  let detail: VerdictDetail | null = null;
  if (selectedRow) {
    detail =
      live.detailByVerdict.get(selectedRow.verdict_id) ??
      (live.source === 'offline'
        ? (FALLBACK_DETAIL[selectedRow.verdict_id] ?? null)
        : null);
  }

  const meanScore = rows.length
    ? rows.reduce((s, r) => s + r.risk_score, 0) / rows.length
    : 0;
  const sourceLabel = t(`governance.source_${live.source}`);
  const selectedVerdict =
    detail?.verdict && detail.evidence_label && !evidenceLabelFrom(detail.verdict)
      ? { ...detail.verdict, evidence_label: detail.evidence_label }
      : detail?.verdict;

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

      <div className="mb-6 px-4 py-2 border border-border bg-surface font-mono text-[11px] uppercase tracking-wider text-ink-dim">
        {t('governance.dataSource')}: {sourceLabel}
      </div>

      <div className="mb-8">
        <KpiCards rollup={rollup} meanRiskBand={riskBand(meanScore)} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <LiveMonitor
          rows={rows}
          selectedVerdictId={selectedRow ? stableRowKey(selectedRow) : null}
          onSelect={(r) => setSelKey(stableRowKey(r))}
        />
        <div>
          <div className="mb-2 font-mono text-[11px] uppercase tracking-wider text-ink-dim">
            {t('governance.verdictPanelTitle')}
          </div>
          {selectedVerdict ? (
            <VerdictPanel
              verdict={selectedVerdict}
              preExec={detail?.pre_exec ?? null}
              postExec={detail?.post_exec ?? null}
              guardianEvidence={detail?.guardian_evidence ?? []}
            />
          ) : (
            <div className="border border-border px-4 py-12 text-center font-mono text-[12px] text-ink-dim">
              {selectedRow ? t('governance.loadingDetail') : t('governance.emptyVerdicts')}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
