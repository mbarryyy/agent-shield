# Release Readiness And Artifact Hygiene

This checklist keeps Agent Shield release, demo, and evaluation artifacts
aligned with the implementation that actually ran.

## Evidence Labels

Use these labels in reports, PR notes, screenshots, and exported artifacts:

- `MEASURED`: produced by an actual execution of the named model, service, or
  infrastructure path under the recorded configuration.
- `MOCKED`: produced by deterministic mocks or scripted fixtures. These results
  can validate plumbing and scoring logic, but they are not model behaviour.
- `ESTIMATED`: computed from dry-run prompts, token estimates, static inputs, or
  fixture constants.
- `SKIPPED`: not executed. Include the reason, for example unsupported host
  egress checks on macOS or a real-eval budget guard.

Never mix these labels in one metric cell without explaining the source of each
component.

## Real-Model Eval Guard

Real-model eval is optional and must be bounded before the first provider call.

- Model: `claude-haiku-4-5-20251001`
- Environment key name: `ANTHROPIC_API_KEY`
- Hard budget cap: `$5.00`
- Planning threshold: `$4.50`
- Cost estimate: base input `$1/MTok` plus output `$5/MTok`

If the estimate exceeds the planning threshold, shrink the sample, task, or arm
set. If the run cannot be bounded under the hard cap, skip it and emit
`REAL_EVAL_SKIPPED_BUDGET_GUARD`.

Do not print, log, commit, screenshot, or export the key value.

## Forbidden Release Contents

Exclude these from commits and shared artifacts:

- `.env*` files, provider credentials, private keys, and production config.
- Raw secret-bearing command lines.
- Raw eval traces with private or attack-sensitive data.
- Local workflow or memory files from the workspace root.
- Generated logs, build caches, `.venv`, `node_modules`, `.next`, coverage
  output, Docker volumes, `.DS_Store`, and editor metadata.

## Claim Checks

Before a release or submission handoff, scan for overclaims:

```bash
rg -n "production ready|prod-ready|real ASR|measured ASR|air-gap proof|egress=0" README.md docs packages console .github
rg -n "ANTHROPIC_API_KEY=.*|sk-ant|BEGIN .*PRIVATE KEY|demo-static-token" README.md docs packages console contracts .github
```

Allowed mentions of `ANTHROPIC_API_KEY` must name the variable only, not its
value. Air-gap claims require `make air-gap-verify` evidence; otherwise mark
the result as `SKIPPED`.
