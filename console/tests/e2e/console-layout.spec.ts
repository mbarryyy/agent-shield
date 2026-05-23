import { expect, test, type Locator, type Page, type Route } from '@playwright/test';

const NOW = 1_716_000_000_000;

const ROUTES = [
  { path: '/', heading: 'Dashboard' },
  { path: '/agents', heading: 'Agents' },
  { path: '/governance', heading: 'Governance' },
  { path: '/governance/incidents', heading: 'Incidents' },
  { path: '/exports', heading: 'Exports' },
  { path: '/audit', heading: 'Audit Trail' },
  { path: '/jwks', heading: 'JWKS' },
  { path: '/settings/team', heading: 'Team' },
] as const;

const TABLE_ROUTES = ['/agents', '/exports', '/audit', '/jwks'] as const;

const operation = {
  operation_id: 'op-0000000000000001',
  agent_id: 'banking-agent',
  org_id: 'dev-org',
  operation_type: 'send_money',
  issued_at: NOW - 10_000,
  created_at: NOW - 9_500,
  ttl_ms: 30_000,
  nonce: 'nonce-1',
  seq_no: 7,
  prev_chain_hash: '0'.repeat(64),
  chain_hash: 'a'.repeat(64),
  r2_payload_key: 'payload/op-0000000000000001.json',
  r2_receipt_key: 'receipt/op-0000000000000001.json',
  payload_hash: 'b'.repeat(64),
  receipt_id: 'ear-0001',
};

const agentsResponse = {
  agents: [
    {
      agent_id: 'banking-agent',
      display_name: 'Banking Guard',
      status: 'active',
      created_at: NOW - 60_000,
    },
  ],
};

const auditResponse = {
  operations: [operation],
  total_count: 1,
  cursor: null,
};

const exportsResponse = {
  exports: [
    {
      export_id: 'exp-0000000000000001',
      status: 'done',
      query_params: JSON.stringify({ format: 'pdf', agent_id: 'banking-agent' }),
      created_at: NOW - 50_000,
      completed_at: NOW - 40_000,
    },
  ],
};

const jwksResponse = {
  keys: [
    {
      kid: 'shield-server-2026-05-21',
      kty: 'OKP',
      alg: 'EdDSA',
      crv: 'Ed25519',
      use: 'sig',
      x: 'f'.repeat(44),
    },
  ],
};

const dashboardKpi = {
  prevented_loss_total: 30_000,
  decision_mix: { PASS: 1, BLOCK: 1, ESCALATE: 1 },
  total_verdicts: 3,
};

const timelineRows = [
  {
    verdict_id: 'v-0001',
    record_id: 'r-0001',
    correlation_id: 'corr-0001',
    run_id: 'banking',
    decision: 'PASS',
    risk_score: 0.03,
    latency_ms: 4,
    created_at: NOW - 9_000,
  },
  {
    verdict_id: 'v-0002',
    record_id: 'r-0002',
    correlation_id: 'corr-0002',
    run_id: 'banking',
    decision: 'ESCALATE',
    risk_score: 0.41,
    latency_ms: 7,
    created_at: NOW - 6_000,
  },
  {
    verdict_id: 'v-0003',
    record_id: 'r-0003',
    correlation_id: 'corr-0003',
    run_id: 'banking',
    decision: 'BLOCK',
    risk_score: 0.92,
    latency_ms: 6,
    created_at: NOW - 3_000,
  },
];

const costRollup = {
  tokens: { prompt: 0, completion: 0, total: 0 },
  decision_mix: { PASS: 1, ALERT: 0, BLOCK: 1, ESCALATE: 1, ROLLBACK: 0, REWRITE: 0 },
  prevented_loss_total: 30_000,
  latency_p50_ms: 5,
  latency_p95_ms: 7,
};

const incidentsResponse = {
  incidents: [
    {
      incident_id: 'v-esc-0001',
      correlation_id: 'corr-0002',
      run_id: 'banking',
      decision: 'ESCALATE',
      risk_score: 0.41,
      status: 'pending',
      resolution: null,
      created_at: NOW - 6_000,
    },
  ],
  cursor: null,
  total_count: 1,
};

const verdictDetail = {
  correlation_id: 'corr-0002',
  verdict: {
    correlation_id: 'corr-0002',
    decision: 'ESCALATE',
    risk_score: 0.41,
    latency_ms: 7,
    reasons: [
      { agent: 'defender', label: 'AMOUNT_ABOVE_BASELINE', score: 0.4 },
      { agent: 'supervisor', label: 'HUMAN_REVIEW', detail: 'Above historical pattern.' },
    ],
    obligations: { require_human: true },
  },
  pre_exec: null,
  post_exec: null,
};

