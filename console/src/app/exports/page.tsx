'use client';

import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useExports, formatTimestamp } from '@/lib/hooks';
import { api } from '@/lib/api';
import PageHeader from '@/components/ui/PageHeader';
import DataTable from '@/components/ui/DataTable';
import type { Column } from '@/components/ui/DataTable';
import StatusBadge from '@/components/ui/StatusBadge';
import Modal from '@/components/ui/Modal';
import type { Export, CreateExportRequest, ExportStatus } from '@elydora/shared';

interface ExportRow extends Export {
  [key: string]: unknown;
}

export default function ExportsPage() {
  const { t } = useTranslation();
  const { data, isLoading, error, mutate } = useExports();
  const exports = (data?.exports ?? []) as ExportRow[];

  const [showCreate, setShowCreate] = useState(false);
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [agentId, setAgentId] = useState('');
  const [operationType, setOperationType] = useState('');
  const [format, setFormat] = useState<'json' | 'pdf'>('json');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const handleCreate = useCallback(async () => {
    if (!startTime || !endTime) {
      setCreateError(t('exports.startEndRequired'));
      return;
    }

    setCreating(true);
    setCreateError(null);
    try {
      const body: CreateExportRequest = {
        start_time: new Date(startTime).getTime(),
        end_time: new Date(endTime).getTime(),
        agent_id: agentId || undefined,
        operation_type: operationType || undefined,
        format,
      };
      await api.exports.create(body);
      setShowCreate(false);
      setStartTime('');
      setEndTime('');
      setAgentId('');
      setOperationType('');
      mutate();
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : t('exports.failedToCreate'));
    } finally {
      setCreating(false);
    }
  }, [startTime, endTime, agentId, operationType, format, mutate]);

  const handleDownload = useCallback(async (exportId: string, queryParams: string) => {
    try {
      let ext = '';
      try {
        const params = JSON.parse(queryParams);
        ext = params.format === 'pdf' ? '.pdf' : '.json';
      } catch { ext = ''; }
      const blob = await api.exports.download(exportId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `export-${exportId}${ext}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      // Download error is non-critical
    }
  }, []);

  const columns: Column<ExportRow>[] = [
    {
      key: 'export_id',
      label: t('exports.colExportId'),
      render: (row) => (
        <span className="font-mono text-[13px] text-ink">
          {row.export_id.slice(0, 16)}...
        </span>
      ),
    },
    {
      key: 'status',
      label: t('exports.colStatus'),
      width: '120px',
      render: (row) => <StatusBadge status={row.status as ExportStatus} size="sm" />,
    },
    {
      key: 'query_params',
      label: t('exports.colFilters'),
      render: (row) => {
        let params: Record<string, unknown> = {};
        try {
          params = JSON.parse(row.query_params);
        } catch {
          // Not valid JSON
        }
        const entries = Object.entries(params).filter(([, v]) => v != null);
        if (entries.length === 0) {
          return <span className="font-mono text-[11px] text-ink-dim">{t('common.allData')}</span>;
        }
        return (
          <span className="font-mono text-[11px] text-ink-dim">
            {entries.map(([k, v]) => `${k}=${v}`).join(', ')}
          </span>
        );
      },
    },
    {
      key: 'created_at',
      label: t('exports.colCreated'),
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[12px] text-ink-dim">
          {formatTimestamp(row.created_at)}
        </span>
      ),
    },
    {
      key: 'completed_at',
      label: t('exports.colCompleted'),
      render: (row) => (
        <span className="font-mono text-[12px] text-ink-dim">
          {row.completed_at ? formatTimestamp(row.completed_at) : '\u2014'}
        </span>
      ),
    },
    {
      key: 'actions',
      label: '',
      width: '100px',
      render: (row) =>
        row.status === 'done' ? (
          <button
            className="btn-ghost text-[10px] py-1 px-3"
            onClick={(e) => {
              e.stopPropagation();
              handleDownload(row.export_id, row.query_params);
            }}
          >
            {t('common.download')}
          </button>
        ) : null,
    },
  ];

  return (
    <div className="fade-in">
      <PageHeader
        title={t('exports.title')}
        subtitle={t('exports.subtitle')}
        breadcrumbs={[
          { label: t('common.dashboard'), href: '/' },
          { label: t('exports.title') },
        ]}
        actions={
          <button className="btn-brutalist" onClick={() => setShowCreate(true)}>
            {t('exports.createExport')}
          </button>
        }
      />

      {error && (
        <div className="mb-6 px-4 py-3 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">
          {t('exports.failedToLoad')} {error instanceof Error ? error.message : t('common.unknownError')}
        </div>
      )}

      <DataTable
        columns={columns}
        data={exports}
        keyExtractor={(row) => row.export_id}
        isLoading={isLoading}
        emptyMessage={t('exports.emptyMessage')}
      />

      {/* Create Export Modal */}
      <Modal
        isOpen={showCreate}
        onClose={() => {
          setShowCreate(false);
          setCreateError(null);
        }}
        title={t('exports.createExport')}
        width="max-w-xl"
      >
        <div className="space-y-4">
          {createError && (
            <div className="px-4 py-3 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">
              {createError}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="section-label block mb-1.5">{t('exports.startTime')}</label>
              <input
                type="datetime-local"
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
                className="w-full px-3 py-2 bg-transparent border border-border font-mono text-[13px] text-ink focus:outline-none focus:border-ink transition-colors"
                required
              />
            </div>
            <div>
              <label className="section-label block mb-1.5">{t('exports.endTime')}</label>
              <input
                type="datetime-local"
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
                className="w-full px-3 py-2 bg-transparent border border-border font-mono text-[13px] text-ink focus:outline-none focus:border-ink transition-colors"
                required
              />
            </div>
          </div>

          <div>
            <label className="section-label block mb-1.5">{t('exports.agentIdOptional')}</label>
            <input
              type="text"
              value={agentId}
              onChange={(e) => setAgentId(e.target.value)}
              placeholder={t('exports.filterByAgent')}
              className="w-full px-3 py-2 bg-transparent border border-border font-mono text-[13px] text-ink placeholder:text-ink-dim focus:outline-none focus:border-ink transition-colors"
            />
          </div>

          <div>
            <label className="section-label block mb-1.5">{t('exports.operationTypeOptional')}</label>
            <input
              type="text"
              value={operationType}
              onChange={(e) => setOperationType(e.target.value)}
              placeholder={t('exports.filterByOperationType')}
              className="w-full px-3 py-2 bg-transparent border border-border font-mono text-[13px] text-ink placeholder:text-ink-dim focus:outline-none focus:border-ink transition-colors"
            />
          </div>

          <div>
            <label className="section-label block mb-1.5">{t('exports.format')}</label>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="format"
                  value="json"
                  checked={format === 'json'}
                  onChange={() => setFormat('json')}
                  className="accent-ink"
                />
                <span className="font-mono text-[13px] text-ink">JSON</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="format"
                  value="pdf"
                  checked={format === 'pdf'}
                  onChange={() => setFormat('pdf')}
                  className="accent-ink"
                />
                <span className="font-mono text-[13px] text-ink">PDF</span>
              </label>
            </div>
          </div>

          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              className="btn-ghost"
              onClick={() => {
                setShowCreate(false);
                setCreateError(null);
              }}
            >
              {t('common.cancel')}
            </button>
            <button className="btn-brutalist" onClick={handleCreate} disabled={creating}>
              {creating ? t('exports.creating') : t('exports.createExport')}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
