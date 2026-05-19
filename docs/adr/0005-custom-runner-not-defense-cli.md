# 0005 — Shield's eval arm uses a custom runner, NOT the AgentDojo `--defense` CLI (C9)

- Status: Accepted
- Date: 2026-05-18
- Deciders: integration-architect (Task #5, C9 closer), delivery-architect (Task #8, code-verified), team-lead

## Context and Problem Statement

Earlier drafts assumed Agent Shield could register as an AgentDojo defense via
`--defense agent_shield --module-to-load shield_sdk.defense`. Code verification
of AgentDojo @ HEAD `18b501a` proves this path is **non-functional for a custom
defense**:

- `DEFENSES` is a static module-level literal at
  `src/agentdojo/agent_pipeline/agent_pipeline.py:43`.
- The `--defense` option binds `type=click.Choice(DEFENSES)` at
  click-decoration/import time (`scripts/benchmark.py:147`) *before*
  `--module-to-load`'s `importlib.import_module` runs (`scripts/benchmark.py:203/229`).
- There is no `register_defense` hook.
- `AgentPipeline.from_config` (`agent_pipeline.py:183`) is a hardcoded if-ladder
  over exactly four names (`tool_filter`, `transformers_pi_detector`,
  `repeat_user_prompt`, `spotlighting_with_delimiting`) ending in
  `raise ValueError("Invalid defense name")` at `:265`.

## Considered Options

- **`--defense` CLI + `--module-to-load`** — code-verified non-functional for a
  custom defense; would silently never load Shield.
- **Custom ~60-LOC `shield_eval.run_ab` runner** — builds `AgentPipeline(elements)`
  directly and calls `benchmark_suite_with_injections()` /
  `_without_injections()`; uses the native `--defense` registry only for the
  four built-in baseline arms it must beat.

## Decision Outcome

Chosen option: **custom runner**. The build path is the ~60-LOC
`packages/shield-eval/src/shield_eval/run_ab.py`, invoked as
**`python -m shield_eval.run_ab`** (the ONE locked entrypoint name, conforming to
tech_stack.md §2 layout / CODEOWNERS `/packages/shield-eval/ @eval-builder`;
implementation_plan.md W0 step 6a). It constructs `AgentPipeline(elements)` and
drives the benchmark suites programmatically; it shells the native `--defense`
registry **only** for the four baseline arms (A0/A0b). `evaluation_plan.md §3`
remains the authoritative *behavioral* spec; only the file/module *name*
conforms to this lock.

### Consequences

- No builder inherits the dead `--defense agent_shield` instruction; residual
  `--defense agent_shield` strings are legitimate only inside this ADR's
  "non-functional" explanation.
- All gates / branch-protection / CODEOWNERS / eval-as-CI split are unchanged;
  `cicd.md` §3 `integration.yml` invokes the runner directly.

## Evidence (§5b)

AgentDojo @ HEAD `18b501a`: `agent_pipeline.py:43/183/265`,
`scripts/benchmark.py:147/203/229`. cicd.md §3 ADR-0005 block;
implementation_plan.md W0 step 6/6a + cross-cutting seam #8.
