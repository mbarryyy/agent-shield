# 0012 — Async-path `shield:verdicts` publish deferred to W4 (W3: server gate-path is the sole signed publisher)

- Status: Accepted
- Date: 2026-05-20
- Deciders: governance-builder (Task #21, flagged the seam — did not guess); team-lead (Part-2 ruling = Option C, brokered server↔gov); reviewer (gates ADR-0012 legitimacy at G3, mirroring ADR-0011 Condition-3 discipline); team-lead ratifies numbering/placement at merge

## Context and Problem Statement

The relayed locked `shield:verdicts` invariant (seam-1 + server PR-S3,
server-derived in-code from `governance._fan_verdicts`): the shield **server**
is the SOLE `shield:verdicts` publisher — it attaches `signature_by_shield` /
`served_at` / `latency_ms`, signs with the shield-server key, and only THEN
`xadd`s the **SIGNED** §4 `GovernanceVerdict` JSON to
`shield:verdicts:{workflow_id}`. Governance returns the verdict **UNSIGNED**
and never signs (seam-1).

`master_design.md` §1.2 step 8 also says async Channel-2 consumers
(`shield-evaluator`/`shield-auditor`) feed `shield:verdicts`. The W3 gov build
had `make_async_channel2_handler` publishing the async Evaluator/Auditor
late-analysis verdict directly via a gov-side `VerdictPublisher` — an
**UNSIGNED** verdict, published by gov. That collides with the locked
invariant (server is sole publisher; every published verdict is SIGNED; no
gov-side double-publish). governance-builder flagged this rather than guessing
(W2 field-map discipline).

## Considered Options

- **A — New async gov→server signing-handoff:** gov hands the async unsigned
  verdict to a new server seam; server signs+fans. Rejected for W3: adds
  net-new W3 seam-surface for W4-grade non-thesis depth under cascade pressure.
- **B — Gov fans async verdicts UNSIGNED on its own group:** breaks the locked
  invariant (server sole publisher; all published verdicts SIGNED) and the
  audit-integrity story. Rejected.
- **C — Defer gov-side async publish to W4.** The W3 thesis / money-shot /
  G3-gate is the **sync `/decide` gate path**: the InjectionTask6 $30k BLOCK
  fires at the pre-exec gate (sync), server signs + `_fan_verdicts` publishes
  that SIGNED gate verdict, console renders it (SSE) and the provenance DAG via
  the `/runs/{id}/provenance` READ endpoint (server returns DATA) — **not** via
  `shield:verdicts`. Async Evaluator/Auditor late-analysis verdicts on the
  stream are non-thesis depth, not required for the W3 demo/G3.

## Decision

**Option C (team-lead Part-2 ruling).** At W3:

- `make_async_channel2_handler` **COMPUTES** the Evaluator/Auditor/Supervisor
  verdict (the async pipeline is real and unit-tested) but does **NOT** publish
  `shield:verdicts`. It exposes an optional `on_verdict` test/W4 sink
  (default `None` = compute-only); no gov-side publish, no double-publish, no
  unsigned verdict on the stream.
- The shield server's gate-path `_fan_verdicts` is the **SOLE W3
  `shield:verdicts` publisher** (signs-then-fans — locked invariant pristine).
- `verdicts.py` (`verdict_fields` = the locked PR-S3 FLAT 8-field envelope +
  `VerdictPublisher`) is retained **test-only / W4-ready** (the 8-field
  contract stays unit-tested so W4 wiring is a drop-in).
- **W4** wires the async fan with the signing division resolved (Option A-style
  gov→server handoff, or a server-side async consumer) — out of W3 scope.

This does **not** weaken HG#5 or the demo: the money-shot is the sync gate
path (model-free Defender + Invariant `LocalPolicy`, 0 LLM tokens
decide→BLOCK); provenance reaches console via a READ endpoint, not the stream.
Smallest correct W3 change, zero new seam, locked invariant untouched — mirrors
the reviewer-blessed ADR-0011 W3→W4 scoping discipline.

## Consequences

- The W3→W4 async-publish carry is a conscious, auditable deferral recorded
  here (not a silent drop) — master_design §1.2-step-8 async fan is explicitly
  carried, not erased.
- Zero §4/contract impact; zero impact on the money-shot / HG#5 / the G3 demo
  (sync gate path + READ-endpoint provenance).
- gov ADR set: 0009 (create_agent) · 0010 (invariant 0.3.5 `count(min=3)`) ·
  0011 (drift→W4) · **0012 (async-publish→W4)**.
- Folded into the G3 milestone report; not user-escalated (planned scope
  sequencing, thesis + locked invariant intact).
