# 0004 — The governance verdict is the synchronous HTTP response

- Status: Accepted
- Date: 2026-05-18
- Deciders: integration-architect (Task #5), delivery-architect (Task #8), team-lead

## Context and Problem Statement

Two layer docs describe the verdict transport differently (tech_stack.md §4
conflict #4). SDK doc §4.3 is authoritative: the verdict is the **synchronous
HTTP response** to `POST /v1/governance/decide` (blocking, 500 ms budget,
fail-open → ALERT/WARN). Governance doc §4 sketches "an in-process callback the
SDK polls" — described loosely, it is the *same* request/response, not a second
mechanism. Five builders must implement exactly one transport or the two-phase
gate will not integrate.

## Considered Options

- **Synchronous request/response** (SDK §4.3) — one round-trip; the SDK blocks
  on `decide()` with a hard timeout and a per-tool fail policy.
- **Async callback / poll bus** (a literal reading of governance §4) — second
  channel, races the tool-execution gate, no upside over request/response.

## Decision Outcome

Chosen option: **synchronous request/response**. `POST /v1/governance/decide`
ingests the `pre_exec` record and returns the `GovernanceVerdict` in one
round-trip. The SDK enforces a 500 ms budget via `concurrent.futures`; on
timeout/transport failure it applies the per-tool fail-open/closed policy table
(fail-open → ALERT/WARN, fail-closed for `send_money`/`update_password`/
`update_scheduled_transaction`). There is **no** separate async callback bus.
Channel-2 (`XADD shield:actions`) carries the `post_exec` record afterwards and
is not the verdict path.

### Consequences

- shield-sdk implements blocking `decide()`; shield-server returns the verdict
  in the same response; shield-governance produces it inline behind `/decide`.
- ESCALATE must degrade deterministically inside AgentDojo's non-interactive
  `benchmark_suite()` (a designed-in seam owned by eval-builder; ADR-0005 for
  the runner that exercises it).

## Evidence (§5b)

SDK layer design §4.3 (authoritative); governance design §4 (loose restatement).
tech_stack.md §4 conflict #4.
