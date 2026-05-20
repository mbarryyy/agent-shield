'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import { SESSION_EXPIRED_EVENT } from '@/lib/api';

/**
 * Global session-expired modal — listens for the 'shield:session-expired'
 * window event (dispatched by lib/api.ts on any 401) and gives the user
 * a single "Sign in again" click. Preserves in-flight UI state (no
 * implicit redirect), per ADR-0013 / team-lead spec replacement of the
 * old hard window.location.href = '/login' on 401.
 */
export default function SessionExpiredModal() {
  const { t } = useTranslation();
  const router = useRouter();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onExpired = () => setOpen(true);
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
  }, []);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="session-expired-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
    >
      <div className="w-[min(420px,92vw)] border border-border bg-bg p-6">
        <h2
          id="session-expired-title"
          className="font-sans text-lg font-semibold text-ink mb-2"
        >
          {t('sessionExpired.title')}
        </h2>
        <p className="font-mono text-[12px] text-ink-dim mb-6">
          {t('sessionExpired.message')}
        </p>
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            router.push('/login');
          }}
          className="px-4 py-2 border border-ink bg-ink text-[#EAEAE5] font-mono text-[12px] uppercase tracking-wider hover:bg-[rgba(0,0,0,0.85)] transition-colors"
        >
          {t('sessionExpired.signInAgain')}
        </button>
      </div>
    </div>
  );
}
