'use client';

import { useTranslation } from 'react-i18next';
import { formatRelativeTime } from '@/lib/hooks';
import type { TimelineRow } from '@/types/governance';
import { riskBand } from '@/types/governance';
import { DecisionBadge, EvidenceBadge, RiskBadge } from './badges';

// U2 — the live monitor. Presentational over the LOCKED timeline feed
// (GET /v1/governance/runs/{id}/timeline rows: flat
// {verdict_id,record_id,correlation_id,run_id,decision,risk_score,
// latency_ms,created_at}). Full verdict + paired records load from
// /verdicts/{correlation_id} on row click. Row tint follows the LOCKED
// §3.3 bands; the console never fabricates a score/decision. The
// SSE/poll data source is the isolated adapter (this component is
// source-agnostic — takes rows as a prop).

const BAND_ROW: Record<string, string> = {
  PASS: '',
  ALERT: 'bg-amber-50',
  ESCALATE: 'bg-amber-50',
  BLOCK: 'bg-red-50',
};

export default function LiveMonitor({
  rows,
  selectedVerdictId,
  onSelect,
}: {
  rows: TimelineRow[];
  /** carry-in #1: selection identity is the server-unique verdict_id
   *  (stable even when MockedLLM collapses correlation_id on the mock
   *  path), so [PASS,PASS,BLOCK] stay distinct rows. */
  selectedVerdictId?: string | null;
  onSelect?: (row: TimelineRow) => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="border border-border">
      <div className="px-4 py-3 border-b border-border font-mono text-[11px] uppercase tracking-wider text-ink-dim">
        {t('governance.liveMonitorTitle')}
      </div>
      {rows.length === 0 ? (
        <div className="px-4 py-8 text-center font-mono text-[12px] text-ink-dim">
          {t('governance.emptyVerdicts')}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[600px]">
            <thead>
              <tr className="border-b border-border">
                {['colTime', 'colCorrelation', 'colDecision', 'colRisk', 'colLatency', 'colEvidence'].map(
                  (k) => (
                    <th
                      key={k}
                      className="px-4 py-2 text-left font-mono text-[10px] uppercase tracking-wider text-ink-dim"
                    >
                      {t(`governance.${k}`)}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const tint = BAND_ROW[riskBand(r.risk_score)] ?? '';
                const selected = selectedVerdictId === r.verdict_id;
                return (
                  <tr
                    key={r.verdict_id}
                    onClick={() => onSelect?.(r)}
                    className={`border-b border-border last:border-0 ${tint} ${
                      onSelect ? 'cursor-pointer hover:bg-surface' : ''
                    } ${selected ? 'outline outline-1 outline-ink' : ''}`}
                  >
                    <td className="px-4 py-3 font-mono text-[12px] text-ink-dim">
                      {formatRelativeTime(r.created_at)}
                    </td>
                    <td className="px-4 py-3 font-mono text-[13px] text-ink break-all">
                      {r.correlation_id}
                    </td>
                    <td className="px-4 py-3">
                      <DecisionBadge decision={r.decision} />
                    </td>
                    <td className="px-4 py-3">
                      <RiskBadge score={r.risk_score} />
                    </td>
                    <td className="px-4 py-3 font-mono text-[12px] text-ink-dim">
                      {r.latency_ms != null ? `${r.latency_ms} ms` : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <EvidenceBadge label={r.evidence_label} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
