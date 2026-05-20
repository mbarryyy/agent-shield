'use client';

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import PageHeader from '@/components/ui/PageHeader';
import IncidentPanel from '@/components/governance/IncidentPanel';
import { DecisionBadge } from '@/components/governance/badges';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useIncidents, useVerdictDetail } from '@/lib/hooks';
import type { Incident, VerdictDetail } from '@/types/governance';

const RUN_ID = process.env.NEXT_PUBLIC_GOV_RUN_ID ?? 'banking';

// PRE-RECORDED-DEMO FALLBACK (data-layer resilience ONLY). ESCALATE-only
// (BLOCK is terminal, not an incident — GATE-ARCH). One pending + one
// resolved to exercise both server-rendered states. Typed to the LOCKED
// incidents shape.
const NOW = 1_716_000_000_000;
const FALLBACK_INCIDENTS: Incident[] = [
  { incident_id: 'v-esc-0001', correlation_id: 'corr-0002', run_id: RUN_ID, decision: 'ESCALATE', risk_score: 0.41, status: 'pending', resolution: null, created_at: NOW - 6000 },
  { incident_id: 'v-esc-0002', correlation_id: 'corr-0005', run_id: RUN_ID, decision: 'ESCALATE', risk_score: 0.33, status: 'resolved', resolution: 'accept', created_at: NOW - 60000 },
];
const FALLBACK_DETAIL: Record<string, VerdictDetail> = {
  'corr-0002': { correlation_id: 'corr-0002', verdict: { correlation_id: 'corr-0002', decision: 'ESCALATE', risk_score: 0.41, reasons: [{ agent: 'defender', label: 'AMOUNT_ABOVE_BASELINE', score: 0.4 }, { agent: 'supervisor', label: 'HUMAN_REVIEW', detail: 'Above this user’s historical pattern.' }], obligations: { require_human: true } }, pre_exec: null, post_exec: null },
  'corr-0005': { correlation_id: 'corr-0005', verdict: { correlation_id: 'corr-0005', decision: 'ESCALATE', risk_score: 0.33, reasons: [{ agent: 'supervisor', label: 'HUMAN_REVIEW' }], obligations: { require_human: true } }, pre_exec: null, post_exec: null },
};

// Console → server decision vocabulary (resume body.decision; the locked
// resolution enum). Approve = accept the action; Reject = ignore it.
const ACTION_DECISION: Record<'approve' | 'reject', string> = {
  approve: 'accept',
  reject: 'ignore',
};

export default function GovernanceIncidentsPage() {
  const { t } = useTranslation();
  const { canResolveIncidents } = useAuth();
  const incidentsQuery = useIncidents({ run_id: RUN_ID });
  const live = incidentsQuery.data != null;
  const incidents = incidentsQuery.data?.incidents ?? FALLBACK_INCIDENTS;

  const [selectedId, setSelectedId] = useState<string>('');
  const selected =
    incidents.find((i) => i.incident_id === selectedId) ?? incidents[0] ?? null;

  const detailQuery = useVerdictDetail(selected?.correlation_id);
  const detail: VerdictDetail | null =
    detailQuery.data ??
    (selected ? (FALLBACK_DETAIL[selected.correlation_id] ?? null) : null);

  async function handleResolve(incidentId: string, action: 'approve' | 'reject') {
    try {
      await api.governance.resume(incidentId, { decision: ACTION_DECISION[action] });
    } finally {
      // Status is server-authoritative — re-read, never reconstruct.
      await incidentsQuery.mutate();
    }
  }

  return (
    <div className="fade-in">
      <PageHeader
        title={t('governance.incidentsTitle')}
        subtitle={t('governance.incidentsSubtitle')}
        breadcrumbs={[
          { label: t('common.dashboard'), href: '/' },
          { label: t('governance.title'), href: '/governance' },
          { label: t('governance.incidentsTitle') },
        ]}
      />

      <div className="mb-6 px-4 py-2 border border-border bg-surface font-mono text-[11px] uppercase tracking-wider text-ink-dim">
        {t('governance.dataSource')}:{' '}
        {live ? t('governance.source_sse') : t('governance.source_offline')}
      </div>

      {incidents.length === 0 ? (
        <div className="border border-border px-4 py-12 text-center font-mono text-[12px] text-ink-dim">
          {t('governance.incidentsEmpty')}
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="border border-border">
            <div className="px-4 py-3 border-b border-border font-mono text-[11px] uppercase tracking-wider text-ink-dim">
              {t('governance.incidentsTitle')}
            </div>
            {incidents.map((inc) => (
              <button
                key={inc.incident_id}
                type="button"
                onClick={() => setSelectedId(inc.incident_id)}
                className={`w-full text-left px-4 py-3 border-b border-border last:border-0 flex items-center justify-between gap-3 hover:bg-surface transition-colors ${
                  inc.incident_id === (selected?.incident_id ?? '') ? 'bg-surface' : ''
                }`}
              >
                <span className="font-mono text-[13px] text-ink break-all">
                  {inc.incident_id}
                </span>
                <DecisionBadge decision={inc.decision} />
              </button>
            ))}
          </div>
          <div>
            {selected ? (
              <IncidentPanel
                incident={selected}
                detail={detail}
                onResolve={canResolveIncidents ? handleResolve : undefined}
              />
            ) : (
              <div className="border border-border px-4 py-12 text-center font-mono text-[12px] text-ink-dim">
                {t('governance.incidentsEmpty')}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
