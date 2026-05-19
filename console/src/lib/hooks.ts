'use client';

import useSWR from 'swr';
import { useEffect, useRef, useState, useCallback } from 'react';
import { api } from './api';
import type {
  AuditQueryRequest,
  GetAgentResponse,
  ListAgentsResponse,
  GetOperationResponse,
  GetEpochResponse,
  GetExportResponse,
  AuditQueryResponse,
  JWKSResponse,
} from '@elydora/shared';

export function useAgent(agentId: string | undefined) {
  return useSWR<GetAgentResponse>(
    agentId ? `/agents/${agentId}` : null,
    agentId ? () => api.agents.get(agentId) : null,
    { revalidateOnFocus: false },
  );
}

export function useAgentsList() {
  return useSWR<ListAgentsResponse>(
    '/agents',
    () => api.agents.list(),
    { revalidateOnFocus: false },
  );
}

export function useOperation(operationId: string | undefined) {
  return useSWR<GetOperationResponse>(
    operationId ? `/operations/${operationId}` : null,
    operationId ? () => api.operations.get(operationId) : null,
    { revalidateOnFocus: false },
  );
}

export function useAudit(params: AuditQueryRequest) {
  return useSWR<AuditQueryResponse>(
    ['/audit', params],
    () => api.audit.query(params),
    { revalidateOnFocus: false },
  );
}

export function useEpoch(epochId: string | undefined) {
  return useSWR<GetEpochResponse>(
    epochId ? `/epochs/${epochId}` : null,
    epochId ? () => api.epochs.get(epochId) : null,
    { revalidateOnFocus: false },
  );
}

export function useEpochs() {
  return useSWR<{ epochs: Array<{ epoch_id: string; org_id: string; start_time: number; end_time: number; root_hash: string; leaf_count: number; r2_epoch_key: string; created_at: number }> }>(
    '/epochs',
    () => api.epochs.list(),
    { revalidateOnFocus: false },
  );
}

export function useExport(exportId: string | undefined) {
  return useSWR<GetExportResponse>(
    exportId ? `/exports/${exportId}` : null,
    exportId ? () => api.exports.get(exportId) : null,
    {
      revalidateOnFocus: false,
      refreshInterval: (data) => {
        if (data?.export?.status === 'queued' || data?.export?.status === 'running') {
          return 3000;
        }
        return 0;
      },
    },
  );
}

export function useExports() {
  return useSWR<{ exports: Array<import('@elydora/shared').Export> }>(
    '/exports',
    () => api.exports.list(),
    { revalidateOnFocus: false },
  );
}

export function useJWKS() {
  return useSWR<JWKSResponse>(
    '/jwks',
    () => api.jwks.get(),
    { revalidateOnFocus: false },
  );
}

export function useFadeIn() {
  const ref = useRef<HTMLDivElement>(null);
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry?.isIntersecting) {
          setIsVisible(true);
          observer.unobserve(element);
        }
      },
      { threshold: 0.1 },
    );

    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return { ref, isVisible };
}

export function useClipboard() {
  const [copied, setCopied] = useState(false);

  const copy = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for older browsers
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, []);

  return { copied, copy };
}

export function formatTimestamp(ms: number): string {
  return new Date(ms).toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function formatRelativeTime(ms: number): string {
  const now = Date.now();
  const diff = now - ms;
  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days > 0) return `${days}d ago`;
  if (hours > 0) return `${hours}h ago`;
  if (minutes > 0) return `${minutes}m ago`;
  return `${seconds}s ago`;
}

export function truncateHash(hash: string, length = 8): string {
  if (hash.length <= length * 2) return hash;
  return `${hash.slice(0, length)}...${hash.slice(-length)}`;
}
