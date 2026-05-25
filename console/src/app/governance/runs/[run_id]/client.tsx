'use client';

import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import PageHeader from '@/components/ui/PageHeader';
import VerdictPanel from '@/components/governance/VerdictPanel';
import { DecisionBadge, EvidenceBadge, RiskBadge } from '@/components/governance/badges';
import {
  formatRelativeTime,
  truncateHash,
  useCost,
  useGovTimeline,
  useIncidents,
  useProvenance,
  useVerdictDetail,
} from '@/lib/hooks';
import { stableRowKey } from '@/lib/governanceKeys';
import { BACKEND_EMPTY_MESSAGE, fallbackFixturesEnabled } from '@/lib/fallbackFixtures';
import type { CostRollup, Incident, ProvenanceGraph, TimelineRow, VerdictDetail } from '@/types/governance';
import { evidenceLabelFrom, isBlockedIntent } from '@/types/governance';

// PRE-RECORDED-DEMO FALLBACK (data-layer resilience ONLY — used if the
// server READ returns nothing/errors; NOT a zero-backend mode). Typed
// against the LOCKED server shapes. Previews the InjectionTask6 money-shot:
// a pre-exec BLOCK whose blocked-intent node is permanent evidence (NOT a
// rollback — GATE-ARCH).
function fallbackRollup(): CostRollup {
  return {
    tokens: { prompt: 0, completion: 0, total: 0 },
    decision_mix: { PASS: 2, ALERT: 0, BLOCK: 1, ESCALATE: 1, ROLLBACK: 0, REWRITE: 0 },
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
    { verdict_id: 'v-run-0003', record_id: 'r-0003', correlation_id: 'corr-0003', run_id: runId, decision: 'ESCALATE', risk_score: 0.45, latency_ms: 5, created_at: 1_716_000_002_000, evidence_label: 'MOCKED' },
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
      { record_id: 'r-0003', phase: 'pre_exec', correlation_id: 'corr-0003', decision: 'ESCALATE', seq_no: 2, chain_hash: 'aGFzaDI' },
      { record_id: 'r-0004', phase: 'pre_exec', correlation_id: 'corr-0004', decision: 'BLOCK', seq_no: 3, chain_hash: 'aGFzaDM' },
    ],
    edges: [
      { src: 'r-0001', dst: 'r-0002', kind: 'chain' },
      { src: 'r-0002', dst: 'r-0003', kind: 'chain' },
      { src: 'r-0003', dst: 'r-0004', kind: 'chain' },
    ],
  };
}

function displayRunName(runId: string): string {
  if (runId === 'demo-shield-block') return 'Payment control run';
  return `Run ${runId}`;
}

function formatMoney(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(value);
}

function countRows(rows: TimelineRow[], decision: TimelineRow['decision']): number {
  return rows.filter((row) => row.decision === decision).length;
}

function countFromRollup(
  rollup: CostRollup | null,
  rows: TimelineRow[],
  decision: TimelineRow['decision'],
): number {
  return rollup?.decision_mix?.[decision] ?? countRows(rows, decision);
}

function criticalRow(rows: TimelineRow[]): TimelineRow | null {
  const priority: Record<string, number> = {
    BLOCK: 0,
    ESCALATE: 1,
    ALERT: 2,
    REWRITE: 3,
    ROLLBACK: 4,
    PASS: 5,
  };
  return [...rows].sort((a, b) => {
    const pa = priority[a.decision] ?? 9;
    const pb = priority[b.decision] ?? 9;
    if (pa !== pb) return pa - pb;
    return b.created_at - a.created_at;
  })[0] ?? null;
}

function orderedTimeline(rows: TimelineRow[]): TimelineRow[] {
  return [...rows].sort((a, b) => a.created_at - b.created_at);
}

function stepNumberForRow(rows: TimelineRow[], row: TimelineRow | null): string | null {
  if (!row) return null;
  const index = orderedTimeline(rows).findIndex((candidate) => stableRowKey(candidate) === stableRowKey(row));
  return index >= 0 ? String(index + 1).padStart(2, '0') : null;
}

