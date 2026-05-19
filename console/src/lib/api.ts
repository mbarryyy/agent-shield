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
} from '@elydora/shared';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8787';

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
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> ?? {}),
  };

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    credentials: 'include',
  });

  if (!response.ok) {
    // On 401, redirect to login (session expired or not authenticated)
    if (response.status === 401 && typeof window !== 'undefined') {
      window.location.href = '/login';
      return undefined as T;
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
} as const;

export { ApiError };
export type { ErrorResponse };
