'use client';

import { useState } from 'react';
import CopyButton from '@/components/ui/CopyButton';
import { formatTimestamp, truncateHash } from '@/lib/hooks';
import type { Operation, Receipt } from '@elydora/shared';
import { useTranslation } from 'react-i18next';

interface OperationDetailCardProps {
  operation: Operation;
  receipt?: Receipt;
  payload?: Record<string, unknown>;
}

interface FieldRowProps {
  label: string;
  value: string | number | null | undefined;
  mono?: boolean;
  copyable?: boolean;
}

function FieldRow({ label, value, mono = true, copyable = false }: FieldRowProps) {
  const displayValue = value == null ? '\u2014' : String(value);

  return (
    <div className="flex flex-col sm:flex-row sm:items-start py-2.5 border-b border-border last:border-b-0 gap-1 sm:gap-0">
      <div className="sm:w-44 sm:shrink-0">
        <span className="section-label">{label}</span>
      </div>
      <div className="flex-1 flex items-center gap-2 min-w-0">
        <span
          className={`${mono ? 'font-mono text-[13px]' : 'font-sans text-sm'} text-ink break-all`}
        >
          {displayValue}
        </span>
        {copyable && value != null && (
          <CopyButton text={String(value)} className="shrink-0" />
        )}
      </div>
    </div>
  );
}

export default function OperationDetailCard({ operation, receipt, payload }: OperationDetailCardProps) {
  const [showRaw, setShowRaw] = useState(false);
  const { t } = useTranslation();

  return (
    <div className="space-y-6">
      {/* Operation record */}
      <div className="border border-border bg-surface p-4 sm:p-6 relative">
        <span className="crosshair ch-tl" />
        <span className="crosshair ch-tr" />
        <span className="crosshair ch-bl" />
        <span className="crosshair ch-br" />

        <div className="flex items-center justify-between mb-4">
          <h3 className="section-label">{t('operationCard.operationRecord')}</h3>
          <button
            onClick={() => setShowRaw(!showRaw)}
            className="btn-ghost text-[10px] py-1 px-3"
          >
            {showRaw ? t('operationCard.formatted') : t('operationCard.rawJson')}
          </button>
        </div>

        {showRaw ? (
          <div className="relative">
            <pre className="font-mono text-[12px] text-ink bg-bg p-4 border border-border overflow-x-auto">
              {JSON.stringify(operation, null, 2)}
            </pre>
            <div className="absolute top-2 right-2">
              <CopyButton text={JSON.stringify(operation, null, 2)} />
            </div>
          </div>
        ) : (
          <div>
            <FieldRow label={t('operationCard.operationId')} value={operation.operation_id} copyable />
            <FieldRow label={t('operationCard.agentId')} value={operation.agent_id} copyable />
            <FieldRow label={t('operationCard.orgId')} value={operation.org_id} copyable />
            <FieldRow label={t('operationCard.type')} value={operation.operation_type} />
            <FieldRow label={t('operationCard.issuedAt')} value={formatTimestamp(operation.issued_at)} mono={false} />
            <FieldRow label={t('operationCard.createdAt')} value={formatTimestamp(operation.created_at)} mono={false} />
            <FieldRow label={t('operationCard.ttlMs')} value={operation.ttl_ms} />
            <FieldRow label={t('operationCard.nonce')} value={operation.nonce} copyable />
            <FieldRow label={t('operationCard.seqNo')} value={operation.seq_no} />
            <FieldRow label={t('operationCard.signingKey')} value={operation.agent_pubkey_kid} copyable />
            <FieldRow label={t('operationCard.payloadHash')} value={truncateHash(operation.payload_hash, 12)} copyable />
            <FieldRow label={t('operationCard.prevChainHash')} value={truncateHash(operation.prev_chain_hash, 12)} copyable />
            <FieldRow label={t('operationCard.chainHash')} value={truncateHash(operation.chain_hash, 12)} copyable />
            <FieldRow label={t('operationCard.r2PayloadKey')} value={operation.r2_payload_key ?? '—'} copyable />
          </div>
        )}
      </div>

      {/* Payload — what the operation actually did */}
      {payload && (
        <div className="border border-border bg-surface p-4 sm:p-6 relative">
          <span className="crosshair ch-tl" />
          <span className="crosshair ch-tr" />
          <span className="crosshair ch-bl" />
          <span className="crosshair ch-br" />

          <div className="flex items-center justify-between mb-4">
            <h3 className="section-label">{t('operationCard.payload')}</h3>
            <div className="flex-1" />
            <CopyButton text={JSON.stringify(payload, null, 2)} />
          </div>
          {Object.entries(payload).map(([key, value]) => {
            if (value == null) return null;
            const isComplex = typeof value === 'object';
            if (isComplex) {
              return (
                <div key={key} className="py-2.5 border-b border-border last:border-b-0">
                  <div className="mb-1">
                    <span className="section-label">{key.replace(/_/g, ' ')}</span>
                  </div>
                  <pre className="font-mono text-[12px] text-ink bg-bg p-3 border border-border max-h-64 overflow-y-auto whitespace-pre-wrap break-all">
                    {JSON.stringify(value, null, 2)}
                  </pre>
                </div>
              );
            }
            return (
              <FieldRow key={key} label={key.replace(/_/g, ' ')} value={String(value)} copyable />
            );
          })}
        </div>
      )}

      {/* Receipt */}
      {receipt && (
        <div className="border border-border bg-surface p-4 sm:p-6">
          <h3 className="section-label mb-4">{t('operationCard.receipt')}</h3>
          <FieldRow label={t('operationCard.receiptId')} value={receipt.receipt_id} copyable />
          <FieldRow label={t('operationCard.operationId')} value={receipt.operation_id} copyable />
          <FieldRow label={t('operationCard.r2ReceiptKey')} value={receipt.r2_receipt_key} copyable />
          <FieldRow label={t('operationCard.createdAt')} value={formatTimestamp(receipt.created_at)} mono={false} />
        </div>
      )}
    </div>
  );
}
