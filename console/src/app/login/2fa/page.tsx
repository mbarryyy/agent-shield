'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import Link from 'next/link';
import { signIn } from '@/lib/auth-client';
import BrandMark from '@/components/ui/BrandMark';
import { authFetch } from '@/lib/auth-client';
import type { OkResponse } from '@/types/auth';

// Two-factor challenge step after sign-in (`SignInResponse.requires_totp ===
// true` from /login). The TOTP code re-submits via POST /v1/auth/sign-in
// with `totp_code`; recovery codes go via POST /v1/auth/totp/recovery.
export default function TwoFactorPage() {
  const { t } = useTranslation();
  const router = useRouter();
  const [code, setCode] = useState('');
  const [recovery, setRecovery] = useState('');
  const [useRecoveryMode, setUseRecoveryMode] = useState(false);
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  function readPending(): { email: string; password: string } | null {
    try {
      const raw = sessionStorage.getItem('shield:pending-2fa');
      if (!raw) return null;
      return JSON.parse(raw) as { email: string; password: string };
    } catch {
      return null;
    }
  }

  async function handleTotp(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setIsSubmitting(true);
    try {
      const pending = readPending();
      if (!pending) {
        router.push('/login');
        return;
      }
      const res = await signIn.email({ ...pending, totp_code: code });
      if (res.requires_totp) {
        setError(t('login.twoFactorInvalid'));
        return;
      }
      sessionStorage.removeItem('shield:pending-2fa');
      router.push('/');
    } catch {
      setError(t('login.twoFactorInvalid'));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleRecovery(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setIsSubmitting(true);
    try {
      const pending = readPending();
      if (!pending) {
        router.push('/login');
        return;
      }
      await authFetch<OkResponse>('/v1/auth/totp/recovery', {
        method: 'POST',
        body: JSON.stringify({ email: pending.email, recovery_code: recovery }),
      });
      sessionStorage.removeItem('shield:pending-2fa');
      router.push('/');
    } catch {
      setError(t('login.twoFactorInvalid'));
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
          <h1 className="font-sans text-xl font-semibold tracking-tight text-ink mb-6">
            {t('login.twoFactorTitle')}
          </h1>
          {error && (
            <div className="mb-4 px-3 py-2 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">
              {error}
            </div>
          )}
          {!useRecoveryMode ? (
            <form onSubmit={handleTotp} className="space-y-4">
              <label className="block">
                <span className="font-mono text-[10px] text-ink-dim uppercase tracking-wider">
                  {t('login.twoFactorCode')}
                </span>
                <input
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  required
                  autoFocus
                  className="mt-1 w-full px-3 py-2.5 bg-transparent border border-border font-mono text-[13px] text-ink focus:outline-none focus:border-ink transition-colors tracking-widest"
                />
              </label>
              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full px-4 py-2.5 bg-ink text-[#EAEAE5] font-mono text-[12px] uppercase tracking-wider hover:bg-[rgba(0,0,0,0.85)] transition-colors disabled:opacity-50"
              >
                {isSubmitting ? '…' : t('common.continue')}
              </button>
            </form>
          ) : (
            <form onSubmit={handleRecovery} className="space-y-4">
              <label className="block">
                <span className="font-mono text-[10px] text-ink-dim uppercase tracking-wider">
                  {t('login.twoFactorUseRecovery')}
                </span>
                <input
                  type="text"
                  value={recovery}
                  onChange={(e) => setRecovery(e.target.value)}
                  required
                  className="mt-1 w-full px-3 py-2.5 bg-transparent border border-border font-mono text-[13px] text-ink focus:outline-none focus:border-ink transition-colors"
                />
              </label>
              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full px-4 py-2.5 bg-ink text-[#EAEAE5] font-mono text-[12px] uppercase tracking-wider hover:bg-[rgba(0,0,0,0.85)] transition-colors disabled:opacity-50"
              >
                {isSubmitting ? '…' : t('common.continue')}
              </button>
            </form>
          )}
          <div className="mt-6 flex items-center justify-between font-mono text-[11px]">
            <button
              type="button"
              onClick={() => setUseRecoveryMode((v) => !v)}
              className="text-ink-dim hover:text-ink transition-colors underline"
            >
              {useRecoveryMode ? t('login.twoFactorCode') : t('login.twoFactorUseRecovery')}
            </button>
            <Link href="/login" className="text-ink-dim hover:text-ink transition-colors no-underline">
              ← {t('forgotPassword.backToLogin')}
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
