'use client';

import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import '@/i18n/config';

export default function I18nProvider({ children }: { children: React.ReactNode }) {
  const { i18n } = useTranslation();

  useEffect(() => {
    document.documentElement.lang = i18n.language;
    const handleChange = (lng: string) => {
      document.documentElement.lang = lng;
    };
    i18n.on('languageChanged', handleChange);
    return () => { i18n.off('languageChanged', handleChange); };
  }, [i18n]);

  return <>{children}</>;
}
