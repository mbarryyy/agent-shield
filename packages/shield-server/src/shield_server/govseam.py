"""gov↔server decide-seam (W3 PR-S1) — the locked Channel-1 in-process seam.

Division of ownership (master §1.2 step 3 / §2.3 / §3.2):
  * SERVER owns: the 12-step canonical ingest, verdict **signing** (the
    shield-server key, via ``shield_sdk.canonical.finalize_verdict``),
    ``intervention_log`` write, Channel-2 XADD, latency/served_at — and the
    chained record identity.
  * GOVERNANCE owns: the verdict DECISION — the gov ``decide()`` aggregate
    (deterministic Defender + ``create_agent`` Evaluator agent per M2
    Phase B + single-prompt Supervisor/Auditor scaffold). It returns an
    **UNSIGNED** ``GovernanceVerdict``; the server signs it (server holds
    the key, W2 HG#1 carry-forward).

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

    async def resume(
        self, incident_id: str, decision: str, payload: dict[str, object] | None
    ) -> GovernanceVerdict:
        """HITL resume (PR-S5): re-enter the paused LangGraph incident with the
        human decision (accept|edit|response|ignore — gov §3.3 interrupt
        schema). Returns the post-resume verdict UNSIGNED; server signs."""
        ...


class NullGovernanceApp:
    """Honest W3 staged-delivery default: UNSIGNED PASS (server signs).

    This is NOT a real governance verdict and is labelled as such in
    ``reasons[]`` — it keeps the server independently green until the real
    gov ``decide()`` app is wired (gov Task #21), exactly the W2
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
                        "gov decide() verdict pending gov Task #21."
                    ),
                    score=0.0,
                )
            ],
        )

    async def resume(
        self, incident_id: str, decision: str, payload: dict[str, object] | None
    ) -> GovernanceVerdict:
        return GovernanceVerdict(
            correlation_id=incident_id,
            decision=Decision.PASS,
            risk_score=0.0,
            reasons=[
                VerdictReason(
                    agent=Guardian.SUPERVISOR,
                    label="HITL_RESUME_STUB",
                    detail=(
                        "server HITL-resume seam default (NullGovernanceApp) — "
                        "real LangGraph Command(resume=) pending gov Task #21."
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

    def __init__(self, decide_fn: object, resume_fn: object, app: object) -> None:
        self._decide_fn = decide_fn
        self._resume_fn = resume_fn
        self._app = app

    async def decide(self, rec: ShieldActionRecord) -> GovernanceVerdict:
        verdict: GovernanceVerdict = await self._decide_fn(self._app, rec)  # type: ignore[operator]
        return verdict

    async def resume(
        self, incident_id: str, decision: str, payload: dict[str, object] | None
    ) -> GovernanceVerdict:
        verdict: GovernanceVerdict = await self._resume_fn(  # type: ignore[operator]
            self._app, incident_id, decision, payload
        )
        return verdict


def load_governance_app() -> GovernanceApp:
    """Pre-warm the real gov app if its converged surface is importable; else
    the honest Null default. Optional runtime import — NOT a shield-server
    pyproject dep (keeps server independently buildable; gov is a workspace
    member so it imports in CI/integration once gov W3 lands the surface).

    Symbol resolution is STATE-ROBUST: ``getattr(gov, name, None)`` is
    statically ``Any`` regardless of whether ``shield_governance`` exports the
    seam fns yet, so this is mypy-clean BOTH when gov-W3 is absent (no
    ``build_decide_app``/``decide``/``resume`` → None → honest Null) AND when
    gov-W3 is present (real callables → adapter) — with NO ``# type: ignore``
    here, so ``warn_unused_ignores`` cannot go red as the cascade advances
    (this is exactly the W3-cascade-red root cause being removed). The
    3-fn-presence requirement, honest-Null fallback and ``_GovSeamAdapter``
    semantics are preserved unchanged."""
    try:
        import shield_governance as gov
    except ImportError:
        return NullGovernanceApp()
    build_decide_app = getattr(gov, "build_decide_app", None)
    decide_fn = getattr(gov, "decide", None)
    resume_fn = getattr(gov, "resume", None)
    if build_decide_app is None or decide_fn is None or resume_fn is None:
        return NullGovernanceApp()  # gov W3 seam not exported yet → honest Null
    # Build the decide-app WITH a checkpointer so the escalate/interrupt node is
    # compiled into the graph and HITL resume() works (gov build_decide_app adds
    # the escalate node + enables Command(resume=…) only when a checkpointer is
    # supplied). InMemorySaver is the W4 dev/single-process saver; a durable
    # PostgresSaver is deferred. Without this the server's
    # POST /v1/governance/incidents/{id}/resume path is dead and no ESCALATE
    # incident can ever pause.
    from langgraph.checkpoint.memory import InMemorySaver

    return _GovSeamAdapter(decide_fn, resume_fn, build_decide_app(checkpointer=InMemorySaver()))