function SignedEvidenceBadge() {
  return (
    <span className="font-mono text-[10px] uppercase tracking-wider px-2 py-1 border border-border text-ink-dim">
      SIGNED
    </span>
  );
}

function EvidenceCell({ row }: { row: TimelineRow }) {
  return row.evidence_label ? <EvidenceBadge label={row.evidence_label} /> : <SignedEvidenceBadge />;
}

function RunOutcomeStrip({
  rollup,
  rows,
}: {
  rollup: CostRollup | null;
  rows: TimelineRow[];
}) {
  const totalVerdicts = rows.length;
  const escalated = countFromRollup(rollup, rows, 'ESCALATE');
  const blocked = countFromRollup(rollup, rows, 'BLOCK');
  const preventedLoss = rollup?.prevented_loss_total ?? 0;

  return (
    <div className="mb-6 border border-border">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between gap-3 flex-wrap">
        <div className="section-label">Payment control summary</div>
        <span className="font-mono text-[11px] uppercase tracking-wider text-ink-dim">
          Intervention complete
        </span>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 divide-x-0 divide-y divide-border lg:divide-y-0 lg:divide-x">
        {[
          ['Verdicts', String(totalVerdicts)],
          ['Escalated', String(escalated)],
          ['Blocked', String(blocked)],
          ['Prevented loss', formatMoney(preventedLoss)],
        ].map(([label, value]) => (
          <div key={label} className="px-4 py-4 min-w-0">
            <div className="font-mono text-[10px] uppercase tracking-wider text-ink-dim mb-2">
              {label}
            </div>
            <div className="font-sans text-2xl font-semibold text-ink break-words">
              {value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function stepTitle(row: TimelineRow): string {
  if (row.decision === 'BLOCK') return 'Blocked structured transfer';
  if (row.decision === 'ESCALATE') return 'Analyst review required';
  if (row.decision === 'PASS') return 'Transfer cleared';
  return `${row.decision} verdict`;
}

function stepDescription(row: TimelineRow): string {
  if (row.decision === 'BLOCK') {
    return 'Cumulative exposure crossed the transfer policy limit before execution.';
  }
  if (row.decision === 'ESCALATE') {
    return 'High-value vendor payment required human approval before execution.';
  }
  if (row.decision === 'PASS') {
    return 'Payment stayed within the active policy controls for this run.';
  }
  return 'Recorded policy verdict for this payment action.';
}

function RunStepList({
  rows,
  selectedKey,
  onSelect,
}: {
  rows: TimelineRow[];
  selectedKey: string | null;
  onSelect: (row: TimelineRow) => void;
}) {
  const orderedRows = orderedTimeline(rows);
  return (
    <div className="border border-border">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between gap-3 flex-wrap">
        <div className="section-label">Payment sequence</div>
        <span className="font-mono text-[11px] text-ink-dim">
          {orderedRows.length} signed verdicts
        </span>
      </div>
      <div className="divide-y divide-border">
        {orderedRows.map((row, index) => {
          const key = stableRowKey(row);
          const selected = selectedKey === key;
          return (
            <button
              key={key}
              type="button"
              onClick={() => onSelect(row)}
              aria-pressed={selected}
              className={`w-full text-left px-4 py-4 border-l-4 transition-colors hover:bg-surface ${
                selected ? 'border-l-ink bg-surface' : 'border-l-transparent'
              }`}
            >
              <div className="grid grid-cols-1 lg:grid-cols-[56px_minmax(0,1fr)_92px] gap-3 items-start">
                <div className="font-mono text-[11px] uppercase tracking-wider text-ink-dim">
                  {String(index + 1).padStart(2, '0')}
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2 mb-2">
                    <DecisionBadge decision={row.decision} />
                    <RiskBadge score={row.risk_score} />
                    <EvidenceCell row={row} />
                  </div>
                  <div className="font-sans text-[15px] font-semibold text-ink mb-1">
                    {stepTitle(row)}
                  </div>
                  <div className="font-mono text-[12px] text-ink-dim mb-2 break-words">
                    {stepDescription(row)}
                  </div>
                  <div className="font-mono text-[12px] text-ink-dim break-all">
                    {row.correlation_id}
                  </div>
                </div>
                <div className="font-mono text-[11px] text-ink-dim lg:text-right">
                  <div>{formatRelativeTime(row.created_at)}</div>
                  <div>{row.latency_ms != null ? `${row.latency_ms.toFixed(2)} ms` : 'latency pending'}</div>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function resolutionLabel(incident: Incident): string {
  if (!incident.resolution) return incident.status;
  const labels: Record<NonNullable<Incident['resolution']>, string> = {
    accept: 'accepted',
    edit: 'edited',
    response: 'responded',
    ignore: 'ignored',
  };
  return `${incident.status} · ${labels[incident.resolution]}`;
}

function HumanReviewPanel({
  incidents,
  onSelectCorrelation,
}: {
  incidents: Incident[];
  onSelectCorrelation: (correlationId: string) => void;
}) {
  return (
    <div className="border border-border">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between gap-3 flex-wrap">
        <div className="section-label">Analyst review</div>
        <span className="font-mono text-[11px] text-ink-dim">
          {incidents.length} escalation{incidents.length === 1 ? '' : 's'}
        </span>
      </div>
      {incidents.length === 0 ? (
        <div className="px-4 py-6 font-mono text-[12px] text-ink-dim">
          No analyst-review incidents for this run.
        </div>
      ) : (
        <div className="divide-y divide-border">
          {incidents.map((incident) => (
            <button
              key={incident.incident_id}
              type="button"
              onClick={() => onSelectCorrelation(incident.correlation_id)}
              className="w-full text-left px-4 py-4 hover:bg-surface transition-colors"
            >
              <div className="flex flex-wrap items-center gap-3 mb-2">
                <DecisionBadge decision={incident.decision} />
                <RiskBadge score={incident.risk_score} />
                <span className="font-mono text-[11px] uppercase tracking-wider text-ink-dim">
                  {resolutionLabel(incident)}
                </span>
              </div>
              <div className="font-sans text-[15px] font-semibold text-ink mb-1">
                New vendor payment approved after review
              </div>
              <div className="font-mono text-[12px] text-ink break-all">
                {incident.incident_id}
              </div>
              <div className="font-mono text-[11px] text-ink-dim break-all mt-1">
                {incident.correlation_id}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function AuditChainPanel({ graph }: { graph: ProvenanceGraph | null }) {
  const { t } = useTranslation();
  if (!graph || graph.nodes.length === 0) {
    return (
      <div className="border border-border px-4 py-12 text-center font-mono text-[12px] text-ink-dim">
        {t('governance.noProvenance')}
      </div>
    );
  }

  const ordered = [...graph.nodes].sort((a, b) => a.seq_no - b.seq_no);
  const preExecCount = ordered.filter((node) => node.phase === 'pre_exec').length;
  const blockedCount = ordered.filter(isBlockedIntent).length;

  return (
    <div className="border border-border">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between gap-3 flex-wrap">
        <div className="section-label">Audit chain</div>
        <span className="font-mono text-[11px] text-ink-dim">
          {ordered.length} linked records
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-border">
        {[
          ['Pre-exec checks', String(preExecCount)],
          ['Pre-exec blocks', String(blockedCount)],
          ['Run id', displayRunName(graph.run_id)],
        ].map(([label, value]) => (
          <div key={label} className="px-4 py-3 min-w-0">
            <div className="font-mono text-[10px] uppercase tracking-wider text-ink-dim mb-1">
              {label}
            </div>
            <div className="font-mono text-[12px] text-ink break-words">{value}</div>
          </div>
        ))}
      </div>
      <ol className="border-t border-border">
        {ordered.map((node, index) => {
          const step = String(index + 1).padStart(2, '0');
          const blocked = isBlockedIntent(node);
          const isLast = index === ordered.length - 1;
          return (
            <li
              key={node.record_id}
              className={`grid grid-cols-[64px_minmax(0,1fr)] gap-4 px-4 py-4 ${
                blocked ? 'bg-red-50' : ''
              }`}
            >
              <div className="relative flex justify-center">
                {!isLast && (
                  <span
                    aria-hidden="true"
                    className="absolute top-10 bottom-[-16px] w-px bg-border"
                  />
                )}
                <span
                  className={`relative z-10 flex h-10 w-10 items-center justify-center border bg-background font-mono text-[11px] uppercase tracking-wider ${
                    blocked ? 'border-red-300 text-red-700' : 'border-border text-ink'
                  }`}
                >
                  {step}
                </span>
              </div>
              <div className="min-w-0">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[11px] uppercase tracking-wider text-ink-dim">
                    Chain step {step}
                  </span>
                  <span className="font-mono text-[11px] uppercase tracking-wider text-ink-dim">
                    {node.phase ?? 'record'}
                  </span>
                  {node.decision ? <DecisionBadge decision={node.decision} /> : null}
                </div>
                <div className="font-mono text-[12px] text-ink break-all">
                  {truncateHash(node.correlation_id ?? node.record_id, 12)}
                  {blocked && (
                    <span className="ml-3 text-[10px] uppercase tracking-wider text-red-700">
                      {t('governance.blockedIntentEvidence')}
                    </span>
                  )}
                </div>
                <div className="mt-1 font-mono text-[11px] text-ink-dim break-all">
                  record {truncateHash(node.record_id, 10)}
                  {node.chain_hash ? ` · hash ${truncateHash(node.chain_hash, 10)}` : ''}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
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
  const [selKey, setSelKey] = useState<string | null>(null);

  const live = cost.data != null || prov.data != null || timeline.data != null || incidentsQuery.data != null;
  const rollup = cost.data ?? (useFallbackFixtures ? fallbackRollup() : null);
  const graph = prov.data ?? (useFallbackFixtures ? fallbackGraph(runId) : null);
  const rows = timeline.data?.rows ?? (useFallbackFixtures ? fallbackTimeline(runId) : []);
  const selectedRow = rows.find((row) => stableRowKey(row) === selKey) ?? criticalRow(rows);
  const detailQuery = useVerdictDetail(timeline.data && selectedRow ? selectedRow.correlation_id : undefined);
  const detail =
    detailQuery.data ?? (useFallbackFixtures && !timeline.data && selectedRow ? fallbackDetail() : null);
  const incidents = incidentsQuery.data?.incidents ?? [];
  const selectedVerdict =
    detail?.verdict && detail.evidence_label && !evidenceLabelFrom(detail.verdict)
      ? { ...detail.verdict, evidence_label: detail.evidence_label }
      : detail?.verdict;
  const selectedStepNumber = stepNumberForRow(rows, selectedRow);
  const selectCorrelation = (correlationId: string) => {
    const row = rows.find((candidate) => candidate.correlation_id === correlationId);
    if (row) setSelKey(stableRowKey(row));
  };

  if (!runId) return null;
  const runDisplayName = displayRunName(runId);

  return (
    <div className="fade-in">
      <PageHeader
        title={runDisplayName}
        subtitle={t('governance.runSubtitle')}
        breadcrumbs={[
          { label: t('common.dashboard'), href: '/' },
          { label: t('governance.title'), href: '/governance' },
          { label: runDisplayName },
        ]}
      />

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

      <RunOutcomeStrip rollup={rollup} rows={rows} />

      {rows.length > 0 && (
        <div data-testid="governance-run-flow" className="grid grid-cols-1 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] gap-6 mb-6">
          <div className="space-y-6 min-w-0">
            <RunStepList
              rows={rows}
              selectedKey={selectedRow ? stableRowKey(selectedRow) : null}
              onSelect={(row) => setSelKey(stableRowKey(row))}
            />
            <HumanReviewPanel incidents={incidents} onSelectCorrelation={selectCorrelation} />
          </div>
          <div className="min-w-0 self-start">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
              <div className="font-mono text-[11px] uppercase tracking-wider text-ink-dim">
                Selected step evidence
              </div>
              {selectedRow && selectedStepNumber && (
                <span className="font-mono text-[11px] uppercase tracking-wider text-ink-dim">
                  Step {selectedStepNumber} · {selectedRow.decision}
                </span>
              )}
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
                {selectedRow ? t('governance.loadingDetail') : t('governance.selectVerdict')}
              </div>
            )}
          </div>
        </div>
      )}

      <AuditChainPanel graph={graph} />
    </div>
  );
}
