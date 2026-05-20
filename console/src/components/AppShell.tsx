'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { AuthProvider, useAuth } from '@/lib/auth';
import Sidebar from '@/components/ui/Sidebar';
import SessionExpiredModal from '@/components/SessionExpiredModal';

// Routes that are reachable without a session (auth flows + invite/reset
// landing pages). Anything else is gated by the 6-step enterprise fan-out
// in AuthGuard.
const PUBLIC_ROUTES = new Set<string>([
  '/login',
  '/login/2fa',
  '/register',
  '/forgot-password',
  '/password-reset',
  '/verify-email',
  '/accept-invite',
]);

function isPublic(pathname: string): boolean {
  if (PUBLIC_ROUTES.has(pathname)) return true;
  for (const p of PUBLIC_ROUTES) if (pathname.startsWith(p + '/')) return true;
  return false;
}

function AuthGuard({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  const {
    user,
    isAuthenticated,
    isLoading,
    authMode,
    isDevSession,
  } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const closeSidebar = useCallback(() => setSidebarOpen(false), []);

  // Close sidebar on route change (mobile)
  useEffect(() => {
    setSidebarOpen(false);
  }, [pathname]);

  const publicRoute = isPublic(pathname);

  // 6-step enterprise guard fan-out (no-op in 'open' mode — AuthProvider
  // seeds a dev session there). Order matters: each step short-circuits the
  // next so a missing precondition never reaches a gated page.
  useEffect(() => {
    if (authMode === 'open') return;
    if (isLoading) return;
    if (!isAuthenticated && !publicRoute) {
      router.push('/login');
      return;
    }
    if (isAuthenticated && user) {
      if (user.email_verified === false && pathname !== '/verify-email') {
        router.push('/verify-email');
        return;
      }
      if (user.two_factor_pending === true && pathname !== '/login/2fa') {
        router.push('/login/2fa');
        return;
      }
      if (
        user.password_change_required === true &&
        pathname !== '/settings/account'
      ) {
        router.push('/settings/account?force_password=1');
        return;
      }
    }
  }, [authMode, isLoading, isAuthenticated, user, publicRoute, pathname, router]);

  if (isLoading) {
    return <div className="min-h-screen bg-bg" />;
  }

  if (publicRoute) {
    return <>{children}</>;
  }

  if (!isAuthenticated) {
    return <div className="min-h-screen bg-bg" />;
  }

  return (
    <div className="min-h-screen">
      <Sidebar isOpen={sidebarOpen} onClose={closeSidebar} />

      {/* Mobile header bar */}
      <div className="fixed top-0 left-0 right-0 z-30 flex items-center gap-3 px-4 h-14 bg-ink md:hidden">
        <button
          onClick={() => setSidebarOpen(true)}
          className="p-2 -ml-2 text-[#EAEAE5]"
          aria-label="Open menu"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M3 5h14M3 10h14M3 15h14" />
          </svg>
        </button>
        <span className="font-sans text-sm font-semibold tracking-wide text-[#EAEAE5]">AGENT SHIELD</span>
      </div>

      <main className="min-h-screen md:ml-[260px]">
        {/* Visible "Dev Session" badge — honest UI (HG#6) when running in
            open mode (CI/dev). Mirrors the W3 "Pre-release" notice template. */}
        {isDevSession && (
          <div
            role="status"
            className="border-b border-amber-300 bg-amber-50 px-4 py-2 font-mono text-[11px] text-amber-800 text-center"
          >
            {t('common.devSessionBadge')}
          </div>
        )}
        <div className="max-w-[1400px] mx-auto px-4 md:px-6 lg:px-12 pt-20 md:pt-8 pb-8 overflow-hidden">
          {children}
        </div>
      </main>
    </div>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <AuthGuard>{children}</AuthGuard>
      <SessionExpiredModal />
    </AuthProvider>
  );
}
