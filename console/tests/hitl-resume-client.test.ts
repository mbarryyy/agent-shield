import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api } from '@/lib/api';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8787';

describe('api.governance.resume', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('posts HITL resume decisions to the server-owned incident endpoint', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          correlation_id: 'corr-hitl',
          decision: 'PASS',
          risk_score: 0.05,
          reasons: [{ agent: 'supervisor', label: 'HUMAN_APPROVED' }],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    const verdict = await api.governance.resume('incident-1', {
      decision: 'accept',
    });

    expect(verdict.decision).toBe('PASS');
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE_URL}/v1/governance/incidents/incident-1/resume`,
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify({ decision: 'accept' }),
      }),
    );
  });
});
