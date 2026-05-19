'use client';

import { useTranslation } from 'react-i18next';
import { truncateHash } from '@/lib/hooks';
import type { ProvenanceGraph, ProvenanceNode } from '@/types/governance';
import { isBlockedIntent } from '@/types/governance';
import { DecisionBadge } from './badges';

// U4 — correlation_id intent↔outcome provenance DAG over the LOCKED
// server shape (GET /v1/governance/runs/{id}/provenance:
// nodes[{record_id,phase,correlation_id,decision,seq_no,chain_hash}],
// edges[{src,dst,kind:"chain"|"correlation"}]). Generalizes the Elydora
// ChainVisualization Block/Arrow idiom (ChainVisualization left intact
// for operation-detail). A blocked-intent node (decision==BLOCK, DERIVED)
// is PERMANENT AUDIT EVIDENCE of a pre-execution BLOCK — NOT a rollback
// (Act-3 GATE-ARCH L6/124/128). The console only RENDERS the
// server-provided graph (Auditor networkx) — it does not infer provenance.

function Node({ node, blockedLabel }: { node: ProvenanceNode; blockedLabel: string }) {
  const blocked = isBlockedIntent(node);
  return (
    <div
      className={`border p-3 min-w-[190px] shrink-0 ${
        blocked ? 'border-red-300 bg-red-50' : 'border-border bg-surface'
      }`}
    >
      <div className="font-mono text-[10px] uppercase tracking-wider text-ink-dim mb-1">
        #{node.seq_no} · {node.phase ?? '—'}
      </div>
      <div className="font-mono text-[11px] text-ink mb-2 break-all">
        {truncateHash(node.correlation_id ?? node.record_id, 8)}
      </div>
      {node.decision ? (
        <DecisionBadge decision={node.decision} />
      ) : (
        <span className="font-mono text-[11px] text-ink-dim italic">—</span>
      )}
      {blocked && (
        <div className="mt-2 font-mono text-[10px] uppercase tracking-wider text-red-700">
          {blockedLabel}
        </div>
      )}
    </div>
  );
}

function Arrow({ kind }: { kind: 'chain' | 'correlation' }) {
  return (
    <div className="flex flex-col items-center px-2 shrink-0">
      <svg width="28" height="12" viewBox="0 0 24 12" fill="none" className="text-ink-dim">
        <path
          d="M0 6h20M16 1l5 5-5 5"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeDasharray={kind === 'correlation' ? '3 2' : undefined}
        />
      </svg>
      <span className="font-mono text-[9px] text-ink-dim uppercase">{kind}</span>
    </div>
  );
}

export default function ProvenanceDAG({ graph }: { graph: ProvenanceGraph | null }) {
  const { t } = useTranslation();

  if (!graph || graph.nodes.length === 0) {
    return (
      <div className="border border-border px-4 py-12 text-center font-mono text-[12px] text-ink-dim">
        {t('governance.noProvenance')}
      </div>
    );
  }

  const ordered = [...graph.nodes].sort((a, b) => a.seq_no - b.seq_no);
  const edgeKind = new Map(graph.edges.map((e) => [`${e.src}->${e.dst}`, e.kind]));

  return (
    <div className="border border-border bg-surface p-4 sm:p-6 overflow-hidden">
      <div className="section-label mb-4">{t('governance.provenanceTitle')}</div>
      <div className="flex items-center overflow-x-auto pb-2 -mx-1 px-1">
        {ordered.map((n, i) => {
          const prev = i > 0 ? ordered[i - 1] : undefined;
          const kind = prev
            ? (edgeKind.get(`${prev.record_id}->${n.record_id}`) ?? 'chain')
            : 'chain';
          return (
            <div key={n.record_id} className="flex items-center">
              {i > 0 && <Arrow kind={kind} />}
              <Node node={n} blockedLabel={t('governance.blockedIntentEvidence')} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
