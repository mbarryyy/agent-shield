'use client';

import { createContext, useContext, useMemo, useCallback } from 'react';
import type { ReactNode } from 'react';
import { useSession, signOut } from '@/lib/auth-client';
import type { RbacRole } from '@elydora/shared';

interface AuthUser {
  id: string;
  sub: string;
  org_id: string;
  role: RbacRole;
  display_name?: string;
  email?: string;
  onboarding_completed: boolean;
}

interface AuthContextValue {
  user: AuthUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  logout: () => void;
  isAdminRole: boolean;
  canManageMembers: boolean;
  canManageAgents: boolean;
  canViewAudit: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const { data: session, isPending } = useSession();

  const user: AuthUser | null = useMemo(() => {
    if (!session?.user) return null;

    const sessionUser = session.user as Record<string, unknown>;
    const sessionData = session.session as Record<string, unknown>;

    const orgId =
      (sessionData.activeOrganizationId as string) ??
      (sessionUser.org_id as string) ??
      '';
    const role =
      (sessionUser.role as RbacRole) ?? 'readonly_investigator';

    return {
      id: session.user.id,
      sub: session.user.id,
      org_id: orgId,
      role,
      display_name: session.user.name || undefined,
      email: session.user.email || undefined,
      onboarding_completed: !!(sessionUser.onboarding_completed),
    };
  }, [session]);

  const isAdminRole = user?.role === 'org_owner' || user?.role === 'security_admin';
  const canManageMembers = isAdminRole;
  const canManageAgents = isAdminRole || user?.role === 'integration_engineer';
  const canViewAudit = isAdminRole || user?.role === 'compliance_auditor';

  const logout = useCallback(async () => {
    await signOut();
    window.location.href = '/login';
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading: isPending,
        logout,
        isAdminRole: !!isAdminRole,
        canManageMembers: !!canManageMembers,
        canManageAgents: !!canManageAgents,
        canViewAudit: !!canViewAudit,
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
