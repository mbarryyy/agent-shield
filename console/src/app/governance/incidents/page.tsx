'use client';

import { useTranslation } from 'react-i18next';
import PageHeader from '@/components/ui/PageHeader';

export default function GovernanceIncidentsPage() {
  const { t } = useTranslation();

  return (
    <div className="fade-in">
      <PageHeader
        title={t('governance.incidentsTitle')}
        subtitle={t('governance.incidentsSubtitle')}
        breadcrumbs={[
          { label: t('common.dashboard'), href: '/' },
          { label: t('governance.title'), href: '/governance' },
          { label: t('governance.incidentsTitle') },
        ]}
      />

      <div className="border border-border px-4 py-12 text-center font-mono text-[12px] text-ink-dim">
        {t('governance.incidentsEmpty')}
      </div>
    </div>
  );
}
