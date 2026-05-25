import { describe, expect, it } from 'vitest';
import { INITIAL_LANGUAGE } from '@/i18n/config';
import { resolveHydratedLanguage } from '@/components/I18nProvider';

describe('i18n hydration language selection', () => {
  it('starts from the SSR language and defers browser preference until after hydration', () => {
    expect(INITIAL_LANGUAGE).toBe('en');
    expect(resolveHydratedLanguage('zh', 'en-US')).toBe('zh');
    expect(resolveHydratedLanguage(null, 'zh-CN')).toBe('zh');
    expect(resolveHydratedLanguage('fr', 'de-DE')).toBe('en');
  });
});
