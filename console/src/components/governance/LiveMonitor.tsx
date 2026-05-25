'use client';

import { useTranslation } from 'react-i18next';
import { formatRelativeTime } from '@/lib/hooks';
import type { TimelineRow } from '@/types/governance';
import { DecisionBadge, EvidenceBadge, RiskBadge } from './badges';

// U2 — the live monitor. Presentational over the LOCKED timeline feed
// (GET /v1/governance/runs/{id}/timeline rows: flat
// {verdict_id,record_id,correlation_id,run_id,decision,risk_score,
// latency_ms,created_at}). Full verdict + paired records load from
// /verdicts/{correlation_id} on row click. Decisions and risk stay visible in
// their badges; the row background is reserved for actual hover/selection so
// recording viewers do not read a BLOCK row as pre-selected.
const latency = new Intl.NumberFormat('en-US', {
  maximumFractionDigits: 2,
});

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
                const selected = selectedVerdictId === r.verdict_id;
                return (
                  <tr
                    key={r.verdict_id}
                    onClick={() => onSelect?.(r)}
                    className={`border-b border-border last:border-0 ${
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
                      {r.latency_ms != null ? `${latency.format(r.latency_ms)} ms` : '—'}
                    </td>
                    <td className="px-4 py-3">
                      {r.evidence_label ? <EvidenceBadge label={r.evidence_label} /> : null}
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
