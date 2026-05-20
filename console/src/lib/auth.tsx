'use client';

import { createContext, useContext, useMemo, useCallback } from 'react';
import type { ReactNode } from 'react';
import { useSession, signOut } from '@/lib/auth-client';
import type { RbacRole } from '@elydora/shared';
import type { FacadeSessionEnvelope, ShieldAuthMode } from '@/types/auth';

interface AuthUser {
  id: string;
  sub: string;
  org_id: string;
  role: RbacRole;
  display_name?: string;
  email?: string;
  onboarding_completed: boolean;
  // ADR-0013 spec extensions:
  email_verified: boolean;
  two_factor_enabled: boolean;
  two_factor_pending: boolean;
  password_change_required: boolean;
  onboarding_step?: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  authMode: ShieldAuthMode;
  isDevSession: boolean;
  logout: () => void;
  isAdminRole: boolean;
  // Existing caps:
  canManageMembers: boolean;
  canManageAgents: boolean;
  canViewAudit: boolean;
  // ADR-0013 new caps:
  canManageOrg: boolean;
  canResolveIncidents: boolean;
  canCreateExports: boolean;
  // Observational caps (always-true for any authed user; explicit for clarity):
  canViewGovernance: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const AUTH_MODE: ShieldAuthMode =
  (process.env.NEXT_PUBLIC_SHIELD_AUTH_MODE === 'open' ? 'open' : 'enterprise');

// In 'open' mode (CI / dev) we seed a dev session so all routes render and
// the visible "Dev Session" badge is honest about the auth bypass. Default
// remains 'enterprise' (default-secure).
const DEV_SESSION: FacadeSessionEnvelope = {
  user: {
    id: 'dev-user',
    email: 'dev@local',
    role: 'org_owner',
    org_id: 'dev-org',
    totp_enabled: false,
    email_verified: true,
    two_factor_pending: false,
    password_change_required: false,
    onboarding_completed: true,
  },
  session: {
    activeOrganizationId: 'dev-org',
    csrf_token: null,
    expires_at: null,
  },
};

function mapAuthUser(envelope: FacadeSessionEnvelope): AuthUser {
  const u = envelope.user;
  return {
    id: u.id,
    sub: u.id,
    org_id: envelope.session.activeOrganizationId || u.org_id,
    role: u.role,
    display_name: u.name ?? undefined,
    email: u.email,
    onboarding_completed: u.onboarding_completed,
    email_verified: u.email_verified,
    two_factor_enabled: u.totp_enabled,
    two_factor_pending: u.two_factor_pending,
    password_change_required: u.password_change_required,
    onboarding_step: u.onboarding_step ?? undefined,
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // In open mode the real /v1/auth/session fetch is bypassed at the
  // provider boundary — useSession() is still called (rules-of-hooks),
  // but its result is ignored in favor of the seeded dev envelope.
  const real = useSession();
  const envelope: FacadeSessionEnvelope | null =
    AUTH_MODE === 'open' ? DEV_SESSION : real.data;
  const isPending = AUTH_MODE === 'open' ? false : real.isPending;

  const user: AuthUser | null = useMemo(
    () => (envelope ? mapAuthUser(envelope) : null),
    [envelope],
  );

  const isAdminRole =
    user?.role === 'org_owner' || user?.role === 'security_admin';
  const canManageMembers = isAdminRole;
  const canManageAgents = isAdminRole || user?.role === 'integration_engineer';
  const canViewAudit = isAdminRole || user?.role === 'compliance_auditor';
  const canManageOrg = user?.role === 'org_owner';
  const canResolveIncidents = isAdminRole;
  const canCreateExports =
    isAdminRole || user?.role === 'compliance_auditor';
  const canViewGovernance = !!user; // observational

  const logout = useCallback(async () => {
    try {
      await signOut();
    } finally {
      window.location.href = '/login';
    }
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading: isPending,
        authMode: AUTH_MODE,
        isDevSession: AUTH_MODE === 'open',
        logout,
        isAdminRole: !!isAdminRole,
        canManageMembers: !!canManageMembers,
        canManageAgents: !!canManageAgents,
        canViewAudit: !!canViewAudit,
        canManageOrg: !!canManageOrg,
        canResolveIncidents: !!canResolveIncidents,
        canCreateExports: !!canCreateExports,
        canViewGovernance,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
