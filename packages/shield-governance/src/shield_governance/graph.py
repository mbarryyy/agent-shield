"""LangGraph 1.2.0 governance graph — W3 real 4-guardian.

* **Sync /decide hot path** (``build_decide_app`` → ``decide``): model-free
  ``DefenderEngine`` (UN-FLAGGED, ``enabled=True``) → deterministic
  ``Supervisor``. NO Evaluator/Auditor, NO LLM, NO arbiter on this path —
  **HG#5**: the model-free InjectionTask6 defeat is preserved THROUGH real
  ``/decide`` with the same deterministic predicate and **0 LLM tokens** on
  decide→BLOCK. Returns a FROZEN §4.2 v1.1 ``GovernanceVerdict`` **UNSIGNED**,
  canonical-stable via ``shield_sdk.canonical.verdict_signable_dict`` — the
  shield server owns Ed25519 signing (gov NEVER signs / NEVER redeclares §4).
* **Async Channel-2 path** (``make_async_channel2_handler``): Evaluator
  (Invariant cross-step + exfil + hallucination) + Auditor (chain/Merkle +
  provenance) → Supervisor re-aggregate → publish ``shield:verdicts``.
* **HITL** (``resume`` — server PR-S5): an ``escalate`` ``interrupt()`` node
  (side-effect-free, re-runs on resume — langgraph ``types.py:801/:814``);
  ``Command(resume=...)`` (``types.py:749``) + checkpointer (dev
  ``InMemorySaver`` / prod ``PostgresSaver``).

§5b primitives verified first-hand vs ``Related_Work`` clones AND probed live
in-env (langgraph 1.2.0): ``StateGraph/START/END`` (graph/state.py:130);
``interrupt``/``Command`` (types.py:801/:749); ``get_state_history``/
``update_state`` (pregel/main.py:1478/:2486) for time-travel rollback;
``InMemorySaver`` (checkpoint.memory). ADR-0009: guardian LLM nodes use the
``model=Callable`` factory (``create_react_agent`` deprecated → ``langchain.
agents.create_agent``; the ShieldModelRouter Callable seam is unchanged).

``langgraph`` is imported lazily inside the builders so importing this module
never pulls the framework.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypedDict

from shield_sdk.schema import (
    Decision,
    GovernanceVerdict,
    Phase,
    ShieldActionRecord,
)

from shield_governance.auditor import Auditor
from shield_governance.defender.engine import DefenderConfig, DefenderEngine
from shield_governance.evaluator import Evaluator
from shield_governance.supervisor import (
    GuardianSignals,
    Supervisor,
    signals_from_defender,
)
from shield_governance.verdicts import AsyncVerdictHandoff

#: Full guardian topology (governance_design §4 loop).
GUARDIAN_TOPOLOGY: tuple[str, ...] = ("defender", "evaluator", "supervisor", "auditor")


class GovernanceState(TypedDict, total=False):
    """Shared LangGraph state threaded through the guardians."""

    record: ShieldActionRecord  # incoming frozen §4 ShieldActionRecord
    defender: dict[str, Any]
    evaluator: dict[str, Any]
    auditor: dict[str, Any]
    supervisor: dict[str, Any]
    conflict: bool
    risk_score: float
    verdict: GovernanceVerdict


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #


def make_defender_node(
    engine: DefenderEngine,
) -> Callable[[GovernanceState], Awaitable[dict[str, Any]]]:
    """Bind the real (W3: un-flagged) Defender engine into an async node."""

    async def defender_node(state: GovernanceState) -> dict[str, Any]:
        verdict = await engine.assess(state["record"])
        return {
            "verdict": verdict,
            "risk_score": verdict.risk_score,
            "defender": {
                "decision": verdict.decision.value,
                "reasons": [r.label for r in verdict.reasons],
            },
        }

    return defender_node


def make_supervisor_node(
    supervisor: Supervisor,
) -> Callable[[GovernanceState], Awaitable[dict[str, Any]]]:
    """Compose the Defender (hot path) verdict via the deterministic
    Supervisor. No LLM unless Defender<->Evaluator conflict (absent on the sync
    path) — HG#5: 0 LLM tokens on decide→BLOCK."""

    async def supervisor_node(state: GovernanceState) -> dict[str, Any]:
        record = state["record"]
        defender_verdict = state["verdict"]
        signals = signals_from_defender(defender_verdict, phase=record.phase)
        final = supervisor.decide(signals, record=record)
        return {
            "verdict": final,
            "risk_score": final.risk_score,
            "supervisor": {"decision": final.decision.value},
        }

    return supervisor_node


