# 0009 — Guardian LLM nodes use `langchain.agents.create_agent` (not deprecated `create_react_agent`)

- Status: Accepted
- Date: 2026-05-19
- Deciders: governance-builder (Task #21); team-lead (docs/adr owner + sole merger, ratifies placement); reviewer (independent §5b review)

## Context and Problem Statement

`governance_design.md` §4, `agent_shield_master_design.md` §3.3/§8 and
`local_deployment_moat.md` §1.1 name **`langgraph.prebuilt.create_react_agent`**
as the constructor for the LLM-backed guardian nodes (Evaluator grey-band,
Supervisor `arbitrate()`, Auditor narrative), with the
`model: Callable[[StateSchema, Runtime], BaseChatModel]` factory form as the
exact injection seam for `ShieldModelRouter` (the moat #7 zero-egress
one-YAML-swap).

§5b code-verification first-hand of the design-locked clone
(`Related_Work/langgraph`, langgraph **1.2.0**,
`libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py:274-307`) found
`create_react_agent` is decorated **`@deprecated(... "create_react_agent has
been moved to langchain.agents. Please update your import to from
langchain.agents import create_agent")`** (`LangGraphDeprecatedSinceV10`). The
design docs predate this deprecation. Building W3 guardian LLM nodes on a
constructor that emits deprecation warnings (and may be removed in a future
langgraph major) is a latent maintenance and audit-trust risk.

## Considered Options

- **A — Keep `create_react_agent` verbatim** as the design docs say. Rejected:
  ships on a deprecated API; warning noise in a public repo; future-removal
  risk; not faithful to the *running* pinned engine (§5b discipline says ship
  what the real pinned code supports, not a stale design snippet).
- **B — Migrate guardian LLM nodes to `from langchain.agents import create_agent`**
  (the langgraph-recommended successor). The `model=Callable[...]` factory
  parameter — the *only* thing the `ShieldModelRouter` moat depends on — is
  **unchanged** on `create_agent` (verified: same factory contract;
  `ShieldModelRouter.model_factory(role)` returns the identical
  `(state, runtime) -> BaseChatModel` shape). No §4/contract impact, no moat
  impact, no design-doc rewrite (the design corpus is Desktop-only/internal;
  this ADR supersedes the named constructor).

## Decision

**Option B.** W3 guardian LLM nodes (and any W4+ LLM node) are constructed via
`langchain.agents.create_agent` with the `ShieldModelRouter` `model=Callable`
factory. The Callable model-factory seam is the invariant — the constructor
name is an implementation detail this ADR pins to the non-deprecated successor.
The cloud↔air-gapped one-YAML-swap (moat #7, C5) is **unaffected**: identical
factory contract on both constructors.

Note: W3's sync `/decide` hot path is **model-free** (Defender deterministic +
Supervisor deterministic) — no `create_agent`/LLM node is on the blocking path
(HG#5: 0 LLM tokens on decide→BLOCK). This ADR governs the *async* Evaluator
grey-band / Supervisor `arbitrate()` / Auditor-narrative nodes only.

## Consequences

- Drift between the design corpus's named constructor and the shipped code is
  recorded here (ADR supersedes; no doc rewrite — corpus is internal).
- Zero impact on the FROZEN §4 contract, the `ShieldModelRouter` moat, or the
  InjectionTask6 thesis (all model-free).
- Folded into the G3 milestone report; not user-escalated (LOW / non-blocking /
  design-faithful in intent).
