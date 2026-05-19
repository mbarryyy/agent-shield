'use client';

import type { Decision } from '@elydora/shared';
import { riskBand } from '@/types/governance';

// Decision -> badge classes. Bands/colours are presentational only; the
// console never asserts a decision — it renders whatever the real verdict
// carries (honest-UI: demo L29, no fabricated state).
const DECISION_STYLE: Record<Decision, string> = {
  PASS: 'text-ink-dim border-border',
  ALERT: 'text-amber-700 border-amber-300',
  BLOCK: 'text-red-700 border-red-300',
  ESCALATE: 'text-amber-700 border-amber-300',
  ROLLBACK: 'text-red-700 border-red-300',
  REWRITE: 'text-ink border-border',
};

export function DecisionBadge({ decision }: { decision: Decision }) {
  return (
    <span
      className={`font-mono text-[11px] uppercase tracking-wider px-2 py-1 border ${DECISION_STYLE[decision]}`}
    >
      {decision}
    </span>
  );
}

// Pending = the sync gate has not returned a verdict yet (live-monitor row
// holds PENDING; demo L123). Distinct from any decision.
export function PendingBadge({ label }: { label: string }) {
  return (
    <span className="font-mono text-[11px] uppercase tracking-wider px-2 py-1 border border-border border-dashed text-ink-dim">
      {label}
    </span>
  );
}

// Renders the live risk SCORE plus its derived §3.3 band label. The score
// is whatever the verdict returns (runtime output, never hardcoded); only
// the band label is derived (master §3.3 / demo L29).
export function RiskBadge({ score }: { score: number | null | undefined }) {
  const band = riskBand(score);
  const cls =
    band === 'PASS'
      ? 'text-ink-dim'
      : band === 'ALERT' || band === 'ESCALATE'
        ? 'text-amber-700'
        : 'text-red-700';
  return (
    <span className={`font-mono text-[12px] ${cls}`}>
      {(score ?? 0).toFixed(2)}
      <span className="text-ink-dim"> · {band}</span>
    </span>
  );
}
