'use client';

import type { VerifyOperationResponse } from '@elydora/shared';
import { useTranslation } from 'react-i18next';

interface VerificationChecklistProps {
  result: VerifyOperationResponse | null;
  isLoading: boolean;
  onVerify: () => void;
}

interface CheckItemProps {
  label: string;
  description: string;
  passed: boolean | undefined;
  pendingText: string;
  passedText: string;
  failedText: string;
}

function CheckItem({ label, description, passed, pendingText, passedText, failedText }: CheckItemProps) {
  return (
    <div className="flex items-start gap-3 py-3 border-b border-border last:border-b-0">
      <div className="mt-0.5 shrink-0">
        {passed === undefined ? (
          <div className="w-5 h-5 border border-border rounded-full" />
        ) : passed ? (
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="check-pass">
            <circle cx="10" cy="10" r="9" stroke="currentColor" strokeWidth="1.5" />
            <path d="M6 10l3 3 5-6" stroke="currentColor" strokeWidth="1.5" fill="none" />
          </svg>
        ) : (
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" className="check-fail">
            <circle cx="10" cy="10" r="9" stroke="currentColor" strokeWidth="1.5" />
            <path d="M7 7l6 6M13 7l-6 6" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        )}
      </div>
      <div className="flex-1">
        <div className="font-mono text-[12px] font-medium uppercase tracking-wider text-ink">
          {label}
        </div>
        <div className="font-sans text-[12px] text-ink-dim mt-0.5">
          {description}
        </div>
      </div>
      <div className="shrink-0">
        {passed === undefined ? (
          <span className="font-mono text-[11px] text-ink-dim uppercase">{pendingText}</span>
        ) : passed ? (
          <span className="font-mono text-[11px] text-green-600 uppercase">{passedText}</span>
        ) : (
          <span className="font-mono text-[11px] text-red-600 uppercase">{failedText}</span>
        )}
      </div>
    </div>
  );
}

export default function VerificationChecklist({
  result,
  isLoading,
  onVerify,
}: VerificationChecklistProps) {
  const { t } = useTranslation();
  const checks = result?.checks;

  return (
    <div className="border border-border bg-surface p-4 sm:p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="section-label">{t('verification.title')}</h3>
        <button
          onClick={onVerify}
          className="btn-brutalist text-[10px] py-1.5 px-4"
          disabled={isLoading}
        >
          {isLoading ? t('verification.verifying') : result ? t('verification.reVerify') : t('verification.verify')}
        </button>
      </div>

      {result && (
        <div className="mb-4 px-4 py-3 border font-mono text-[12px] flex items-center gap-2"
          style={{
            borderColor: result.valid ? '#16a34a' : '#dc2626',
            backgroundColor: result.valid ? 'rgba(22, 163, 74, 0.05)' : 'rgba(220, 38, 38, 0.05)',
            color: result.valid ? '#16a34a' : '#dc2626',
          }}
        >
          {result.valid ? (
            <>
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M2 7.5l3 3 7-7" />
              </svg>
              {t('verification.verifiedSuccess')}
            </>
          ) : (
            <>
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M1 1l12 12M13 1L1 13" />
              </svg>
              {t('verification.verificationFailed')}
            </>
          )}
        </div>
      )}

      <div>
        <CheckItem
          label={t('verification.signature')}
          description={t('verification.signatureDesc')}
          passed={checks?.signature}
          pendingText={t('verification.pending')}
          passedText={t('verification.passed')}
          failedText={t('verification.failed')}
        />
        <CheckItem
          label={t('verification.chainCheck')}
          description={t('verification.chainCheckDesc')}
          passed={checks?.chain}
          pendingText={t('verification.pending')}
          passedText={t('verification.passed')}
          failedText={t('verification.failed')}
        />
        <CheckItem
          label={t('verification.receiptCheck')}
          description={t('verification.receiptCheckDesc')}
          passed={checks?.receipt}
          pendingText={t('verification.pending')}
          passedText={t('verification.passed')}
          failedText={t('verification.failed')}
        />
        <CheckItem
          label={t('verification.merkle')}
          description={t('verification.merkleDesc')}
          passed={checks?.merkle}
          pendingText={t('verification.pending')}
          passedText={t('verification.passed')}
          failedText={t('verification.failed')}
        />
      </div>

      {result?.errors && result.errors.length > 0 && (
        <div className="mt-4 pt-4 border-t border-border">
          <div className="section-label mb-2">{t('verification.errors')}</div>
          <ul className="space-y-1">
            {result.errors.map((err, i) => (
              <li key={i} className="font-mono text-[12px] text-red-600">
                {err}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
