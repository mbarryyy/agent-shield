'use client';

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import QRCode from 'qrcode';
import PageHeader from '@/components/ui/PageHeader';
import { authFetch } from '@/lib/auth-client';
import type {
  TotpSetupResponse,
  TotpConfirmResponse,
  OkResponse,
} from '@/types/auth';

type Step = 'init' | 'scan' | 'recovery' | 'done';

export default function TwoFactorSetupPage() {
  const { t } = useTranslation();
  const [step, setStep] = useState<Step>('init');
  const [setup, setSetup] = useState<TotpSetupResponse | null>(null);
  const [qrDataUrl, setQrDataUrl] = useState<string>('');
  const [code, setCode] = useState('');
  const [recovery, setRecovery] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  async function handleStart() {
    setError('');
    setSubmitting(true);
    try {
      const res = await authFetch<TotpSetupResponse>('/v1/auth/totp/setup', { method: 'POST' });
      setSetup(res);
      try {
        const url = await QRCode.toDataURL(res.provisioning_uri, { margin: 1, scale: 6 });
        setQrDataUrl(url);
      } catch {
        setQrDataUrl('');
      }
      setStep('scan');
    } catch (err) {
      setError(err instanceof Error ? err.message : t('twoFactorSetup.enable'));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleConfirm(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      const res = await authFetch<TotpConfirmResponse>('/v1/auth/totp/confirm', {
        method: 'POST',
        body: JSON.stringify({ code }),
      });
      setRecovery(res.recovery_codes);
      setStep('recovery');
    } catch {
      setError(t('login.twoFactorInvalid'));
    } finally {
      setSubmitting(false);
    }
  }

  useEffect(() => {
    // No auto-start: TOTP setup must be a deliberate user action.
  }, []);

  return (
    <div className="fade-in">
      <PageHeader
        title={t('twoFactorSetup.title')}
        breadcrumbs={[
          { label: t('common.dashboard'), href: '/' },
          { label: t('account.title'), href: '/settings/account' },
          { label: t('twoFactorSetup.title') },
        ]}
      />

      {error && <div className="mb-4 px-3 py-2 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">{error}</div>}

      {step === 'init' && (
        <div className="border border-border p-6">
          <p className="font-mono text-[12px] text-ink-dim mb-4">{t('twoFactorSetup.scanQR')}</p>
          <button type="button" onClick={handleStart} disabled={submitting} className="px-4 py-2 border border-ink bg-ink text-[#EAEAE5] font-mono text-[12px] uppercase tracking-wider hover:bg-[rgba(0,0,0,0.85)] transition-colors disabled:opacity-50">
            {submitting ? '…' : t('twoFactorSetup.enable')}
          </button>
        </div>
      )}

      {step === 'scan' && setup && (
        <div className="border border-border p-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div>
            {qrDataUrl ? (
              // QR is a deterministic render of setup.provisioning_uri (the
              // server-issued otpauth:// URI); we render it locally only.
              // eslint-disable-next-line @next/next/no-img-element
              <img src={qrDataUrl} alt={t('twoFactorSetup.scanQR')} className="border border-border bg-white p-2" />
            ) : (
              <div className="font-mono text-[12px] text-ink-dim">{t('common.loading')}</div>
            )}
            <div className="mt-3 font-mono text-[10px] text-ink-dim uppercase tracking-wider">{t('twoFactorSetup.manualKey')}</div>
            <div className="font-mono text-[12px] text-ink break-all select-all">{setup.secret}</div>
          </div>
          <form onSubmit={handleConfirm} className="space-y-3 self-center">
            <label className="block">
              <span className="font-mono text-[10px] text-ink-dim uppercase tracking-wider">{t('twoFactorSetup.enterCode')}</span>
              <input type="text" inputMode="numeric" pattern="[0-9]*" value={code} onChange={(e) => setCode(e.target.value)} required autoFocus className="mt-1 w-full px-3 py-2.5 bg-transparent border border-border font-mono text-[13px] text-ink focus:outline-none focus:border-ink transition-colors tracking-widest" />
            </label>
            <button type="submit" disabled={submitting} className="px-4 py-2 border border-ink bg-ink text-[#EAEAE5] font-mono text-[12px] uppercase tracking-wider hover:bg-[rgba(0,0,0,0.85)] transition-colors disabled:opacity-50">
              {submitting ? '…' : t('twoFactorSetup.enable')}
            </button>
          </form>
        </div>
      )}

      {step === 'recovery' && (
        <div className="border border-border p-6">
          <h2 className="font-sans text-base font-semibold text-ink mb-2">{t('twoFactorSetup.recoveryCodesTitle')}</h2>
          <p className="font-mono text-[12px] text-amber-800 bg-amber-50 border border-amber-300 px-3 py-2 mb-4">{t('twoFactorSetup.recoveryCodesNotice')}</p>
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-2 font-mono text-[13px] text-ink mb-4 select-all">
            {recovery.map((c) => (
              <li key={c} className="px-3 py-2 border border-border bg-surface">{c}</li>
            ))}
          </ul>
          <button type="button" onClick={() => setStep('done')} className="px-4 py-2 border border-ink bg-ink text-[#EAEAE5] font-mono text-[12px] uppercase tracking-wider hover:bg-[rgba(0,0,0,0.85)] transition-colors">
            {t('twoFactorSetup.finish')}
          </button>
        </div>
      )}

      {step === 'done' && (
        <div className="border border-border p-6 font-mono text-[12px] text-ink">
          {t('common.saved')}
        </div>
      )}
    </div>
  );
}
// Reference unused server type to keep import meaningful in future iterations.
export type _OkResponse = OkResponse;
