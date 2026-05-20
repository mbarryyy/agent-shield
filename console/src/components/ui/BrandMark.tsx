'use client';

import { useTranslation } from 'react-i18next';

const SIZE: Record<'sm' | 'md' | 'lg', number> = { sm: 16, md: 24, lg: 36 };

/**
 * The Agent Shield brand mark — an inline SVG shield glyph. Replaces the
 * inherited `<span>E</span>` Elydora monogram on login/register (CONSOLE-W3
 * leak fixed here in the auth-v1 refactor; C5 / ADR-0013). Semantic match
 * with the product name, no font dependency, a11y title from i18n.
 */
export default function BrandMark({
  size = 'md',
  className,
}: {
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}) {
  const { t } = useTranslation();
  const px = SIZE[size];
  return (
    <svg
      width={px}
      height={px}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      role="img"
      aria-label={t('common.brandMarkAlt')}
    >
      <title>{t('common.brandMarkAlt')}</title>
      <path d="M12 2l8 3v6c0 4.6-3.3 8.4-8 10-4.7-1.6-8-5.4-8-10V5z" />
      <path d="M8 12l3 3 5-5" />
    </svg>
  );
}
