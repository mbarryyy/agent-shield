'use client';

import { Suspense, useState, useCallback, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import { useAgentsList, useAudit, formatRelativeTime } from '@/lib/hooks';
import { api } from '@/lib/api';
import PageHeader from '@/components/ui/PageHeader';
import DataTable from '@/components/ui/DataTable';
import type { Column } from '@/components/ui/DataTable';
import SearchInput from '@/components/ui/SearchInput';
import Modal from '@/components/ui/Modal';
import AgentRegistrationForm from '@/components/AgentRegistrationForm';

interface AgentRow {
  agent_id: string;
  display_name: string;
  status: string;
  created_at: number;
  [key: string]: unknown;
}

/** Fetches the real total_count for a single agent via the audit API. */
function AgentOpCount({ agentId }: { agentId: string }) {
  const { data, isLoading } = useAudit({ agent_id: agentId });
  if (isLoading) return <span className="font-mono text-[13px] text-ink-dim">&mdash;</span>;
  return <span className="font-mono text-[13px] text-ink-dim">{data?.total_count ?? 0}</span>;
}

/** Fetches the latest operation timestamp for a single agent via the audit API. */
function AgentLatestActivity({ agentId, fallback }: { agentId: string; fallback: number }) {
  const { data, isLoading } = useAudit({ agent_id: agentId });
  if (isLoading) return <span className="font-mono text-[12px] text-ink-dim">&mdash;</span>;
  const latest = data?.operations?.[0]?.issued_at ?? fallback;
  return <span className="font-mono text-[12px] text-ink-dim">{formatRelativeTime(latest)}</span>;
}

function AgentsContent() {
  const { t } = useTranslation();
  const router = useRouter();
  const [search, setSearch] = useState('');
  const [showRegister, setShowRegister] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<AgentRow | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const { data: agentsData, isLoading: agentsLoading, error: agentsError, mutate } = useAgentsList();

  const agents: AgentRow[] = useMemo(() => {
    if (!agentsData?.agents) return [];
    return agentsData.agents.map((agent) => ({
      agent_id: agent.agent_id,
      display_name: agent.display_name,
      status: agent.status,
      created_at: agent.created_at,
    }));
  }, [agentsData]);

  const filteredAgents = useMemo(() => {
    if (!search.trim()) return agents;
    const q = search.toLowerCase();
    return agents.filter(
      (a) => a.agent_id.toLowerCase().includes(q) || a.display_name.toLowerCase().includes(q),
    );
  }, [agents, search]);

  const columns: Column<AgentRow>[] = [
    {
      key: 'agent_id',
      label: t('agents.colAgent'),
      sortable: true,
      render: (row) => (
        <div>
          <span className="font-mono text-[13px] text-ink font-medium">{row.agent_id}</span>
          {row.display_name && row.display_name !== row.agent_id && (
            <span className="ml-2 font-mono text-[11px] text-ink-dim">{row.display_name}</span>
          )}
        </div>
      ),
    },
    {
      key: 'status',
      label: t('agents.colStatus'),
      sortable: true,
      width: '100px',
      render: (row) => (
        <span
          className={`font-mono text-[11px] uppercase tracking-wider ${
            row.status === 'active'
              ? 'text-ink'
              : row.status === 'frozen'
                ? 'text-amber-600'
                : 'text-red-600'
          }`}
        >
          {row.status}
        </span>
      ),
    },
    {
      key: 'operation_count',
      label: t('agents.colOperations'),
      width: '120px',
      render: (row) => <AgentOpCount agentId={row.agent_id} />,
    },
    {
      key: 'latest_activity',
      label: t('agents.colLatestActivity'),
      render: (row) => <AgentLatestActivity agentId={row.agent_id} fallback={row.created_at} />,
    },
    {
      key: 'actions',
      label: '',
      width: '80px',
      render: (row) => (
        <button
          className="btn-ghost text-[10px] py-1 px-2 text-red-600 hover:text-red-700"
          onClick={(e) => {
            e.stopPropagation();
            setDeleteTarget(row);
          }}
        >
          {t('common.delete')}
        </button>
      ),
    },
  ];

  const handleRowClick = useCallback(
    (row: AgentRow) => {
      router.push(`/agents/${row.agent_id}`);
    },
    [router],
  );

  const handleRegisterSuccess = useCallback(() => {
    setShowRegister(false);
    mutate();
  }, [mutate]);

  const handleDelete = useCallback(async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.agents.delete(deleteTarget.agent_id);
      setDeleteTarget(null);
      mutate();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : t('agents.failedToDelete'));
    } finally {
      setDeleting(false);
    }
  }, [deleteTarget, mutate]);

  return (
    <div className="fade-in">
      <PageHeader
        title={t('agents.title')}
        subtitle={t('agents.subtitle')}
        breadcrumbs={[
          { label: t('common.dashboard'), href: '/' },
          { label: t('agents.title') },
        ]}
        actions={
          <button className="btn-brutalist" onClick={() => setShowRegister(true)}>
            {t('agents.registerAgent')}
          </button>
        }
      />

      {agentsError && (
        <div className="mb-6 px-4 py-3 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">
          {t('agents.failedToLoad')} {agentsError instanceof Error ? agentsError.message : t('common.unknownError')}
        </div>
      )}

      <div className="mb-4">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder={t('agents.searchPlaceholder')}
          className="max-w-md"
        />
      </div>

      <DataTable
        columns={columns}
        data={filteredAgents}
        keyExtractor={(row) => row.agent_id}
        onRowClick={handleRowClick}
        isLoading={agentsLoading}
        emptyMessage={t('agents.emptyMessage')}
      />

      <Modal
        isOpen={showRegister}
        onClose={() => setShowRegister(false)}
        title={t('agents.registerAgent')}
        width="max-w-2xl"
      >
        <AgentRegistrationForm
          onSuccess={handleRegisterSuccess}
          onCancel={() => setShowRegister(false)}
        />
      </Modal>

      <Modal
        isOpen={deleteTarget !== null}
        onClose={() => { setDeleteTarget(null); setDeleteError(null); }}
        title={t('agents.deleteAgent')}
      >
        <div className="space-y-4">
          <p className="font-sans text-sm text-ink-dim">
            {t('agents.deleteConfirmPre')}<strong className="text-ink font-mono text-[13px]">{deleteTarget?.agent_id}</strong>{t('agents.deleteConfirmPost')}
          </p>
          {deleteError && (
            <div className="px-4 py-3 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">
              {deleteError}
            </div>
          )}
          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              className="btn-ghost"
              onClick={() => { setDeleteTarget(null); setDeleteError(null); }}
            >
              {t('common.cancel')}
            </button>
            <button
              className="btn-brutalist bg-red-600 text-white border-red-700 hover:bg-red-700"
              onClick={handleDelete}
              disabled={deleting}
            >
              {deleting ? t('agents.deleting') : t('agents.deleteAgent')}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

export default function AgentsPage() {
  return (
    <Suspense fallback={<div className="fade-in"><div className="border border-border p-6"><div className="space-y-3"><div className="skeleton h-10 w-full max-w-md" /><div className="skeleton h-6 w-full" /><div className="skeleton h-6 w-full" /><div className="skeleton h-6 w-3/4" /></div></div></div>}>
      <AgentsContent />
    </Suspense>
  );
}
