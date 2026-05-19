'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { signUp } from '@/lib/auth-client';
import { useTranslation } from 'react-i18next';

export default function RegisterPage() {
  const { t } = useTranslation();
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [orgName, setOrgName] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setIsSubmitting(true);
    try {
      const result = await signUp.email({ email, password, name: displayName });
      if (result.error) {
        throw new Error(result.error.message ?? t('register.registrationFailed'));
      }
      router.push('/');
    } catch (err) {
      setError(err instanceof Error ? err.message : t('register.registrationFailed'));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center px-6">
      <div className="w-full max-w-[400px]">
        {/* Logo */}
        <div className="mb-12 text-center">
          <div className="inline-flex items-center gap-3">
            <div className="w-10 h-10 border border-ink flex items-center justify-center">
              <span className="font-mono text-lg font-bold text-ink">E</span>
            </div>
            <div className="text-left">
              <div className="font-sans text-base font-semibold tracking-wide text-ink">ELYDORA</div>
              <div className="font-mono text-[10px] text-ink-dim tracking-widest uppercase">Console</div>
            </div>
          </div>
        </div>

        {/* Form */}
        <div className="border border-border bg-surface p-8">
          <h1 className="font-sans text-xl font-semibold tracking-tight text-ink mb-6">{t('register.createAccount')}</h1>

          {error && (
            <div className="mb-4 p-3 border border-red-300 bg-red-50 text-red-700 text-sm font-mono">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block font-mono text-[11px] uppercase tracking-wider text-ink-dim mb-1.5">{t('register.orgName')}</label>
              <input
                type="text"
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
                required
                className="w-full px-3 py-2.5 border border-border bg-bg font-mono text-sm text-ink focus:outline-none focus:border-ink transition-colors"
                placeholder={t('register.orgPlaceholder')}
              />
            </div>
            <div>
              <label className="block font-mono text-[11px] uppercase tracking-wider text-ink-dim mb-1.5">{t('register.displayName')}</label>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                required
                className="w-full px-3 py-2.5 border border-border bg-bg font-mono text-sm text-ink focus:outline-none focus:border-ink transition-colors"
                placeholder={t('register.displayNamePlaceholder')}
              />
            </div>
            <div>
              <label className="block font-mono text-[11px] uppercase tracking-wider text-ink-dim mb-1.5">{t('register.email')}</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full px-3 py-2.5 border border-border bg-bg font-mono text-sm text-ink focus:outline-none focus:border-ink transition-colors"
                placeholder={t('register.emailPlaceholder')}
              />
            </div>
            <div>
              <label className="block font-mono text-[11px] uppercase tracking-wider text-ink-dim mb-1.5">{t('register.password')}</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
                className="w-full px-3 py-2.5 border border-border bg-bg font-mono text-sm text-ink focus:outline-none focus:border-ink transition-colors"
                placeholder={t('register.passwordPlaceholder')}
              />
            </div>
            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full btn-brutalist py-3 text-xs uppercase font-bold tracking-wider disabled:opacity-50"
            >
              {isSubmitting ? t('register.creatingAccount') : t('register.submitCreateAccount')}
            </button>
          </form>

          <div className="mt-6 text-center">
            <span className="font-mono text-xs text-ink-dim">{t('register.hasAccount')}</span>
            <Link href="/login" className="font-mono text-xs text-ink underline hover:no-underline">
              {t('register.signIn')}
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
