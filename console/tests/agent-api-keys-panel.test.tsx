import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import { SWRConfig } from 'swr';
import type { ReactNode } from 'react';
import AgentApiKeysPanel from '@/components/AgentApiKeysPanel';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8787';

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

describe('AgentApiKeysPanel', () => {
  it('lists scoped API tokens and revokes through /v1/auth/api-keys', async () => {
    let revoked = false;
    server.use(
      http.get(`${API_BASE_URL}/v1/auth/api-keys`, () =>
        HttpResponse.json({
          api_keys: revoked
            ? [
                {
                  api_key_id: 'key-1',
                  display_name: 'agent-a SDK key',
                  prefix: 'as_live_',
                  agent_id: 'agent-a',
                  agent_id_allowlist: null,
                  created_at: 1716000000000,
                  created_by: 'user-1',
                  expires_at: null,
                  last_used_at: null,
                  revoked_at: 1716000100000,
                },
              ]
            : [
                {
                  api_key_id: 'key-1',
                  display_name: 'agent-a SDK key',
                  prefix: 'as_live_',
                  agent_id: 'agent-a',
                  agent_id_allowlist: null,
                  created_at: 1716000000000,
                  created_by: 'user-1',
                  expires_at: null,
                  last_used_at: null,
                  revoked_at: null,
                },
              ],
        }),
      ),
      http.delete(`${API_BASE_URL}/v1/auth/api-keys/key-1`, () => {
        revoked = true;
        return HttpResponse.json({ ok: true });
      }),
    );

    render(
      <Fresh>
        <AgentApiKeysPanel agentId="agent-a" />
      </Fresh>,
    );

    expect(await screen.findByText('agent-a SDK key')).toBeInTheDocument();
    expect(screen.getByText('active')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /revoke api token key-1/i }));

    await waitFor(() => {
      expect(screen.getByText('revoked')).toBeInTheDocument();
    });
  });

  it('labels missing backend support instead of falling back to demo-static-token', async () => {
    server.use(
      http.get(`${API_BASE_URL}/v1/auth/api-keys`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'NOT_FOUND',
              message: 'API key routes are not mounted.',
              request_id: 'req-key-routes',
            },
          },
          { status: 404 },
        ),
      ),
    );

    render(
      <Fresh>
        <AgentApiKeysPanel agentId="agent-a" />
      </Fresh>,
    );

    expect(await screen.findByText(/Module B enterprise auth API required/i)).toBeInTheDocument();
    expect(screen.queryByText(/demo-static-token/i)).not.toBeInTheDocument();
  });
});
