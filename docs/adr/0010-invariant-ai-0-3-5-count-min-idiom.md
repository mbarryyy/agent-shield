# 0010 — Invariant `LocalPolicy` cross-step uses the verified `count(min=N)` idiom (not §3.2's `sum`/`input.data`)

- Status: Accepted
- Date: 2026-05-19
- Deciders: governance-builder (Tasks #11, #21); team-lead (docs/adr owner + sole merger, ratifies placement); reviewer (independent §5b review)

## Context and Problem Statement

`governance_design.md` §3.2 specifies the Evaluator's Invariant cross-step
policy verbatim as:

```
from invariant import sum
...
raise PolicyViolation("structuring", ...) if:
    (a: ToolCall)
    a is tool:send_money
    amounts := [c.function.arguments.amount for c in input.data
                if c.function.arguments.recipient == a.function.arguments.recipient]
    sum(amounts) > input.cumulative_cap
```

§5b code-verification + a live probe of the design-pinned engine
(`invariant-ai==0.3.5`, Apache-2.0, `Related_Work/invariant`,
`invariant/analyzer/policy.py:23/77/90`) found this policy is **non-functional
in 0.3.5**:

1. `from invariant import sum` → `AttributeError: module 'invariant' has no
   attribute 'sum'` — `sum` is a DSL *builtin*
   (`stdlib/invariant/builtins.py:66`), **not** an importable symbol; only
   quantifiers like `count` are importable (`from invariant import count`,
   verified working `tests/analyzer/test_quantifiers.py:9-25`).
2. `[c ... for c in input.data ...]` → `TypeError: 'Input' object is not
   iterable` — 0.3.5 does not support list-comprehension over `input.data`.

The §5b standard requires shipping what the *running pinned engine* supports,
verified, never transcribing a non-working design snippet.

## Considered Options

- **A — Ship §3.2 verbatim.** Rejected: provably non-functional in the pinned
  `invariant-ai==0.3.5`; would be a fabricated capability.
- **B — Pin a different Invariant version where §3.2's idiom works.** Rejected:
  unverified it exists; churns the FROZEN dependency set (ADR-0006) and the
  air-gap register (C5) for no benefit — the model-free deterministic catcher
  already owns the thesis.
- **C — Use the verified-working 0.3.5 idiom**: `from invariant import count` +
  `count(min=3): (tc: ToolCall) tc is tool:send_money [recipient ==]` for
  structuring + a relational rule for secret-in-`subject` exfil. Probed against
  the real engine: fires on the InjectionTask6 3×$10k structuring and on a
  secret subject; does NOT fire on 2 calls / clean subject. `LocalPolicy` only
  (never bare `Policy`/`RemotePolicy` — air-gap import-lint, C5).

## Decision

**Option C.** The Evaluator's Invariant cross-step uses the §5b-verified 0.3.5
`count(min=N)` quantifier + relational exfil rule
(`shield_governance.defender.scanners.STRUCTURING_POLICY`, reused by the W3
Evaluator). **Authority on the cumulative-amount structuring catch remains the
deterministic, model-free `CumulativeRecipientTracker`** (W1, audited
oracle-faithful against AgentDojo `InjectionTask6.security()`); the Invariant
`LocalPolicy` is a verified DSL *cross-check*, not the primary mechanism — so
this idiom correction has **zero impact on the thesis / money-shot** (HG#5).

## Consequences

- Drift between §3.2's literal policy text and the shipped, engine-verified
  policy is recorded here (ADR supersedes; no doc rewrite — corpus is internal).
- Zero §4/contract impact; zero impact on the InjectionTask6 defeat (model-free
  deterministic; 0 LLM tokens on decide→BLOCK).
- `LocalPolicy`-only is retained (air-gap zero-egress, C5 / moat #7).
- Folded into the G3 milestone report; not user-escalated (LOW / non-blocking /
  the §5b discipline working correctly — probe the real engine, ship what works).
