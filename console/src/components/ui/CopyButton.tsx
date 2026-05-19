'use client';

import { useClipboard } from '@/lib/hooks';
import { useTranslation } from 'react-i18next';

interface CopyButtonProps {
  text: string;
  label?: string;
  className?: string;
}

export default function CopyButton({ text, label, className = '' }: CopyButtonProps) {
  const { copied, copy } = useClipboard();
  const { t } = useTranslation();

  return (
    <button
      onClick={() => copy(text)}
      className={`inline-flex items-center gap-1.5 font-mono text-[12px] text-ink-dim hover:text-ink transition-colors ${className}`}
      title={t('common.copyToClipboard')}
    >
      {label && <span>{label}</span>}
      {copied ? (
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-green-600">
          <path d="M2 7.5l3 3 7-7" />
        </svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
          <rect x="4" y="4" width="9" height="9" rx="1" />
          <path d="M10 4V2a1 1 0 00-1-1H2a1 1 0 00-1 1v7a1 1 0 001 1h2" />
        </svg>
      )}
    </button>
  );
}
