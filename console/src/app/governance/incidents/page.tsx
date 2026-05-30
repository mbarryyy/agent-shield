'use client';

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import PageHeader from '@/components/ui/PageHeader';
import IncidentPanel from '@/components/governance/IncidentPanel';
import { DecisionBadge } from '@/components/governance/badges';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useIncidents, useVerdictDetail } from '@/lib/hooks';
import type { VerdictDetail } from '@/types/governance';

const RUN_ID = process.env.NEXT_PUBLIC_GOV_RUN_ID ?? 'banking';

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
  const incidents = incidentsQuery.data?.incidents ?? [];

  const [selectedId, setSelectedId] = useState<string>('');
  const selected =
    incidents.find((i) => i.incident_id === selectedId) ?? incidents[0] ?? null;

  const detailQuery = useVerdictDetail(selected?.correlation_id);
  const detail: VerdictDetail | null = detailQuery.data ?? null;

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
        {live ? t('governance.source_poll') : t('governance.source_backend_empty')}
      </div>

      {incidents.length === 0 ? (
        <div className="border border-border px-4 py-12 text-center font-mono text-[12px] text-ink-dim">
          {live ? t('governance.incidentsEmpty') : t('governance.backendEmpty')}
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
