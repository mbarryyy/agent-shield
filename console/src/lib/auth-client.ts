import { createAuthClient } from 'better-auth/react';
import { organizationClient } from 'better-auth/client/plugins';

export const authClient = createAuthClient({
  baseURL: process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8787',
  fetchOptions: {
    credentials: 'include' as RequestCredentials,
  },
  plugins: [
    organizationClient(),
  ],
});

export const { signIn, signUp, signOut, useSession } = authClient;
