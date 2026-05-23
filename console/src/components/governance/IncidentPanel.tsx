'use client';

import { useTranslation } from 'react-i18next';
import type { Incident, VerdictDetail } from '@/types/governance';
import { evidenceLabelFrom } from '@/types/governance';
import { DecisionBadge, RiskBadge } from './badges';
import VerdictPanel from './VerdictPanel';

// U6 — incident detail + HITL control. The incident row is
// SERVER-AUTHORITATIVE (lightweight: id/correlation/decision/risk/status);
// the full verdict + paired records load from /verdicts/{correlation_id}
// (VerdictDetail) when opened. The Approve/Reject handler is INJECTED
// (`onResolve`) and round-trips server PR-S5
// POST /v1/governance/incidents/{incident_id}/resume — the one console
// WRITE; the server/LangGraph owns the resume and the resulting status
// (console holds no resolution state of its own).
export default function IncidentPanel({
  incident,
  detail,
  onResolve,
}: {
  incident: Incident;
  detail?: VerdictDetail | null;
  onResolve?: (incidentId: string, action: 'approve' | 'reject') => void;
}) {
  const { t } = useTranslation();
  const pending = incident.status === 'pending';
  const verdict =
    detail?.verdict && detail.evidence_label && !evidenceLabelFrom(detail.verdict)
      ? { ...detail.verdict, evidence_label: detail.evidence_label }
      : detail?.verdict;

  return (
    <div className="border border-border">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <DecisionBadge decision={incident.decision} />
          <RiskBadge score={incident.risk_score} />
        </div>
        <span className="font-mono text-[11px] uppercase tracking-wider text-ink-dim">
          {t(`governance.incidentStatus_${incident.status}`)}
        </span>
      </div>

      <div className="px-4 py-3 border-b border-border font-mono text-[11px] text-ink-dim flex flex-wrap gap-x-6 gap-y-1">
        <span>{incident.incident_id}</span>
        <span className="break-all">{incident.correlation_id}</span>
        {incident.resolution && (
          <span>
            {t('governance.incidentResolution')}:{' '}
            {t(`governance.resolution_${incident.resolution}`)}
          </span>
        )}
      </div>

      <div className="p-4">
        {verdict ? (
          <VerdictPanel
            verdict={verdict}
            preExec={detail?.pre_exec ?? null}
            postExec={detail?.post_exec ?? null}
            guardianEvidence={detail?.guardian_evidence ?? []}
          />
        ) : (
          <div className="border border-border px-4 py-8 text-center font-mono text-[12px] text-ink-dim">
            {t('governance.loadingDetail')}
          </div>
        )}
      </div>

      {pending && (
        <div className="px-4 py-3 border-t border-border flex gap-3">
          <button
            type="button"
            onClick={() => onResolve?.(incident.incident_id, 'approve')}
            className="px-4 py-2 border border-border font-mono text-[12px] uppercase tracking-wider text-ink hover:bg-surface transition-colors"
          >
            {t('governance.approve')}
          </button>
          <button
            type="button"
            onClick={() => onResolve?.(incident.incident_id, 'reject')}
            className="px-4 py-2 border border-red-300 font-mono text-[12px] uppercase tracking-wider text-red-700 hover:bg-red-50 transition-colors"
          >
            {t('governance.reject')}
          </button>
        </div>
      )}
    </div>
  );
}
