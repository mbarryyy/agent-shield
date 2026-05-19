'use client';

import { useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import { useAudit, formatTimestamp, formatRelativeTime } from '@/lib/hooks';
import PageHeader from '@/components/ui/PageHeader';
import DataTable from '@/components/ui/DataTable';
import type { Column } from '@/components/ui/DataTable';
import type { Operation, AuditQueryRequest } from '@elydora/shared';
import Link from 'next/link';

export default function AuditPage() {
  const { t } = useTranslation();
  const router = useRouter();
  const [agentId, setAgentId] = useState('');
  const [operationType, setOperationType] = useState('');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const [limit] = useState(50);

  const queryParams: AuditQueryRequest = {
    agent_id: agentId || undefined,
    operation_type: operationType || undefined,
    start_time: startTime ? new Date(startTime).getTime() : undefined,
    end_time: endTime ? new Date(endTime).getTime() : undefined,
    cursor,
    limit,
  };

  const { data, isLoading, error } = useAudit(queryParams);
  const operations = data?.operations ?? [];

  const columns: Column<Operation & Record<string, unknown>>[] = [
    {
      key: 'operation_id',
      label: t('audit.colOperationId'),
      render: (row) => (
        <Link
          href={`/operations/${row.operation_id}`}
          className="font-mono text-[13px] text-ink hover:underline no-underline"
        >
          {row.operation_id.slice(0, 18)}...
        </Link>
      ),
    },
    {
      key: 'agent_id',
      label: t('audit.colAgent'),
      sortable: true,
      render: (row) => (
        <Link
          href={`/agents/${row.agent_id}`}
          className="font-mono text-[13px] text-ink-dim hover:text-ink no-underline transition-colors"
        >
          {row.agent_id}
        </Link>
      ),
    },
    {
      key: 'operation_type',
      label: t('audit.colType'),
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[11px] uppercase tracking-wider px-2 py-1 bg-surface border border-border">
          {row.operation_type}
        </span>
      ),
    },
    {
      key: 'issued_at',
      label: t('audit.colIssuedAt'),
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[12px] text-ink-dim" title={formatTimestamp(row.issued_at)}>
          {formatRelativeTime(row.issued_at)}
        </span>
      ),
    },
    {
      key: 'seq_no',
      label: t('audit.colSeq'),
      sortable: true,
      width: '80px',
      render: (row) => (
        <span className="font-mono text-[13px] text-ink-dim">#{row.seq_no}</span>
      ),
    },
    {
      key: 'chain_hash',
      label: t('audit.colChainHash'),
      render: (row) => (
        <span className="font-mono text-[11px] text-ink-dim">
          {row.chain_hash.slice(0, 12)}...
        </span>
      ),
    },
  ];

  const handleClearFilters = useCallback(() => {
    setAgentId('');
    setOperationType('');
    setStartTime('');
    setEndTime('');
    setCursor(undefined);
  }, []);

  return (
    <div className="fade-in">
      <PageHeader
        title={t('audit.title')}
        subtitle={t('audit.subtitle')}
        breadcrumbs={[
          { label: t('common.dashboard'), href: '/' },
          { label: t('audit.title') },
        ]}
        actions={
          <Link href="/exports" className="btn-ghost inline-block no-underline">
            {t('audit.exportData')}
          </Link>
        }
      />

      {error && (
        <div className="mb-6 px-4 py-3 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">
          {t('audit.failedToLoad')} {error instanceof Error ? error.message : t('common.unknownError')}
        </div>
      )}

      {/* Query Builder */}
      <div className="border border-border bg-surface p-4 sm:p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="section-label">{t('audit.queryBuilder')}</h3>
          <button className="btn-ghost text-[10px] py-1 px-3" onClick={handleClearFilters}>
            {t('audit.clearFilters')}
          </button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div>
            <label className="font-mono text-[10px] text-ink-dim uppercase tracking-wider block mb-1">
              {t('audit.agentId')}
            </label>
            <input
              type="text"
              value={agentId}
              onChange={(e) => {
                setAgentId(e.target.value);
                setCursor(undefined);
              }}
              placeholder={t('audit.filterByAgent')}
              className="w-full px-3 py-2 bg-transparent border border-border font-mono text-[13px] text-ink placeholder:text-ink-dim focus:outline-none focus:border-ink transition-colors"
            />
          </div>

          <div>
            <label className="font-mono text-[10px] text-ink-dim uppercase tracking-wider block mb-1">
              {t('audit.operationType')}
            </label>
            <input
              type="text"
              value={operationType}
              onChange={(e) => {
                setOperationType(e.target.value);
                setCursor(undefined);
              }}
              placeholder={t('audit.filterByType')}
              className="w-full px-3 py-2 bg-transparent border border-border font-mono text-[13px] text-ink placeholder:text-ink-dim focus:outline-none focus:border-ink transition-colors"
            />
          </div>

          <div>
            <label className="font-mono text-[10px] text-ink-dim uppercase tracking-wider block mb-1">
              {t('audit.startTime')}
            </label>
            <input
              type="datetime-local"
              value={startTime}
              onChange={(e) => {
                setStartTime(e.target.value);
                setCursor(undefined);
              }}
              className="w-full px-3 py-2 bg-transparent border border-border font-mono text-[13px] text-ink focus:outline-none focus:border-ink transition-colors"
            />
          </div>

          <div>
            <label className="font-mono text-[10px] text-ink-dim uppercase tracking-wider block mb-1">
              {t('audit.endTime')}
            </label>
            <input
              type="datetime-local"
              value={endTime}
              onChange={(e) => {
                setEndTime(e.target.value);
                setCursor(undefined);
              }}
              className="w-full px-3 py-2 bg-transparent border border-border font-mono text-[13px] text-ink focus:outline-none focus:border-ink transition-colors"
            />
          </div>
        </div>

        {data && (
          <div className="mt-4 pt-4 border-t border-border flex items-center gap-6">
            <span className="font-mono text-[11px] text-ink-dim">
              {t('audit.showing', { shown: operations.length, total: data.total_count })}
            </span>
            {data.cursor && (
              <span className="font-mono text-[11px] text-ink-dim">
                {t('audit.moreResults')}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Results Table */}
      <DataTable
        columns={columns}
        data={operations as (Operation & Record<string, unknown>)[]}
        keyExtractor={(row) => row.operation_id as string}
        onRowClick={(row) => { router.push(`/operations/${row.operation_id}`); }}
        isLoading={isLoading}
        emptyMessage={t('audit.emptyMessage')}
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
    </div>
  );
}
