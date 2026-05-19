'use client';

import CopyButton from '@/components/ui/CopyButton';
import { truncateHash } from '@/lib/hooks';
import { useTranslation } from 'react-i18next';

interface ChainBlock {
  label: string;
  hash: string;
  isCurrent?: boolean;
}

interface ChainVisualizationProps {
  prevHash: string;
  currentHash: string;
  operationId: string;
}

function Block({ label, hash, isCurrent }: ChainBlock) {
  return (
    <div
      className={`border ${
        isCurrent ? 'border-ink bg-white' : 'border-border bg-surface'
      } p-3 sm:p-4 min-w-[140px] sm:min-w-[180px] shrink-0`}
    >
      <div className="section-label mb-2 truncate">{label}</div>
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-[11px] sm:text-[12px] text-ink">
          {truncateHash(hash, 8)}
        </span>
        <CopyButton text={hash} />
      </div>
    </div>
  );
}

function Arrow() {
  return (
    <div className="flex items-center px-1 sm:px-2 shrink-0">
      <svg width="24" height="12" viewBox="0 0 24 12" fill="none" className="text-ink-dim sm:w-8">
        <path d="M0 6h20M16 1l5 5-5 5" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    </div>
  );
}

export default function ChainVisualization({
  prevHash,
  currentHash,
  operationId,
}: ChainVisualizationProps) {
  const { t } = useTranslation();

  return (
    <div className="border border-border bg-surface p-4 sm:p-6 overflow-hidden">
      <h3 className="section-label mb-4">{t('chain.title')}</h3>

      <div className="flex items-center overflow-x-auto pb-2 -mx-1 px-1">
        <Block label={t('chain.previous')} hash={prevHash} />
        <Arrow />
        <Block label={t('chain.current', { id: truncateHash(operationId, 6) })} hash={currentHash} isCurrent />
        <Arrow />
        <div className="border border-border border-dashed p-3 sm:p-4 min-w-[140px] sm:min-w-[180px] bg-surface shrink-0">
          <div className="section-label mb-2">{t('chain.next')}</div>
          <span className="font-mono text-[12px] text-ink-dim italic">
            {t('chain.pending')}
          </span>
        </div>
      </div>

      <div className="mt-4 pt-4 border-t border-border">
        <div className="flex items-center gap-4 sm:gap-6 text-[11px] font-mono text-ink-dim flex-wrap">
          <span className="flex items-center gap-2">
            <span className="w-3 h-3 border border-border bg-surface inline-block" />
            {t('chain.chainBlock')}
          </span>
          <span className="flex items-center gap-2">
            <span className="w-3 h-3 border border-ink bg-white inline-block" />
            {t('chain.currentOperation')}
          </span>
          <span className="flex items-center gap-2">
            <span className="w-3 h-3 border border-dashed border-border bg-surface inline-block" />
            {t('chain.pending')}
          </span>
        </div>
      </div>
    </div>
  );
}
