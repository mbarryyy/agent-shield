'use client';

import { useState, useCallback } from 'react';
import { useAgent, useAudit, formatTimestamp } from '@/lib/hooks';
import { api } from '@/lib/api';
import PageHeader from '@/components/ui/PageHeader';
import StatusBadge from '@/components/ui/StatusBadge';
import CopyButton from '@/components/ui/CopyButton';
import DataTable from '@/components/ui/DataTable';
import type { Column } from '@/components/ui/DataTable';
import Modal from '@/components/ui/Modal';
import Link from 'next/link';
import type { AgentKey, Operation } from '@elydora/shared';
import { useTranslation } from 'react-i18next';

const HOOKS_INTEGRATIONS = new Set([
  'claudecode', 'cursor', 'gemini', 'kirocli', 'kiroide', 'opencode', 'copilot', 'letta',
]);

export default function AgentDetailClient({ agentId }: { agentId: string }) {
  const { t } = useTranslation();

  const { data: agentData, isLoading: agentLoading, error: agentError, mutate: mutateAgent } = useAgent(agentId);
  const { data: opsData, isLoading: opsLoading } = useAudit({ agent_id: agentId });

  const [showFreezeModal, setShowFreezeModal] = useState(false);
  const [freezeReason, setFreezeReason] = useState('');
  const [freezing, setFreezing] = useState(false);
  const [freezeError, setFreezeError] = useState<string | null>(null);

  const [showUnfreezeModal, setShowUnfreezeModal] = useState(false);
  const [unfreezeReason, setUnfreezeReason] = useState('');
  const [unfreezing, setUnfreezing] = useState(false);
  const [unfreezeError, setUnfreezeError] = useState<string | null>(null);

  const [revokeKeyId, setRevokeKeyId] = useState<string | null>(null);
  const [revokeReason, setRevokeReason] = useState('');
  const [revoking, setRevoking] = useState(false);
  const [revokeError, setRevokeError] = useState<string | null>(null);

  const agent = agentData?.agent;
  const supportsFreeze = !agent?.integration_type || HOOKS_INTEGRATIONS.has(agent.integration_type);
  const keys = agentData?.keys ?? [];
  const operations = opsData?.operations ?? [];

  const handleFreeze = useCallback(async () => {
    if (!freezeReason.trim()) {
      setFreezeError(t('agentDetail.reasonRequired'));
      return;
    }
    setFreezing(true);
    setFreezeError(null);
    try {
      await api.agents.freeze(agentId, freezeReason.trim());
      setShowFreezeModal(false);
      setFreezeReason('');
      mutateAgent();
    } catch (err) {
      setFreezeError(err instanceof Error ? err.message : t('agentDetail.failedToFreeze'));
    } finally {
      setFreezing(false);
    }
  }, [agentId, freezeReason, mutateAgent, t]);

  const handleUnfreeze = useCallback(async () => {
    if (!unfreezeReason.trim()) {
      setUnfreezeError(t('agentDetail.reasonRequired'));
      return;
    }
    setUnfreezing(true);
    setUnfreezeError(null);
    try {
      await api.agents.unfreeze(agentId, unfreezeReason.trim());
      setShowUnfreezeModal(false);
      setUnfreezeReason('');
      mutateAgent();
    } catch (err) {
      setUnfreezeError(err instanceof Error ? err.message : t('agentDetail.failedToUnfreeze'));
    } finally {
      setUnfreezing(false);
    }
  }, [agentId, unfreezeReason, mutateAgent, t]);

  const handleRevokeKey = useCallback(async () => {
    if (!revokeKeyId || !revokeReason.trim()) {
      setRevokeError(t('agentDetail.reasonRequired'));
      return;
    }
    setRevoking(true);
    setRevokeError(null);
    try {
      await api.agents.revokeKey(agentId, revokeKeyId, revokeReason.trim());
      setRevokeKeyId(null);
      setRevokeReason('');
      mutateAgent();
    } catch (err) {
      setRevokeError(err instanceof Error ? err.message : t('agentDetail.failedToRevoke'));
    } finally {
      setRevoking(false);
    }
  }, [agentId, revokeKeyId, revokeReason, mutateAgent, t]);

  const keyColumns: Column<AgentKey & Record<string, unknown>>[] = [
    {
      key: 'kid',
      label: t('agentDetail.colKeyId'),
      render: (row) => (
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-[13px] text-ink">{row.kid}</span>
          <CopyButton text={row.kid} />
        </div>
      ),
    },
    {
      key: 'algorithm',
      label: t('agentDetail.colAlgorithm'),
      width: '120px',
      render: (row) => (
        <span className="font-mono text-[11px] uppercase tracking-wider px-2 py-1 bg-surface border border-border">
          {row.algorithm}
        </span>
      ),
    },
    {
      key: 'status',
      label: t('agentDetail.colStatus'),
      width: '120px',
      render: (row) => <StatusBadge status={row.status} size="sm" />,
    },
    {
      key: 'created_at',
      label: t('agentDetail.colCreated'),
      render: (row) => (
        <span className="font-mono text-[12px] text-ink-dim">
          {formatTimestamp(row.created_at)}
        </span>
      ),
    },
    {
      key: 'actions',
      label: '',
      width: '80px',
      render: (row) =>
        row.status === 'active' ? (
          <button
            className="btn-ghost text-[10px] py-1 px-2"
            onClick={(e) => {
              e.stopPropagation();
              setRevokeKeyId(row.kid);
            }}
          >
            {t('agentDetail.revoke')}
          </button>
        ) : null,
    },
  ];

  const opColumns: Column<Operation & Record<string, unknown>>[] = [
    {
      key: 'operation_id',
      label: t('operationCard.operationId'),
      render: (row) => (
        <Link
          href={`/operations/${row.operation_id}`}
          className="font-mono text-[13px] text-ink hover:underline no-underline"
        >
          {row.operation_id.slice(0, 16)}...
        </Link>
      ),
    },
    {
      key: 'operation_type',
      label: t('operationCard.type'),
      render: (row) => (
        <span className="font-mono text-[11px] uppercase tracking-wider px-2 py-1 bg-surface border border-border">
          {row.operation_type}
        </span>
      ),
    },
    {
      key: 'issued_at',
      label: t('operationCard.issuedAt'),
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[12px] text-ink-dim">
          {formatTimestamp(row.issued_at)}
        </span>
      ),
    },
    {
      key: 'seq_no',
      label: t('operationCard.seqNo'),
      width: '80px',
      render: (row) => (
        <span className="font-mono text-[13px] text-ink-dim">#{row.seq_no}</span>
      ),
    },
  ];

  if (agentLoading) {
    return (
      <div className="fade-in">
        <PageHeader
          title={t('agentDetail.title')}
          breadcrumbs={[
            { label: t('common.dashboard'), href: '/' },
            { label: t('common.agents'), href: '/agents' },
            { label: agentId },
          ]}
        />
        <div className="space-y-4">
          <div className="border border-border bg-surface p-6">
            <div className="space-y-3">
              <div className="skeleton h-6 w-64" />
              <div className="skeleton h-4 w-48" />
              <div className="skeleton h-4 w-32" />
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (agentError) {
    return (
      <div className="fade-in">
        <PageHeader
          title={t('agentDetail.title')}
          breadcrumbs={[
            { label: t('common.dashboard'), href: '/' },
            { label: t('common.agents'), href: '/agents' },
            { label: agentId },
          ]}
        />
        <div className="px-4 py-3 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">
          {t('agentDetail.failedToLoad')} {agentError instanceof Error ? agentError.message : t('agentDetail.mayNotExist')}
        </div>
      </div>
    );
  }

  return (
    <div className="fade-in">
      <PageHeader
        title={agent?.display_name ?? agentId}
        subtitle={agent?.display_name ? agentId : undefined}
        breadcrumbs={[
          { label: t('common.dashboard'), href: '/' },
          { label: t('common.agents'), href: '/agents' },
          { label: agent?.display_name ?? agentId },
        ]}
        actions={
          supportsFreeze && agent?.status === 'active' ? (
            <button
              className="btn-brutalist"
              onClick={() => setShowFreezeModal(true)}
            >
              {t('agentDetail.freezeAgent')}
            </button>
          ) : supportsFreeze && agent?.status === 'frozen' ? (
            <button
              className="btn-brutalist"
              onClick={() => setShowUnfreezeModal(true)}
            >
              {t('agentDetail.unfreezeAgent')}
            </button>
          ) : undefined
        }
      />

      {/* Agent Info Card */}
      <div className="border border-border bg-surface p-4 sm:p-6 mb-6 relative">
        <span className="crosshair ch-tl" />
        <span className="crosshair ch-tr" />
        <span className="crosshair ch-bl" />
        <span className="crosshair ch-br" />

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <div>
            <div className="section-label mb-1">{t('agentDetail.agentId')}</div>
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-[14px] text-ink break-all">{agent?.agent_id}</span>
              {agent?.agent_id && <CopyButton text={agent.agent_id} />}
            </div>
          </div>
          <div>
            <div className="section-label mb-1">{t('agentDetail.status')}</div>
            {agent?.status && <StatusBadge status={agent.status} />}
          </div>
          <div>
            <div className="section-label mb-1">{t('agentDetail.organization')}</div>
            <span className="font-mono text-[13px] text-ink break-all">{agent?.org_id}</span>
          </div>
          <div>
            <div className="section-label mb-1">{t('agentDetail.displayName')}</div>
            <span className="font-sans text-sm text-ink">
              {agent?.display_name ?? '\u2014'}
            </span>
          </div>
          <div>
            <div className="section-label mb-1">{t('agentDetail.responsibleEntity')}</div>
            <span className="font-sans text-sm text-ink">
              {agent?.responsible_entity ?? '\u2014'}
            </span>
          </div>
          <div>
            <div className="section-label mb-1">{t('agentDetail.created')}</div>
            <span className="font-mono text-[12px] text-ink-dim">
              {agent?.created_at ? formatTimestamp(agent.created_at) : '\u2014'}
            </span>
          </div>
        </div>
      </div>

      {/* Keys */}
      <div className="mb-6">
        <div className="section-label mb-3">{t('agentDetail.keys')} ({keys.length})</div>
        <DataTable
          columns={keyColumns}
          data={keys as (AgentKey & Record<string, unknown>)[]}
          keyExtractor={(row) => row.kid}
          emptyMessage={t('agentDetail.noKeys')}
        />
      </div>

      {/* Recent Operations */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div className="section-label">
            {t('agentDetail.operations')} ({opsData?.total_count ?? 0})
          </div>
          <Link
            href={`/operations?agent_id=${agentId}`}
            className="font-mono text-[11px] text-ink-dim hover:text-ink transition-colors no-underline uppercase tracking-wider"
          >
            {t('common.viewAll')}
          </Link>
        </div>
        <DataTable
          columns={opColumns}
          data={(operations.slice(0, 10)) as (Operation & Record<string, unknown>)[]}
          keyExtractor={(row) => row.operation_id}
          isLoading={opsLoading}
          emptyMessage={t('agentDetail.noOperations')}
        />
      </div>

      {/* Freeze Modal */}
      <Modal
        isOpen={showFreezeModal}
        onClose={() => {
          setShowFreezeModal(false);
          setFreezeError(null);
        }}
        title={t('agentDetail.freezeAgent')}
      >
        <div className="space-y-4">
          <p className="font-sans text-sm text-ink-dim">
            {t('agentDetail.freezeDescPre')}<strong className="text-ink">{agentId}</strong>{t('agentDetail.freezeDescPost')}
          </p>
          {freezeError && (
            <div className="px-4 py-3 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">
              {freezeError}
            </div>
          )}
          <div>
            <label className="section-label block mb-1.5">{t('agentDetail.reason')}</label>
            <textarea
              value={freezeReason}
              onChange={(e) => setFreezeReason(e.target.value)}
              placeholder={t('agentDetail.freezePlaceholder')}
              rows={3}
              className="w-full px-3 py-2 bg-transparent border border-border font-mono text-[13px] text-ink placeholder:text-ink-dim focus:outline-none focus:border-ink transition-colors resize-none"
            />
          </div>
          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              className="btn-ghost"
              onClick={() => {
                setShowFreezeModal(false);
                setFreezeError(null);
              }}
            >
              {t('common.cancel')}
            </button>
            <button className="btn-brutalist" onClick={handleFreeze} disabled={freezing}>
              {freezing ? t('agentDetail.freezing') : t('agentDetail.confirmFreeze')}
            </button>
          </div>
        </div>
      </Modal>

      {/* Unfreeze Modal */}
      <Modal
        isOpen={showUnfreezeModal}
        onClose={() => {
          setShowUnfreezeModal(false);
          setUnfreezeError(null);
        }}
        title={t('agentDetail.unfreezeAgent')}
      >
        <div className="space-y-4">
          <p className="font-sans text-sm text-ink-dim">
            {t('agentDetail.unfreezeDescPre')}<strong className="text-ink">{agentId}</strong>{t('agentDetail.unfreezeDescPost')}
          </p>
          {unfreezeError && (
            <div className="px-4 py-3 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">
              {unfreezeError}
            </div>
          )}
          <div>
            <label className="section-label block mb-1.5">{t('agentDetail.reason')}</label>
            <textarea
              value={unfreezeReason}
              onChange={(e) => setUnfreezeReason(e.target.value)}
              placeholder={t('agentDetail.unfreezePlaceholder')}
              rows={3}
              className="w-full px-3 py-2 bg-transparent border border-border font-mono text-[13px] text-ink placeholder:text-ink-dim focus:outline-none focus:border-ink transition-colors resize-none"
            />
          </div>
          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              className="btn-ghost"
              onClick={() => {
                setShowUnfreezeModal(false);
                setUnfreezeError(null);
              }}
            >
              {t('common.cancel')}
            </button>
            <button className="btn-brutalist" onClick={handleUnfreeze} disabled={unfreezing}>
              {unfreezing ? t('agentDetail.unfreezing') : t('agentDetail.confirmUnfreeze')}
            </button>
          </div>
        </div>
      </Modal>

      {/* Revoke Key Modal */}
      <Modal
        isOpen={revokeKeyId !== null}
        onClose={() => {
          setRevokeKeyId(null);
          setRevokeError(null);
        }}
        title={t('agentDetail.revokeKey')}
      >
        <div className="space-y-4">
          <p className="font-sans text-sm text-ink-dim">
            {t('agentDetail.revokeKeyDescPre')}<strong className="text-ink font-mono text-[13px]">{revokeKeyId}</strong>{t('agentDetail.revokeKeyDescPost')}
          </p>
          {revokeError && (
            <div className="px-4 py-3 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">
              {revokeError}
            </div>
          )}
          <div>
            <label className="section-label block mb-1.5">{t('agentDetail.reason')}</label>
            <textarea
              value={revokeReason}
              onChange={(e) => setRevokeReason(e.target.value)}
              placeholder={t('agentDetail.revokePlaceholder')}
              rows={3}
              className="w-full px-3 py-2 bg-transparent border border-border font-mono text-[13px] text-ink placeholder:text-ink-dim focus:outline-none focus:border-ink transition-colors resize-none"
            />
          </div>
          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              className="btn-ghost"
              onClick={() => {
                setRevokeKeyId(null);
                setRevokeError(null);
              }}
            >
              {t('common.cancel')}
            </button>
            <button className="btn-brutalist" onClick={handleRevokeKey} disabled={revoking}>
              {revoking ? t('agentDetail.revoking') : t('agentDetail.confirmRevoke')}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
