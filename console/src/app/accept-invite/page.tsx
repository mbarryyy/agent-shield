'use client';

import { Suspense, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import { authFetch } from '@/lib/auth-client';
import BrandMark from '@/components/ui/BrandMark';

// Landing page for the invite link emitted by POST /v1/auth/admin/invite
// (auth/routes.py:961 builds `${public_base_url}/accept-invite?token=…`).
// Server's invite-accept POST endpoint is at /v1/auth/invites/accept (in
// the auth dep allowlist, dep.py:212). Body shape inferred from the
// invite token + new-user credential pattern — server is authoritative.
function AcceptInviteForm() {
  const { t } = useTranslation();
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get('token') ?? '';
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setIsSubmitting(true);
    try {
      await authFetch<{ ok: boolean }>('/v1/auth/invites/accept', {
        method: 'POST',
        body: JSON.stringify({ token, password, name }),
      });
      router.push('/');
    } catch {
      setError(t('invite.expired'));
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
        <span className="font-mono text-[10px] text-ink-dim uppercase tracking-wider">{t('register.displayName')}</span>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="mt-1 w-full px-3 py-2.5 bg-transparent border border-border font-mono text-[13px] text-ink focus:outline-none focus:border-ink transition-colors"
        />
      </label>
      <label className="block">
        <span className="font-mono text-[10px] text-ink-dim uppercase tracking-wider">{t('register.password')}</span>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
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
        {isSubmitting ? '…' : t('invite.accept')}
      </button>
    </form>
  );
}

export default function AcceptInvitePage() {
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
          <h1 className="font-sans text-xl font-semibold tracking-tight text-ink mb-6">{t('invite.title')}</h1>
          <Suspense fallback={<div className="font-mono text-[12px] text-ink-dim">{t('common.loading')}</div>}>
            <AcceptInviteForm />
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
