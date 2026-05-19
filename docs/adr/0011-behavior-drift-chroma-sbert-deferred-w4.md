# 0011 — Behavior-drift / Chroma-SBERT staging deferred to W4 (wired-behind-sub-flag at W3)

- Status: Accepted
- Date: 2026-05-20
- Deciders: governance-builder (Task #21, proposed the cut); team-lead (W3 board, accepted); reviewer (independently adjudicated ACCEPTABLE for G3 — 4 conditions attached); team-lead ratifies numbering/placement at merge

## Context and Problem Statement

`governance_design.md` §3.2 + `implementation_plan.md` line 74 specify the
Evaluator's `behavior_drift` / `peer_relative_anomaly` as a training-free
re-implementation of the GUARDIAN / XG-Guard *idea*: Sentence-BERT
`all-MiniLM-L6-v2` (XG-Guard `MA/Ours.py:238`) embeddings vs a
per-(agent,workflow,tool) **Chroma centroid built from a benign staging run** +
parameter-free fusion (`Ours.py:395-399,428-459`). GUARDIAN/XG-Guard repos are
themselves training-bound / unlicensed (governance_design §1) → the *idea*
only, never their weights.

The full mechanism requires: a benign-staging harness to produce baseline
traffic, Chroma centroid construction/persistence, SBERT model staging, and
fusion tuning. That is materially larger than the rest of the W3 Evaluator and
is **not the InjectionTask6 thesis**: the model-free $30k structuring defeat is
W2-proven via the deterministic `CumulativeRecipientTracker` + Invariant
`LocalPolicy` (HG#5) — drift is *additive Act-2 depth* (intent/anomaly
narration), not the Act-3 money-shot. Shipping it fully at W3 risks the G3
gate (impl_plan line 35 e2e-A/B + FPR + console-contract) for non-thesis depth.

## Considered Options

- **A — Build full benign-staging + Chroma centroid + SBERT at W3.** Rejected:
  largest W3 unit, not the thesis, jeopardizes a reviewable on-time G3; the
  binding G3 gate does not enumerate full drift-staging.
- **B — Drop `behavior_drift` from scope.** Rejected: silently dropping
  impl_plan-line-74 scope is thesis-erosion-by-omission and unauditable.
- **C — Wire it, behind an OFF-by-default sub-flag, baseline-seedable, with
  the real detector RAISING until W4; defer the benign-staging baseline to W4;
  record the carry here.** The seam exists and is honest; nothing fakes a
  "drift" value.

## Decision

**Option C.** W3 ships:

- `EvaluatorConfig.drift_enabled: bool = False` — **OFF by default**.
- `NullDriftDetector` (the default): returns a genuine `0.0` (no drift) — it is
  a true no-op, **not** a hardcoded/scripted "drift" constant masquerading as a
  measured value. The drift multiplier is always a RUNTIME OUTPUT, never an
  asserted constant (reviewer Condition 2 / HG#6-adjacent).
- `SbertChromaDriftDetector` — the WIRED seam; its `__init__` and `score`
  **raise `NotImplementedError("W4: …")`** so it can never silently no-op into
  a false `PASS`. Any reachable drift path is explicitly W4-labeled in code.

**W4 completes:** the benign-staging harness, Chroma per-(agent,workflow,tool)
centroid construction/persistence, SBERT `all-MiniLM-L6-v2` local staging, the
parameter-free fusion, and flipping `drift_enabled` on with a genuine
embedding-distance computation vs the seeded centroid.

This cut does **not** weaken HG#5: the InjectionTask6 BLOCK is the deterministic
model-free predicate (Defender + Invariant `LocalPolicy`), 0 LLM tokens on
decide→BLOCK — entirely independent of drift. FPR (UserTask0/10 ≤10%, reviewer
Condition 4) is evaluated against whatever Evaluator logic is LIVE; the cut is
not a backdoor to dodge FPR — Invariant cross-step + exfil + hallucination run
REAL.

## Consequences

- The W3→W4 drift carry is a conscious, auditable deferral recorded here (not a
  silent scope drop) — this ADR is what makes the cut legitimate.
- Zero §4/contract impact; zero impact on the money-shot / HG#5.
- Reviewer's G3 gate enforces: model-free BLOCK (Cond 1), honest deferral
  representation (Cond 2 — this ADR + the raising detector + OFF-default), this
  ADR (Cond 3), FPR-holds-with-live-logic (Cond 4).
- Folded into the G3 milestone report; not user-escalated (planned scope
  sequencing, thesis intact).
