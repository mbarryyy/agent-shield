import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import BrandMark from '@/components/ui/BrandMark';

// Smoke: the C5 replacement for the inherited `<span>E</span>` Elydora
// monogram renders as an inline SVG carrying the a11y title from i18n.
describe('BrandMark', () => {
  it('renders an accessible Agent Shield mark', () => {
    render(<BrandMark size="md" />);
    expect(screen.getByRole('img', { name: 'Agent Shield' })).toBeInTheDocument();
  });
});
