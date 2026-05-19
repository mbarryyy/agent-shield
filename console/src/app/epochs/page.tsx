'use client';

import { Suspense, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import { useEpochs, formatTimestamp, truncateHash } from '@/lib/hooks';
import PageHeader from '@/components/ui/PageHeader';
import DataTable from '@/components/ui/DataTable';
import type { Column } from '@/components/ui/DataTable';
import CopyButton from '@/components/ui/CopyButton';

interface EpochRow {
  epoch_id: string;
  org_id: string;
  start_time: number;
  end_time: number;
  root_hash: string;
  leaf_count: number;
  r2_epoch_key: string;
  created_at: number;
  [key: string]: unknown;
}

function EpochsContent() {
  const { t } = useTranslation();
  const router = useRouter();
  const { data, isLoading, error } = useEpochs();
  const epochs = (data?.epochs ?? []) as EpochRow[];

  const columns: Column<EpochRow>[] = [
    {
      key: 'epoch_id',
      label: t('epochs.colEpochId'),
      render: (row) => (
        <span className="font-mono text-[13px] text-ink font-medium">
          {row.epoch_id.slice(0, 16)}...
        </span>
      ),
    },
    {
      key: 'start_time',
      label: t('epochs.colTimeRange'),
      sortable: true,
      render: (row) => (
        <div className="font-mono text-[11px] text-ink-dim">
          <div>{formatTimestamp(row.start_time)}</div>
          <div className="text-[10px]">to {formatTimestamp(row.end_time)}</div>
        </div>
      ),
    },
    {
      key: 'leaf_count',
      label: t('epochs.colLeaves'),
      sortable: true,
      width: '100px',
      render: (row) => (
        <span className="font-mono text-[13px] text-ink">{row.leaf_count}</span>
      ),
    },
    {
      key: 'root_hash',
      label: t('epochs.colRootHash'),
      render: (row) => (
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-[12px] text-ink-dim">
            {truncateHash(row.root_hash, 10)}
          </span>
          <CopyButton text={row.root_hash} />
        </div>
      ),
    },
    {
      key: 'created_at',
      label: t('epochs.colCreated'),
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[12px] text-ink-dim">
          {formatTimestamp(row.created_at)}
        </span>
      ),
    },
  ];

  const handleRowClick = useCallback(
    (row: EpochRow) => {
      router.push(`/epochs/${row.epoch_id}`);
    },
    [router],
  );

  return (
    <div className="fade-in">
      <PageHeader
        title={t('epochs.title')}
        subtitle={t('epochs.subtitle')}
        breadcrumbs={[
          { label: t('common.dashboard'), href: '/' },
          { label: t('epochs.title') },
        ]}
      />

      {error && (
        <div className="mb-6 px-4 py-3 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">
          {t('epochs.failedToLoad')} {error instanceof Error ? error.message : t('common.unknownError')}
        </div>
      )}

      <DataTable
        columns={columns}
        data={epochs}
        keyExtractor={(row) => row.epoch_id}
        onRowClick={handleRowClick}
        isLoading={isLoading}
        emptyMessage={t('epochs.emptyMessage')}
      />
    </div>
  );
}

export default function EpochsPage() {
  return (
    <Suspense fallback={<div className="fade-in"><div className="border border-border p-6"><div className="space-y-3"><div className="skeleton h-10 w-full max-w-md" /><div className="skeleton h-6 w-full" /><div className="skeleton h-6 w-full" /><div className="skeleton h-6 w-3/4" /></div></div></div>}>
      <EpochsContent />
    </Suspense>
  );
}
