# 0003 — mypy is the type checker for our code (not pyright)

- Status: Accepted
- Date: 2026-05-18
- Deciders: delivery-architect (Task #8), team-lead

## Context and Problem Statement

There is a type-checker divergence (tech_stack.md §4 conflict #2). AgentDojo CI
uses **pyright**. The W0 task brief and Elydora's reference Python SDK (whose
`crypto.py`/`utils.py` we port byte-for-byte) use **mypy**. Two type checkers
across parallel worktrees means contradictory diagnostics and per-builder
whipsaw.

## Considered Options

- **mypy for our `packages/*`** — matches the Elydora crypto we port and the
  task directive; AgentDojo's vendored pyright is left untouched (external clone,
  not in our workspace).
- **pyright everywhere** — would re-type-check the byte-exact Elydora port under
  a different inference engine than its origin and contradict the task directive.
- **Both** — guaranteed parallel-build whipsaw.

## Decision Outcome

Chosen option: **mypy for our code**. Standardize mypy for everything under
`packages/*`; leave AgentDojo's pyright alone (it lives in `Related_Work/`,
git-ignored, not a workspace member). One type checker for our code → no
cross-worktree diagnostic conflict.

### Consequences

- CI gate is `uv run mypy packages` (cicd.md §2); root `[tool.mypy]` is
  `strict = true`, `python_version = "3.11"`.
- Unimplemented W0 stub bodies raising `NotImplementedError` are
  `# pragma: no cover`; where strict mypy is unavoidably noisy for a pure stub,
  a narrowest-scope `# type: ignore[code]` with a justifying comment is
  acceptable and must be reported.
- `mypy>=1.8.0` floor (AgentDojo dev floor; Elydora SDK uses `mypy>=1`).

## Evidence (§5b)

AgentDojo CI pyright vs `pyproject.toml [dependency-groups] dev mypy>=1.8.0`;
Elydora `sdks/python/pyproject.toml` mypy dev-dep. tech_stack.md §3.2/§4 #2.
