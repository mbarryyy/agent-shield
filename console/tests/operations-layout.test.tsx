import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import { SWRConfig } from 'swr';
import type { ReactNode } from 'react';
import OperationsPage from '@/app/operations/page';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8787';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function Fresh({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      {children}
    </SWRConfig>
  );
}

describe('Operations filter layout', () => {
  it('keeps all filter controls on the same input baseline with a centered search icon', async () => {
    server.use(
      http.post(`${API_BASE_URL}/v1/audit/query`, () =>
        HttpResponse.json({ operations: [], total_count: 0, cursor: null }),
      ),
    );

    render(
      <Fresh>
        <OperationsPage />
      </Fresh>,
    );

    const filterBar = await screen.findByTestId('operations-filter-bar');
    expect(filterBar).toHaveClass('items-end');

    const searchField = screen.getByTestId('operations-search-filter');
    expect(searchField).toHaveClass('sm:col-span-2');
    expect(screen.getByText('Search')).toHaveClass('block');
    expect(screen.getByText('Search')).toHaveClass('mb-1');

    const searchInput = screen.getByPlaceholderText('Search by ID, agent, or type...');
    expect(searchInput).toHaveClass('h-11');
    expect(searchInput).toHaveClass('pl-10');

    const searchIcon = searchField.querySelector('svg');
    expect(searchIcon).toHaveClass('pointer-events-none');
    expect(searchIcon).toHaveClass('top-1/2');
    expect(searchIcon).toHaveClass('-translate-y-1/2');

    expect(screen.getByPlaceholderText('Filter by agent')).toHaveClass('h-11');
    expect(screen.getByPlaceholderText('Filter by type')).toHaveClass('h-11');
  });
});
