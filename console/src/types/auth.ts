// Console-side view-model for the server auth-v1 surface (ADR-0013).
// Shapes mirror packages/shield-server/src/shield_server/auth/routes.py
// byte-for-byte; verified §5b vs origin/main bc6008f.

import type { RbacRole } from '@elydora/shared';

// --- session / sign-in/up ---------------------------------------------- //
export interface SignUpRequest {
  email: string;
  password: string;
  name?: string;
}
export interface SignInRequest {
  email: string;
  password: string;
  totp_code?: string;
}
export interface SignInResponse {
  user_id: string;
  email: string;
  role: RbacRole;
  org_id: string;
  csrf_token: string;
  requires_totp: boolean;
}
export interface SessionResponse {
  user_id: string;
  email: string;
  org_id: string;
  role: RbacRole;
  totp_enabled: boolean;
  auth_kind: string;
  csrf_token?: string | null;
  session_expires_at?: number | null;
}
export interface OkResponse {
  ok: boolean;
}

// --- password / email / TOTP ------------------------------------------- //
export interface PasswordResetRequest {
  email: string;
}
export interface PasswordResetComplete {
  token: string;
  new_password: string;
}
export interface PasswordChangeRequest {
  current_password: string;
  new_password: string;
}
export interface EmailVerifyComplete {
  token: string;
}
export interface TotpSetupResponse {
  provisioning_uri: string;
  secret: string;
}
export interface TotpConfirmRequest {
  code: string;
}
export interface TotpConfirmResponse {
  recovery_codes: string[];
}
export interface TotpDisableRequest {
  password: string;
  code: string;
}
export interface TotpRecoveryRequest {
  email: string;
  recovery_code: string;
}

// --- admin (team management) ------------------------------------------- //
export interface AdminUser {
  user_id: string;
  email: string;
  name: string;
  status: string;
  totp_enabled: boolean;
  role?: RbacRole | null;
  last_login_at?: number | null;
  created_at: number;
}
export interface AdminUsersResponse {
  users: AdminUser[];
}
export interface AdminSessionRow {
  session_id: string;
  user_id: string;
  ip: string | null;
  user_agent: string | null;
  created_at: number;
  last_used_at: number;
  expires_at: number;
  revoked_at: number | null;
}
export interface AdminSessionsResponse {
  sessions: AdminSessionRow[];
}
export interface AdminRoleChangeRequest {
  role: RbacRole;
}
export interface AdminInviteRequest {
  email: string;
  role: RbacRole;
}
export interface AdminInviteResponse {
  invite_id: string;
  expires_at: number;
}

// --- console-internal auth UI state ------------------------------------ //
/**
 * Facade-shape (kept identical to the better-auth/react `useSession()`
 * return so all current consumers — login/register/AppShell/Sidebar/auth.tsx
 * — compile unchanged). Mapped from SessionResponse by the auth-client.
 */
export interface FacadeUser {
  id: string;
  email: string;
  name?: string;
  image?: string | null;
  role: RbacRole;
  org_id: string;
  totp_enabled: boolean;
  email_verified: boolean;
  two_factor_pending: boolean;
  password_change_required: boolean;
  onboarding_step?: string | null;
  onboarding_completed: boolean;
}
export interface FacadeSession {
  activeOrganizationId: string;
  csrf_token?: string | null;
  expires_at?: number | null;
}
export interface FacadeSessionEnvelope {
  user: FacadeUser;
  session: FacadeSession;
}

export type ShieldAuthMode = 'enterprise' | 'open';
