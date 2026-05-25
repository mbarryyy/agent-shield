import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import VerdictPanel from '@/components/governance/VerdictPanel';
import KpiCards from '@/components/governance/KpiCards';
import ProvenanceDAG from '@/components/governance/ProvenanceDAG';
import LiveMonitor from '@/components/governance/LiveMonitor';
import type { GovernanceVerdict } from '@elydora/shared';
import type { CostRollup, ProvenanceGraph, TimelineRow } from '@/types/governance';

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

  it('allows long guardian labels to wrap inside their lane', () => {
    const verdict: GovernanceVerdict = {
      correlation_id: 'c-long-label',
      decision: 'ESCALATE',
      risk_score: 0.35,
      reasons: [
        { agent: 'defender', label: 'AMOUNT_REVIEW_REQUIRED', score: 0.45 },
      ],
    };
    render(<VerdictPanel verdict={verdict} />);

    expect(screen.getByText('AMOUNT_REVIEW_REQUIRED')).toHaveClass(
      '[overflow-wrap:anywhere]',
    );
  });

  it('renders provider, model, latency, evidence label, and record token evidence when present', () => {
    const verdict: GovernanceVerdict & { evidence_label: 'PROVIDER_BACKED' } = {
      correlation_id: 'c-provider',
      decision: 'ESCALATE',
      risk_score: 0.42,
      latency_ms: 90,
      evidence_label: 'PROVIDER_BACKED',
      reasons: [
        {
          agent: 'evaluator',
          label: 'MODEL_POLICY_REVIEW',
          model_id: 'claude-haiku-4-5-20251001',
          served_via: 'anthropic',
        },
      ],
    };
    render(
      <VerdictPanel
        verdict={verdict}
        preExec={{
          run_id: 'run-provider',
          phase: 'pre_exec',
          payload: {
            llm: {
              model: 'claude-haiku-4-5-20251001',
              prompt_tokens: 150,
              completion_tokens: 40,
            },
          },
        }}
      />,
    );

    expect(screen.getByText('PROVIDER_BACKED')).toBeInTheDocument();
    expect(screen.getByText(/latency 90 ms/i)).toBeInTheDocument();
    expect(screen.getAllByText(/claude-haiku-4-5-20251001/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/anthropic/i)).toBeInTheDocument();
    expect(screen.getByText(/pre_exec llm/i)).toBeInTheDocument();
    expect(screen.getByText(/150 prompt \/ 40 completion/i)).toBeInTheDocument();
  });

  it('renders server guardian evidence rows without relying on verdict reasons', () => {
    const verdict: GovernanceVerdict & { evidence_label: 'MOCKED' } = {
      correlation_id: 'c-guardian-evidence',
      decision: 'ALERT',
      risk_score: 0.42,
      evidence_label: 'MOCKED',
      reasons: [],
    };
    render(
      <VerdictPanel
        verdict={verdict}
        guardianEvidence={[
          {
            record_id: 'r-guardian',
            correlation_id: 'c-guardian-evidence',
            guardian: 'auditor',
            decision: 'ALERT',
            reasons: ['ARQ audit queue requested'],
            model_id: 'fixture-auditor-v1',
            served_via: 'local',
            prompt_tokens: 3,
            completion_tokens: 2,
            latency_ms: 4.5,
            cost_usd: 0.0012,
            tool_calls: ['inspect_chain_state', 'recall_similar_incidents'],
            memory_backend: 'chroma',
            collection: 'agent_shield_worker_memory_test',
            hit_count: 1,
            memory_latency_ms: 2.4,
            top_hit_id: 'rec-prior',
            score: 0.98,
            distance: 0.02,
          },
        ]}
      />,
    );

    expect(screen.getByText('MOCKED')).toBeInTheDocument();
    expect(screen.getByText('ARQ audit queue requested')).toBeInTheDocument();
    expect(screen.getByText(/fixture-auditor-v1/i)).toBeInTheDocument();
    expect(screen.getByText(/3 prompt \/ 2 completion/i)).toBeInTheDocument();
    expect(screen.getByText(/4.5 ms/i)).toBeInTheDocument();
    expect(screen.getByText(/cost \$0.0012/i)).toBeInTheDocument();
    expect(screen.getByText(/tools inspect_chain_state, recall_similar_incidents/i)).toBeInTheDocument();
    expect(screen.getByText(/memory chroma · agent_shield_worker_memory_test · 1 hit/i)).toBeInTheDocument();
    expect(screen.getByText(/rec-prior · score 0.98/i)).toBeInTheDocument();
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

  it('surfaces the rollup evidence label and token breakdown without recomputing cost', () => {
    const rollup: CostRollup & { evidence_label: 'MEASURED'; cost_usd: number } = {
      tokens: { prompt: 120, completion: 40, total: 160 },
      decision_mix: { PASS: 1, ALERT: 0, BLOCK: 1, ESCALATE: 1, ROLLBACK: 0, REWRITE: 0 },
      prevented_loss_total: 30000,
      latency_p50_ms: 8,
      latency_p95_ms: 21,
      evidence_label: 'MEASURED',
      cost_usd: 0.0123,
    };
    render(<KpiCards rollup={rollup} />);

    expect(screen.getByText('MEASURED')).toBeInTheDocument();
    expect(screen.getByText(/160 tokens/i)).toBeInTheDocument();
    expect(screen.getByText(/120 prompt \/ 40 completion/i)).toBeInTheDocument();
    expect(screen.getByText(/\$0.01 cost/i)).toBeInTheDocument();
  });
});

describe('LiveMonitor evidence labels', () => {
  it('renders row-level evidence labels distinctly from the data-source label', () => {
    const rows: Array<TimelineRow & { evidence_label: 'MOCKED' | 'SKIPPED' }> = [
      {
        verdict_id: 'v1',
        record_id: 'r1',
        correlation_id: 'corr-mocked',
        run_id: 'run-1',
        decision: 'BLOCK',
        risk_score: 0.92,
        latency_ms: 18,
        created_at: Date.now(),
        evidence_label: 'MOCKED',
      },
      {
        verdict_id: 'v2',
        record_id: 'r2',
        correlation_id: 'corr-skipped',
        run_id: 'run-1',
        decision: 'PASS',
        risk_score: 0.03,
        latency_ms: null,
        created_at: Date.now(),
        evidence_label: 'SKIPPED',
      },
    ];

    render(<LiveMonitor rows={rows} />);

    expect(screen.getByText('MOCKED')).toBeInTheDocument();
    expect(screen.getByText('SKIPPED')).toBeInTheDocument();
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
