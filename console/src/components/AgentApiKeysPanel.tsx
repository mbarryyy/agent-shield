'use client';

import { useMemo, useState } from 'react';
import { api } from '@/lib/api';
import { formatTimestamp } from '@/lib/hooks';
import { useApiKeys } from '@/lib/hooks';
import type { ApiKeyView } from '@/types/auth';

function appliesToAgent(key: ApiKeyView, agentId: string): boolean {
  if (key.agent_id === agentId) return true;
  if (key.agent_id_allowlist?.includes(agentId)) return true;
  return key.agent_id == null && key.agent_id_allowlist == null;
}

function scopeLabel(key: ApiKeyView): string {
  if (key.agent_id) return `single agent: ${key.agent_id}`;
  if (key.agent_id_allowlist?.length) return `allowlist: ${key.agent_id_allowlist.join(', ')}`;
  return 'org-wide';
}

function statusLabel(key: ApiKeyView): 'active' | 'revoked' | 'expired' {
  if (key.revoked_at != null) return 'revoked';
  if (key.expires_at != null && key.expires_at < Date.now()) return 'expired';
  return 'active';
}

export default function AgentApiKeysPanel({ agentId }: { agentId: string }) {
  const { data, error, isLoading, mutate } = useApiKeys();
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);

  const rows = useMemo(
    () => (data?.api_keys ?? []).filter((key) => appliesToAgent(key, agentId)),
    [agentId, data],
  );

  async function handleRevoke(apiKeyId: string) {
    setRevokingId(apiKeyId);
    setRevokeError(null);
    try {
      await api.auth.apiKeys.revoke(apiKeyId);
      await mutate();
    } catch (err) {
      setRevokeError(err instanceof Error ? err.message : 'Failed to revoke API token.');
    } finally {
      setRevokingId(null);
    }
  }

  if (error) {
    return (
      <div className="border border-amber-300 bg-amber-50 p-4">
        <div className="font-mono text-[11px] uppercase tracking-wider text-amber-800">
          API tokens unavailable
        </div>
        <p className="mt-2 font-mono text-[12px] text-amber-900">
          Module B enterprise auth API required for /v1/auth/api-keys. The
          deprecated /v1/auth/token shim is intentionally not used here.
        </p>
        <p className="mt-1 font-mono text-[11px] text-amber-800">
          {error instanceof Error ? error.message : 'API key routes are unavailable.'}
        </p>
      </div>
    );
  }

  return (
    <div className="border border-border">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="section-label">SDK API tokens</div>
          <p className="mt-1 font-mono text-[11px] text-ink-dim">
            Real /v1/auth/api-keys list and revoke path. Raw tokens are shown only when issued.
          </p>
        </div>
        {isLoading && (
          <span className="font-mono text-[11px] uppercase tracking-wider text-ink-dim">
            Loading...
          </span>
        )}
      </div>

      {revokeError && (
        <div className="mx-4 mt-4 px-4 py-3 border border-red-300 bg-red-50 font-mono text-[12px] text-red-700">
          {revokeError}
        </div>
      )}

      {rows.length === 0 ? (
        <div className="px-4 py-8 text-center font-mono text-[12px] text-ink-dim">
          No SDK API tokens scoped to this agent.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] border-collapse">
            <thead>
              <tr className="border-b border-border bg-surface">
                {['Token', 'Scope', 'Status', 'Expires', 'Last used', ''].map((label) => (
                  <th key={label} className="table-header text-left px-4 py-3">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((key) => {
                const status = statusLabel(key);
                return (
                  <tr key={key.api_key_id} className="border-b border-border last:border-b-0">
                    <td className="px-4 py-3">
                      <div className="font-mono text-[13px] text-ink">
                        {key.display_name || key.api_key_id}
                      </div>
                      <div className="font-mono text-[11px] text-ink-dim">
                        {key.prefix}... · {key.api_key_id}
                      </div>
                    </td>
                    <td className="px-4 py-3 font-mono text-[12px] text-ink-dim">
                      {scopeLabel(key)}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`font-mono text-[11px] uppercase tracking-wider ${
                          status === 'active'
                            ? 'text-ink'
                            : status === 'expired'
                              ? 'text-amber-700'
                              : 'text-red-700'
                        }`}
                      >
                        {status}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-[12px] text-ink-dim">
                      {key.expires_at ? formatTimestamp(key.expires_at) : 'Never'}
                    </td>
                    <td className="px-4 py-3 font-mono text-[12px] text-ink-dim">
                      {key.last_used_at ? formatTimestamp(key.last_used_at) : '-'}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {status === 'active' && (
                        <button
                          type="button"
                          aria-label={`Revoke API token ${key.api_key_id}`}
                          className="btn-ghost text-[10px] py-1 px-3 text-red-700"
                          onClick={() => { void handleRevoke(key.api_key_id); }}
                          disabled={revokingId === key.api_key_id}
                        >
                          {revokingId === key.api_key_id ? 'Revoking...' : 'Revoke'}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
