# `contracts/` — the FROZEN §4 integration boundary

This directory is the hard, change-controlled boundary between the five parallel
builders. The **runtime** pydantic models live in exactly one place
(`packages/shield-sdk/src/shield_sdk/schema.py`); server, governance and eval
**import** them and never re-declare them — drift is impossible by construction.
This directory holds the **frozen artifacts** CI diffs on every PR:

| Artifact | Purpose |
|---|---|
| `shield_action_record.schema.json` | JSON-Schema snapshot of `ShieldActionRecord` |
| `governance_verdict.schema.json`   | JSON-Schema snapshot of `GovernanceVerdict` |
| `elydora/*.schema.json`            | Elydora REST DTO schemas (the `@elydora/shared` replacement — see `elydora/README.md`) |
| `examples/*.json`                  | canonical pre_exec / post_exec / verdict / verdict_escalate envelopes |
| `golden/vectors.json`              | cross-impl crypto vectors vs Elydora's reference Python SDK |
| `codegen/`                         | JSON-Schema → TypeScript generator feeding `console/` |

## Status: W0 STUBS

Everything here is a **W0 compile-unblock stub**. The real freeze happens at
**W1**: `sdk-builder` finalizes `shield_sdk.schema` as `shield_version` **1.1**
(the §4 baseline *including* the three optional cost fields) and regenerates
these snapshots. The `1.0 → 1.1` MINOR bump is the **single planned all-owner
contract ritual** (ADR-0007), executed once at W1 *before* any consumer builds.

## Change ritual (after W1 freeze — the only place a mistake propagates)

A genuine §4 change = proposer SendMessages the integrator → ADR + a single
`contracts/` PR → **all** module owners sign (CODEOWNERS-enforced) → merge →
all builders rebase. No unilateral `contracts/` edits, ever. After the W1 v1.1
freeze, this ritual exists only to *reject* further changes.
