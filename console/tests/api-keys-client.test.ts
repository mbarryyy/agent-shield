import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api } from '@/lib/api';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8787';

describe('api.auth.apiKeys', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('issues scoped SDK API keys through the real enterprise endpoint', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          api_key: 'as_live_once',
          view: {
            api_key_id: 'key-1',
            display_name: 'agent-a SDK key',
            prefix: 'as_live_',
            agent_id: 'agent-a',
            agent_id_allowlist: null,
            created_at: 1716000000000,
            created_by: 'user-1',
            expires_at: 1716086400000,
            last_used_at: null,
            revoked_at: null,
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    const result = await api.auth.apiKeys.issue({
      display_name: 'agent-a SDK key',
      prefix: 'as_live_',
      agent_id: 'agent-a',
      ttl_seconds: 86400,
    });

    expect(result.api_key).toBe('as_live_once');
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE_URL}/v1/auth/api-keys`,
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify({
          display_name: 'agent-a SDK key',
          prefix: 'as_live_',
          agent_id: 'agent-a',
          ttl_seconds: 86400,
        }),
      }),
    );
  });

  it('lists and revokes API keys without using the deprecated token shim', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            api_keys: [
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
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      );

    const listed = await api.auth.apiKeys.list();
    await api.auth.apiKeys.revoke('key-1');

    expect(listed.api_keys[0]?.agent_id).toBe('agent-a');
    expect(fetchMock.mock.calls[0]?.[0]).toBe(`${API_BASE_URL}/v1/auth/api-keys`);
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({ credentials: 'include' }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `${API_BASE_URL}/v1/auth/api-keys/key-1`,
      expect.objectContaining({ method: 'DELETE', credentials: 'include' }),
    );
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining('/v1/auth/token'),
      expect.anything(),
    );
  });
});