const teamUsersResponse = {
  users: [
    {
      user_id: 'user-1',
      email: 'security.admin@example.com',
      role: 'security_admin',
      status: 'active',
      totp_enabled: true,
    },
  ],
};

async function mockConsoleApi(page: Page): Promise<void> {
  await page.addInitScript(() => {
    class NoopEventSource extends EventTarget {
      readonly url: string;
      readonly readyState = 2;
      onerror: ((event: Event) => void) | null = null;

      constructor(url: string) {
        super();
        this.url = url;
        window.setTimeout(() => {
          const event = new Event('error');
          this.onerror?.(event);
          this.dispatchEvent(event);
        }, 0);
      }

      close() {}
    }

    window.EventSource = NoopEventSource as unknown as typeof EventSource;
  });

  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());

    if (url.hostname === 'fonts.googleapis.com') {
      await route.fulfill({ status: 200, contentType: 'text/css', body: '' });
      return;
    }

    if (url.hostname === 'fonts.gstatic.com') {
      await route.fulfill({ status: 200, body: '' });
      return;
    }

    if (!['127.0.0.1:8787', 'localhost:8787'].includes(url.host)) {
      await route.continue();
      return;
    }

    await fulfillApiRoute(route, url.pathname);
  });
}

async function fulfillApiRoute(route: Route, pathname: string): Promise<void> {
  if (pathname === '/v1/auth/session') {
    await json(route, {
      user_id: 'dev-user',
      email: 'dev@example.com',
      role: 'org_owner',
      org_id: 'dev-org',
      totp_enabled: false,
      csrf_token: 'csrf-e2e',
      session_expires_at: null,
    });
    return;
  }

  if (pathname === '/v1/agents') {
    await json(route, agentsResponse);
    return;
  }

  if (pathname === '/v1/audit/query') {
    await json(route, auditResponse);
    return;
  }

  if (pathname === '/v1/epochs') {
    await json(route, { epochs: [] });
    return;
  }

  if (pathname === '/v1/exports') {
    await json(route, exportsResponse);
    return;
  }

  if (pathname === '/v1/governance/dashboard/kpi') {
    await json(route, dashboardKpi);
    return;
  }

  if (pathname === '/v1/governance/runs/banking/timeline') {
    await json(route, { rows: timelineRows, cursor: null, total_count: timelineRows.length });
    return;
  }

  if (pathname === '/v1/governance/runs/banking/cost') {
    await json(route, costRollup);
    return;
  }

  if (pathname === '/v1/governance/incidents') {
    await json(route, incidentsResponse);
    return;
  }

  if (pathname.startsWith('/v1/governance/verdicts/')) {
    await json(route, verdictDetail);
    return;
  }

  if (pathname === '/.well-known/elydora/jwks.json') {
    await json(route, jwksResponse);
    return;
  }

  if (pathname === '/v1/auth/admin/users') {
    await json(route, teamUsersResponse);
    return;
  }

  await json(route, { ok: true });
}

async function json(route: Route, body: unknown): Promise<void> {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

async function gotoConsoleRoute(page: Page, path: string, heading: string): Promise<void> {
  await mockConsoleApi(page);
  await page.goto(path);
  await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
}

async function expectNoBodyLevelOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => ({
    bodyClientWidth: document.body.clientWidth,
    bodyScrollWidth: document.body.scrollWidth,
    documentClientWidth: document.documentElement.clientWidth,
    documentScrollWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
  }));

  expect(overflow.documentScrollWidth, JSON.stringify(overflow)).toBeLessThanOrEqual(
    overflow.documentClientWidth + 1,
  );
  expect(overflow.bodyScrollWidth, JSON.stringify(overflow)).toBeLessThanOrEqual(
    overflow.bodyClientWidth + 1,
  );
}