def make_escalate_node() -> Callable[[GovernanceState], dict[str, Any]]:
    """Side-effect-free HITL pause. Re-runs on resume (langgraph types.py:814)
    so it does NO irreversible work — it surfaces the pending verdict and folds
    the human decision back in."""

    def escalate_node(state: GovernanceState) -> dict[str, Any]:
        from langgraph.types import interrupt

        verdict = state["verdict"]
        if verdict.decision != Decision.ESCALATE:
            return {}
        human = interrupt(
            {
                "verdict_id": verdict.verdict_id,
                "decision": verdict.decision.value,
                "risk_score": verdict.risk_score,
                "reasons": [r.label for r in verdict.reasons],
            }
        )
        resolved = _coerce_decision(human, default=verdict.decision)
        # 4-arg resume threads `payload` (edit|response data) — surfaced for
        # server/console; W3 does not auto-mutate gov-owned verdict fields from
        # free-form payload (unsound) — decision drives; payload is recorded.
        payload = human.get("payload") if isinstance(human, dict) else None
        new = verdict.model_copy(update={"decision": resolved})
        return {
            "verdict": new,
            "supervisor": {"decision": resolved.value, "hitl": True, "payload": payload},
        }

    return escalate_node


def _coerce_decision(value: object, *, default: Decision) -> Decision:
    if isinstance(value, Decision):
        return value
    if isinstance(value, str):
        try:
            return Decision(value)
        except ValueError:
            return default
    if isinstance(value, dict):
        return _coerce_decision(value.get("decision", ""), default=default)
    return default


# Topology placeholders (kept importable for agents/__init__ + the W3 contract).
def defender_node(state: GovernanceState) -> dict[str, Any]:  # pragma: no cover
    raise NotImplementedError("use make_defender_node(engine)")


def evaluator_node(state: GovernanceState) -> dict[str, Any]:  # pragma: no cover
    raise NotImplementedError("Evaluator runs async (make_async_channel2_handler)")


def supervisor_node(state: GovernanceState) -> dict[str, Any]:  # pragma: no cover
    raise NotImplementedError("use make_supervisor_node(supervisor)")


def auditor_node(state: GovernanceState) -> dict[str, Any]:  # pragma: no cover
    raise NotImplementedError("Auditor runs async (make_async_channel2_handler)")


# --------------------------------------------------------------------------- #
# W2 back-compat (defender-only graph + Channel-2 handler)
# --------------------------------------------------------------------------- #


def build_graph(engine: DefenderEngine, *, checkpointer: object | None = None) -> Any:
    """W2-compatible defender-only graph (START -> defender -> END)."""
    from langgraph.graph import END, START, StateGraph

    g: Any = StateGraph(GovernanceState)
    g.add_node("defender", make_defender_node(engine))
    g.add_edge(START, "defender")
    g.add_edge("defender", END)
    return g.compile(checkpointer=checkpointer) if checkpointer is not None else g.compile()


def make_channel2_handler(
    engine: DefenderEngine,
) -> Callable[[ShieldActionRecord], Awaitable[None]]:
    """W2-compatible Channel-2 handler (defender-only graph)."""
    app = build_graph(engine)

    async def handle(record: ShieldActionRecord) -> None:
        await app.ainvoke({"record": record})

    return handle


# --------------------------------------------------------------------------- #
# W3 — real /decide app (pre-warmed, in-process; server PR-S1 seam)
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class GovApp:
    """Pre-warmed governance app the shield server holds on
    ``request.app.state`` and invokes per ``/decide`` round-trip (no cold start
    in the 500 ms budget — master_design §1.2 step 3)."""

    app: Any
    defender: DefenderEngine
    supervisor: Supervisor
    has_checkpointer: bool


def build_decide_app(
    *,
    defender_config: DefenderConfig | None = None,
    supervisor: Supervisor | None = None,
    defender: DefenderEngine | None = None,
    checkpointer: object | None = None,
) -> GovApp:
    """Pre-warm the sync /decide graph: START → defender → supervisor [→
    escalate] → END. Defender is UN-FLAGGED here (``enabled=True``) — this is
    the real verdict path. Construct ONCE at server startup."""
    from langgraph.graph import END, START, StateGraph

    eng = defender or DefenderEngine(defender_config or DefenderConfig(enabled=True))
    sup = supervisor or Supervisor()

    g: Any = StateGraph(GovernanceState)
    g.add_node("defender", make_defender_node(eng))
    g.add_node("supervisor", make_supervisor_node(sup))
    g.add_edge(START, "defender")
    g.add_edge("defender", "supervisor")
    if checkpointer is not None:
        g.add_node("escalate", make_escalate_node())
        g.add_edge("supervisor", "escalate")
        g.add_edge("escalate", END)
        compiled = g.compile(checkpointer=checkpointer)
    else:
        g.add_edge("supervisor", END)
        compiled = g.compile()
    return GovApp(
        app=compiled,
        defender=eng,
        supervisor=sup,
        has_checkpointer=checkpointer is not None,
    )


