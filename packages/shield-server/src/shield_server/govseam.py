"""gov↔server decide-seam (W3 PR-S1) — the locked Channel-1 in-process seam.

Division of ownership (master §1.2 step 3 / §2.3 / §3.2):
  * SERVER owns: the 12-step canonical ingest, verdict **signing** (the
    shield-server key, via ``shield_sdk.canonical.finalize_verdict``),
    ``intervention_log`` write, Channel-2 XADD, latency/served_at — and the
    chained record identity.
  * GOVERNANCE owns: the verdict DECISION — the real LangGraph 4-guardian
    aggregate. It returns an **UNSIGNED** ``GovernanceVerdict``; the server
    signs it (server holds the key, W2 HG#1 carry-forward).

Pre-warmed ONCE at server startup into ``app.state.governance`` (master §1.2
step 3 / §2.3 "pre-warmed LangGraph app, no cold start in the 500 ms budget").

Default = an **honest** ``NullGovernanceApp`` → UNSIGNED PASS (explicitly
labelled a staged-delivery stub, NOT a faked-real verdict) until governance's
``build_decide_app()`` lands (Task #21). The real gov app is an OPTIONAL
runtime import (NOT a shield-server pyproject dependency) so the server stays
independently buildable/testable; ``shield_governance`` is a uv-workspace
member, importable in CI/integration once Task #21 ships its converged surface.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from shield_sdk.schema import (
    Decision,
    GovernanceVerdict,
    Guardian,
    ShieldActionRecord,
    VerdictReason,
)


@runtime_checkable
class GovernanceApp(Protocol):
    """The seam the server calls. Implementations return an UNSIGNED verdict —
    the server attaches served_at/latency/shield_kid and the signature."""

    async def decide(self, rec: ShieldActionRecord) -> GovernanceVerdict: ...


class NullGovernanceApp:
    """Honest W3 staged-delivery default: UNSIGNED PASS (server signs).

    This is NOT a real governance verdict and is labelled as such in
    ``reasons[]`` — it keeps the server independently green until the real
    LangGraph 4-guardian app is wired (gov Task #21), exactly the W2
    stub→PASS discipline carried into the W3 seam.
    """

    async def decide(self, rec: ShieldActionRecord) -> GovernanceVerdict:
        return GovernanceVerdict(
            record_id=rec.record_id,
            correlation_id=rec.correlation_id,
            run_id=rec.run_id,
            decision=Decision.PASS,
            risk_score=0.0,
            reasons=[
                VerdictReason(
                    agent=Guardian.DEFENDER,
                    label="STUB_PASS",
                    detail=(
                        "server decide-seam default (NullGovernanceApp) — real "
                        "LangGraph 4-guardian verdict pending gov Task #21."
                    ),
                    score=0.0,
                )
            ],
        )


class _GovSeamAdapter:
    """Adapts the converged ``shield_governance`` module surface —
    ``build_decide_app() -> GovApp`` + ``async decide(app, rec) ->
    GovernanceVerdict`` (server W3 proposal / gov Task #21) — to the
    server-side ``GovernanceApp`` protocol (``.decide(rec)``)."""

    def __init__(self, decide_fn: object, app: object) -> None:
        self._decide_fn = decide_fn
        self._app = app

    async def decide(self, rec: ShieldActionRecord) -> GovernanceVerdict:
        verdict: GovernanceVerdict = await self._decide_fn(self._app, rec)  # type: ignore[operator]
        return verdict


def load_governance_app() -> GovernanceApp:
    """Pre-warm the real gov app if its converged surface is importable; else
    the honest Null default. Optional runtime import — NOT a shield-server
    pyproject dep (keeps server independently buildable; gov is a workspace
    member so it imports in CI/integration once Task #21 lands the surface).
    ``(ImportError, AttributeError)`` = "gov not ready yet" → Null; any other
    exception propagates (a real gov-import bug must surface, not be hidden)."""
    try:
        import shield_governance as gov

        build_decide_app = gov.build_decide_app  # type: ignore[attr-defined]
        decide_fn = gov.decide  # type: ignore[attr-defined]  # the seam fn
    except (ImportError, AttributeError):
        return NullGovernanceApp()
    return _GovSeamAdapter(decide_fn, build_decide_app())
