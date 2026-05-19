'use client';

import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import PageHeader from '@/components/ui/PageHeader';
import KpiCards from '@/components/governance/KpiCards';
import ProvenanceDAG from '@/components/governance/ProvenanceDAG';
import { useCost, useProvenance } from '@/lib/hooks';
import type { CostRollup, ProvenanceGraph } from '@/types/governance';

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
  if (!runId) return null;

  const rollup = cost.data ?? fallbackRollup();
  const graph = prov.data ?? fallbackGraph(runId);
  const live = cost.data != null || prov.data != null;

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
        {live ? t('governance.source_sse') : t('governance.source_offline')}
      </div>

      <div className="mb-8">
        <KpiCards rollup={rollup} />
      </div>

      <ProvenanceDAG graph={graph} />
    </div>
  );
}
