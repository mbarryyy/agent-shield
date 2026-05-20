# Agent Shield

Two-layer runtime governance for high-risk agentic workflows.

- **Layer 1 — Free SDK** (`packages/shield-sdk`): tamper-evident action records
  (Ed25519 / JCS-RFC8785 / chain-hash / Merkle), a single frozen pydantic schema
  (`shield_sdk.schema`, the §4 source of truth), and AgentDojo pipeline elements
  (`ShieldGuard` / `ShieldedToolsExecutor` / `ShieldRecorder`).
- **Layer 2 — Governance** (`packages/shield-governance`): a LangGraph
  four-guardian graph (Defender / Evaluator / Supervisor / Auditor) plus
  `ShieldModelRouter` for a zero-egress, air-gapped local-serving profile.
- **Server** (`packages/shield-server`): FastAPI ingest/verify/Merkle/audit and
  the synchronous `POST /v1/governance/decide` gate + Redis-Streams fan-out.
- **Eval** (`packages/shield-eval`): the `python -m shield_eval.run_ab` A/B
  harness over the AgentDojo `banking` suite.
- **Console** (`console/`): the Next.js operations + governance UI.

## Layout

```
contracts/   FROZEN §4 integration boundary (JSON-Schema snapshots, examples, golden vectors)
packages/    uv workspace members (Python 3.11): shield-sdk, shield-server, shield-governance, shield-eval
console/     Next.js (npm, Node 20)
infra/       docker-compose (Postgres + Redis + MinIO + ChromaDB)
docs/adr/    Architecture Decision Records
```

The design corpus (research / specifications) is maintained out-of-repo as an
internal reference; this public repository carries build artifacts only.

`Related_Work/` is a git-ignored symlink to read-only upstream reference clones
(AgentDojo @ `18b501a`, Elydora, LangGraph, …) used for source-grounded
verification; it is never tracked.

## Quickstart

```bash
make doctor        # preflight: toolchain + infra reachability
uv sync --frozen   # reproducible install from uv.lock
make test          # unit + contract
make integration   # docker-compose smoke + mocked AgentDojo A/B
```

New contributors: read [ONBOARDING.md](ONBOARDING.md) first — it covers
first-day setup, the team workflow, and the honest scope of the demo numbers
below.

## What this is

- A working two-layer governance stack: SDK records → Server ingests/verifies
  → Governance four-guardian graph decides → audit/Merkle/export.
- A rule-based BLOCK path that genuinely defeats AgentDojo's `InjectionTask6`
  (the 3×$10,000 structuring attack on the banking suite) end-to-end through
  the real governance decide pipeline — `python -m shield_eval.money_shot`
  drives it.
- Real authentication (`docs/adr/0013-enterprise-auth-v1.md`): argon2id +
  pepper password hashing, session cookies + CSRF transport-separation, TOTP
  enrolment, RBAC, Ed25519 agent keys, invite flow, audit log. Real Postgres
  / Redis / NATS / Mailhog services via `infra/docker-compose.yml`.

## What this is not (honest scope)

These caveats matter — please don't quote anything below as "measured" or
"benchmarked":

- **No LLM is invoked anywhere in the current demo.** `python -m
  shield_eval.run_ab` uses
  [`MockedLLM`](packages/shield-eval/src/shield_eval/mock_llm.py), a
  deterministic, key-free pipeline element that **replays each AgentDojo
  task's own `ground_truth` transcript** as the agent's tool-call sequence.
  When the mocked agent observes the `<INFORMATION>` injection marker in a
  tool result, it follows the injection by also replaying the injection
  task's ground-truth — that is what makes the undefended A0 baseline
  genuinely fail AgentDojo's own `security()` oracle. The mock proves the
  A0/A0b plumbing + oracle scoring offline; it does **not** measure model
  behaviour.
- **No API keys are required.** `infra/.env.example:ANTHROPIC_API_KEY=` is a
  template field for the eventual W4/W5 `eval.yml` runs against real models;
  the current `make test` / `make integration` / `python -m shield_eval.*`
  paths all run without it.
- **The `$30,000` figure is `InjectionTask6`'s oracle constant**, not a
  measured outcome. `INJECTIONTASK6_AT_RISK_USD = 30_000.0`
  (`packages/shield-eval/src/shield_eval/money_shot.py`) is read directly
  from the AgentDojo task definition (`banking/injection_tasks.py:331-338`).
  The number tells you what is at risk in that one fixture, not what an
  attacker against a real model would steal.
- **`DEFAULT_WORKER = "claude-3-haiku-20240307"`**
  (`packages/shield-eval/src/shield_eval/run_ab.py`) is just a prose-name
  string so `important_instructions` attacks can address the model by name in
  their injected text. **No Anthropic API call is made.**
- **The governance decide path is genuinely rule-based** and runs end-to-end
  on the real stack — single-cap (transfer > $10k) and cross-call
  structuring (Σ ≥ $30k) rules; not LLM-judged. This is why "no API key"
  still produces a real BLOCK verdict.
- **Quotable ASR / utility numbers come later.** The `eval.yml` design that
  wires real Claude / GPT models against the AgentDojo banking suite is
  W4/W5 work and is not run in this snapshot.

The honest positioning is locked in
[`packages/shield-eval/src/shield_eval/run_ab.py`](packages/shield-eval/src/shield_eval/run_ab.py):
"comparisons are scoped to *beat the 4 AgentDojo built-in baselines + the
Axis-C governance moat*, never *beat SOTA*. `InjectionTask6` is itself
injection-delivered — stated plainly; mock numbers are
deterministic-transcript scaffolding, never reported as measured ASR."

## Development

- Branch protection: only the integrator merges to `main`; PRs must be
  up-to-date, linear history, CODEOWNERS review required on `contracts/`.
- The `contracts/` schema is frozen: changing it requires bumping
  `shield_version`, regenerating the snapshot, an ADR, and all-owner sign-off.
- Conventional-commit titles; ruff + mypy clean; coverage ≥80% overall,
  ≥90% on `shield-sdk` crypto/schema.
