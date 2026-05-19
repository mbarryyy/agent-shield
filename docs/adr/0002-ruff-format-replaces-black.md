# 0002 — `ruff format` is the single formatter (replaces Black)

- Status: Accepted
- Date: 2026-05-18
- Deciders: delivery-architect (Task #8), team-lead

## Context and Problem Statement

The W0 task brief named "ruff/black/mypy". AgentDojo — the LOCKED toolchain we
are aligning to — runs `uv run ruff format` (its `.pre-commit-config.yaml` pins
`ruff-pre-commit rev v0.5.2`) and does **not** run Black. Running both Black
*and* `ruff format` produces a guaranteed formatter war (each reformats the
other's output), which is exactly the kind of cross-worktree churn that breaks a
five-agent parallel build.

## Considered Options

- **Black + `ruff format`** — two formatters, deterministic conflict on every
  save/CI run.
- **`ruff format` only** — Black-compatible output; one tool also doing lint.
- **Black only** — diverges from AgentDojo CI; adds a tool uv must resolve that
  the harness does not use.

## Decision Outcome

Chosen option: **`ruff format` only**. `ruff format` is Black-compatible and is
exactly what AgentDojo runs, so it satisfies the "black" intent of the brief
without a second formatter. One tool (`ruff`) does both lint and format.

### Consequences

- CI gate is `uv run ruff check` + `uv run ruff format --check .` (cicd.md §2).
- Shared `[tool.ruff]` config lives in the root `pyproject.toml`
  (`line-length = 100`, `target-version = "py311"`); no per-package drift.
- No Black dependency in the dev group; nothing to keep in sync with Black's
  release cadence.

## Evidence (§5b)

AgentDojo `.pre-commit-config.yaml` (`ruff-pre-commit v0.5.2`), CI `uv run ruff
check` + `uv run ruff format`. tech_stack.md §3.2 "`black` note".
