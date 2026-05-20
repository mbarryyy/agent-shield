import type {
  Agent,
  RegisterAgentRequest,
  RegisterAgentResponse,
  GetAgentResponse,
  ListAgentsResponse,
  FreezeAgentRequest,
  UnfreezeAgentRequest,
  RevokeAgentRequest,
  UpdateAgentRequest,
  SubmitOperationRequest,
  SubmitOperationResponse,
  GetOperationResponse,
  VerifyOperationResponse,
  AuditQueryRequest,
  AuditQueryResponse,
  GetEpochResponse,
  CreateExportRequest,
  CreateExportResponse,
  GetExportResponse,
  IssueTokenResponse,
  JWKSResponse,
  ErrorResponse,
  ShieldActionRecord,
  GovernanceVerdict,
} from '@elydora/shared';
import type {
  TimelinePage,
  VerdictDetail,
  ProvenanceGraph,
  CostRollup,
  IncidentList,
  ShieldVerdictEvent,
  DashboardKpi,
} from '@/types/governance';
import { getCsrfToken } from '@/lib/auth-client';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8787';

/** Browser-side global event for session expiry — consumed by the
 *  SessionExpiredModal mounted in AppShell. Preserves in-flight UI state
 *  (no hard redirect; the modal owns the redirect on user click). */
export const SESSION_EXPIRED_EVENT = 'shield:session-expired';

class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    public readonly requestId: string,
    message: string,
    public readonly details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const method = (options.method ?? 'GET').toUpperCase();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> ?? {}),
  };
  // §A10: echo CSRF token on state-changing requests. Token is read from
  // GET /v1/auth/session JSON body by the auth-client (NEVER cookie).
  if (method !== 'GET' && method !== 'HEAD') {
    const t = getCsrfToken();
    if (t && !headers['X-CSRF-Token']) headers['X-CSRF-Token'] = t;
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    credentials: 'include',
  });

  if (!response.ok) {
    // On 401 dispatch a global session-expired event; the SessionExpiredModal
    // (mounted in AppShell) owns the redirect — preserves in-flight UI state.
    if (response.status === 401 && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));
    }

    let errorBody: ErrorResponse | null = null;
    try {
      errorBody = await response.json() as ErrorResponse;
    } catch {
      // Response body is not JSON
    }

    if (errorBody?.error) {
      throw new ApiError(
        response.status,
        errorBody.error.code,
        errorBody.error.request_id,
        errorBody.error.message,
        errorBody.error.details,
      );
    }

    throw new ApiError(
      response.status,
      'INTERNAL_ERROR',
      'unknown',
      `Request failed with status ${response.status}`,
    );
  }

  return response.json() as Promise<T>;
}

