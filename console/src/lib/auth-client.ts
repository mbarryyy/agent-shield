'use client';

// Thin facade replacing better-auth/react. Preserves the public API
// (signIn.email / signUp.email / signOut / useSession) verbatim so all
// consumers (login/register/AppShell/Sidebar/auth.tsx) compile unchanged.
// Internally calls our own /v1/auth/* per ADR-0013. CSRF transport
// (§A10): csrf_token is read from the GET /v1/auth/session JSON body only
// (NEVER cookies), echoed via X-CSRF-Token header on all state-changing
// requests. Sessions are HttpOnly secure cookies (credentials:'include').

import useSWR, { mutate as swrMutate } from 'swr';
import type {
  FacadeSessionEnvelope,
  SessionResponse,
  SignInRequest,
  SignInResponse,
  SignUpRequest,
} from '@/types/auth';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8787';

// In-memory CSRF token. Set by /session reads + sign-in/up successes;
// cleared on sign-out.
let _csrf: string | null = null;
export function getCsrfToken(): string | null {
  return _csrf;
}
function setCsrf(token: string | null | undefined): void {
  _csrf = token ?? null;
}

const SESSION_KEY = '/v1/auth/session';

export class AuthError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
  ) {
    super(`auth ${status}`);
    this.name = 'AuthError';
  }
}

async function _fetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase();
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(init.headers as Record<string, string> | undefined),
  };
  if (init.body != null && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  if (method !== 'GET' && method !== 'HEAD') {
    const t = getCsrfToken();
    if (t && !headers['X-CSRF-Token']) headers['X-CSRF-Token'] = t;
  }
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    method,
    headers,
    credentials: 'include',
  });
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* not JSON */
    }
    throw new AuthError(res.status, body);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function envelope(s: SessionResponse | null): FacadeSessionEnvelope | null {
  if (!s) return null;
  setCsrf(s.csrf_token ?? null);
  // Server SessionResponse has no email_verified / two_factor_pending /
  // password_change_required / onboarding fields today (forward-compatible
  // additions in v1.x); default safe so AppShell guard does not loop.
  // totp_enabled is server-authoritative.
  return {
    user: {
      id: s.user_id,
      email: s.email,
      role: s.role,
      org_id: s.org_id,
      totp_enabled: s.totp_enabled,
      email_verified: true,
      two_factor_pending: false,
      password_change_required: false,
      onboarding_completed: true,
    },
    session: {
      activeOrganizationId: s.org_id,
      csrf_token: s.csrf_token ?? null,
      expires_at: s.session_expires_at ?? null,
    },
  };
}

async function _getSession(): Promise<FacadeSessionEnvelope | null> {
  try {
    const s = await _fetch<SessionResponse>(SESSION_KEY);
    return envelope(s);
  } catch (err) {
    if (err instanceof AuthError && err.status === 401) return null;
    throw err;
  }
}

// --- public facade (kept identical in shape to better-auth/react) -------- //

export function useSession() {
  const { data, isLoading, mutate } = useSWR<FacadeSessionEnvelope | null>(
    SESSION_KEY,
    _getSession,
    { revalidateOnFocus: false, refreshInterval: 5 * 60 * 1000 /* 5 min */ },
  );
  return { data: data ?? null, isPending: isLoading, mutate } as const;
}

async function _refreshSession(): Promise<void> {
  await swrMutate(SESSION_KEY);
}

export const signIn = {
  async email(body: SignInRequest): Promise<SignInResponse> {
    const res = await _fetch<SignInResponse>('/v1/auth/sign-in', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    setCsrf(res.csrf_token);
    if (!res.requires_totp) await _refreshSession();
    return res;
  },
};

export const signUp = {
  async email(body: SignUpRequest): Promise<SignInResponse> {
    const res = await _fetch<SignInResponse>('/v1/auth/sign-up', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    setCsrf(res.csrf_token);
    await _refreshSession();
    return res;
  },
};

export async function signOut(): Promise<void> {
  try {
    await _fetch<{ ok: boolean }>('/v1/auth/sign-out', { method: 'POST' });
  } finally {
    setCsrf(null);
    await _refreshSession();
  }
}

// Generic typed fetch helper for the auth pages (forgot/reset/verify/totp/
// admin) so they don't re-invent fetch + CSRF wiring.
export const authFetch = _fetch;

// Back-compat shim — legacy `authClient.signIn/...` consumers (none in the
// console today, but kept for safety / future imports).
export const authClient = { signIn, signUp, signOut, useSession };
