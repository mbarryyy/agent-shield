# 0007 — §4 frozen at shield_version 1.1 (the cost-field MINOR bump, C11)

- Status: Accepted
- Date: 2026-05-19
- Deciders: team-lead (runs the ritual), sdk-builder (SoT proposer), and ALL
  module owners — server-builder, governance-builder, eval-builder,
  console-builder (CODEOWNERS sign-off on `contracts/`)
- Sign-off: team-lead (integrator) + independent reviewer (G1 §4-ritual
  hard-gate PASS, reframed criteria #1/#2a/#2b/#2c/#3/#4/#5 independently
  verified, golden byte-exact vs Elydora ref SDK). All-owner acceptance
  operationalized via the designed consumer rebase-onto-v1.1 + reviewer
  re-review (O4 procedural — CODEOWNERS handles are not GitHub accounts).

## Context and Problem Statement

The §4 contract (`sdk_layer_design.md` §4) is the single hard coupling between
the five parallel builders. The W0 scaffold shipped a `contracts/` *stub* at a
placeholder `shield_version` "1.1". W1 freezes the real contract. Two things
must happen exactly once, before any consumer builds against the schema:

1. The three planned cost-model fields (C11 / commercial stress test hooks
   #2,#4) must enter `GovernanceVerdict` — `reasons[].model_id`,
   `reasons[].served_via`, `obligations.prevented_loss`. Per delivery #8's own
   rule (`cicd.md`:218 / :298-299) *any* §4 change ⇒ `shield_version` bump +
   `contracts/*.schema.json` regen + ADR + all-owner CODEOWNERS sign-off.
   Treating these as a silent "free additive" would surprise a later builder
   with a contract gate mid-build (the verifier-MEDIUM C11 failure mode).
2. While finalizing `shield_sdk.schema` from §4, sdk-builder found W0-stub
   field choices that diverge from §4 (the sole source of truth) and must be
   corrected as part of the same one-time freeze (below).

## Decision Outcome

Bump `shield_version` **1.0 → 1.1** as a single, planned MINOR evolution,
ratified once here via the full all-owner ritual, landing in the frozen
baseline **before** server/governance/eval/console depend on it. The three
cost fields are optional-with-default so W1/W2 stub consumers do not break.
After this, §4 is frozen at v1.1 and the ritual exists only to *reject*
further changes.

The single pydantic source of truth is `packages/shield-sdk/src/shield_sdk/
schema.py`; `contracts/*.schema.json` are regenerated from it by
`packages/shield-sdk/tests/_tools/gen_contract_snapshots.py`, with
`additionalProperties: false` on every closed object (O5) so the snapshot-diff
firewall actually bites (open maps `payload.tool_args`, `subject`, and
`obligations.rewrite_args` — the same sanitized-`FunctionCall.args` class —
stay open by design).

### v1.1 delta ledger — every field traceable to §4 or the 3 cost fields

Line cites are `sdk_layer_design.md` §4.1 (`ShieldActionRecord`, the JSONC
block lines 119–160 + L161 narrative) and §4.2 (`GovernanceVerdict`, lines
165–191). Tag legend: **COST** = one of the 3 planned C11 cost fields;
**FIX** = W0-stub→§4 correction (the stub was the off-spec party — it was
explicitly a compile-unblock stub for sdk-builder to freeze at W1); **BASE**
= §4 baseline field, unchanged in intent from the stub. The reframed G1 gate
rejects any v1.1 field not in this ledger.

#### `ShieldActionRecord` (§4.1)

| v1.1 field | tag | §4 cite | note |
|---|---|---|---|
| `shield_version` | FIX | §4.1 L121 | §4 shows `"1.0"`; the 1.0→1.1 bump **is** this ritual |
| `record_id` | BASE | §4.1 L122 | == Elydora `operation_id` (chain `operation_id`) |
| `correlation_id` | BASE | §4.1 L123 | pairs pre↔post |
| `org_id` | BASE | §4.1 L124 | |
| `agent_id` | BASE | §4.1 L125 | |
| `workflow_id` | BASE | §4.1 L126 | |
| `run_id` | BASE | §4.1 L127 | |
| `step_index` | BASE | §4.1 L128 | |
| `issued_at` | FIX | §4.1 L129 | stub `str` → **`int` unix-epoch-ms** (`// unix ms`). Required for byte-exact `chain_hash` (`SHA-256(prev\|payload_hash\|record_id\|issued_at)`) parity with Elydora + shield-server |
| `ttl_ms` | FIX | §4.1 L130 | stub omitted |
| `nonce` | BASE | §4.1 L130 | |
| `phase` | BASE | §4.1 L132 | enum `{pre_exec,post_exec}` |
| `action_type` | FIX | §4.1 L133 | stub omitted; enum `{tool_call,llm_inference,decision,checkpoint,escalation}` |
| `operation_type` | FIX | §4.1 L134 | stub omitted; Elydora-compat mirror |
| `subject` | FIX | §4.1 L136–137 | stub omitted; open map (scenario-specific) by design |
| `action.tool` | FIX | §4.1 L138 | stub had no `action`; |
| `action.args_digest` | FIX | §4.1 L139 | stub had a flat top-level `args_digest`; §4 nests under `action` |
| `payload.tool_name` | FIX | §4.1 L141 | stub had a flat top-level `tool_name`; §4 nests under `payload` |
| `payload.tool_args` | FIX | §4.1 L142–143 | stub omitted; open map by design |
| `payload.tool_result` | FIX | §4.1 L144 | stub omitted; null on pre, result on post |
| `payload.tool_error` | FIX | §4.1 L145 | stub omitted |
| `payload.llm.{model,prompt_tokens,completion_tokens}` | BASE | §4.1 L146 | stub had this sub-object; cost hook #1 (already §4) |
| `payload.confidence` | FIX | §4.1 L147 | stub omitted |
| `context.checkpoint_id` | BASE | §4.1 L150 | dual-substrate rollback key |
| `context.langgraph_thread_id` | BASE | §4.1 L151 | |
| `context.env_snapshot_ref` | BASE | §4.1 L152 | |
| `payload_hash` | BASE | §4.1 L154 | |
| `prev_chain_hash` | BASE | §4.1 L155 | default = GENESIS |
| `chain_hash` | BASE | §4.1 L161 | server-derived ONLY; excluded from the signable projection |
| `agent_pubkey_kid` | FIX | §4.1 L156 | stub omitted |
| `verdict_ref` | BASE | §4.1 L157 | post_exec → matching gate verdict_id |
| `signature` | BASE | §4.1 L158 | b64url Ed25519 |
| ~~top-level `tool_name`~~ | FIX (removed) | §4.1 L141 | stub had it flat; §4 nests it under `payload` (→ `payload.tool_name`) |
| ~~top-level `args_digest`~~ | FIX (removed) | §4.1 L139 | stub had it flat; §4 nests it under `action` (→ `action.args_digest`) |

#### `GovernanceVerdict` (§4.2)

| v1.1 field | tag | §4 cite | note |
|---|---|---|---|
| `shield_version` | FIX | §4.1 L121 | the 1.0→1.1 ritual bump (versioning parallels §4.1) |
| `verdict_id` | FIX | §4.2 L167 | stub omitted |
| `record_id` | FIX | §4.2 L168 | stub omitted; the pre_exec it judges |
| `correlation_id` | BASE | §4.2 L169 | |
| `run_id` | FIX | §4.2 L170 | stub omitted |
| `decision` | BASE | §4.2 L171 | enum `{PASS,ALERT,BLOCK,ESCALATE,ROLLBACK,REWRITE}` |
| `risk_score` | BASE | §4.2 L172 | 0..1 |
| `reasons[].agent` | FIX | §4.2 L174 | stub had `guardian` → §4 name `agent` (enum `{defender,evaluator,supervisor,auditor}`) |
| `reasons[].label` | FIX | §4.2 L174 | stub had `code` → §4 name `label` |
| `reasons[].detail` | FIX | §4.2 L174 | stub had `message` → §4 name `detail` |
| `reasons[].score` | FIX | §4.2 L174–175 | stub omitted |
| `reasons[].model_id` | **COST** | C11 | master_design §2.2/§2.5 hook #2; not in raw §4.2 — the planned additive |
| `reasons[].served_via` | **COST** | C11 | master_design §2.2/§2.5 hook #2; enum `{cloud,local}` |
| `obligations.mask_args` | BASE | §4.2 L178 | |
| `obligations.rewrite_args` | BASE | §4.2 L179 | on REWRITE |
| `obligations.require_human` | BASE | §4.2 L180 | |
| `obligations.rollback.langgraph_checkpoint_id` | BASE | §4.2 L182 | dual-substrate |
| `obligations.rollback.env_snapshot_ref` | BASE | §4.2 L183 | dual-substrate |
| `obligations.prevented_loss` | **COST** | C11 | master_design §2.2/§2.5 hook #4 |
| `latency_ms` | BASE | §4.2 L186 | |
| `served_at` | FIX | §4.2 L187 | stub omitted |
| `shield_kid` | FIX | §4.2 L188 | stub omitted |
| `signature_by_shield` | FIX | §4.2 L189 | stub omitted; b64url Ed25519, EAR-like |
| ~~`confidence`~~ | FIX (removed) | §4.2 (absent) | stub had a speculative verdict `confidence`; §4.2 has no such field (`confidence` exists only on §4.1 `payload` L147) → dropped |

Net: **3 COST fields** (C11), **0 fields without a §4 or C11 trace**. Every
`FIX` row aligns the off-spec W0 stub to §4; every `BASE` row is unchanged §4
intent. Cost fields are optional-with-default ⇒ W1/W2 stub consumers don't
break.

### Signable-field projection (frozen, server-builder imports it)

`model_dump(mode="json", exclude_none=True)` minus `signature`
(+ `chain_hash` for records, server-derived/never-signed); **present-null ≡
absent ≡ omitted**; empty containers kept. Defined once in
`shield_sdk.canonical`; shield-server's 12-step ingest imports it and never
re-derives the rule. Cross-impl golden vectors (`contracts/golden/
vectors.json`) were captured byte-exact from Elydora's reference Python SDK
and are re-verified by `contracts/test_golden_vectors.py`.

## Considered Options

- **(a) Planned one-time MINOR bump via the full ritual at W1** (chosen) —
  closes verifier-MEDIUM C11; no mid-build surprise; firewall intact.
- **(b) Exempt additive fields from the all-owner ritual** — rejected:
  weakening the parallel-build firewall is the wrong trade in a 5-builder
  world, and that rule is delivery-owner-2's to own, not sdk-builder's to
  dilute.

### Consequences

- This `contracts/` PR is **separate** from the SDK feature PR (`feat/sdk`).
  It is green only against the v1.1 `shield_sdk.schema`, so it merges **with /
  after** `feat/sdk` (team-lead sequences as sole merger).
- server/governance/eval/console rebase onto v1.1 and build against the frozen
  baseline; optional-with-default ⇒ existing W0/W2 stubs keep compiling.
- After merge, §4 is frozen at v1.1; further change requires a new ADR +
  another all-owner ritual (the firewall now only rejects).

## Evidence (§5b)

Elydora `sdks/python/elydora/{crypto.py,utils.py}` (byte-exact port source);
`sdk_layer_design.md` §4.1/§4.2; `00_integration_conflicts.md` C11;
`agent_shield_master_design.md` §2.2/§2.5; `implementation_plan.md` W1 row +
cross-cutting seam #1. Golden vectors cross-verified against the Elydora
reference SDK at generation time (`gen_golden_vectors.py`).
