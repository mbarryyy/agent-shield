import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import { SWRConfig } from 'swr';
import type { ReactNode } from 'react';
import GovernancePage from '@/app/governance/page';
import GovernanceIncidentsPage from '@/app/governance/incidents/page';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8787';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));
vi.mock('@/lib/auth', () => ({
  useAuth: () => ({ canResolveIncidents: true }),
}));

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
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

describe('backend-first demo pages', () => {
  it('keeps /governance on backend-empty state instead of MOCKED fallback by default', async () => {
    server.use(
      http.get(`${API_BASE_URL}/v1/governance/runs/banking/timeline`, () =>
        HttpResponse.json({ rows: [], cursor: null, total_count: 0 }),
      ),
      http.get(`${API_BASE_URL}/v1/governance/runs/banking/cost`, () => HttpResponse.error()),
    );

    render(
      <Fresh>
        <GovernancePage />
      </Fresh>,
    );

    expect(await screen.findByText(/Backend has not produced data yet, run demo flow first/i)).toBeInTheDocument();
    expect(screen.queryByText(/MOCKED/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Pre-recorded fallback/i)).not.toBeInTheDocument();
  });

  it('does not auto-select a governance timeline row before the operator clicks', async () => {
    server.use(
      http.get(`${API_BASE_URL}/v1/governance/runs/banking/timeline`, () =>
        HttpResponse.json({
          rows: [
            { verdict_id: 'verdict-pass', record_id: 'rec-1', correlation_id: 'corr-pass', run_id: 'banking', decision: 'PASS', risk_score: 0.03, latency_ms: 5, created_at: 1716000000000 },
            { verdict_id: 'verdict-block', record_id: 'rec-2', correlation_id: 'corr-block', run_id: 'banking', decision: 'BLOCK', risk_score: 0.92, latency_ms: 6, created_at: 1716000001000 },
          ],
          cursor: null,
          total_count: 2,
        }),
      ),
      http.get(`${API_BASE_URL}/v1/governance/runs/banking/cost`, () =>
        HttpResponse.json({
          tokens: { prompt: 0, completion: 0, total: 0 },
          decision_mix: { PASS: 1, ALERT: 0, BLOCK: 1, ESCALATE: 0, ROLLBACK: 0, REWRITE: 0 },
          prevented_loss_total: 30000,
          latency_p50_ms: 5,
          latency_p95_ms: 6,
        }),
      ),
      http.get(`${API_BASE_URL}/v1/governance/verdicts/corr-block`, () =>
        HttpResponse.json({
          correlation_id: 'corr-block',
          verdict: {
            correlation_id: 'corr-block',
            decision: 'BLOCK',
            risk_score: 0.92,
            reasons: [{ agent: 'defender', label: 'RECIPIENT_NOT_ALLOWLISTED', score: 0.8 }],
            obligations: { prevented_loss: 30000 },
          },
          pre_exec: null,
          post_exec: null,
        }),
      ),
    );

    render(
      <Fresh>
        <GovernancePage />
      </Fresh>,
    );

    expect(await screen.findByText(/Select a verdict to inspect details/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open transfer run/i })).toHaveAttribute(
      'href',
      '/governance/runs/banking',
    );
    expect(screen.queryByText('RECIPIENT_NOT_ALLOWLISTED')).not.toBeInTheDocument();

    const row = screen.getByText('corr-block').closest('tr');
    expect(row).not.toBeNull();
    fireEvent.click(row as HTMLTableRowElement);

    expect(await screen.findByText('RECIPIENT_NOT_ALLOWLISTED')).toBeInTheDocument();
  });

  it('keeps /governance/incidents on backend-empty state when backend errors and fixtures are disabled', async () => {
    server.use(
      http.get(`${API_BASE_URL}/v1/governance/incidents`, () => HttpResponse.error()),
    );

    render(
      <Fresh>
        <GovernanceIncidentsPage />
      </Fresh>,
    );

    expect(await screen.findByText(/Backend has not produced data yet, run demo flow first/i)).toBeInTheDocument();
    expect(screen.queryByText(/v-esc-0001/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Pre-recorded fallback/i)).not.toBeInTheDocument();
  });

  it('loads incidents org-wide so the demo HITL run is visible from the incidents page', async () => {
    let sawRunFilter = false;
    server.use(
      http.get(`${API_BASE_URL}/v1/governance/incidents`, ({ request }) => {
        const url = new URL(request.url);
        sawRunFilter = url.searchParams.has('run_id');
        return HttpResponse.json({
          incidents: [
            { incident_id: 'incident-hitl', correlation_id: 'corr-hitl', run_id: 'demo-hitl', decision: 'ESCALATE', risk_score: 0.41, status: 'resolved', resolution: 'accept', created_at: 1716000002000 },
          ],
          cursor: null,
          total_count: 1,
        });
      }),
      http.get(`${API_BASE_URL}/v1/governance/verdicts/corr-hitl`, () =>
        HttpResponse.json({
          correlation_id: 'corr-hitl',
          verdict: {
            correlation_id: 'corr-hitl',
            decision: 'ESCALATE',
            risk_score: 0.41,
            reasons: [{ agent: 'supervisor', label: 'HUMAN_REVIEW', score: 0.41 }],
            obligations: { require_human: true },
          },
          pre_exec: null,
          post_exec: null,
        }),
      ),
    );

    render(
      <Fresh>
        <GovernanceIncidentsPage />
      </Fresh>,
    );

    expect((await screen.findAllByText('incident-hitl')).length).toBeGreaterThan(0);
    expect(sawRunFilter).toBe(false);
  });
});