async def decide(app: GovApp, record: ShieldActionRecord) -> GovernanceVerdict:
    """Server PR-S1 seam: sync /decide → UNSIGNED frozen §4 GovernanceVerdict
    (canonical-stable; server signs). Model-free hot path (HG#5)."""
    config = {"configurable": {"thread_id": record.run_id}} if app.has_checkpointer else None
    out = await app.app.ainvoke({"record": record}, config)
    verdict = out["verdict"]
    assert isinstance(verdict, GovernanceVerdict)
    return verdict


async def resume(
    gov_app: GovApp,
    incident_id: str,
    decision: Decision,
    payload: dict[str, Any] | None = None,
) -> GovernanceVerdict:
    """Server PR-S5 HITL seam (LOCKED 4-arg signature:
    ``async resume(app, incident_id, decision, payload) -> GovernanceVerdict``,
    UNSIGNED — server signs). ``incident_id`` is the LangGraph thread id (= the
    run_id used at ``decide``). ``payload`` carries the edit|response data for
    the accept|edit|response|ignore human decision (langgraph resume schema
    prebuilt/interrupt.py:87-105). Requires a checkpointer-backed app
    (``build_decide_app(checkpointer=…)``)."""
    if not gov_app.has_checkpointer:
        raise RuntimeError(
            "resume() requires a checkpointer-backed app "
            "(build_decide_app(checkpointer=InMemorySaver()|PostgresSaver()))"
        )
    from langgraph.types import Command

    out = await gov_app.app.ainvoke(
        Command(resume={"decision": decision.value, "payload": payload}),
        {"configurable": {"thread_id": incident_id}},
    )
    verdict = out["verdict"]
    assert isinstance(verdict, GovernanceVerdict)
    return verdict


# --------------------------------------------------------------------------- #
# W3 — async Channel-2 path (Evaluator + Auditor → Supervisor → shield:verdicts)
# --------------------------------------------------------------------------- #


def make_async_channel2_handler(
    *,
    evaluator: Evaluator,
    auditor: Auditor,
    supervisor: Supervisor,
    on_verdict: Callable[[AsyncVerdictHandoff], Awaitable[None]] | None = None,
) -> Callable[[ShieldActionRecord], Awaitable[None]]:
    """The async (post-exec) Channel-2 path. Pass to
    ``Channel2Consumer.run_once`` with an explicit ``group=`` per the W3
    consumer-group contract: callers MUST pass ``shield-evaluator`` /
    ``shield-auditor``; the ``shield-governance`` DEFAULT must NOT reach prod
    fan-out (governance_design §4 / ADR-0010 sibling note).

    This computes the Evaluator/Auditor/Supervisor verdict but never signs,
    stores, or publishes it. ``on_verdict`` is the server-owned handoff seam:
    production callers must take the unsigned :class:`AsyncVerdictHandoff`
    through the server signing/persistence boundary before any stream fan-out.
    """

    async def handle(record: ShieldActionRecord) -> None:
        eval_result = await evaluator.evaluate(record)
        audit_result = auditor.audit([record], agent_pubkey_b64url=record.agent_pubkey_kid)
        signals = GuardianSignals(
            defender_decision=Decision.PASS,
            evaluator_anomaly=eval_result.anomaly,
            evaluator_reasons=eval_result.reasons,
            evaluator_ran=True,  # async path — Evaluator has run (conflict is meaningful)
            auditor_integrity=audit_result.integrity,
            auditor_reasons=audit_result.reasons,
            structuring_or_exfil=eval_result.structuring_or_exfil,
            chain_broken=audit_result.chain_broken,
            post_exec=record.phase == Phase.POST_EXEC,
        )
        verdict = supervisor.decide(signals, record=record)
        if on_verdict is not None:
            await on_verdict(AsyncVerdictHandoff.from_record(record, verdict))

    return handle
