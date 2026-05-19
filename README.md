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

## Development

- Branch protection: only the integrator merges to `main`; PRs must be
  up-to-date, linear history, CODEOWNERS review required on `contracts/`.
- The `contracts/` schema is frozen: changing it requires bumping
  `shield_version`, regenerating the snapshot, an ADR, and all-owner sign-off.
- Conventional-commit titles; ruff + mypy clean; coverage ≥80% overall,
  ≥90% on `shield-sdk` crypto/schema.
