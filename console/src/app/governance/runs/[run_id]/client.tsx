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
import { BACKEND_EMPTY_MESSAGE, fallbackFixturesEnabled } from '@/lib/fallbackFixtures';
import type { CostRollup, ProvenanceGraph, TimelineRow, VerdictDetail } from '@/types/governance';
import { evidenceLabelFrom, riskBand } from '@/types/governance';

// PRE-RECORDED-DEMO FALLBACK (data-layer resilience ONLY — used if the
// server READ returns nothing/errors; NOT a zero-backend mode). Typed
// against the LOCKED server shapes. Previews the InjectionTask6 money-shot:
// a pre-exec BLOCK whose blocked-intent node is permanent evidence (NOT a
// rollback — GATE-ARCH).
function fallbackRollup(): CostRollup {
  return {
    tokens: { prompt: 0, completion: 0, total: 0 },
    decision_mix: { PASS: 3, ALERT: 0, BLOCK: 1, ESCALATE: 0, ROLLBACK: 0, REWRITE: 0 },
    prevented_loss_total: 30000,
    latency_p50_ms: 5,
    latency_p95_ms: 7,
    evidence_label: 'MOCKED',
  };
}
function fallbackTimeline(runId: string): TimelineRow[] {
  return [
    { verdict_id: 'v-run-0001', record_id: 'r-0001', correlation_id: 'corr-0001', run_id: runId, decision: 'PASS', risk_score: 0.03, latency_ms: 4, created_at: 1_716_000_000_000, evidence_label: 'MOCKED' },
    { verdict_id: 'v-run-0002', record_id: 'r-0002', correlation_id: 'corr-0002', run_id: runId, decision: 'PASS', risk_score: 0.05, latency_ms: 6, created_at: 1_716_000_001_000, evidence_label: 'MOCKED' },
    { verdict_id: 'v-run-0003', record_id: 'r-0003', correlation_id: 'corr-0003', run_id: runId, decision: 'PASS', risk_score: 0.04, latency_ms: 5, created_at: 1_716_000_002_000, evidence_label: 'MOCKED' },
    { verdict_id: 'v-run-0004', record_id: 'r-0004', correlation_id: 'corr-0004', run_id: runId, decision: 'BLOCK', risk_score: 0.92, latency_ms: 7, created_at: 1_716_000_003_000, evidence_label: 'MOCKED' },
  ];
}
function fallbackDetail(): VerdictDetail {
  return {
    correlation_id: 'corr-0004',
    verdict: {
      correlation_id: 'corr-0004',
      decision: 'BLOCK',
      risk_score: 0.92,
      reasons: [
        { agent: 'defender', label: 'RECIPIENT_NOT_ALLOWLISTED', score: 0.8 },
        { agent: 'supervisor', label: 'HARD_OVERRIDE_BLOCK', score: 0.92 },
        { agent: 'auditor', label: 'PROVENANCE_RECORDED' },
      ],
      obligations: { prevented_loss: 30000 },
    },
    pre_exec: null,
    post_exec: null,
    evidence_label: 'MOCKED',
  };
}
function fallbackGraph(runId: string): ProvenanceGraph {
  return {
    run_id: runId,
    nodes: [
      { record_id: 'r-0001', phase: 'pre_exec', correlation_id: 'corr-0001', decision: 'PASS', seq_no: 0, chain_hash: 'aGFzaDA' },
      { record_id: 'r-0002', phase: 'pre_exec', correlation_id: 'corr-0002', decision: 'PASS', seq_no: 1, chain_hash: 'aGFzaDE' },
      { record_id: 'r-0003', phase: 'pre_exec', correlation_id: 'corr-0003', decision: 'PASS', seq_no: 2, chain_hash: 'aGFzaDI' },
      { record_id: 'r-0004', phase: 'pre_exec', correlation_id: 'corr-0004', decision: 'BLOCK', seq_no: 3, chain_hash: 'aGFzaDM' },
    ],
    edges: [
      { src: 'r-0001', dst: 'r-0002', kind: 'chain' },
      { src: 'r-0002', dst: 'r-0003', kind: 'chain' },
      { src: 'r-0003', dst: 'r-0004', kind: 'chain' },
    ],
  };
}

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
  const useFallbackFixtures = fallbackFixturesEnabled();

  const live = cost.data != null || prov.data != null || timeline.data != null || incidentsQuery.data != null;
  const rollup = cost.data ?? (useFallbackFixtures ? fallbackRollup() : null);
  const graph = prov.data ?? (useFallbackFixtures ? fallbackGraph(runId) : null);
  const rows = timeline.data?.rows ?? (useFallbackFixtures ? fallbackTimeline(runId) : []);
  const selectedRow = rows.find((row) => row.decision === 'BLOCK') ?? rows[rows.length - 1] ?? null;
  const detailQuery = useVerdictDetail(timeline.data && selectedRow ? selectedRow.correlation_id : undefined);
  const detail = detailQuery.data ?? (useFallbackFixtures && !timeline.data ? fallbackDetail() : null);
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
        {live ? t('governance.source_poll') : useFallbackFixtures ? t('governance.source_offline') : t('governance.source_backend_empty')}
      </div>

      {!live && useFallbackFixtures && (
        <div className="mb-6 px-4 py-3 border border-amber-300 bg-amber-50 font-mono text-[12px] text-amber-900">
          Fixture data is enabled for local development; live backend data is not available yet.
        </div>
      )}

      {!useFallbackFixtures && rows.length === 0 && (
        <div className="mb-6 border border-border px-4 py-12 text-center font-mono text-[12px] text-ink-dim">
          {BACKEND_EMPTY_MESSAGE}
        </div>
      )}

      <div className="mb-8">
        <KpiCards rollup={rollup} meanRiskBand={riskBand(meanScore)} />
      </div>

      {rows.length > 0 && (
        <div data-testid="governance-run-flow" className="space-y-6 mb-6">
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
