import type { TimelineRow } from '@/types/governance';

export function mergeTimelineRows(...groups: Array<TimelineRow[] | undefined>): TimelineRow[] {
  const byVerdict = new Map<string, TimelineRow>();
  for (const rows of groups) {
    for (const row of rows ?? []) {
      byVerdict.set(row.verdict_id, row);
    }
  }
  return [...byVerdict.values()].sort((a, b) => b.created_at - a.created_at);
}
