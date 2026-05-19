'use client';

import { useEpoch, formatTimestamp, truncateHash } from '@/lib/hooks';
import PageHeader from '@/components/ui/PageHeader';
import CopyButton from '@/components/ui/CopyButton';
import Link from 'next/link';
import { useTranslation } from 'react-i18next';

export default function EpochDetailClient({ epochId }: { epochId: string }) {
  const { t } = useTranslation();

  const { data, isLoading, error } = useEpoch(epochId);
  const epoch = data?.epoch;
  const anchor = data?.anchor;

  if (isLoading) {
    return (
      <div className="fade-in">
        <PageHeader
          title={t('epochDetail.title')}
          breadcrumbs={[
            { label: t('common.dashboard'), href: '/' },
            { label: t('common.epochs'), href: '/epochs' },
            { label: epochId.slice(0, 16) + '...' },
          ]}
        />
        <div className="border border-border bg-surface p-4 sm:p-6">
          <div className="space-y-3">
            <div className="skeleton h-6 w-64" />
            <div className="skeleton h-4 w-full" />
            <div className="skeleton h-4 w-3/4" />
          </div>
        </div>
      </div>
    );
  }

  if (error || !epoch) {
    return (
      <div className="fade-in">
        <PageHeader
          title={t('epochDetail.title')}
          breadcrumbs={[
            { label: t('common.dashboard'), href: '/' },
            { label: t('common.epochs'), href: '/epochs' },
            { label: epochId.slice(0, 16) + '...' },
          ]}
        />
        <div className="px-4 py-3 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">
          {t('epochDetail.failedToLoad')} {error instanceof Error ? error.message : t('epochDetail.mayNotExist')}
        </div>
      </div>
    );
  }

  const durationMs = epoch.end_time - epoch.start_time;
  const durationMinutes = Math.round(durationMs / 60000);

  return (
    <div className="fade-in">
      <PageHeader
        title={t('epochDetail.title')}
        subtitle={epoch.epoch_id}
        breadcrumbs={[
          { label: t('common.dashboard'), href: '/' },
          { label: t('common.epochs'), href: '/epochs' },
          { label: epoch.epoch_id.slice(0, 16) + '...' },
        ]}
        actions={
          <Link
            href={`/audit?start_time=${new Date(epoch.start_time).toISOString().slice(0, 16)}&end_time=${new Date(epoch.end_time).toISOString().slice(0, 16)}`}
            className="btn-ghost inline-block no-underline"
          >
            {t('epochDetail.viewOperations')}
          </Link>
        }
      />

      <div className="space-y-6">
        {/* Epoch Metadata */}
        <div className="border border-border bg-surface p-4 sm:p-6 relative">
          <span className="crosshair ch-tl" />
          <span className="crosshair ch-tr" />
          <span className="crosshair ch-bl" />
          <span className="crosshair ch-br" />

          <h3 className="section-label mb-4">{t('epochDetail.epochMetadata')}</h3>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <div className="section-label mb-1">{t('epochDetail.epochId')}</div>
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-[13px] text-ink break-all">{epoch.epoch_id}</span>
                <CopyButton text={epoch.epoch_id} />
              </div>
            </div>

            <div>
              <div className="section-label mb-1">{t('epochDetail.organization')}</div>
              <span className="font-mono text-[13px] text-ink">{epoch.org_id}</span>
            </div>

            <div>
              <div className="section-label mb-1">{t('epochDetail.startTime')}</div>
              <span className="font-mono text-[12px] text-ink">
                {formatTimestamp(epoch.start_time)}
              </span>
            </div>

            <div>
              <div className="section-label mb-1">{t('epochDetail.endTime')}</div>
              <span className="font-mono text-[12px] text-ink">
                {formatTimestamp(epoch.end_time)}
              </span>
            </div>

            <div>
              <div className="section-label mb-1">{t('epochDetail.duration')}</div>
              <span className="font-mono text-[13px] text-ink">
                {t('epochDetail.durationMinutes', { count: durationMinutes })}
              </span>
            </div>

            <div>
              <div className="section-label mb-1">{t('epochDetail.createdAt')}</div>
              <span className="font-mono text-[12px] text-ink-dim">
                {formatTimestamp(epoch.created_at)}
              </span>
            </div>
          </div>
        </div>

        {/* Merkle Root */}
        <div className="border border-border bg-surface p-4 sm:p-6">
          <h3 className="section-label mb-4">{t('epochDetail.merkleTree')}</h3>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <div className="section-label mb-1">{t('epochDetail.rootHash')}</div>
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-[13px] text-ink break-all">
                  {epoch.root_hash}
                </span>
                <CopyButton text={epoch.root_hash} className="shrink-0" />
              </div>
            </div>

            <div>
              <div className="section-label mb-1">{t('epochDetail.leafCount')}</div>
              <span className="font-sans text-2xl font-semibold text-ink">
                {epoch.leaf_count}
              </span>
              <span className="font-mono text-[11px] text-ink-dim ml-2">
                {t('epochDetail.operationsUnit')}
              </span>
            </div>
          </div>
        </div>

        {/* TSA Anchor */}
        <div className="border border-border bg-surface p-4 sm:p-6">
          <h3 className="section-label mb-4">{t('epochDetail.tsaAnchor')}</h3>

          {anchor?.tsa_token ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="md:col-span-2">
                <div className="section-label mb-1">{t('epochDetail.tsaToken')}</div>
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-[12px] text-ink break-all">
                    {truncateHash(anchor.tsa_token, 20)}
                  </span>
                  <CopyButton text={anchor.tsa_token} className="shrink-0" />
                </div>
              </div>

              {anchor.tsa_url && (
                <div>
                  <div className="section-label mb-1">{t('epochDetail.tsaUrl')}</div>
                  <span className="font-mono text-[12px] text-ink">
                    {anchor.tsa_url}
                  </span>
                </div>
              )}

              {anchor.anchored_at && (
                <div>
                  <div className="section-label mb-1">{t('epochDetail.anchoredAt')}</div>
                  <span className="font-mono text-[12px] text-ink">
                    {formatTimestamp(anchor.anchored_at)}
                  </span>
                </div>
              )}
            </div>
          ) : (
            <p className="font-mono text-sm text-ink-dim">
              {t('epochDetail.noTsaAnchor')}
            </p>
          )}
        </div>

        {/* R2 Storage */}
        <div className="border border-border bg-surface p-4 sm:p-6">
          <h3 className="section-label mb-4">{t('epochDetail.storage')}</h3>
          <div>
            <div className="section-label mb-1">{t('epochDetail.r2EpochKey')}</div>
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-[13px] text-ink break-all">
                {epoch.r2_epoch_key}
              </span>
              <CopyButton text={epoch.r2_epoch_key} className="shrink-0" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
