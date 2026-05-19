'use client';

import { useState, useCallback } from 'react';
import { useOperation } from '@/lib/hooks';
import { api } from '@/lib/api';
import PageHeader from '@/components/ui/PageHeader';
import OperationDetailCard from '@/components/OperationDetailCard';
import ChainVisualization from '@/components/ChainVisualization';
import VerificationChecklist from '@/components/VerificationChecklist';
import type { VerifyOperationResponse } from '@elydora/shared';
import { useTranslation } from 'react-i18next';

export default function OperationDetailClient({ operationId }: { operationId: string }) {
  const { t } = useTranslation();

  const { data, isLoading, error } = useOperation(operationId);
  const [verifyResult, setVerifyResult] = useState<VerifyOperationResponse | null>(null);
  const [verifying, setVerifying] = useState(false);

  const operation = data?.operation;
  const receipt = data?.receipt;
  const payload = data?.payload;

  const handleVerify = useCallback(async () => {
    setVerifying(true);
    try {
      const result = await api.operations.verify(operationId);
      setVerifyResult(result);
    } catch (err) {
      setVerifyResult({
        valid: false,
        checks: {
          signature: false,
          chain: false,
          receipt: false,
        },
        errors: [err instanceof Error ? err.message : 'Verification request failed.'],
      });
    } finally {
      setVerifying(false);
    }
  }, [operationId]);

  if (isLoading) {
    return (
      <div className="fade-in">
        <PageHeader
          title={t('operationDetail.title')}
          breadcrumbs={[
            { label: t('common.dashboard'), href: '/' },
            { label: t('common.operations'), href: '/operations' },
            { label: operationId.slice(0, 16) + '...' },
          ]}
        />
        <div className="space-y-4">
          <div className="border border-border bg-surface p-6">
            <div className="space-y-3">
              <div className="skeleton h-6 w-64" />
              <div className="skeleton h-4 w-full" />
              <div className="skeleton h-4 w-3/4" />
              <div className="skeleton h-4 w-1/2" />
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (error || !operation) {
    return (
      <div className="fade-in">
        <PageHeader
          title={t('operationDetail.title')}
          breadcrumbs={[
            { label: t('common.dashboard'), href: '/' },
            { label: t('common.operations'), href: '/operations' },
            { label: operationId.slice(0, 16) + '...' },
          ]}
        />
        <div className="px-4 py-3 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">
          {t('operationDetail.failedToLoad')} {error instanceof Error ? error.message : t('operationDetail.mayNotExist')}
        </div>
      </div>
    );
  }

  return (
    <div className="fade-in">
      <PageHeader
        title={t('operationDetail.title')}
        subtitle={operation.operation_id}
        breadcrumbs={[
          { label: t('common.dashboard'), href: '/' },
          { label: t('common.operations'), href: '/operations' },
          { label: operation.operation_id.slice(0, 16) + '...' },
        ]}
      />

      <div className="space-y-6">
        <OperationDetailCard operation={operation} receipt={receipt} payload={payload} />
        <ChainVisualization
          prevHash={operation.prev_chain_hash}
          currentHash={operation.chain_hash}
          operationId={operation.operation_id}
        />
        <VerificationChecklist
          result={verifyResult}
          isLoading={verifying}
          onVerify={handleVerify}
        />
      </div>
    </div>
  );
}
