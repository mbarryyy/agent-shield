'use client';

import { useEffect, useRef, useState } from 'react';
import { openGovernanceStream } from './api';
import { useGovTimeline } from './hooks';
import { streamEventToDetail, streamEventToRow } from './governanceKeys';
import type { TimelineRow, VerdictDetail } from '@/types/governance';

export type LiveSource = 'sse' | 'poll' | 'offline' | 'backend_empty';

/**
 * Live-monitor data, SSE-PRIMARY with deterministic fallbacks (demo
 * resilience, NOT a zero-backend mode — auth stays server-backed):
 *   1. SSE `/v1/governance/stream?workflow_id=` (primary; server bridges
 *      Redis Channel-2 → browser). Each `verdict` event → a TimelineRow
 *      keyed by the server-unique `verdict_id` (carry-in #1: correct
 *      [PASS,PASS,BLOCK] granularity even when MockedLLM collapses
 *      correlation_id on the mock path) + a per-verdict_id VerdictDetail
 *      from the embedded signed §4 verdict.
 *   2. SWR polling of `/runs/{run_id}/timeline` (pre-recorded-demo
 *      fallback) when no SSE rows arrive.
 *   3. `offlineRows` (caller-supplied pre-recorded fixture) only if both
 *      backend paths yield nothing — pure data-layer resilience.
 */
export function useLiveGovernance(
  workflowId: string,
  runId: string,
  offlineRows: TimelineRow[],
  options: { fallbackFixtures: boolean } = { fallbackFixtures: false },
): {
  rows: TimelineRow[];
  detailByVerdict: Map<string, VerdictDetail>;
  source: LiveSource;
} {
  const [sseRows, setSseRows] = useState<Map<string, TimelineRow>>(new Map());
  const detailRef = useRef<Map<string, VerdictDetail>>(new Map());
  const [sseSeen, setSseSeen] = useState(false);

  // SWR polling fallback only matters when SSE produced nothing.
  const poll = useGovTimeline(runId, true);

  useEffect(() => {
    const close = openGovernanceStream(workflowId, {
      onVerdict: (ev) => {
        if (ev.run_id !== runId) return;
        const row = streamEventToRow(ev, Date.now());
        const detail = streamEventToDetail(ev);
        if (detail) detailRef.current.set(ev.verdict_id, detail);
        setSseRows((prev) => {
          const next = new Map(prev);
          next.set(ev.verdict_id, row);
          return next;
        });
        setSseSeen(true);
      },
    });
    return close;
  }, [workflowId, runId]);

  const sseList = [...sseRows.values()].sort((a, b) => b.created_at - a.created_at);
  const pollRows = poll.data?.rows;
  if (sseSeen && sseList.length > 0) {
    if (pollRows && pollRows.length > 0) {
      const pollIds = new Set(pollRows.map((row) => row.verdict_id));
      const sseOnlyRows = sseList.filter((row) => !pollIds.has(row.verdict_id));
      return {
        rows: [...sseOnlyRows, ...pollRows].sort((a, b) => b.created_at - a.created_at),
        detailByVerdict: detailRef.current,
        source: 'sse',
      };
    }
    return { rows: sseList, detailByVerdict: detailRef.current, source: 'sse' };
  }
  if (pollRows && pollRows.length > 0) {
    return { rows: pollRows, detailByVerdict: detailRef.current, source: 'poll' };
  }
  if (!options.fallbackFixtures) {
    return { rows: [], detailByVerdict: detailRef.current, source: 'backend_empty' };
  }
  return { rows: offlineRows, detailByVerdict: detailRef.current, source: 'offline' };
}
