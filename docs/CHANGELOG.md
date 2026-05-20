# CHANGELOG

A rolling, human-curated record of the merged work on `main`. ADRs in
`docs/adr/` carry the rationale; this file is the bird's-eye view by phase.

## Handoff Hardening (post-W3) — in progress

Closing the gaps surfaced during the W3 enterprise-mode live walkthrough so
the repo is safe to hand off to the next contributor without ambiguity.
Five PRs dispatched off main `9c7bc99` (the post-auth-v1 + brand-cleanup
state). Each lands via reviewer §5b independent re-derivation; the
team-lead is the sole merger. This section currently describes the
*planned* shape of each PR; entries will be amended with the merged-SHA
and post-merge file references as each lands. The final order of merge
is whatever the §5b cadence dictates (the docs PR — A.5 — is the only
one whose body you are reading on this very head).

- **A.1** (dispatched as task #28 — pending §5b) — `feat(server-auth):
  enterprise mode disables /v1/auth/sign-up`. Will implement ADR-0013 D5
  ("CLI seed-admin only") at the route level: return `403
  ENTERPRISE_MODE_SIGNUP_DISABLED` when `SHIELD_AUTH_MODE=enterprise`,
  preserve existing open-mode behaviour. Will add an ADR-0013 §A1.c
  addendum.
- **A.2** (dispatched as task #29 — pending §5b) — `fix(console): surface
  server error.message instead of "Load failed"`. Will update
  `lib/auth-client.ts` to read `{error:{code,message,details}}` from the
  response JSON; register / login / forgot / reset forms will render the
  real message. Will lock the contract with a Vitest + MSW assertion.
- **A.3** (dispatched as task #30 — pending §5b) — `feat(server-auth-cli):
  seed-admin auto-creates organization row`. Will add `ON CONFLICT DO
  NOTHING` on the `organizations` INSERT so a first-time runner against
  a fresh database doesn't hit the FK error today's CLI produces.
- **A.4** (dispatched as task #31 — pending §5b; tri-PR coordination
  across gov / server / console) — `feat: prevented_loss end-to-end`.
  Governance decide will compute `prevented_amount` on BLOCK paths
  (single-cap and cross-call structuring rule families) and set
  `Obligations.prevented_loss` (the field already exists in the §4
  frozen `GovernanceVerdict` schema at
  `contracts/governance_verdict.schema.json:85`). Server will persist
  the verdict's `obligations.prevented_loss` into the
  `governance_verdicts.prevented_loss` DB column (currently hard-coded
  to 0). Console will add a fifth dashboard stat card with HG#6-honest
  labeling that qualifies the figure as eval-suite / oracle-fixed /
  MockedLLM (per the reviewer's pre-staged labeling mandate). After
  the tri-PR cascade lands, `python -m shield_eval.money_shot` on the
  rebuilt stack will produce DB rows with `prevented_loss > 0` and the
  UI card will display the cumulative `$` figure with the qualifier.
- **A.5** (this PR, task #32) — `docs: README "What this is / What it
  isn't" + ONBOARDING.md + CHANGELOG.md`. Locks the honest-scope
  language for the demo (MockedLLM, no API keys, `$30,000` is the
  `InjectionTask6` oracle constant), captures the W1–W3 history, and
  gives the next contributor a first-day setup path including the
  team workflow + cascade discipline.

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
