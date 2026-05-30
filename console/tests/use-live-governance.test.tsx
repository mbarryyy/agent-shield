import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useLiveGovernance } from '@/lib/useLiveGovernance';

// useLiveGovernance renders ONLY what the server streams: SSE rows first,
// then a polling fallback, otherwise an honest `backend_empty`. There is
// no offline/fixture leg — the hook can never fabricate rows.
const mockOpenStream = vi.fn();
const mockUseGovTimeline = vi.fn();

vi.mock('@/lib/api', () => ({
  openGovernanceStream: (
    workflowId: string,
    handlers: { onVerdict?: (ev: unknown) => void },
  ) => mockOpenStream(workflowId, handlers),
}));
vi.mock('@/lib/hooks', () => ({
  useGovTimeline: (runId: string, poll: boolean) => mockUseGovTimeline(runId, poll),
}));

describe('useLiveGovernance source cascade', () => {
  beforeEach(() => {
    mockOpenStream.mockReset();
    mockUseGovTimeline.mockReset();
    mockOpenStream.mockReturnValue(() => {});
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('returns an honest backend_empty state when neither SSE nor poll yields rows', () => {
    mockUseGovTimeline.mockReturnValue({ data: undefined });
    const { result } = renderHook(() => useLiveGovernance('wf', 'run'));
    expect(result.current.source).toBe('backend_empty');
    expect(result.current.rows).toEqual([]);
  });

  it('returns poll rows verbatim when the timeline endpoint returns data', () => {
    const pollRows = [
      {
        verdict_id: 'p1', record_id: 'r1', correlation_id: 'c1', run_id: 'run',
        decision: 'PASS', risk_score: 0.02, latency_ms: 4, created_at: 2,
        evidence_label: 'MEASURED',
      },
    ];
    mockUseGovTimeline.mockReturnValue({ data: { rows: pollRows } });
    const { result } = renderHook(() => useLiveGovernance('wf', 'run'));
    expect(result.current.source).toBe('poll');
    expect(result.current.rows).toEqual(pollRows);
  });

  it('surfaces SSE rows as source=sse when a verdict event arrives', async () => {
    mockUseGovTimeline.mockReturnValue({ data: undefined });
    let captured: { onVerdict?: (ev: unknown) => void } = {};
    mockOpenStream.mockImplementation((_wf, handlers) => {
      captured = handlers;
      return () => {};
    });
    const { result, rerender } = renderHook(() => useLiveGovernance('wf', 'run'));
    captured.onVerdict?.({
      verdict_id: 's1', record_id: 'r1', correlation_id: 'c1', run_id: 'run',
      decision: 'BLOCK', risk_score: 0.92, latency_ms: 6, created_at: 9,
    });
    rerender();
    await waitFor(() => expect(result.current.source).toBe('sse'));
  });
});