export const api = {
  agents: {
    list(): Promise<ListAgentsResponse> {
      return request<ListAgentsResponse>('/v1/agents');
    },

    register(body: RegisterAgentRequest): Promise<RegisterAgentResponse> {
      return request<RegisterAgentResponse>('/v1/agents/register', {
        method: 'POST',
        body: JSON.stringify(body),
      });
    },

    get(agentId: string): Promise<GetAgentResponse> {
      return request<GetAgentResponse>(`/v1/agents/${encodeURIComponent(agentId)}`);
    },

    update(agentId: string, body: UpdateAgentRequest): Promise<{ agent: Agent }> {
      return request<{ agent: Agent }>(`/v1/agents/${encodeURIComponent(agentId)}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      });
    },

    freeze(agentId: string, reason: string): Promise<void> {
      const body: FreezeAgentRequest = { reason };
      return request<void>(`/v1/agents/${encodeURIComponent(agentId)}/freeze`, {
        method: 'POST',
        body: JSON.stringify(body),
      });
    },

    unfreeze(agentId: string, reason: string): Promise<void> {
      const body: UnfreezeAgentRequest = { reason };
      return request<void>(`/v1/agents/${encodeURIComponent(agentId)}/unfreeze`, {
        method: 'POST',
        body: JSON.stringify(body),
      });
    },

    revokeKey(agentId: string, kid: string, reason: string): Promise<void> {
      const body: RevokeAgentRequest = { kid, reason };
      return request<void>(`/v1/agents/${encodeURIComponent(agentId)}/revoke`, {
        method: 'POST',
        body: JSON.stringify(body),
      });
    },

    delete(agentId: string): Promise<void> {
      return request<void>(`/v1/agents/${encodeURIComponent(agentId)}`, {
        method: 'DELETE',
      });
    },
  },

  operations: {
    submit(eor: SubmitOperationRequest): Promise<SubmitOperationResponse> {
      return request<SubmitOperationResponse>('/v1/operations', {
        method: 'POST',
        body: JSON.stringify(eor),
      });
    },

    get(operationId: string): Promise<GetOperationResponse> {
      return request<GetOperationResponse>(
        `/v1/operations/${encodeURIComponent(operationId)}`,
      );
    },

    verify(operationId: string): Promise<VerifyOperationResponse> {
      return request<VerifyOperationResponse>(
        `/v1/operations/${encodeURIComponent(operationId)}/verify`,
        { method: 'POST' },
      );
    },
  },

  audit: {
    query(params: AuditQueryRequest): Promise<AuditQueryResponse> {
      return request<AuditQueryResponse>(`/v1/audit/query`, {
        method: 'POST',
        body: JSON.stringify(params),
      });
    },
  },

  epochs: {
    list(): Promise<{ epochs: Array<{ epoch_id: string; org_id: string; start_time: number; end_time: number; root_hash: string; leaf_count: number; r2_epoch_key: string; created_at: number }> }> {
      return request(`/v1/epochs`);
    },

    get(epochId: string): Promise<GetEpochResponse> {
      return request<GetEpochResponse>(`/v1/epochs/${encodeURIComponent(epochId)}`);
    },
  },

  exports: {
    create(body: CreateExportRequest): Promise<CreateExportResponse> {
      return request<CreateExportResponse>('/v1/exports', {
        method: 'POST',
        body: JSON.stringify(body),
      });
    },

    get(exportId: string): Promise<GetExportResponse> {
      return request<GetExportResponse>(`/v1/exports/${encodeURIComponent(exportId)}`);
    },

    list(): Promise<{ exports: Array<import('@elydora/shared').Export> }> {
      return request(`/v1/exports`);
    },

    async download(exportId: string): Promise<Blob> {
      const response = await fetch(
        `${API_BASE_URL}/v1/exports/${encodeURIComponent(exportId)}/download`,
        {
          credentials: 'include',
        },
      );
      if (!response.ok) {
        throw new ApiError(response.status, 'DOWNLOAD_ERROR', 'unknown', `Download failed with status ${response.status}`);
      }
      return response.blob();
    },
  },

  jwks: {
    get(): Promise<JWKSResponse> {
      return request<JWKSResponse>('/.well-known/elydora/jwks.json');
    },
  },

  auth: {
    issueToken(ttlSeconds: number | null): Promise<IssueTokenResponse> {
      return request<IssueTokenResponse>('/v1/auth/token', {
        method: 'POST',
        body: JSON.stringify({ ttl_seconds: ttlSeconds }),
      });
    },
  },

  // §4 governance surface (SDK §4.3 / ADR-0004). W2 = server STUB:
  // `decide` (Channel-1 sync gate) returns a stub-PASS GovernanceVerdict;
  // `record` (post_exec) is async, chain-linked, returns no verdict. The
  // governance READ surface (per-run cost rollup, verdict stream for the
  // live monitor / provenance DAG / KPI cards) is wired in W3 (G3).
  governance: {
    /** Channel-1 sync gate: pre_exec ShieldActionRecord -> signed GovernanceVerdict (one round-trip). */
    decide(rec: ShieldActionRecord): Promise<GovernanceVerdict> {
      return request<GovernanceVerdict>('/v1/governance/decide', {
        method: 'POST',
        body: JSON.stringify(rec),
      });
    },

    /** Channel-2 async post_exec ingest: chain-linked, no verdict returned. */
    record(rec: ShieldActionRecord): Promise<void> {
      return request<void>('/v1/governance/record', {
        method: 'POST',
        body: JSON.stringify(rec),
      });
    },

    // --- W3 console READ contract (server PR-S2; additive /v1/governance/*,
    //     console-pact; paths/shapes verified §5b vs shield-server routes). ---

    /** U2 live-monitor feed — keyset-paginated, org-scoped. */
    timeline(
      runId: string,
      params: { cursor?: string; limit?: number } = {},
    ): Promise<TimelinePage> {
      const q = new URLSearchParams();
      if (params.cursor) q.set('cursor', params.cursor);
      if (params.limit != null) q.set('limit', String(params.limit));
      const qs = q.toString();
      return request<TimelinePage>(
        `/v1/governance/runs/${encodeURIComponent(runId)}/timeline${qs ? `?${qs}` : ''}`,
      );
    },

    /** U3 verdict tab — signed §4 verdict + paired pre↔post (404 if unknown). */
    verdict(correlationId: string): Promise<VerdictDetail> {
      return request<VerdictDetail>(
        `/v1/governance/verdicts/${encodeURIComponent(correlationId)}`,
      );
    },

    /** U4 provenance DAG data (console renders; BLOCK = blocked-intent node). */
    provenance(runId: string): Promise<ProvenanceGraph> {
      return request<ProvenanceGraph>(
        `/v1/governance/runs/${encodeURIComponent(runId)}/provenance`,
      );
    },

    /** U5 hook#5 cost rollup — server-authoritative; console renders verbatim. */
    cost(runId: string): Promise<CostRollup> {
      return request<CostRollup>(
        `/v1/governance/runs/${encodeURIComponent(runId)}/cost`,
      );
    },

    /** Task #31.b — org-wide Dashboard KPI rollup; server NEVER recomputes
     *  `prevented_loss_total` (the figure is Σ obligations.prevented_loss
     *  over signed verdicts, MEASURED env-diff). Console renders verbatim. */
    dashboardKpi(): Promise<DashboardKpi> {
      return request<DashboardKpi>('/v1/governance/dashboard/kpi');
    },

    /** U6 incidents list — ESCALATE-only; server-authoritative HITL state. */
    incidents(
      params: { run_id?: string; status?: string; cursor?: string; limit?: number } = {},
    ): Promise<IncidentList> {
      const q = new URLSearchParams();
      if (params.run_id) q.set('run_id', params.run_id);
      if (params.status) q.set('status', params.status);
      if (params.cursor) q.set('cursor', params.cursor);
      if (params.limit != null) q.set('limit', String(params.limit));
      const qs = q.toString();
      return request<IncidentList>(
        `/v1/governance/incidents${qs ? `?${qs}` : ''}`,
      );
    },

    /** U6 HITL — re-enter a paused ESCALATE; server signs the post-resume
     *  verdict & owns the resulting status (the one console WRITE). */
    resume(
      incidentId: string,
      body: { decision: string; payload?: Record<string, unknown> },
    ): Promise<GovernanceVerdict> {
      return request<GovernanceVerdict>(
        `/v1/governance/incidents/${encodeURIComponent(incidentId)}/resume`,
        { method: 'POST', body: JSON.stringify(body) },
      );
    },
  },
} as const;

/**
 * SSE-PRIMARY live governance stream (server bridges Redis Channel-2 →
 * browser; a browser cannot read Redis). `event: verdict` carries the
 * LOCKED FLAT 8-string shield:verdicts envelope; `event: action` the
 * action-record fields. SWR polling of /timeline is the deterministic
 * pre-recorded-demo fallback (caller's choice), not a replacement.
 * Returns an unsubscribe; no-op (returns a noop closer) outside the
 * browser so SSR/build never touches EventSource.
 */
export function openGovernanceStream(
  workflowId: string,
  handlers: {
    onVerdict?: (ev: ShieldVerdictEvent) => void;
    onAction?: (fields: Record<string, string>) => void;
    onError?: (err: unknown) => void;
  },
): () => void {
  if (typeof window === 'undefined' || typeof EventSource === 'undefined') {
    return () => {};
  }
  const url = `${API_BASE_URL}/v1/governance/stream?workflow_id=${encodeURIComponent(workflowId)}`;
  const es = new EventSource(url, { withCredentials: true });
  es.addEventListener('verdict', (e: MessageEvent) => {
    try {
      handlers.onVerdict?.(JSON.parse(e.data as string) as ShieldVerdictEvent);
    } catch (err) {
      handlers.onError?.(err);
    }
  });
  es.addEventListener('action', (e: MessageEvent) => {
    try {
      handlers.onAction?.(JSON.parse(e.data as string) as Record<string, string>);
    } catch (err) {
      handlers.onError?.(err);
    }
  });
  es.onerror = (err) => handlers.onError?.(err);
  return () => es.close();
}

export { ApiError };
export type { ErrorResponse };
