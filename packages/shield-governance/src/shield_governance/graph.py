"""LangGraph 1.2.0 governance graph.

W2: the spine is LIVE and wired to consume Channel-2. The **Defender** node
runs the real :class:`~shield_governance.defender.engine.DefenderEngine`
(deterministic + LlamaFirewall + Invariant ``LocalPolicy``) BEHIND ITS FLAG and
emits a real frozen §4 ``GovernanceVerdict``. Evaluator / Supervisor / Auditor
remain W3 (kept here as the documented topology contract). ``decide()`` is NOT
yet swapped into ``POST /v1/governance/decide`` — that is W3 (server stub still
returns PASS).

§5b primitives — verified first-hand against ``Related_Work/`` clones
(2026-05-19), and re-probed live in the W2 env:

* ``StateGraph`` / ``START`` / ``END`` —
  ``langgraph/libs/langgraph/langgraph/graph/state.py:130``; build+``invoke``
  confirmed on langgraph **1.2.0** in this env.
* Guardian nodes (W3) = ``create_react_agent``/``create_agent``
  ``model=Callable`` factory from :class:`ShieldModelRouter`
  (``…/prebuilt/chat_agent_executor.py:278-307``). DRIFT (already reported,
  ADR-0009 W3): ``create_react_agent`` deprecated -> ``langchain.agents.
  create_agent``; the Callable seam is unchanged.
* Supervisor routing ``Command(goto,update)`` ``types.py:749``; HITL
  ``interrupt()`` ``types.py:801``; rollback ``get_state_history`` /
  ``update_state`` ``pregel/main.py:1478`` / ``:2486`` — W3.

``langgraph`` is imported lazily inside :func:`build_graph` so importing this
module never pulls the framework.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from shield_sdk.schema import GovernanceVerdict, ShieldActionRecord  # frozen §4 — never redeclared

from shield_governance.defender.engine import DefenderEngine

#: Full guardian topology (W3 wires Evaluator/Supervisor/Auditor + edges).
GUARDIAN_TOPOLOGY: tuple[str, ...] = ("defender", "evaluator", "supervisor", "auditor")


class GovernanceState(TypedDict, total=False):
    """Shared LangGraph state threaded through the guardians."""

    record: ShieldActionRecord  # incoming frozen §4 ShieldActionRecord
    defender: dict[str, Any]  # deterministic + scanner + invariant findings
    evaluator: dict[str, Any]  # async semantic findings (W3)
    auditor: dict[str, Any]  # chain/Merkle/provenance integrity (W3)
    conflict: bool  # Defender<->Evaluator disagreement -> arbitrate() (W3)
    risk_score: float
    verdict: GovernanceVerdict


def make_defender_node(
    engine: DefenderEngine,
) -> Callable[[GovernanceState], Awaitable[dict[str, Any]]]:
    """Bind the real Defender engine into an async LangGraph node."""

    async def defender_node(state: GovernanceState) -> dict[str, Any]:
        record = state["record"]
        verdict = await engine.assess(record)
        return {
            "verdict": verdict,
            "risk_score": verdict.risk_score,
            "defender": {
                "decision": verdict.decision.value,
                "reasons": [r.label for r in verdict.reasons],
            },
        }

    return defender_node


def defender_node(state: GovernanceState) -> dict[str, Any]:  # pragma: no cover
    """Topology placeholder — the live W2 node is built by
    :func:`make_defender_node` (it needs a bound :class:`DefenderEngine`)."""
    raise NotImplementedError("W2: use make_defender_node(engine) to bind the live Defender")


def evaluator_node(state: GovernanceState) -> dict[str, Any]:  # pragma: no cover
    """Async semantic guardian — W3 (behaviour-drift, exfil, hallucination,
    AgentSafe ReviewMemory; LLM via ShieldModelRouter.model_factory)."""
    raise NotImplementedError("W3: Evaluator node")


def supervisor_node(state: GovernanceState) -> dict[str, Any]:  # pragma: no cover
    """Deterministic risk + hard overrides; Command routing; interrupt() HITL;
    time-travel rollback; arbitrate() on conflict — W3."""
    raise NotImplementedError("W3: Supervisor node")


def auditor_node(state: GovernanceState) -> dict[str, Any]:  # pragma: no cover
    """Parallel integrity: chain/Merkle verify, provenance DAG, compliance —
    W3."""
    raise NotImplementedError("W3: Auditor node")


def build_graph(engine: DefenderEngine, *, checkpointer: object | None = None) -> Any:
    """Compile the W2 governance graph: ``START -> defender -> END``.

    W3 adds Evaluator/Supervisor/Auditor nodes + edges, the Postgres
    checkpointer (HITL/rollback) and the ``/decide`` swap. ``langgraph`` is
    imported lazily here.
    """
    from langgraph.graph import END, START, StateGraph

    g: Any = StateGraph(GovernanceState)
    g.add_node("defender", make_defender_node(engine))
    g.add_edge(START, "defender")
    g.add_edge("defender", END)
    return g.compile(checkpointer=checkpointer) if checkpointer is not None else g.compile()


def make_channel2_handler(
    engine: DefenderEngine,
) -> Callable[[ShieldActionRecord], Awaitable[None]]:
    """The Channel-2 wiring: a handler that runs each consumed record through
    the live graph. Pass this to
    :meth:`shield_governance.channel2.Channel2Consumer.run_once`.
    """
    app = build_graph(engine)

    async def handle(record: ShieldActionRecord) -> None:
        await app.ainvoke({"record": record})

    return handle


def decide(record: object) -> GovernanceVerdict:
    """Synchronous entry for ``POST /v1/governance/decide``. W3 (not yet
    swapped in — server still stub->PASS)."""
    raise NotImplementedError("W3: real multi-guardian verdict + /decide swap")  # pragma: no cover
