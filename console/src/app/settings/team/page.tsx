'use client';

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { RbacRole } from '@elydora/shared';
import { useAuth } from '@/lib/auth';
import { authFetch } from '@/lib/auth-client';
import PageHeader from '@/components/ui/PageHeader';
import type {
  AdminInviteRequest,
  AdminInviteResponse,
  AdminUser,
  AdminUsersResponse,
} from '@/types/auth';

const ROLES: RbacRole[] = [
  'org_owner',
  'security_admin',
  'integration_engineer',
  'compliance_auditor',
  'readonly_investigator',
];

export default function TeamSettingsPage() {
  const { t } = useTranslation();
  const { canManageMembers } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<RbacRole>('readonly_investigator');
  const [inviteSent, setInviteSent] = useState(false);

  const refresh = useCallback(async () => {
    setError('');
    setLoading(true);
    try {
      const res = await authFetch<AdminUsersResponse>('/v1/auth/admin/users');
      setUsers(res.users);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.unknownError'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (canManageMembers) void refresh();
  }, [canManageMembers, refresh]);

  if (!canManageMembers) {
    return (
      <div className="fade-in">
        <PageHeader
          title={t('team.title')}
          breadcrumbs={[{ label: t('common.dashboard'), href: '/' }, { label: t('team.title') }]}
        />
        <div className="border border-border px-4 py-12 text-center font-mono text-[12px] text-ink-dim">
          {t('common.missingPermission')}
        </div>
      </div>
    );
  }

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setInviteSent(false);
    try {
      const body: AdminInviteRequest = { email: inviteEmail, role: inviteRole };
      await authFetch<AdminInviteResponse>('/v1/auth/admin/invite', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      setInviteSent(true);
      setInviteEmail('');
      void refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.unknownError'));
    }
  }

  async function handleRoleChange(userId: string, role: RbacRole) {
    setError('');
    try {
      await authFetch<{ ok: boolean }>(
        `/v1/auth/admin/users/${encodeURIComponent(userId)}/role`,
        { method: 'POST', body: JSON.stringify({ role }) },
      );
      void refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.unknownError'));
    }
  }

  return (
    <div className="fade-in">
      <PageHeader
        title={t('team.title')}
        breadcrumbs={[{ label: t('common.dashboard'), href: '/' }, { label: t('team.title') }]}
      />

      {error && <div className="mb-4 px-3 py-2 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">{error}</div>}

      <section className="mb-8 border border-border p-5">
        <h2 className="font-sans text-base font-semibold text-ink mb-3">{t('team.invite')}</h2>
        {inviteSent && <div className="mb-3 px-3 py-2 border border-border bg-surface font-mono text-[12px] text-ink-dim">{t('team.inviteSent')}</div>}
        <form onSubmit={handleInvite} className="flex flex-col sm:flex-row gap-3 items-stretch sm:items-end max-w-2xl">
          <label className="flex-1 block">
            <span className="font-mono text-[10px] text-ink-dim uppercase tracking-wider">Email</span>
            <input type="email" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} required className="mt-1 w-full px-3 py-2.5 bg-transparent border border-border font-mono text-[13px] text-ink focus:outline-none focus:border-ink transition-colors" />
          </label>
          <label className="block">
            <span className="font-mono text-[10px] text-ink-dim uppercase tracking-wider">{t('team.role')}</span>
            <select value={inviteRole} onChange={(e) => setInviteRole(e.target.value as RbacRole)} className="mt-1 w-full px-3 py-2.5 bg-transparent border border-border font-mono text-[13px] text-ink focus:outline-none focus:border-ink transition-colors">
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
          <button type="submit" className="px-4 py-2.5 border border-ink bg-ink text-[#EAEAE5] font-mono text-[12px] uppercase tracking-wider hover:bg-[rgba(0,0,0,0.85)] transition-colors">
            {t('team.invite')}
          </button>
        </form>
      </section>

      <div className="border border-border">
        <div className="px-4 py-3 border-b border-border font-mono text-[11px] uppercase tracking-wider text-ink-dim">
          {t('team.title')}
        </div>
        {loading ? (
          <div className="px-4 py-8 text-center font-mono text-[12px] text-ink-dim">{t('common.loading')}</div>
        ) : users.length === 0 ? (
          <div className="px-4 py-8 text-center font-mono text-[12px] text-ink-dim">{t('team.noMembers')}</div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-border">
                <th className="px-4 py-2 text-left font-mono text-[10px] uppercase tracking-wider text-ink-dim">Email</th>
                <th className="px-4 py-2 text-left font-mono text-[10px] uppercase tracking-wider text-ink-dim">{t('team.role')}</th>
                <th className="px-4 py-2 text-left font-mono text-[10px] uppercase tracking-wider text-ink-dim">{t('team.status')}</th>
                <th className="px-4 py-2 text-left font-mono text-[10px] uppercase tracking-wider text-ink-dim">{t('account.twoFactor')}</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.user_id} className="border-b border-border last:border-0">
                  <td className="px-4 py-3 font-mono text-[13px] text-ink break-all">{u.email}</td>
                  <td className="px-4 py-3">
                    <select
                      value={u.role ?? 'readonly_investigator'}
                      onChange={(e) => handleRoleChange(u.user_id, e.target.value as RbacRole)}
                      className="bg-transparent border border-border font-mono text-[12px] text-ink px-2 py-1"
                    >
                      {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </td>
                  <td className="px-4 py-3 font-mono text-[12px] text-ink-dim">{u.status}</td>
                  <td className="px-4 py-3 font-mono text-[12px] text-ink-dim">{u.totp_enabled ? '✓' : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
