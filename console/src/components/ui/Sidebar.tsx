'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { useTranslation } from 'react-i18next';
import { LanguageDropdown } from './LanguageDropdown';

interface NavItem {
  label: string;
  href: string;
  icon: React.ReactNode;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function Sidebar({ isOpen, onClose }: SidebarProps) {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const { t } = useTranslation();

  const sections: NavSection[] = [
    {
      title: t('sidebar.overview'),
      items: [
        {
          label: t('common.dashboard'),
          href: '/',
          icon: (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <rect x="1" y="1" width="6" height="6" rx="1" />
              <rect x="9" y="1" width="6" height="6" rx="1" />
              <rect x="1" y="9" width="6" height="6" rx="1" />
              <rect x="9" y="9" width="6" height="6" rx="1" />
            </svg>
          ),
        },
      ],
    },
    {
      title: t('sidebar.management'),
      items: [
        {
          label: t('common.agents'),
          href: '/agents',
          icon: (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="8" cy="5" r="3" />
              <path d="M2 14c0-3.3 2.7-6 6-6s6 2.7 6 6" />
            </svg>
          ),
        },
        {
          label: t('common.operations'),
          href: '/operations',
          icon: (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M2 4h12M2 8h12M2 12h12" />
            </svg>
          ),
        },
      ],
    },
    {
      title: t('sidebar.compliance'),
      items: [
        {
          label: t('common.auditTrail'),
          href: '/audit',
          icon: (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M4 1v14M12 1v14M1 4h14M1 12h14" />
            </svg>
          ),
        },
        {
          label: t('common.epochs'),
          href: '/epochs',
          icon: (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="8" cy="8" r="6" />
              <path d="M8 4v4l3 3" />
            </svg>
          ),
        },
        {
          label: t('common.exports'),
          href: '/exports',
          icon: (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M8 2v8M5 7l3 3 3-3M3 12v2h10v-2" />
            </svg>
          ),
        },
      ],
    },
    {
      title: t('sidebar.system'),
      items: [
        {
          label: t('common.jwks'),
          href: '/jwks',
          icon: (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M8 1l2 3h3l-2.5 3L12 11l-4-2-4 2 1.5-4L3 4h3z" />
            </svg>
          ),
        },
        {
          label: t('common.settings'),
          href: '/settings',
          icon: (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="8" cy="8" r="2" />
              <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.41 1.41M11.54 11.54l1.41 1.41M3.05 12.95l1.41-1.41M11.54 4.46l1.41-1.41" />
            </svg>
          ),
        },
      ],
    },
  ];

  function isActive(href: string): boolean {
    if (href === '/') return pathname === '/';
    return pathname.startsWith(href);
  }

  return (
    <>
      {/* Backdrop overlay — mobile only */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 md:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={`fixed left-0 top-0 bottom-0 bg-ink text-[#EAEAE5] flex flex-col z-50 transition-transform duration-300 ease-in-out md:translate-x-0 ${isOpen ? 'translate-x-0' : '-translate-x-full'}`}
        style={{ width: 'var(--sidebar-width)' }}
      >
        {/* Logo */}
        <div className="px-5 py-6 border-b border-[rgba(234,234,229,0.1)]">
          <Link href="/" className="flex items-center gap-3 no-underline" onClick={onClose}>
            <div className="w-8 h-8 border border-[#EAEAE5] flex items-center justify-center">
              <span className="font-mono text-sm font-bold text-[#EAEAE5]">E</span>
            </div>
            <div>
              <div className="font-sans text-sm font-semibold tracking-wide text-[#EAEAE5]">
                ELYDORA
              </div>
              <div className="font-mono text-[10px] text-[rgba(234,234,229,0.4)] tracking-widest uppercase">
                {t('common.console')}
              </div>
            </div>
          </Link>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-4">
          {sections.map((section) => (
            <div key={section.title} className="mb-4">
              <div className="px-5 py-2 font-mono text-[10px] font-medium tracking-[0.15em] uppercase text-[rgba(234,234,229,0.3)]">
                {section.title}
              </div>
              {section.items.map((item) => (
                <Link
                  key={item.href + item.label}
                  href={item.href}
                  onClick={onClose}
                  className={`sidebar-nav-item mx-2 rounded-sm ${isActive(item.href) ? 'active' : ''}`}
                >
                  {item.icon}
                  {item.label}
                </Link>
              ))}
            </div>
          ))}
        </nav>

      {/* External links */}
      <div className="px-5 py-3 border-t border-[rgba(234,234,229,0.1)]">
        <div className="font-mono text-[10px] font-medium tracking-[0.15em] uppercase text-[rgba(234,234,229,0.3)] mb-2">
          {t('common.links')}
        </div>
        <a
          href="https://elydora.com"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 px-3 py-1.5 text-[rgba(234,234,229,0.6)] hover:text-[#EAEAE5] transition-colors no-underline font-mono text-[12px]"
        >
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M6 3H3v10h10v-3M9 2h5v5M14 2L7 9" />
          </svg>
          {t('common.home')}
        </a>
        <a
          href="https://docs.elydora.com"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 px-3 py-1.5 text-[rgba(234,234,229,0.6)] hover:text-[#EAEAE5] transition-colors no-underline font-mono text-[12px]"
        >
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M6 3H3v10h10v-3M9 2h5v5M14 2L7 9" />
          </svg>
          {t('common.docs')}
        </a>
      </div>

      {/* Language dropdown */}
      <div className="px-5 py-3 border-t border-[rgba(234,234,229,0.1)]">
        <LanguageDropdown />
      </div>

      {/* Bottom user info */}
      <div className="px-5 py-4 border-t border-[rgba(234,234,229,0.1)]">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-[rgba(234,234,229,0.1)] flex items-center justify-center">
            <span className="font-mono text-xs text-[rgba(234,234,229,0.6)]">
              {user?.display_name?.[0]?.toUpperCase() ?? user?.email?.[0]?.toUpperCase() ?? 'U'}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <div className="font-mono text-xs text-[#EAEAE5] truncate">
              {user?.display_name ?? user?.email ?? 'User'}
            </div>
            <div className="font-mono text-[10px] text-[rgba(234,234,229,0.4)] uppercase tracking-wider">
              {user?.role ?? 'unknown'}
            </div>
          </div>
          <button
            onClick={logout}
            className="p-1.5 rounded transition-colors hover:bg-[rgba(234,234,229,0.1)]"
            title={t('common.signOut')}
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="rgba(234,234,229,0.4)" strokeWidth="1.5">
              <path d="M6 2H3v12h3M11 4l4 4-4 4M7 8h8" />
            </svg>
          </button>
        </div>
      </div>
    </aside>
    </>
  );
}
