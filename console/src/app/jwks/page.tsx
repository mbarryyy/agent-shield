'use client';

import { useJWKS } from '@/lib/hooks';
import { useTranslation } from 'react-i18next';
import PageHeader from '@/components/ui/PageHeader';
import CopyButton from '@/components/ui/CopyButton';
import DataTable from '@/components/ui/DataTable';
import type { Column } from '@/components/ui/DataTable';
import type { JWK } from '@elydora/shared';

interface JWKRow extends JWK {
  [key: string]: unknown;
}

export default function JWKSPage() {
  const { t } = useTranslation();
  const { data: jwksData, isLoading: jwksLoading, error: jwksError } = useJWKS();
  const keys = (jwksData?.keys ?? []) as JWKRow[];

  const jwkColumns: Column<JWKRow>[] = [
    {
      key: 'kid',
      label: t('jwks.colKeyId'),
      render: (row) => (
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-[13px] text-ink font-medium">{row.kid}</span>
          <CopyButton text={row.kid} />
        </div>
      ),
    },
    {
      key: 'kty',
      label: t('jwks.colKeyType'),
      width: '100px',
      render: (row) => (
        <span className="font-mono text-[11px] uppercase tracking-wider px-2 py-1 bg-surface border border-border">
          {row.kty}
        </span>
      ),
    },
    {
      key: 'alg',
      label: t('jwks.colAlgorithm'),
      width: '120px',
      render: (row) => (
        <span className="font-mono text-[13px] text-ink">{row.alg}</span>
      ),
    },
    {
      key: 'crv',
      label: t('jwks.colCurve'),
      width: '100px',
      render: (row) => (
        <span className="font-mono text-[13px] text-ink-dim">{row.crv ?? '\u2014'}</span>
      ),
    },
    {
      key: 'use',
      label: t('jwks.colUse'),
      width: '80px',
      render: (row) => (
        <span className="font-mono text-[11px] text-ink-dim uppercase">{row.use}</span>
      ),
    },
    {
      key: 'x',
      label: t('jwks.colPublicKey'),
      render: (row) =>
        row.x ? (
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-[11px] text-ink-dim">
              {row.x.slice(0, 20)}...
            </span>
            <CopyButton text={row.x} />
          </div>
        ) : (
          <span className="font-mono text-[11px] text-ink-dim">{'\u2014'}</span>
        ),
    },
  ];

  return (
    <div className="fade-in">
      <PageHeader
        title={t('jwks.title')}
        subtitle={t('jwks.subtitle')}
        breadcrumbs={[
          { label: t('common.dashboard'), href: '/' },
          { label: t('jwks.title') },
        ]}
      />

      <div className="mb-8">
        <div className="flex items-center justify-between mb-3">
          <div className="section-label">{t('jwks.publicKeys')}</div>
          {jwksData && (
            <CopyButton
              text={JSON.stringify(jwksData, null, 2)}
              label={t('common.copyJwks')}
              className="text-[11px]"
            />
          )}
        </div>

        {jwksError && (
          <div className="mb-4 px-4 py-3 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">
            {t('jwks.failedToLoad')} {jwksError instanceof Error ? jwksError.message : t('common.unknownError')}
          </div>
        )}

        <DataTable
          columns={jwkColumns}
          data={keys}
          keyExtractor={(row) => row.kid}
          isLoading={jwksLoading}
          emptyMessage={t('jwks.emptyMessage')}
        />

        <div className="mt-3 font-mono text-[11px] text-ink-dim">
          {t('jwks.endpoint')} <span className="text-ink">/.well-known/elydora/jwks.json</span>
        </div>
      </div>
    </div>
  );
}
