import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import DataTable, { type Column } from '@/components/ui/DataTable';
import LiveMonitor from '@/components/governance/LiveMonitor';
import type { TimelineRow } from '@/types/governance';

type AuditRow = {
  correlation_id: string;
  decision: string;
  risk: string;
  latency: string;
};

const columns: Column<AuditRow>[] = [
  { key: 'correlation_id', label: 'Correlation' },
  { key: 'decision', label: 'Decision' },
  { key: 'risk', label: 'Risk' },
  { key: 'latency', label: 'Latency' },
];

function expectResponsiveTable() {
  const table = screen.getByRole('table');
  expect(table.parentElement?.className).toContain('overflow-x-auto');
  expect(table.parentElement?.parentElement?.className).not.toContain('overflow-hidden');
  expect(table.className).toContain('min-w-[600px]');
}

describe('DataTable responsive table shell', () => {
  it('wraps the loading table in the horizontal scroll container', () => {
    render(
      <DataTable<AuditRow>
        columns={columns}
        data={[]}
        keyExtractor={(row) => row.correlation_id}
        isLoading
      />,
    );

    expectResponsiveTable();
  });

  it('wraps the empty table in the horizontal scroll container', () => {
    render(
      <DataTable<AuditRow>
        columns={columns}
        data={[]}
        keyExtractor={(row) => row.correlation_id}
        emptyMessage="No verdicts yet"
      />,
    );

    expectResponsiveTable();
  });

  it('keeps populated tables in the same horizontal scroll container', () => {
    render(
      <DataTable<AuditRow>
        columns={columns}
        data={[
          {
            correlation_id: 'corr-mobile-regression',
            decision: 'BLOCK',
            risk: '0.92',
            latency: '7 ms',
          },
        ]}
        keyExtractor={(row) => row.correlation_id}
      />,
    );

    expectResponsiveTable();
  });
});

describe('LiveMonitor responsive table shell', () => {
  it('wraps live verdict rows in a horizontal scroll container', () => {
    const rows: TimelineRow[] = [
      {
        verdict_id: 'v1',
        record_id: 'r1',
        correlation_id: 'corr-mobile-risk-latency',
        run_id: 'run-1',
        decision: 'BLOCK',
        risk_score: 0.92,
        latency_ms: 18,
        created_at: Date.now(),
      },
    ];

    render(<LiveMonitor rows={rows} />);

    expectResponsiveTable();
  });
});
