import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
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

    expect(await screen.findByText(/Backend has not produced verdicts yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/MOCKED/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Offline fallback/i)).not.toBeInTheDocument();
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

    expect(await screen.findByText(/Backend has not produced verdicts yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/v-esc-0001/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Offline fallback/i)).not.toBeInTheDocument();
  });
});
