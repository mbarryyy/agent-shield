'use client';

import { Suspense, useState, useCallback, useMemo } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import { useAudit, formatRelativeTime } from '@/lib/hooks';
import PageHeader from '@/components/ui/PageHeader';
import DataTable from '@/components/ui/DataTable';
import type { Column } from '@/components/ui/DataTable';
import SearchInput from '@/components/ui/SearchInput';
import type { Operation } from '@elydora/shared';

function OperationsContent() {
  const { t } = useTranslation();
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialAgentId = searchParams.get('agent_id') ?? '';

  const [search, setSearch] = useState('');
  const [agentFilter, setAgentFilter] = useState(initialAgentId);
  const [typeFilter, setTypeFilter] = useState('');
  const [cursor, setCursor] = useState<string | undefined>(undefined);

  const { data, isLoading, error } = useAudit({
    agent_id: agentFilter || undefined,
    operation_type: typeFilter || undefined,
    cursor,
    limit: 50,
  });

  const operations = data?.operations ?? [];

  const filteredOps = useMemo(() => {
    if (!search.trim()) return operations;
    const q = search.toLowerCase();
    return operations.filter(
      (op) =>
        op.operation_id.toLowerCase().includes(q) ||
        op.agent_id.toLowerCase().includes(q) ||
        op.operation_type.toLowerCase().includes(q),
    );
  }, [operations, search]);

  const columns: Column<Operation & Record<string, unknown>>[] = [
    {
      key: 'operation_id',
      label: t('operations.colOperationId'),
      render: (row) => (
        <span className="font-mono text-[13px] text-ink">
          {row.operation_id.slice(0, 20)}...
        </span>
      ),
    },
    {
      key: 'agent_id',
      label: t('operations.colAgent'),
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[13px] text-ink-dim">{row.agent_id}</span>
      ),
    },
    {
      key: 'operation_type',
      label: t('operations.colType'),
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[11px] uppercase tracking-wider px-2 py-1 bg-surface border border-border">
          {row.operation_type}
        </span>
      ),
    },
    {
      key: 'issued_at',
      label: t('operations.colIssuedAt'),
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[12px] text-ink-dim">
          {formatRelativeTime(row.issued_at)}
        </span>
      ),
    },
    {
      key: 'seq_no',
      label: t('operations.colSeq'),
      sortable: true,
      width: '80px',
      render: (row) => (
        <span className="font-mono text-[13px] text-ink-dim">#{row.seq_no}</span>
      ),
    },
  ];

  const handleRowClick = useCallback(
    (row: Operation & Record<string, unknown>) => {
      router.push(`/operations/${row.operation_id}`);
    },
    [router],
  );

  return (
    <>
      {error && (
        <div className="mb-6 px-4 py-3 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">
          {t('operations.failedToLoad')} {error instanceof Error ? error.message : t('common.unknownError')}
        </div>
      )}

      {/* Filter Bar */}
      <div className="mb-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder={t('operations.searchPlaceholder')}
          className="sm:col-span-2"
        />
        <div>
          <label className="font-mono text-[10px] text-ink-dim uppercase tracking-wider block mb-1">
            {t('operations.agentIdFilter')}
          </label>
          <input
            type="text"
            value={agentFilter}
            onChange={(e) => setAgentFilter(e.target.value)}
            placeholder={t('operations.filterByAgent')}
            className="w-full px-3 py-2.5 bg-transparent border border-border font-mono text-[13px] text-ink placeholder:text-ink-dim focus:outline-none focus:border-ink transition-colors"
          />
        </div>
        <div>
          <label className="font-mono text-[10px] text-ink-dim uppercase tracking-wider block mb-1">
            {t('operations.typeFilter')}
          </label>
          <input
            type="text"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            placeholder={t('operations.filterByType')}
            className="w-full px-3 py-2.5 bg-transparent border border-border font-mono text-[13px] text-ink placeholder:text-ink-dim focus:outline-none focus:border-ink transition-colors"
          />
        </div>
      </div>

      <DataTable
        columns={columns}
        data={filteredOps as (Operation & Record<string, unknown>)[]}
        keyExtractor={(row) => row.operation_id as string}
        onRowClick={handleRowClick}
        isLoading={isLoading}
        emptyMessage={t('operations.emptyMessage')}
        pagination={
          data?.cursor
            ? {
                cursor: data.cursor,
                hasMore: true,
                onLoadMore: () => setCursor(data.cursor),
              }
            : undefined
        }
      />
    </>
  );
}

export default function OperationsPage() {
  const { t } = useTranslation();
  return (
    <div className="fade-in">
      <PageHeader
        title={t('operations.title')}
        subtitle={t('operations.subtitle')}
        breadcrumbs={[
          { label: t('common.dashboard'), href: '/' },
          { label: t('operations.title') },
        ]}
      />
      <Suspense fallback={
        <div className="border border-border p-6">
          <div className="space-y-3">
            <div className="skeleton h-10 w-full max-w-md" />
            <div className="skeleton h-6 w-full" />
            <div className="skeleton h-6 w-full" />
            <div className="skeleton h-6 w-3/4" />
          </div>
        </div>
      }>
        <OperationsContent />
      </Suspense>
    </div>
  );
}
