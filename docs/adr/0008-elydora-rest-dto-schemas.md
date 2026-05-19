# 0008 — Elydora REST DTO schemas in `contracts/` (replace `@elydora/shared` via codegen)

- Status: Accepted
- Date: 2026-05-19
- Deciders: team-lead, console-builder (Task #7); reviewer (independent contracts ritual)

## Context and Problem Statement

The inherited Elydora Next.js console imports its REST data-transfer types from
the package alias `@elydora/shared` — code-verified **across 14 files: 13
static `import … from '@elydora/shared'` statements + 2 inline
`import('@elydora/shared')` type expressions** (16 reference lines total; e.g.
`src/lib/api.ts:1-24` + `:199`, `src/lib/hooks.ts:6-15` + `:82`,
`src/components/OperationDetailClient.tsx:10`). `console/tsconfig.json` `paths`
mapped `@elydora/shared` → `../server/src/shared`, i.e. the **Hono server**
that Agent Shield replaces with the Python FastAPI backend. Once that server
package is gone the mapping target vanishes and the console fails
`tsc`/`build`/`lint` (the deferred `Console` G1 check cannot go green).

These ~30 symbols (`Agent`, `Operation`, `AuditQueryRequest/Response`,
`GetEpochResponse`, `Export`, `JWK`, `VerifyOperationResponse`, …) are **Elydora
REST DTOs**, *not* §4 governance types. The W0 `contracts/` codegen of the §4
snapshots (`shield_action_record` / `governance_verdict`) does **not** cover
them, and they are explicitly **out of scope** for ADR-0007 (the §4
`shield_version` 1.0→1.1 cost-fields MINOR — that diff must stay exactly the
three cost fields for the reviewer hard-gate).

## Considered Options

- **A — Vendor a hand-written copy** of `server/src/shared/types/*` into
  `console/src/`. Rejected: a second hand-maintained source of truth, drifts
  from the FastAPI backend, no mechanical enforcement, violates the
  single-firewall principle.
- **B — Expand the existing W0 codegen** to also emit the Elydora DTOs from
  schemas under `contracts/elydora/*.schema.json`, repoint the console's
  `@elydora/shared` alias to the generated `console/src/types/contracts.d.ts`.
  One JSON-Schema → TypeScript pipeline (`contracts/codegen/gen.mjs`, already
  W0-scaffolded and globbing `contracts/elydora/`), one change-controlled
  firewall for both §4 and DTO types.
- **C — Have server-builder publish a TS types artifact** from the FastAPI
  backend. Rejected for W1: couples the console's G1 to a Python→TS toolchain on
  the server critical path; the DTOs are stable Elydora shapes that do not need
  to be derived from FastAPI at this stage.

## Decision Outcome

Chosen option: **B**. `contracts/elydora/elydora_shared.schema.json` (50
`$defs`, transcribed **1:1, code-verified §5b** from
`Related_Work/Elydora-Open-Source-main/packages/server/src/shared/{index.ts,
types/enums.ts,types/entities.ts,types/protocol.ts,types/api.ts}`) mirrors the
**full** `@elydora/shared` public surface, so the generated module is a faithful
drop-in and no second contracts ritual is needed later. `contracts/codegen`
emits `console/src/types/contracts.d.ts`; `console/tsconfig.json` maps
`@elydora/shared` → `./src/types/contracts`.

Scope boundaries:

- This is a **console-support** addition to the `contracts/` firewall. It is
  **not** a §4 governance type and is **not** part of ADR-0007's scope. It does
  **not** bump `shield_version` and does **not** touch
  `shield_action_record.schema.json` / `governance_verdict.schema.json`.
- It lands as its **own dedicated `contracts/` ritual PR** (never bundled into a
  feature PR; never folded into the §4 ADR-0007 PR — keeps the reviewer's
  "§4 v1.1 diff == exactly the 3 cost fields" hard-gate clean). All-owner
  CODEOWNERS sign-off is **procedural** (reviewer independently reviews it as
  the contracts ritual; team-lead is sole merger).
- It is **independent** of the §4 ADR-0007 / sdk critical path: the console
  imports **zero** §4 types in W1.

### Consequences

- `console/src/types/contracts.d.ts` is a **generated artifact** under
  `/console/` ownership: never hand-edited; always produced by
  `cd contracts/codegen && npm run gen`. It is **committed** because the ci.yml
  `console` job runs `npm ci/lint/typecheck/build` only (not codegen).
- **Regen-in-same-PR rule:** any `contracts/` PR that changes a TS-affecting
  schema MUST, in that same PR, regenerate and commit
  `console/src/types/contracts.d.ts`; console-builder reviews that `console/`
  hunk; team-lead verifies byte-sync at merge. (So the future §4 v1.1/ADR-0007
  PR regenerates its §4-typed portion of `contracts.d.ts` with no merge
  collision.)
- A CI **`codegen-sync`** job mechanically enforces the above: it runs the
  codegen and fails on any `git diff` in `console/src/types/contracts.d.ts`.
- `contracts/codegen/package-lock.json` is added (W0 had none) so codegen is
  reproducible (pins `json-schema-to-typescript`).

## Evidence (§5b)

`Related_Work/Elydora-Open-Source-main/packages/server/src/shared/index.ts` +
`types/{enums,entities,protocol,api}.ts` (the transcription source);
`console/src/{lib/api.ts,lib/hooks.ts,components/*}` (the `@elydora/shared`
references: 13 static imports + 2 inline `import()` type expressions across 14
files); `contracts/codegen/gen.mjs` + `contracts/elydora/README.md` (W0
scaffold intent); `console/tsconfig.json` (the broken `paths` mapping).
Codegen verified deterministic and byte-identical to the consumer
(`feat/console`) committed `contracts.d.ts`. Master design §3.4 (console scope);
implementation_plan W1 console-builder row; cicd.md §2/§7 (CI gate, CODEOWNERS
contracts firewall).
