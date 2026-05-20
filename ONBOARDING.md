# Agent Shield — Onboarding

A first-day guide for contributors picking up this repo after W3. Read this
before touching any code.

## 1. What's in your hands

This repo is the W1–W3 deliverable of a two-layer governance stack for
high-risk agentic workflows. The README has the architecture summary; this
file covers the practical questions a new contributor will hit on day one.

Three things to internalise immediately:

1. **The contracts (`contracts/` + `packages/shield-sdk/src/shield_sdk/schema.py`)
   are frozen.** Changing any byte requires `docs/adr/0007-contracts-freeze.md`
   ritual: bump `shield_version`, regenerate the JSON-Schema snapshot, write
   an ADR, all-owner sign-off. CI will refuse the diff otherwise. If your work
   seems to need a contract change, stop and propose the ADR first.
2. **The demo is honest by construction.** No LLM is invoked, no API key is
   required, the `$30,000` figure is the `InjectionTask6` oracle constant.
   See "What this is not" in the README — that scoping survives the handoff
   and must keep surviving it. Don't quote the mock as a measured ASR.
3. **The merge gate is a person, not a CI badge.** The team-lead is the sole
   merger to `main`. Every PR goes through the `reviewer` agent's §5b
   independent re-derivation before the team-lead merges. CI green is
   necessary but not sufficient.

## 2. First-day setup

### Prerequisites

