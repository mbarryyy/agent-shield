'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useTranslation } from 'react-i18next';
import { useAuth } from '@/lib/auth';
import { authFetch, signOut } from '@/lib/auth-client';
import PageHeader from '@/components/ui/PageHeader';
import type { OkResponse } from '@/types/auth';

export default function AccountSettingsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [pwError, setPwError] = useState('');
  const [pwOk, setPwOk] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault();
    setPwError('');
    setPwOk(false);
    setSubmitting(true);
    try {
      await authFetch<OkResponse>('/v1/auth/password/change', {
        method: 'POST',
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      setPwOk(true);
      setCurrent('');
      setNext('');
    } catch (err) {
      setPwError(err instanceof Error ? err.message : t('account.passwordChangeFailed'));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDisable2fa() {
    // Disabling 2FA requires (password, code) per the server contract; v1
    // surfaces this inline only when the user already supplies them via the
    // /settings/2fa-setup re-flow. The "Disable 2FA" button below is a
    // link to that re-flow so the disable form is in one place.
  }
  void handleDisable2fa;

  return (
    <div className="fade-in">
      <PageHeader
        title={t('account.title')}
        breadcrumbs={[
          { label: t('common.dashboard'), href: '/' },
          { label: t('account.title') },
        ]}
      />

      <section className="mb-8 border border-border p-5">
        <h2 className="font-sans text-base font-semibold text-ink mb-2">{t('account.profile')}</h2>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-y-2 gap-x-6 font-mono text-[12px] text-ink-dim">
          <div><dt className="uppercase tracking-wider text-[10px]">Email</dt><dd className="text-ink mt-0.5 break-all">{user?.email ?? '—'}</dd></div>
          <div><dt className="uppercase tracking-wider text-[10px]">Role</dt><dd className="text-ink mt-0.5">{user?.role ?? '—'}</dd></div>
          <div><dt className="uppercase tracking-wider text-[10px]">Org</dt><dd className="text-ink mt-0.5 break-all">{user?.org_id ?? '—'}</dd></div>
          <div><dt className="uppercase tracking-wider text-[10px]">{t('account.twoFactor')}</dt><dd className="text-ink mt-0.5">{user?.two_factor_enabled ? 'enabled' : 'disabled'}</dd></div>
        </dl>
      </section>

      <section className="mb-8 border border-border p-5">
        <h2 className="font-sans text-base font-semibold text-ink mb-4">{t('account.changePassword')}</h2>
        {pwError && <div className="mb-3 px-3 py-2 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">{pwError}</div>}
        {pwOk && <div className="mb-3 px-3 py-2 border border-border bg-surface font-mono text-[12px] text-ink-dim">{t('common.saved')}</div>}
        <form onSubmit={handleChangePassword} className="space-y-3 max-w-md">
          <label className="block">
            <span className="font-mono text-[10px] text-ink-dim uppercase tracking-wider">{t('account.currentPassword')}</span>
            <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} required className="mt-1 w-full px-3 py-2.5 bg-transparent border border-border font-mono text-[13px] text-ink focus:outline-none focus:border-ink transition-colors" />
          </label>
          <label className="block">
            <span className="font-mono text-[10px] text-ink-dim uppercase tracking-wider">{t('resetPassword.newPassword')}</span>
            <input type="password" value={next} onChange={(e) => setNext(e.target.value)} required minLength={8} className="mt-1 w-full px-3 py-2.5 bg-transparent border border-border font-mono text-[13px] text-ink focus:outline-none focus:border-ink transition-colors" />
          </label>
          <button type="submit" disabled={submitting} className="px-4 py-2 border border-ink bg-ink text-[#EAEAE5] font-mono text-[12px] uppercase tracking-wider hover:bg-[rgba(0,0,0,0.85)] transition-colors disabled:opacity-50">
            {submitting ? '…' : t('account.changePassword')}
          </button>
        </form>
      </section>

      <section className="mb-8 border border-border p-5">
        <h2 className="font-sans text-base font-semibold text-ink mb-3">{t('account.twoFactor')}</h2>
        <Link href="/settings/2fa-setup" className="inline-block px-4 py-2 border border-ink font-mono text-[12px] uppercase tracking-wider text-ink hover:bg-surface transition-colors no-underline">
          {user?.two_factor_enabled ? t('twoFactorSetup.title') : t('twoFactorSetup.enable')}
        </Link>
      </section>

      <section className="border border-red-300 p-5">
        <h2 className="font-sans text-base font-semibold text-red-700 mb-3">{t('account.dangerZone')}</h2>
        <button type="button" onClick={signOut} className="px-4 py-2 border border-red-300 font-mono text-[12px] uppercase tracking-wider text-red-700 hover:bg-red-50 transition-colors">
          {t('common.signOut')}
        </button>
      </section>
    </div>
  );
}
