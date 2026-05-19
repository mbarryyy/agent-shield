# 0001 — uv single workspace + one polyglot monorepo

- Status: Accepted
- Date: 2026-05-18
- Deciders: delivery-architect (Task #8), integration-architect (Task #5), team-lead

## Context and Problem Statement

Agent Shield is four Python packages (`shield-sdk`, `shield-server`,
`shield-governance`, `shield-eval`) that share one source-of-truth `§4` schema,
plus a TypeScript/Next.js console, plus `contracts/`, `infra/`, `docs/adr/`. Up
to five builder agents work in parallel git worktrees. We must pick (a) a Python
dependency/lock strategy and (b) a repository shape that makes parallel builds
reproducible and low-friction. The LOCKED worker **and** eval harness is
AgentDojo, into which our SDK plugs as a Python package subclassing
`agentdojo.agent_pipeline.BasePipelineElement`.

## Considered Options

- **uv** — single workspace, one committed `uv.lock`, `uv sync --frozen` in CI.
- **poetry** — slower resolver; workspace support is plugin-grade; different lock
  format → would diverge from AgentDojo's `uv.lock` (a second dependency
  universe for the harness vs our code).
- **pip-tools** — no workspace concept for our 4 packages + shared schema, no
  Python-version management, manual multi-`requirements` fan-out — exactly the
  coordination hazard we are removing for parallel agents.

## Decision Outcome

Chosen option: **uv**, because AgentDojo *already* uses uv (`[tool.uv] managed =
true`, committed `uv.lock`, CI `uv sync --dev`, `astral-sh/setup-uv` with
`cache-dependency-glob: "uv.lock"`, OIDC trusted-publish). Matching its
toolchain removes a whole class of resolver/lock friction and lets our SDK live
in the same dependency universe as the harness it plugs into. Concretely:

- ONE polyglot repo rooted at the project directory (`git init` here, **not** at
  the parent — that would track `Related_Work/` clones and course material).
  `.gitignore` excludes `Related_Work/` (cicd.md §6).
- uv workspace members = `packages/*`; the console stays **npm** +
  `package-lock.json` (Node 20) — it is a single TS package we extend, not
  rewrite; a package-manager migration is pure risk with no parallel-build
  benefit.
- Pin philosophy (AgentDojo's, verbatim): declare floors (`>=`) in each
  `pyproject.toml`; commit `uv.lock`; CI uses `uv sync --frozen` so every
  worktree, every CI run, and the demo resolve byte-identically.

### Consequences

- One resolver, native multi-package workspace, trivial Python-version matrix,
  fastest cold install (matters for per-worktree agent builds).
- `uv.lock` regeneration (`uv lock`) is a deliberate, **team-lead-owned** act
  after a merge — never an incidental side effect of an agent's `uv add`.
  `uv.lock` is the only conflict-prone artifact and is never hand-merged.

## Evidence (§5b)

`Related_Work/agentdojo/pyproject.toml`, `.github/workflows/{lint-docs,publish}.yaml`,
`.pre-commit-config.yaml`, committed `uv.lock`; Elydora `.gitignore` +
`packages/*/package.json`. tech_stack.md §1–§2, implementation_plan.md W0.
