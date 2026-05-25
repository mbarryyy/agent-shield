import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import { SWRConfig } from 'swr';
import type { ReactNode } from 'react';
import GovernanceRunShell from '@/app/governance/runs/[run_id]/client';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8787';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  delete process.env.NEXT_PUBLIC_USE_FALLBACK_FIXTURES;
  server.resetHandlers();
});
afterAll(() => server.close());

function Fresh({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      {children}
    </SWRConfig>
  );
}

describe('Governance run detail', () => {
  it('renders backend-driven timeline, guardian reasons, incidents, cost, and provenance', async () => {
    window.history.pushState({}, '', '/governance/runs/run-e2e');
    server.use(
      http.get(`${API_BASE_URL}/v1/governance/runs/run-e2e/cost`, () =>
        HttpResponse.json({
          tokens: { prompt: 120, completion: 40, total: 160 },
          decision_mix: { PASS: 1, ALERT: 0, BLOCK: 1, ESCALATE: 1, ROLLBACK: 0, REWRITE: 0 },
          prevented_loss_total: 30000,
          latency_p50_ms: 8,
          latency_p95_ms: 21,
        }),
      ),
      http.get(`${API_BASE_URL}/v1/governance/runs/run-e2e/provenance`, () =>
        HttpResponse.json({
          run_id: 'run-e2e',
          nodes: [
            { record_id: 'rec-1', phase: 'pre_exec', correlation_id: 'corr-pass', decision: 'PASS', seq_no: 0, chain_hash: 'hash-1' },
            { record_id: 'rec-2', phase: 'pre_exec', correlation_id: 'corr-block', decision: 'BLOCK', seq_no: 1, chain_hash: 'hash-2' },
          ],
          edges: [{ src: 'rec-1', dst: 'rec-2', kind: 'chain' }],
        }),
      ),
      http.get(`${API_BASE_URL}/v1/governance/runs/run-e2e/timeline`, () =>
        HttpResponse.json({
          rows: [
            { verdict_id: 'verdict-pass', record_id: 'rec-1', correlation_id: 'corr-pass', run_id: 'run-e2e', decision: 'PASS', risk_score: 0.03, latency_ms: 5, created_at: 1716000000000 },
            { verdict_id: 'verdict-block', record_id: 'rec-2', correlation_id: 'corr-block', run_id: 'run-e2e', decision: 'BLOCK', risk_score: 0.92, latency_ms: 6, created_at: 1716000001000 },
          ],
          cursor: null,
          total_count: 2,
        }),
      ),
      http.get(`${API_BASE_URL}/v1/governance/verdicts/corr-block`, () =>
        HttpResponse.json({
          correlation_id: 'corr-block',
          verdict: {
            correlation_id: 'corr-block',
            decision: 'BLOCK',
            risk_score: 0.92,
            reasons: [
              { agent: 'defender', label: 'RECIPIENT_NOT_ALLOWLISTED', score: 0.8 },
              { agent: 'evaluator', label: 'STRUCTURING', score: 0.95 },
              { agent: 'supervisor', label: 'HARD_OVERRIDE_BLOCK', score: 0.92 },
              { agent: 'auditor', label: 'PROVENANCE_RECORDED' },
            ],
            obligations: { prevented_loss: 30000 },
          },
          pre_exec: { record_id: 'rec-2' },
          post_exec: null,
        }),
      ),
      http.get(`${API_BASE_URL}/v1/governance/incidents`, () =>
        HttpResponse.json({
          incidents: [
            { incident_id: 'incident-1', correlation_id: 'corr-hitl', run_id: 'run-e2e', decision: 'ESCALATE', risk_score: 0.45, status: 'pending', resolution: null, created_at: 1716000002000 },
          ],
          cursor: null,
          total_count: 1,
        }),
      ),
    );

    render(
      <Fresh>
        <GovernanceRunShell />
      </Fresh>,
    );

    expect(await screen.findByText('$30,000')).toBeInTheDocument();
    expect(screen.getByText(/160 tokens/i)).toBeInTheDocument();
    expect((await screen.findAllByText('corr-block')).length).toBeGreaterThan(0);
    expect(screen.getByText(/Select a verdict to inspect details/i)).toBeInTheDocument();
    expect(screen.queryByText('STRUCTURING')).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByText('corr-block')[0]);

    expect(await screen.findByText('STRUCTURING')).toBeInTheDocument();
    expect(screen.getByText(/Pending HITL incidents/i)).toBeInTheDocument();
    expect(screen.getByText('incident-1')).toBeInTheDocument();
    expect(screen.getByText(/permanent evidence/i)).toBeInTheDocument();
    const flow = await screen.findByTestId('governance-run-flow');
    expect(flow).toHaveClass('space-y-6');
    expect(flow).not.toHaveClass('grid');
  });

  it('shows backend-empty state instead of fallback data by default', async () => {
    window.history.pushState({}, '', '/governance/runs/run-empty-default');
    server.use(
      http.get(`${API_BASE_URL}/v1/governance/runs/run-empty-default/cost`, () => HttpResponse.error()),
      http.get(`${API_BASE_URL}/v1/governance/runs/run-empty-default/provenance`, () => HttpResponse.error()),
      http.get(`${API_BASE_URL}/v1/governance/runs/run-empty-default/timeline`, () => HttpResponse.error()),
      http.get(`${API_BASE_URL}/v1/governance/incidents`, () => HttpResponse.error()),
    );

    render(
      <Fresh>
        <GovernanceRunShell />
      </Fresh>,
    );

    expect(await screen.findByText(/Backend has not produced data yet, run demo flow first/i)).toBeInTheDocument();
    expect(screen.queryByText(/Pre-recorded fallback/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/MOCKED/i)).not.toBeInTheDocument();
  });

  it('labels fallback data only when fixture mode is explicitly enabled', async () => {
    process.env.NEXT_PUBLIC_USE_FALLBACK_FIXTURES = '1';
    window.history.pushState({}, '', '/governance/runs/run-offline');
    server.use(
      http.get(`${API_BASE_URL}/v1/governance/runs/run-offline/cost`, () => HttpResponse.error()),
      http.get(`${API_BASE_URL}/v1/governance/runs/run-offline/provenance`, () => HttpResponse.error()),
      http.get(`${API_BASE_URL}/v1/governance/runs/run-offline/timeline`, () => HttpResponse.error()),
      http.get(`${API_BASE_URL}/v1/governance/incidents`, () => HttpResponse.error()),
    );

    render(
      <Fresh>
        <GovernanceRunShell />
      </Fresh>,
    );

    expect((await screen.findAllByText(/Offline fallback/i)).length).toBeGreaterThan(0);
    expect(screen.getByText(/Fixture data is enabled/i)).toBeInTheDocument();
  });
});
