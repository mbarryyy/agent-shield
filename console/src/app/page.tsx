'use client';

import { useAgentsList, useAudit, useEpochs, useExports, formatTimestamp, formatRelativeTime } from '@/lib/hooks';
import { useTranslation } from 'react-i18next';
import PageHeader from '@/components/ui/PageHeader';
import Link from 'next/link';

function StatCard({
  label,
  value,
  subtitle,
  isLoading,
}: {
  label: string;
  value: string | number;
  subtitle?: string;
  isLoading?: boolean;
}) {
  return (
    <div className="stat-card">
      <div className="section-label mb-3">{label}</div>
      {isLoading ? (
        <div className="skeleton h-8 w-20 mb-1" />
      ) : (
        <div className="font-sans text-3xl font-semibold tracking-tight text-ink leading-none">
          {value}
        </div>
      )}
      {subtitle && (
        <div className="font-mono text-[11px] text-ink-dim mt-2">{subtitle}</div>
      )}
    </div>
  );
}

export default function DashboardPage() {
  const { t } = useTranslation();
  const { data: agentsData, isLoading: agentsLoading } = useAgentsList();
  const { data: auditData, isLoading: auditLoading, error: auditError } = useAudit({});
  const { data: epochsData, isLoading: epochsLoading } = useEpochs();
  const { data: exportsData, isLoading: exportsLoading } = useExports();

  const agentsList = agentsData?.agents ?? [];
  const operations = auditData?.operations ?? [];
  const recentOps = operations.slice(0, 10);
  const totalOps = auditData?.total_count ?? 0;
  const epochs = epochsData?.epochs ?? [];
  const exports = exportsData?.exports ?? [];
  const pendingExports = exports.filter((e) => e.status === 'queued' || e.status === 'running');

  return (
    <div className="fade-in">
      <PageHeader
        title={t('dashboard.title')}
        subtitle={t('dashboard.subtitle')}
      />

      {auditError && (
        <div className="mb-6 px-4 py-3 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">
          {t('dashboard.failedToLoad')}
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8 stagger-children">
        <StatCard
          label={t('dashboard.totalAgents')}
          value={agentsList.length}
          subtitle={t('dashboard.registeredAgents')}
          isLoading={agentsLoading}
        />
        <StatCard
          label={t('dashboard.totalOperations')}
          value={totalOps}
          subtitle={t('dashboard.allRecordedOps')}
          isLoading={auditLoading}
        />
        <StatCard
          label={t('dashboard.activeEpochs')}
          value={epochs.length}
          subtitle={t('dashboard.merkleRollups')}
          isLoading={epochsLoading}
        />
        <StatCard
          label={t('dashboard.pendingExports')}
          value={pendingExports.length}
          subtitle={t('dashboard.queuedOrRunning')}
          isLoading={exportsLoading}
        />
      </div>

      {/* Quick Actions */}
      <div className="mb-8">
        <div className="section-label mb-3">{t('dashboard.quickActions')}</div>
        <div className="flex flex-wrap gap-3">
          <Link href="/agents" className="btn-brutalist inline-block no-underline">
            {t('dashboard.registerAgent')}
          </Link>
          <Link href="/operations" className="btn-ghost inline-block no-underline">
            {t('dashboard.viewOperations')}
          </Link>
          <Link href="/exports" className="btn-ghost inline-block no-underline">
            {t('dashboard.createExport')}
          </Link>
        </div>
      </div>

      {/* Recent Operations */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-3">
          <div className="section-label">{t('dashboard.recentOperations')}</div>
          <Link
            href="/operations"
            className="font-mono text-[11px] text-ink-dim hover:text-ink transition-colors no-underline uppercase tracking-wider"
          >
            {t('common.viewAll')}
          </Link>
        </div>

        <div className="border border-border overflow-hidden">
          {auditLoading ? (
            <div className="p-4 space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex gap-4">
                  <div className="skeleton h-4 w-40" />
                  <div className="skeleton h-4 w-24" />
                  <div className="skeleton h-4 w-32" />
                  <div className="skeleton h-4 w-20" />
                </div>
              ))}
            </div>
          ) : recentOps.length === 0 ? (
            <div className="py-12 text-center">
              <p className="font-mono text-sm text-ink-dim">
                {t('dashboard.noOperations')}
              </p>
            </div>
          ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse min-w-[600px]">
              <thead>
                <tr className="border-b border-border bg-surface">
                  <th className="table-header text-left px-4 py-3">{t('dashboard.colOperationId')}</th>
                  <th className="table-header text-left px-4 py-3">{t('dashboard.colAgent')}</th>
                  <th className="table-header text-left px-4 py-3">{t('dashboard.colType')}</th>
                  <th className="table-header text-left px-4 py-3">{t('dashboard.colIssued')}</th>
                  <th className="table-header text-left px-4 py-3">{t('dashboard.colSeq')}</th>
                </tr>
              </thead>
              <tbody>
                {recentOps.map((op) => (
                  <tr key={op.operation_id} className="data-row border-b border-border last:border-b-0">
                    <td className="px-4 py-3">
                      <Link
                        href={`/operations/${op.operation_id}`}
                        className="font-mono text-[13px] text-ink hover:underline no-underline"
                      >
                        {op.operation_id.slice(0, 16)}...
                      </Link>
                    </td>
                    <td className="px-4 py-3 font-mono text-[13px] text-ink-dim">
                      {op.agent_id}
                    </td>
                    <td className="px-4 py-3">
                      <span className="font-mono text-[11px] uppercase tracking-wider px-2 py-1 bg-surface border border-border">
                        {op.operation_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-[12px] text-ink-dim">
                      {formatRelativeTime(op.issued_at)}
                    </td>
                    <td className="px-4 py-3 font-mono text-[13px] text-ink-dim">
                      #{op.seq_no}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          )}
        </div>
      </div>

      {/* Agent Status Summary */}
      <div>
        <div className="section-label mb-3">{t('dashboard.agentSummary')}</div>
        <div className="border border-border bg-surface p-4 sm:p-6">
          {agentsLoading ? (
            <div className="flex gap-8">
              <div className="skeleton h-4 w-32" />
              <div className="skeleton h-4 w-32" />
              <div className="skeleton h-4 w-32" />
            </div>
          ) : agentsList.length === 0 ? (
            <p className="font-mono text-sm text-ink-dim">
              {t('dashboard.noAgentsRegistered')}
            </p>
          ) : (
            <div className="flex flex-wrap gap-8">
              <div>
                <div className="font-mono text-[11px] text-ink-dim uppercase tracking-wider mb-1">
                  {t('dashboard.totalAgents')}
                </div>
                <div className="font-sans text-xl font-semibold text-ink">
                  {agentsList.length}
                </div>
              </div>
              <div>
                <div className="font-mono text-[11px] text-ink-dim uppercase tracking-wider mb-1">
                  {t('dashboard.totalOperations')}
                </div>
                <div className="font-sans text-xl font-semibold text-ink">
                  {totalOps}
                </div>
              </div>
              {operations.length > 0 && operations[0] != null && (
                <div>
                  <div className="font-mono text-[11px] text-ink-dim uppercase tracking-wider mb-1">
                    {t('dashboard.latestActivity')}
                  </div>
                  <div className="font-mono text-sm text-ink">
                    {formatTimestamp(operations[0].issued_at)}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
