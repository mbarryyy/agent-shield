'use client';

import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import PageHeader from '@/components/ui/PageHeader';
import KpiCards from '@/components/governance/KpiCards';
import LiveMonitor from '@/components/governance/LiveMonitor';
import ProvenanceDAG from '@/components/governance/ProvenanceDAG';
import VerdictPanel from '@/components/governance/VerdictPanel';
import { DecisionBadge, RiskBadge } from '@/components/governance/badges';
import {
  useCost,
  useGovTimeline,
  useIncidents,
  useProvenance,
  useVerdictDetail,
} from '@/lib/hooks';
import { stableRowKey } from '@/lib/governanceKeys';
import { evidenceLabelFrom, riskBand } from '@/types/governance';

export default function GovernanceRunShell() {
  const { t } = useTranslation();
  const [runId, setRunId] = useState('');
  useEffect(() => {
    // Path: /governance/runs/<run_id>  ->  split('/') index 3
    setRunId(window.location.pathname.split('/')[3] ?? '');
  }, []);

  const cost = useCost(runId || undefined);
  const prov = useProvenance(runId || undefined);
  const timeline = useGovTimeline(runId || undefined);
  const incidentsQuery = useIncidents({ run_id: runId }, !!runId);

  const live = cost.data != null || prov.data != null || timeline.data != null || incidentsQuery.data != null;
  const rollup = cost.data ?? null;
  const graph = prov.data ?? null;
  const rows = timeline.data?.rows ?? [];
  const selectedRow = rows.find((row) => row.decision === 'BLOCK') ?? rows[rows.length - 1] ?? null;
  const detailQuery = useVerdictDetail(timeline.data && selectedRow ? selectedRow.correlation_id : undefined);
  const detail = detailQuery.data ?? null;
  const incidents = incidentsQuery.data?.incidents ?? [];
  const meanScore = rows.length
    ? rows.reduce((total, row) => total + row.risk_score, 0) / rows.length
    : 0;
  const pendingIncidents = incidents.filter((incident) => incident.status === 'pending');
  const selectedVerdict =
    detail?.verdict && detail.evidence_label && !evidenceLabelFrom(detail.verdict)
      ? { ...detail.verdict, evidence_label: detail.evidence_label }
      : detail?.verdict;

  if (!runId) return null;

  return (
    <div className="fade-in">
      <PageHeader
        title={`${t('governance.runTitle')} ${runId}`}
        subtitle={t('governance.runSubtitle')}
        breadcrumbs={[
          { label: t('common.dashboard'), href: '/' },
          { label: t('governance.title'), href: '/governance' },
          { label: runId },
        ]}
      />

      <div className="mb-6 px-4 py-2 border border-border bg-surface font-mono text-[11px] uppercase tracking-wider text-ink-dim">
        {t('governance.dataSource')}:{' '}
        {live ? t('governance.source_poll') : t('governance.source_backend_empty')}
      </div>

      {!live && rows.length === 0 && (
        <div className="mb-6 border border-border px-4 py-12 text-center font-mono text-[12px] text-ink-dim">
          {t('governance.backendEmpty')}
        </div>
      )}

      <div className="mb-8">
        <KpiCards rollup={rollup} meanRiskBand={riskBand(meanScore)} />
      </div>

      {rows.length > 0 && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 mb-6">
          <LiveMonitor
            rows={rows}
            selectedVerdictId={selectedRow ? stableRowKey(selectedRow) : null}
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
                {t('governance.loadingDetail')}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="border border-border mb-6">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between gap-3 flex-wrap">
          <div className="section-label">Pending HITL incidents</div>
          <span className="font-mono text-[11px] text-ink-dim">
            {pendingIncidents.length} pending / {incidents.length} total
          </span>
        </div>
        {incidents.length === 0 ? (
          <div className="px-4 py-6 font-mono text-[12px] text-ink-dim">
            No server-authoritative HITL incidents for this run.
          </div>
        ) : (
          <div className="divide-y divide-border">
            {incidents.map((incident) => (
              <div key={incident.incident_id} className="px-4 py-3 flex flex-wrap items-center gap-3">
                <span className="font-mono text-[13px] text-ink break-all">
                  {incident.incident_id}
                </span>
                <DecisionBadge decision={incident.decision} />
                <RiskBadge score={incident.risk_score} />
                <span className="font-mono text-[11px] uppercase tracking-wider text-ink-dim">
                  {incident.status}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {graph ? (
        <ProvenanceDAG graph={graph} />
      ) : (
        <div className="border border-border px-4 py-12 text-center font-mono text-[12px] text-ink-dim">
          {t('governance.noProvenance')}
        </div>
      )}
    </div>
  );
}
