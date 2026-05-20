'use client';

import { Suspense, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import { authFetch, resolveAuthErrorMessage } from '@/lib/auth-client';
import BrandMark from '@/components/ui/BrandMark';
import type { OkResponse } from '@/types/auth';

function ResetForm() {
  const { t } = useTranslation();
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get('token') ?? '';
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    if (newPassword !== confirm) {
      setError(t('register.passwordMismatch'));
      return;
    }
    setIsSubmitting(true);
    try {
      await authFetch<OkResponse>('/v1/auth/password/reset/complete', {
        method: 'POST',
        body: JSON.stringify({ token, new_password: newPassword }),
      });
      router.push('/login');
    } catch (err) {
      setError(resolveAuthErrorMessage(err, t('resetPassword.tokenExpired')));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div className="px-3 py-2 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">{error}</div>
      )}
      <label className="block">
        <span className="font-mono text-[10px] text-ink-dim uppercase tracking-wider">{t('resetPassword.newPassword')}</span>
        <input
          type="password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          required
          minLength={8}
          autoFocus
          className="mt-1 w-full px-3 py-2.5 bg-transparent border border-border font-mono text-[13px] text-ink focus:outline-none focus:border-ink transition-colors"
        />
      </label>
      <label className="block">
        <span className="font-mono text-[10px] text-ink-dim uppercase tracking-wider">{t('resetPassword.confirm')}</span>
        <input
          type="password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          required
          minLength={8}
          className="mt-1 w-full px-3 py-2.5 bg-transparent border border-border font-mono text-[13px] text-ink focus:outline-none focus:border-ink transition-colors"
        />
      </label>
      <button
        type="submit"
        disabled={isSubmitting || !token}
        className="w-full px-4 py-2.5 bg-ink text-[#EAEAE5] font-mono text-[12px] uppercase tracking-wider hover:bg-[rgba(0,0,0,0.85)] transition-colors disabled:opacity-50"
      >
        {isSubmitting ? '…' : t('resetPassword.submit')}
      </button>
    </form>
  );
}

export default function PasswordResetPage() {
  const { t } = useTranslation();
  return (
    <div className="min-h-screen flex items-center justify-center bg-bg px-4">
      <div className="w-full max-w-sm">
        <div className="mb-12 text-center">
          <div className="inline-flex items-center gap-3">
            <div className="w-10 h-10 border border-ink flex items-center justify-center text-ink">
              <BrandMark size="md" />
            </div>
            <div className="text-left">
              <div className="font-sans text-base font-semibold tracking-wide text-ink">AGENT SHIELD</div>
              <div className="font-mono text-[10px] text-ink-dim tracking-widest uppercase">Console</div>
            </div>
          </div>
        </div>
        <div className="border border-border p-6">
          <h1 className="font-sans text-xl font-semibold tracking-tight text-ink mb-6">{t('resetPassword.title')}</h1>
          <Suspense fallback={<div className="font-mono text-[12px] text-ink-dim">{t('common.loading')}</div>}>
            <ResetForm />
          </Suspense>
          <div className="mt-6 text-center">
            <Link href="/login" className="font-mono text-[11px] text-ink-dim hover:text-ink no-underline">
              ← {t('forgotPassword.backToLogin')}
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
