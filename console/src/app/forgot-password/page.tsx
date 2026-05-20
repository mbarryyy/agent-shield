'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useTranslation } from 'react-i18next';
import { authFetch, resolveAuthErrorMessage } from '@/lib/auth-client';
import BrandMark from '@/components/ui/BrandMark';
import type { OkResponse } from '@/types/auth';

export default function ForgotPasswordPage() {
  const { t } = useTranslation();
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setIsSubmitting(true);
    try {
      await authFetch<OkResponse>('/v1/auth/password/reset/request', {
        method: 'POST',
        body: JSON.stringify({ email }),
      });
      setSent(true);
    } catch (err) {
      // Email-enumeration safety is the SERVER's responsibility (it returns
      // 200 OK for both existing and non-existing emails — see
      // shield_server/auth/routes.py:password_reset_request). A 4xx/5xx
      // received here is therefore a real server error (rate-limit, 500,
      // network) NOT an enumeration leak — surface it via the unified
      // renderer for honest feedback. Task #29 (A.2).
      setError(resolveAuthErrorMessage(err, t('forgotPassword.sent')));
    } finally {
      setIsSubmitting(false);
    }
  }

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
          <h1 className="font-sans text-xl font-semibold tracking-tight text-ink mb-2">
            {t('forgotPassword.title')}
          </h1>
          <p className="font-mono text-[12px] text-ink-dim mb-6">{t('forgotPassword.instruction')}</p>
          {sent ? (
            <div className="px-3 py-3 border border-border bg-surface font-mono text-[12px] text-ink-dim">
              {t('forgotPassword.sent')}
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              {error && (
                <div className="px-3 py-2 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">{error}</div>
              )}
              <label className="block">
                <span className="font-mono text-[10px] text-ink-dim uppercase tracking-wider">{t('forgotPassword.email')}</span>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoFocus
                  className="mt-1 w-full px-3 py-2.5 bg-transparent border border-border font-mono text-[13px] text-ink focus:outline-none focus:border-ink transition-colors"
                />
              </label>
              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full px-4 py-2.5 bg-ink text-[#EAEAE5] font-mono text-[12px] uppercase tracking-wider hover:bg-[rgba(0,0,0,0.85)] transition-colors disabled:opacity-50"
              >
                {isSubmitting ? '…' : t('forgotPassword.send')}
              </button>
            </form>
          )}
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
