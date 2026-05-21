import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import PageHeader from '@/components/ui/PageHeader';
import Sidebar from '@/components/ui/Sidebar';
import nextConfig from '../next.config';

const mocks = vi.hoisted(() => ({
  pathname: '/',
  logout: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => mocks.pathname,
}));

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    user: {
      display_name: 'Demo Operator',
      email: 'demo@example.com',
      role: 'admin',
    },
    logout: mocks.logout,
    canManageMembers: true,
  }),
}));

describe('console responsive UI contracts', () => {
  it('lets PageHeader subtitles wrap naturally and keeps mobile actions touch-friendly', () => {
    render(
      <PageHeader
        title="Governance"
        subtitle="Long English subtitle should wrap at spaces instead of splitting words mid-token."
        breadcrumbs={[{ label: 'Dashboard', href: '/' }, { label: 'Governance' }]}
        actions={<button type="button">Export report</button>}
      />,
    );

    expect(screen.getByText(/Long English subtitle/)).not.toHaveClass('break-all');
    expect(screen.getByText(/Long English subtitle/)).toHaveClass('break-words');

    const actionRail = screen.getByRole('button', { name: 'Export report' }).parentElement;
    expect(actionRail).toHaveClass('page-header-actions');
    expect(actionRail).toHaveClass('flex-wrap');
    expect(actionRail).toHaveClass('w-full');
    expect(actionRail).toHaveClass('sm:w-auto');
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveClass('page-header-crumb-link');
  });

  it('keeps mobile sidebar controls reachable without fixed bottom overlap', () => {
    render(<Sidebar isOpen onClose={vi.fn()} />);

    const navigation = screen.getByRole('navigation');
    expect(navigation.parentElement).toHaveClass('flex-1');
    expect(navigation.parentElement).toHaveClass('min-h-0');
    expect(navigation.parentElement).toHaveClass('overflow-y-auto');

    expect(screen.getByRole('link', { name: 'Home' })).toHaveClass('sidebar-footer-link');
    expect(screen.getByRole('link', { name: 'Docs' })).toHaveClass('sidebar-footer-link');
    expect(screen.getByRole('button', { name: 'Sign Out' })).toHaveClass('console-mobile-icon-button');
  });

  it('keeps mobile touch target rules in shared CSS without changing desktop density', () => {
    const css = readFileSync(path.resolve(process.cwd(), 'src/app/globals.css'), 'utf8');

    expect(css).toContain('@media (max-width: 767px)');
    for (const selector of [
      '.btn-brutalist',
      '.btn-ghost',
      '.sidebar-nav-item',
      '.sidebar-footer-link',
      '.page-header-crumb-link',
      '.console-mobile-icon-button',
      'button[title]',
      '.page-header-actions button',
      '.page-header-actions a',
      'button',
      'input',
      'select',
      'textarea',
    ]) {
      expect(css).toContain(selector);
    }
    expect(css).toMatch(/min-height:\s*44px/);
    expect(css).toMatch(/min-width:\s*44px/);
    expect(css).toMatch(/touch-action:\s*manipulation/);
  });

  it('keeps the mobile hamburger on the 44px icon-button contract', () => {
    const appShell = readFileSync(path.resolve(process.cwd(), 'src/components/AppShell.tsx'), 'utf8');

    expect(appShell).toContain('console-mobile-icon-button');
    expect(appShell).toContain('aria-label="Open menu"');
  });

  it('does not configure unsupported Next 16 eslint build options', () => {
    expect(nextConfig).toMatchObject({ output: 'standalone' });
    expect(nextConfig).not.toHaveProperty('eslint');
  });
});
