import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import { SWRConfig } from 'swr';
import type { ReactNode } from 'react';

// Dashboard stat card binds GET /v1/governance/dashboard/kpi and keeps the
// scope visible without stale MockedLLM/eval-suite wording. The card is demo
// evidence, not production deployment framing.

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/',
}));

import DashboardPage from '@/app/page';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8787';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// Fresh SWR cache per test (SWR's module-global cache otherwise leaks
// data across tests, masking the 401 error path with the previous 200's
// stale-data hit).
function Fresh({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      {children}
    </SWRConfig>
  );
}

describe('Dashboard prevented loss card', () => {
  it('renders $60,000 + the local demo qualifier on 200', async () => {
    server.use(
      http.get(`${API_BASE_URL}/v1/governance/dashboard/kpi`, () =>
        HttpResponse.json(
          {
            prevented_loss_total: 60000.0,
            decision_mix: { PASS: 0, ALERT: 0, BLOCK: 2, ESCALATE: 0, ROLLBACK: 0, REWRITE: 0 },
            total_verdicts: 2,
          },
          { status: 200 },
        ),
      ),
    );

    render(<Fresh><DashboardPage /></Fresh>);

    await waitFor(() => {
      // Value rendered from the SERVER's prevented_loss_total — console
      // never recomputes the dollar figure.
      expect(screen.getByText('$60,000')).toBeInTheDocument();
    });
    expect(screen.getByText('Local demo prevented loss')).toBeInTheDocument();
    expect(
      screen.getByText('AgentDojo InjectionTask6 local backend demo · no provider call'),
    ).toBeInTheDocument();
    // Negative guards: no banned framings.
    expect(screen.queryByText(/saved from real attacks/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/total fraud prevented/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^money saved$/i)).not.toBeInTheDocument();
  });

  it('renders the AuthError-resolver message (NOT "Load failed") on 401', async () => {
    server.use(
      http.get(`${API_BASE_URL}/v1/governance/dashboard/kpi`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'UNAUTHORIZED',
              message: 'Session expired — sign in again.',
              request_id: 'req-test-1',
            },
          },
          { status: 401 },
        ),
      ),
    );

    render(<Fresh><DashboardPage /></Fresh>);

    // The card replaces its methodology subtitle with the resolved server
    // message; value becomes "—".
    await waitFor(() => {
      expect(screen.getByText('Session expired — sign in again.')).toBeInTheDocument();
    });
    // Browser network-layer placeholders MUST NOT leak through.
    expect(screen.queryByText(/load failed/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/failed to fetch/i)).not.toBeInTheDocument();
    // Title still present.
    expect(screen.getByText('Local demo prevented loss')).toBeInTheDocument();
  });
});
