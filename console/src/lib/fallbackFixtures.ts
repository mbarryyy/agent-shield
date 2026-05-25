export function fallbackFixturesEnabled(): boolean {
  return process.env.NEXT_PUBLIC_USE_FALLBACK_FIXTURES === '1';
}

export const BACKEND_EMPTY_MESSAGE = 'Backend has not produced data yet, run demo flow first.';
