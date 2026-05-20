# CHANGELOG

A rolling, human-curated record of the merged work on `main`. ADRs in
`docs/adr/` carry the rationale; this file is the bird's-eye view by phase.

## Handoff Hardening (post-W3)

Closing the gaps surfaced during the W3 enterprise-mode live walkthrough so
the repo is safe to hand off to the next contributor without ambiguity.
All five PRs are dispatched off main `9c7bc99` (the post-auth-v1 +
brand-cleanup state) and merged in dependency order via reviewer §5b.

- **A.1** — `feat(server-auth): enterprise mode disables /v1/auth/sign-up`.
  Implements ADR-0013 D5 ("CLI seed-admin only") at the route level. Returns
  `403 ENTERPRISE_MODE_SIGNUP_DISABLED` in enterprise mode; open mode
  behaviour unchanged. ADR-0013 §A1.c addendum.
- **A.2** — `fix(console): surface server error.message instead of "Load
  failed"`. `lib/auth-client.ts` now reads `{error:{code,message,details}}`
  from response JSON; register / login / forgot / reset forms render the
  real message. Vitest+MSW assertion locks the contract.
- **A.3** — `feat(server-auth-cli): seed-admin auto-creates organization
  row`. `ON CONFLICT DO NOTHING` on the `organizations` INSERT removes the
  confusing FK error a first-time runner hits today.
- **A.4** — `feat: prevented_loss end-to-end (gov + server + console)`.
  Governance decide computes `prevented_amount` on BLOCK (single-cap or
  cross-call structuring); server `/v1/governance/record` persists it into
  `governance_verdicts.prevented_loss`; dashboard adds a fifth stat card
  "Total Prevented Loss" reading the cumulative `$` figure via a new
  read API. money_shot.py now lights the UI card.
- **A.5** — `docs: README "What this is / What it isn't" + ONBOARDING.md +
  CHANGELOG.md`. (This commit.) Locks the honest-scope language for the
  demo (MockedLLM, no API keys, `$30,000` is the InjectionTask6 oracle
  constant), captures the W1–W3 history, and gives the next contributor a
  first-day setup path.

## auth-v1 cascade (ADR-0013, main `9c7bc99`)

Self-hosted enterprise auth, no third-party SaaS. Cascade:

- `feat(server-auth-w0): ADR-0013 scaffold + §A5 forcing-function`
- `feat(server-auth): §A1-§A11 implementation` (+ two gitleaks/.gitleaksignore
  hotfixes; lessons-learned captured for ADR-0014)
- `feat(sdk): api_key Bearer kwarg + §A8(e) signature-orthogonality test`
- `feat(console): /v1/auth/* facade, 13 UI surfaces, Vitest+RTL+MSW+
  Playwright, BrandMark`
- `feat(server-auth): /v1/auth/invites/accept handler + ADR §A1.b row`
  (restored allowlist↔handler symmetry — 7↔7)
- `fix(console): brand-cleanup — 4 i18n strings + 2 Sidebar URLs +
  ADR-0013 §A7.1 addendum`

Strict 11-gate full-green; push-CI 10/10 GREEN; enterprise-mode live
walkthrough on the brand-clean state captured.

## W3 — console + money-shot (G3 PASS, integrated main `48a9707`)

Console (13 surfaces) + dispositive `InjectionTask6` $30k BLOCK end-to-end
on the real stack. Two accepted tracked-debt items at G3: no-console-tests
(retired in auth-v1 by the Vitest stack) and FLAG-C eval prose-tidy
(retired in this Handoff Hardening cascade).

## W2 — governance + integration (G2 PASS, main `493e53a`)

Four-guardian decide graph, Channel-2 stream, server `/decide` + `/record`.
Repo-hygiene pass: `delete_branch_on_merge=true` enabled, stale merged
remotes pruned.

## W1 — SDK + contracts (G1 PASS, main `fbfaace3`)

Frozen §4 contracts, Ed25519/JCS-RFC8785/chain-hash/Merkle plumbing, golden
vectors, AgentDojo pipeline elements.
