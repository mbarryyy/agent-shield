'use client';

import { useEffect, useRef, useState } from 'react';
import { openGovernanceStream } from './api';
import { useGovTimeline } from './hooks';
import { streamEventToDetail, streamEventToRow } from './governanceKeys';
import type { TimelineRow, VerdictDetail } from '@/types/governance';

export type LiveSource = 'sse' | 'poll' | 'backend_empty';

/**
 * Live-monitor data, SSE-PRIMARY with a deterministic polling fallback.
 * The console renders ONLY what the server streams; there is no
 * client-side fabrication. When neither backend path yields rows the
 * source is `backend_empty` and the caller shows an honest empty state.
 *   1. SSE `/v1/governance/stream?workflow_id=` (primary; server bridges
 *      Redis Channel-2 → browser). Each `verdict` event → a TimelineRow
 *      keyed by the server-unique `verdict_id` (carry-in #1: correct
 *      [PASS,PASS,BLOCK] granularity even when the correlation_id
 *      collapses on the mock path) + a per-verdict_id VerdictDetail from
 *      the embedded signed §4 verdict.
 *   2. SWR polling of `/runs/{run_id}/timeline` when no SSE rows arrive.
 */
export function useLiveGovernance(
  workflowId: string,
  runId: string,
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
  }, [workflowId]);

  const sseList = [...sseRows.values()].sort((a, b) => a.created_at - b.created_at);
  if (sseSeen && sseList.length > 0) {
    return { rows: sseList, detailByVerdict: detailRef.current, source: 'sse' };
  }
  const pollRows = poll.data?.rows;
  if (pollRows && pollRows.length > 0) {
    return { rows: pollRows, detailByVerdict: detailRef.current, source: 'poll' };
  }
  return { rows: [], detailByVerdict: detailRef.current, source: 'backend_empty' };
}
