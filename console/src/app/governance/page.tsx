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
import type { VerdictDetail } from '@/types/governance';
import { evidenceLabelFrom, riskBand } from '@/types/governance';

const WORKFLOW_ID = process.env.NEXT_PUBLIC_GOV_WORKFLOW_ID ?? 'banking';
const RUN_ID = process.env.NEXT_PUBLIC_GOV_RUN_ID ?? 'banking';

export default function GovernancePage() {
  const { t } = useTranslation();
  const live = useLiveGovernance(WORKFLOW_ID, RUN_ID);
  const cost = useCost(RUN_ID);
  const rollup = cost.data ?? null;

  const rows = live.rows;
  const [selKey, setSelKey] = useState<string>('');
  const selectedRow =
    rows.find((r) => stableRowKey(r) === selKey) ?? rows[rows.length - 1] ?? null;

  let detail: VerdictDetail | null = null;
  if (selectedRow) {
    detail = live.detailByVerdict.get(selectedRow.verdict_id) ?? null;
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

      {rows.length === 0 ? (
        <div className="border border-border px-4 py-12 text-center font-mono text-[12px] text-ink-dim">
          {t('governance.backendEmpty')}
        </div>
      ) : (
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
      )}
    </div>
  );
}
