import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import VerdictPanel from '@/components/governance/VerdictPanel';
import KpiCards from '@/components/governance/KpiCards';
import ProvenanceDAG from '@/components/governance/ProvenanceDAG';
import type { GovernanceVerdict } from '@elydora/shared';
import type { CostRollup, ProvenanceGraph } from '@/types/governance';

// W3 governance-component smoke tests — closes part of the G3-NOTE
// tracked-debt while protecting the demo-centerpiece invariants:
//   1. VerdictPanel renders all 4 fixed guardian lanes (Defender,
//      Evaluator, Supervisor, Auditor) from reasons[].agent — the lanes
//      audience-learns in Act-1 must always be present.
//   2. KpiCards binds CostRollup VERBATIM — no recompute; honest-UI.
//   3. ProvenanceDAG marks BLOCK nodes as blocked-intent permanent
//      evidence (NOT a rollback — GATE-ARCH invariant).

describe('VerdictPanel', () => {
  it('renders all 4 guardian lanes', () => {
    const verdict: GovernanceVerdict = {
      correlation_id: 'c1',
      decision: 'BLOCK',
      risk_score: 0.92,
      reasons: [
        { agent: 'defender', label: 'RECIPIENT_NOT_ALLOWLISTED' },
        { agent: 'evaluator', label: 'STRUCTURING' },
        { agent: 'supervisor', label: 'HARD_OVERRIDE_BLOCK' },
        { agent: 'auditor', label: 'PROVENANCE_RECORDED' },
      ],
    };
    render(<VerdictPanel verdict={verdict} />);
    expect(screen.getByText('defender')).toBeInTheDocument();
    expect(screen.getByText('evaluator')).toBeInTheDocument();
    expect(screen.getByText('supervisor')).toBeInTheDocument();
    expect(screen.getByText('auditor')).toBeInTheDocument();
  });
});

describe('KpiCards', () => {
  it('renders $prevented and tokens verbatim from server rollup', () => {
    const rollup: CostRollup = {
      tokens: { prompt: 0, completion: 0, total: 0 },
      decision_mix: { PASS: 1, ALERT: 0, BLOCK: 1, ESCALATE: 1, ROLLBACK: 0, REWRITE: 0 },
      prevented_loss_total: 30000,
      latency_p50_ms: 5,
      latency_p95_ms: 7,
    };
    render(<KpiCards rollup={rollup} />);
    // $30,000 = AgentDojo env-diff oracle MEASURED (rendered, never recomputed).
    expect(screen.getByText('$30,000')).toBeInTheDocument();
    // 0 tokens = the model-free decisive block (honest, rendered verbatim).
    expect(screen.getByText(/0 tokens/i)).toBeInTheDocument();
  });
});

describe('ProvenanceDAG', () => {
  it('marks a BLOCK node as blocked-intent permanent evidence (NOT rollback)', () => {
    const graph: ProvenanceGraph = {
      run_id: 'r1',
      nodes: [
        { record_id: 'n1', phase: 'pre_exec', correlation_id: 'c1', decision: 'BLOCK', seq_no: 0, chain_hash: 'h0' },
      ],
      edges: [],
    };
    render(<ProvenanceDAG graph={graph} />);
    expect(screen.getByText(/permanent evidence/i)).toBeInTheDocument();
  });
});