async function expectWideTablesUseLocalScroll(page: Page): Promise<void> {
  const checks = await page.locator('table').evaluateAll((tables) =>
    tables
      .map((table) => {
        let ancestor = table.parentElement;
        while (ancestor && ancestor !== document.body) {
          const style = window.getComputedStyle(ancestor);
          if (style.overflowX === 'auto' || style.overflowX === 'scroll') {
            const tableRect = table.getBoundingClientRect();
            const ancestorRect = ancestor.getBoundingClientRect();
            return {
              found: true,
              overflowX: style.overflowX,
              tableWidth: tableRect.width,
              containerWidth: ancestorRect.width,
              viewportWidth: window.innerWidth,
            };
          }
          ancestor = ancestor.parentElement;
        }
        return {
          found: false,
          overflowX: '',
          tableWidth: table.getBoundingClientRect().width,
          containerWidth: 0,
          viewportWidth: window.innerWidth,
        };
      })
      .filter((check) => check.tableWidth > check.viewportWidth + 1),
  );

  expect(checks.length).toBeGreaterThan(0);
  for (const check of checks) {
    expect(check.found, JSON.stringify(check)).toBe(true);
    expect(['auto', 'scroll']).toContain(check.overflowX);
    expect(check.containerWidth, JSON.stringify(check)).toBeLessThanOrEqual(
      check.viewportWidth + 1,
    );
  }
}

async function expectTargetAtLeast44(locator: Locator): Promise<void> {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  expect(Math.round(box!.width)).toBeGreaterThanOrEqual(44);
  expect(Math.round(box!.height)).toBeGreaterThanOrEqual(44);
}

test.describe('desktop console routes', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  for (const route of ROUTES) {
    test(`${route.path} renders without body-level horizontal overflow`, async ({ page }) => {
      await gotoConsoleRoute(page, route.path, route.heading);
      await expectNoBodyLevelOverflow(page);
    });
  }
});

test.describe('mobile console layout', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true });

  for (const route of ROUTES) {
    test(`${route.path} keeps mobile content inside the body viewport`, async ({ page }) => {
      await gotoConsoleRoute(page, route.path, route.heading);
      await expectNoBodyLevelOverflow(page);
    });
  }

  for (const path of TABLE_ROUTES) {
    test(`${path} keeps wide tables inside local horizontal scroll containers`, async ({ page }) => {
      const route = ROUTES.find((candidate) => candidate.path === path)!;
      await gotoConsoleRoute(page, route.path, route.heading);
      await expectWideTablesUseLocalScroll(page);
      await expectNoBodyLevelOverflow(page);
    });
  }

  test('mobile sidebar opens and closes without shifting body overflow', async ({ page }) => {
    await gotoConsoleRoute(page, '/', 'Dashboard');

    const sidebar = page.locator('aside');
    const closedBox = await sidebar.boundingBox();
    expect(closedBox).not.toBeNull();
    expect(closedBox!.x).toBeLessThan(0);

    await page.getByRole('button', { name: 'Open menu' }).click();
    await expect
      .poll(async () => (await sidebar.boundingBox())?.x ?? Number.NEGATIVE_INFINITY)
      .toBeGreaterThanOrEqual(-1);
    const agentsLinkBox = await page.getByRole('link', { name: 'Agents' }).boundingBox();
    expect(agentsLinkBox).not.toBeNull();
    expect(agentsLinkBox!.x).toBeGreaterThanOrEqual(0);
    await expectNoBodyLevelOverflow(page);

    await page.mouse.click(380, 80);
    await expect
      .poll(async () => (await sidebar.boundingBox())?.x ?? 0)
      .toBeLessThan(0);
    await expectNoBodyLevelOverflow(page);
  });

  test('key mobile touch targets are at least 44px', async ({ page }) => {
    await gotoConsoleRoute(page, '/', 'Dashboard');
    await expectTargetAtLeast44(page.getByRole('button', { name: 'Open menu' }));
    await expectTargetAtLeast44(page.getByRole('link', { name: 'Register Agent' }));
    await expectTargetAtLeast44(page.getByRole('link', { name: 'Create Export' }));

    await gotoConsoleRoute(page, '/agents', 'Agents');
    await expectTargetAtLeast44(page.getByRole('button', { name: 'Register Agent' }));

    await gotoConsoleRoute(page, '/audit', 'Audit Trail');
    await expectTargetAtLeast44(page.getByRole('button', { name: 'Clear Filters' }));
    await expectTargetAtLeast44(page.getByRole('link', { name: 'Export Data' }));

    await gotoConsoleRoute(page, '/exports', 'Exports');
    await expectTargetAtLeast44(page.getByRole('button', { name: 'Create Export' }));

    await gotoConsoleRoute(page, '/settings/team', 'Team');
    await expectTargetAtLeast44(page.getByRole('button', { name: 'Invite member' }));
    await expectTargetAtLeast44(page.getByLabel('Email'));
  });
});
