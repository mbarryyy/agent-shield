# `contracts/elydora/` — Elydora REST DTO schemas (the `@elydora/shared` replacement)

**Decision (user-approved at W0):** the existing Elydora console imports ~13
REST DTO type names from `@elydora/shared`, mapped (`tsconfig.json` paths) to
`../server/src/shared` — the Hono server being replaced by the Python FastAPI
backend. The W0 `contracts/` codegen of the **§4 governance** types
(`shield_action_record` / `governance_verdict`) does **not** cover these — they
are Elydora REST DTOs, not §4 Shield types.

So `contracts/` is the single type firewall for **both**:
1. the §4 Shield governance types (`../*.schema.json`), and
2. the Elydora REST DTOs the console needs (here, `contracts/elydora/*.schema.json`).

Both feed the one `contracts/codegen/` JSON-Schema → TypeScript pipeline, which
emits `console/src/types/contracts.d.ts`. The console's `@elydora/shared`
imports are repointed (via `tsconfig.json` paths) to that generated file, so the
console `tsc`/builds green once the Hono server is gone.

## W0 status: EMPTY (skeleton only)

The actual Elydora DTO schemas are generated at **W1** by `sdk-builder` (owns
`contracts/`) with `console-builder`, from the authoritative source
`Related_Work/Elydora-Open-Source-main/packages/server/src/shared/types/*.ts`
(`protocol.ts` / `api.ts` / `entities.ts` / `enums.ts`). Symbols to cover
(code-verified by console-builder): `Agent`, `Operation`,
`AuditQueryRequest/Response`, `GetEpochResponse`, `Export`, `ExportStatus`,
`JWK`, `JWKSResponse`, `RegisterAgentRequest`, `Receipt`, `AgentKey`,
`RbacRole`, `AgentStatus`, `KeyStatus`, `VerifyOperationResponse`,
`ErrorResponse`, … (15 import sites across 14 files).
