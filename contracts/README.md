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

## Status: FROZEN at shield_version 1.1 (ADR-0007)

These artifacts are regenerated from the single pydantic source of truth
`packages/shield-sdk/src/shield_sdk/schema.py` via
`packages/shield-sdk/tests/_tools/gen_contract_snapshots.py`
(`additionalProperties: false` on every closed object — O5; `payload.tool_args`
/ `subject` stay open by design). The `1.0 → 1.1` MINOR bump (the three
optional cost fields + the W0-stub→§4 corrections) is the **single planned
all-owner contract ritual** (ADR-0007), ratified once *before* any consumer
builds. After this, §4 is frozen at v1.1.

## Change ritual (after W1 freeze — the only place a mistake propagates)

A genuine §4 change = proposer SendMessages the integrator → ADR + a single
`contracts/` PR → **all** module owners sign (CODEOWNERS-enforced) → merge →
all builders rebase. No unilateral `contracts/` edits, ever. After the W1 v1.1
freeze, this ritual exists only to *reject* further changes.
