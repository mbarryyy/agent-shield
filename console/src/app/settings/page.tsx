'use client';

import { useAuth } from '@/lib/auth';
import { useTranslation } from 'react-i18next';
import PageHeader from '@/components/ui/PageHeader';
import CopyButton from '@/components/ui/CopyButton';

export default function SettingsPage() {
  const { t } = useTranslation();
  const { user, logout } = useAuth();

  return (
    <div className="fade-in">
      <PageHeader
        title={t('settings.title')}
        subtitle={t('settings.subtitle')}
        breadcrumbs={[
          { label: t('common.dashboard'), href: '/' },
          { label: t('settings.title') },
        ]}
      />

      {/* User Information */}
      <div className="mb-8">
        <div className="section-label mb-3">{t('settings.user')}</div>
        <div className="border border-border bg-surface p-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <div className="font-mono text-[10px] text-ink-dim uppercase tracking-wider mb-1">
                {t('settings.displayName')}
              </div>
              <div className="font-sans text-sm text-ink">
                {user?.display_name ?? '\u2014'}
              </div>
            </div>
            <div>
              <div className="font-mono text-[10px] text-ink-dim uppercase tracking-wider mb-1">
                {t('settings.email')}
              </div>
              <div className="font-sans text-sm text-ink">
                {user?.email ?? '\u2014'}
              </div>
            </div>
            <div>
              <div className="font-mono text-[10px] text-ink-dim uppercase tracking-wider mb-1">
                {t('settings.subject')}
              </div>
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-[13px] text-ink">{user?.sub ?? '\u2014'}</span>
                {user?.sub && <CopyButton text={user.sub} />}
              </div>
            </div>
            <div>
              <div className="font-mono text-[10px] text-ink-dim uppercase tracking-wider mb-1">
                {t('settings.role')}
              </div>
              <span className="font-mono text-[11px] uppercase tracking-wider px-2 py-1 bg-bg border border-border text-ink">
                {user?.role ?? '\u2014'}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Organization */}
      <div className="mb-8">
        <div className="section-label mb-3">{t('settings.organization')}</div>
        <div className="border border-border bg-surface p-6">
          <div>
            <div className="font-mono text-[10px] text-ink-dim uppercase tracking-wider mb-1">
              {t('settings.organizationId')}
            </div>
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-[13px] text-ink">{user?.org_id ?? '\u2014'}</span>
              {user?.org_id && <CopyButton text={user.org_id} />}
            </div>
          </div>
        </div>
      </div>

      {/* Sign Out */}
      <div>
        <button
          onClick={logout}
          className="px-4 py-2 font-mono text-[12px] uppercase tracking-wider border border-border bg-surface text-ink hover:bg-bg transition-colors"
        >
          {t('common.signOut')}
        </button>
      </div>
    </div>
  );
}
