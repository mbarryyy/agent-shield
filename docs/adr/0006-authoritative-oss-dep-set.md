# 0006 — Authoritative OSS dependency set (C10)

- Status: Accepted
- Date: 2026-05-18
- Deciders: integration-architect (Task #5, C10 closer), delivery-architect (Task #8, code-verified vs PurpleLlama + guardrails-ai clones), team-lead

## Context and Problem Statement

The Layer-2 defender/scanner dependency set was specified loosely across earlier
docs ("guardrails-ai", "PromptGuard2-22M", bare Invariant `Policy`, a hard local
model-serving dep). Code verification against the cloned PurpleLlama and
guardrails-ai repos shows several of these are wrong or air-gap-hostile (C5/MOAT
risk). The dependency graph for five parallel builders must be authoritative now.

## Considered Options & Findings

- **`guardrails-ai`** — `guardrails-ai/pyproject.toml version = "0.10.0"` ships
  **zero in-repo validators** (`guardrails/validators/` is only `__init__.py`);
  all validators are token-gated network hub installs ⇒ air-gap / C5 violation.
- **PromptGuard model size** — LlamaFirewall's `_load_model_and_tokenizer`
  (`PurpleLlama/LlamaFirewall/src/llamafirewall/scanners/promptguard_utils.py`)
  loads `meta-llama/Llama-Prompt-Guard-2-**86M**` by default; the "-22M" label
  carried from §5d is **stale** (a 22M variant exists upstream but is not what
  LlamaFirewall loads).
- **Invariant `invariant-ai`** — Apache-2.0 but Snyk-owned post-2025. Bare
  `Policy` calls a **remote hosted API** (data egress = air-gap / MOAT
  violation, C5); `LocalPolicy` is pure-local, sub-ms, whole-trace.
- **Local model serving** — needed for the §7 zero-egress MOAT but the demo
  uses cloud APIs; making vLLM/Ollama a hard dep bloats every worktree.

## Decision Outcome

Chosen authoritative set:

- **`guardrails-ai` DROPPED.** PII/IBAN coverage moves to LlamaFirewall's
  Regex/HiddenASCII scanners + our own regex.
- **LlamaFirewall** (Meta PurpleLlama, framework MIT) with **PromptGuard2-86M** +
  CodeShield on the local hot path.
- **`invariant-ai` pinned EXACT** (never floated); import **`LocalPolicy` only**,
  never bare `Policy`. `LocalPolicy` catches the $30k cumulative structuring a
  single-call rule cannot.
- **Local serving behind the `ShieldModelRouter` config seam**, NOT a hard dep
  (cloud APIs ↔ local vLLM/Ollama, zero-egress, config-selected; owned by Task
  #7). The dep graph reserves the `ShieldModelRouter` seam now.

### Consequences

- Smaller, air-gap-safe Layer-2 dep set; governance-builder builds against
  exactly this set (`shield-governance/pyproject.toml` floors:
  `networkx>=3.2`, `pyyaml>=6.0.1`; W1 adds `langgraph`,
  `langgraph-checkpoint-postgres`, `chromadb`, `llamafirewall`,
  `invariant-ai==<exact-pin>`).
- No token-gated network installs in the hot path → the air-gap / `egress=0`
  attestation (#7) stays provable.

## Evidence (§5b)

`guardrails-ai/pyproject.toml` + `guardrails/validators/`;
`PurpleLlama/LlamaFirewall/.../promptguard_utils.py`. tech_stack.md §3.1/§4,
implementation_plan.md W0 step 5/6.
