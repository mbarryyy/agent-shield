'use client';

import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import PageHeader from '@/components/ui/PageHeader';

export default function GovernanceRunShell() {
  const { t } = useTranslation();
  const [runId, setRunId] = useState('');
  useEffect(() => {
    // Path: /governance/runs/<run_id>  ->  split('/') index 3
    setRunId(window.location.pathname.split('/')[3] ?? '');
  }, []);
  if (!runId) return null;

  return (
    <div className="fade-in">
      <PageHeader
        title={`${t('governance.runTitle')} ${runId}`}
        subtitle={t('governance.runSubtitle')}
        breadcrumbs={[
          { label: t('common.dashboard'), href: '/' },
          { label: t('governance.title'), href: '/governance' },
          { label: runId },
        ]}
      />

      <div className="border border-border px-4 py-12 text-center font-mono text-[12px] text-ink-dim">
        {t('governance.runStub')}
      </div>
    </div>
  );
}
