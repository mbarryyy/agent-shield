'use client';

import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import { authFetch } from '@/lib/auth-client';
import BrandMark from '@/components/ui/BrandMark';
import type { OkResponse } from '@/types/auth';

type Status = 'idle' | 'verifying' | 'success' | 'expired';

function VerifyEmailInner() {
  const { t } = useTranslation();
  const searchParams = useSearchParams();
  const token = searchParams.get('token') ?? '';
  const [status, setStatus] = useState<Status>('idle');
  const [resentOk, setResentOk] = useState(false);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setStatus('verifying');
    authFetch<OkResponse>('/v1/auth/email/verify/complete', {
      method: 'POST',
      body: JSON.stringify({ token }),
    })
      .then(() => !cancelled && setStatus('success'))
      .catch(() => !cancelled && setStatus('expired'));
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function handleResend() {
    setResentOk(false);
    try {
      await authFetch<OkResponse>('/v1/auth/email/verify/request', { method: 'POST' });
      setResentOk(true);
    } catch {
      setResentOk(true); // surface same generic state (enumeration-safe)
    }
  }

  return (
    <div className="border border-border p-6">
      <h1 className="font-sans text-xl font-semibold tracking-tight text-ink mb-6">
        {t('verifyEmail.title')}
      </h1>
      {status === 'idle' && (
        <p className="font-mono text-[12px] text-ink-dim">{t('verifyEmail.alreadyVerified')}</p>
      )}
      {status === 'verifying' && (
        <p className="font-mono text-[12px] text-ink-dim">{t('verifyEmail.verifying')}</p>
      )}
      {status === 'success' && (
        <p className="font-mono text-[12px] text-ink">{t('verifyEmail.success')}</p>
      )}
      {status === 'expired' && (
        <>
          <p className="font-mono text-[12px] text-red-700 mb-4">{t('verifyEmail.expired')}</p>
          <button
            type="button"
            onClick={handleResend}
            className="px-4 py-2 border border-ink font-mono text-[12px] uppercase tracking-wider text-ink hover:bg-surface transition-colors"
          >
            {t('verifyEmail.resend')}
          </button>
          {resentOk && (
            <div className="mt-3 font-mono text-[11px] text-ink-dim">{t('verifyEmail.resent')}</div>
          )}
        </>
      )}
      <div className="mt-6 text-center">
        <Link href="/login" className="font-mono text-[11px] text-ink-dim hover:text-ink no-underline">
          ← {t('forgotPassword.backToLogin')}
        </Link>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
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
        <Suspense fallback={<div className="font-mono text-[12px] text-ink-dim">{t('common.loading')}</div>}>
          <VerifyEmailInner />
        </Suspense>
      </div>
    </div>
  );
}
