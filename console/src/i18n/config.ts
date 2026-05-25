import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import en from './en.json';
import zh from './zh.json';

export const INITIAL_LANGUAGE = 'en';
export const LANGUAGE_STORAGE_KEY = 'i18nextLng';

const resources = {
  en: { translation: en },
  zh: { translation: zh },
};

if (!i18n.isInitialized) {
  void i18n.use(initReactI18next).init({
    resources,
    lng: INITIAL_LANGUAGE,
    fallbackLng: 'en',
    interpolation: {
      escapeValue: false,
    },
  });
}

export default i18n;