- macOS or Linux. Windows works via WSL2 but is not tested.
- `git`, `make`, Docker Desktop (or compatible engine).
- Python 3.11 (managed via `uv`; install at <https://docs.astral.sh/uv/>).
- Node 20 + npm (managed however you like; nvm is fine).
- GitHub CLI (`gh`) authenticated against the repo.

### Bootstrap

```bash
git clone <repo-url> agent-shield
cd agent-shield
make doctor                         # preflight checks
uv sync --frozen                    # Python deps from uv.lock
cd console && npm ci && cd ..       # console deps
docker compose -f infra/docker-compose.yml up -d   # Postgres / Redis / NATS / Mailhog
make test                           # unit + contract, ~minutes
make integration                    # docker-compose smoke + mocked AgentDojo A/B
```

### Get the console + auth running locally

The console runs at `:3000`, server at `:8787`. Two modes:

| Mode       | When to use                                          | How to start                                                       |
|------------|------------------------------------------------------|--------------------------------------------------------------------|
| **open**   | Local hacking, no auth friction                      | `SHIELD_AUTH_MODE=open` on the server                              |
| **enterprise** | The realistic demo path with real auth + sessions | `SHIELD_AUTH_MODE=enterprise` + seed an admin via the CLI          |

To seed the first admin in enterprise mode:

```bash
cd packages/shield-server
SHIELD_SEED_ADMIN_PASSWORD='correct-horse-battery-staple' \
  uv run python -m shield_server.auth.cli seed-admin \
    --email demo@example.com \
    --org demo-org \
    --name "Demo Admin"
```

After the handoff-hardening cascade (see CHANGELOG "Handoff Hardening
(post-W3)") the CLI will auto-create the `demo-org` row if it doesn't exist.
Sign-up via the public `/v1/auth/sign-up` endpoint is disabled in enterprise
mode — new users arrive via invite from an org admin.

### Run the money-shot

```bash
python -m shield_eval.money_shot
```

This drives `InjectionTask6` end-to-end through the real governance decide
pipeline and BLOCKs the 3×$10,000 structuring attack. Verdicts land in the
`governance_verdicts` table; after the prevented-loss cascade, the dashboard
displays the cumulative `$ prevented` total.

## 3. Team workflow (cascade discipline)

The team `agent-shield-build` stays alive across phases. Members:

- **team-lead** — sole merger to `main`, dispatcher, sole router to reviewer.
- **server-builder** — `packages/shield-server`, FastAPI, auth, ingest.
- **gov-builder** — `packages/shield-governance`, LangGraph decide, ChannelStream.
- **sdk-builder** — `packages/shield-sdk`, contracts, Ed25519, schema.
- **console-builder** — `console/`, Next.js, Vitest, Playwright.
- **reviewer** — an independent agent who runs `§5b` on every PR before merge.
  See [`docs/adr/0013-enterprise-auth-v1.md`](docs/adr/0013-enterprise-auth-v1.md)
  for the latest `§5b` discipline set.

The standing rules:

1. **No fake green.** Source-evidence only — quote the file:line. If a test
   passes for the wrong reason, the reviewer must catch it.
2. **No AI attribution in the repo.** Author and committer are real people.
   Co-authored-by Claude / "Generated with" footers etc. are stripped.
   Commits / PRs / ADRs / docs.
3. **`gh run view` before reporting.** Don't claim CI green from a local
   inference — pull the actual run. (This is the literal "lessons-learned"
   item from the auth-v1 cascade.)
4. **`.gitleaksignore` is by-SHA — incompatible with rebase-merge.** If you
   add a fingerprint and then rebase, the SHA changes and the entry stops
   matching. Plan accordingly or use squash.
5. **Allowlist ↔ handler symmetry.** Any path in
   `packages/shield-server/src/shield_server/auth/dep.py:PUBLIC_ROUTE_PATHS`
   must have a corresponding `@auth_router` handler, and vice versa. Both
   sides of a cross-PR boundary must ship before merge.
6. **Keep the team alive between phases.** Don't shut down teammates when a
   feature lands — they keep their context for the next round.

### Sending work

Use `TaskCreate` for any multi-step work; assign with `TaskUpdate owner=…`.
`SendMessage` to teammates by name (never by UUID). Each PR off `main` (no
intermediate base branches), each cleared by `reviewer` §5b before the
team-lead merges.

## 4. What's done, what's deliberately deferred

### Done (W1–W3 + auth-v1 + handoff-hardening)

- W1: SDK + contracts frozen at v1.1, golden vectors, Merkle plumbing.
- W2: governance decide + ChannelStream, server `/decide` + `/record`, integration
  green.
- W3: console (13 surfaces), real money-shot end-to-end on rebuilt stack.
- auth-v1 (ADR-0013): enterprise auth — argon2id+pepper, sessions, CSRF,
  TOTP, RBAC, invites, audit, MultiFernet rotation, seed-admin CLI.
- Handoff-hardening (post-W3): see [CHANGELOG.md](docs/CHANGELOG.md).

### Deliberately deferred (W4 carryovers)

- **ADR-0011** — behavior-drift detector (out of W3 scope; design only).
- **ADR-0012** — async `shield:verdicts` publish channel (W3 deferred; current
  surface is the synchronous `/decide` gate).
- **D7** — PII retention policy (G3 deferred per ADR-0013).
- **WebAuthn / SCIM / SAML** — D4 v1.1 / v2 roadmap from ADR-0013.
- **Magic-link / OAuth providers** — D6 v2 from ADR-0013.
- **`eval.yml` against real LLM models** — the W4/W5 work that turns the
  mocked A/B into a quotable real-model benchmark.
- **Register-Agent wizard `Issue API Token` UI wiring** — server endpoint
  `/v1/agents/{id}/tokens` exists; the wizard currently shows a
  `demo-static-token` placeholder.
- **ADR-0014** — codify the lessons-learned trio (gitleaksignore SHA pitfall,
  gh-run-view-before-reporting, allowlist↔handler symmetry) as a permanent
  reference doc.

### Branch hygiene

`delete_branch_on_merge=true` is enabled on the repo. Local worktrees from
the W2/W3/auth-v1 cascade are preserved under `agent-shield-wt/` for
archaeology; they can be pruned with `git worktree remove …` once no longer
needed.

## 5. Where to read next

- `docs/adr/` — every architectural decision with its rationale. Read 0007
  (contracts freeze), 0013 (auth-v1) and the latest ADR for the active
  shape of the codebase.
- `docs/CHANGELOG.md` — the rolling list of merged work, with the
  Handoff-Hardening cascade as the most recent section.
- `packages/shield-eval/src/shield_eval/run_ab.py` and `money_shot.py` —
  the canonical entry points for the demo; their docstrings are the most
  honest summary of the eval scope.
- `packages/shield-server/src/shield_server/auth/routes.py` — the 18-endpoint
  auth surface; pair with ADR-0013 `§A1`-`§A11`.

Welcome aboard.
