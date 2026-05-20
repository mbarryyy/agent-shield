import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';

// Task #29 (A.2): the auth-client fetch error path must surface the
// server's `{error:{code,message,details}}` envelope verbatim — NOT a
// generic "Load failed" / "auth 409" message. Pages render the resolved
// message via resolveAuthErrorMessage; AuthError carries code + details
// for programmatic consumers.

// next/navigation must be stubbed before importing the page module —
// the App-Router hooks throw outside a Next runtime.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/',
}));

import RegisterPage from '@/app/register/page';
import { AuthError, resolveAuthErrorMessage } from '@/lib/auth-client';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8787';

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe('AuthError envelope parsing', () => {
  it('reads server error.message into Error.message', () => {
    const err = new AuthError(409, {
      error: {
        message: 'Email already registered',
        code: 'VALIDATION_ERROR',
        details: { field: 'email' },
      },
    });
    expect(err.message).toBe('Email already registered');
    expect(err.code).toBe('VALIDATION_ERROR');
    expect(err.details).toEqual({ field: 'email' });
  });

  it('falls back to code then to "auth <status>"', () => {
    expect(new AuthError(500, { error: { code: 'INTERNAL_ERROR' } }).message).toBe('INTERNAL_ERROR');
    expect(new AuthError(503, null).message).toBe('auth 503');
    expect(new AuthError(409, { unrelated: true }).message).toBe('auth 409');
  });
});

describe('resolveAuthErrorMessage', () => {
  it('returns server message for AuthError', () => {
    const err = new AuthError(409, { error: { message: 'Email already registered' } });
    expect(resolveAuthErrorMessage(err, 'fallback')).toBe('Email already registered');
  });

  it('hides browser network-layer placeholders behind the fallback', () => {
    expect(resolveAuthErrorMessage(new TypeError('Load failed'), 'fallback')).toBe('fallback');
    expect(resolveAuthErrorMessage(new TypeError('Failed to fetch'), 'fallback')).toBe('fallback');
  });
});

describe('RegisterPage — 409 surfaces real server message via MSW', () => {
  it('shows "Email already registered" NOT "Load failed"', async () => {
    server.use(
      http.post(`${API_BASE_URL}/v1/auth/sign-up`, () =>
        HttpResponse.json(
          {
            error: {
              message: 'Email already registered',
              code: 'VALIDATION_ERROR',
              details: { field: 'email' },
            },
          },
          { status: 409 },
        ),
      ),
    );

    const user = userEvent.setup();
    render(<RegisterPage />);

    // The register form has 4 required fields; query by placeholder
    // (the inherited Elydora form uses sibling <label> + <input> without
    // htmlFor, so getByLabelText doesn't pair them — placeholders are
    // the stable handle). Password meets the >=8 server constraint.
    await user.type(screen.getByPlaceholderText('Acme Corp'), 'Acme');
    await user.type(screen.getByPlaceholderText('Jane Smith'), 'Jane');
    await user.type(screen.getByPlaceholderText('you@company.com'), 'taken@example.com');
    await user.type(screen.getByPlaceholderText(/minimum 8 characters/i), 'password123');
    await user.click(screen.getByRole('button', { name: /create account/i }));

    await waitFor(() =>
      expect(screen.getByText('Email already registered')).toBeInTheDocument(),
    );
    // Negative assertion: the noisy fallbacks must NOT appear.
    expect(screen.queryByText(/load failed/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/auth 409/i)).not.toBeInTheDocument();
  });
});
