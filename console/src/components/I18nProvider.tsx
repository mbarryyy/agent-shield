'use client';

import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import '@/i18n/config';
import { LANGUAGE_STORAGE_KEY } from '@/i18n/config';

export function resolveHydratedLanguage(
  storedLanguage: string | null | undefined,
  navigatorLanguage: string | null | undefined,
): 'en' | 'zh' {
  const stored = normalizeLanguage(storedLanguage);
  if (stored) return stored;
  return normalizeLanguage(navigatorLanguage) ?? 'en';
}

function normalizeLanguage(value: string | null | undefined): 'en' | 'zh' | null {
  if (!value) return null;
  const normalized = value.toLowerCase();
  if (normalized.startsWith('zh')) return 'zh';
  if (normalized.startsWith('en')) return 'en';
  return null;
}

export default function I18nProvider({ children }: { children: React.ReactNode }) {
  const { i18n } = useTranslation();

  useEffect(() => {
    const handleChange = (lng: string) => {
      document.documentElement.lang = lng;
      window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lng);
    };
    i18n.on('languageChanged', handleChange);
    const preferred = resolveHydratedLanguage(
      window.localStorage.getItem(LANGUAGE_STORAGE_KEY),
      window.navigator.language,
    );
    if (i18n.language !== preferred) {
      void i18n.changeLanguage(preferred);
    } else {
      handleChange(i18n.language);
    }
    return () => { i18n.off('languageChanged', handleChange); };
  }, [i18n]);

  return <>{children}</>;
}
