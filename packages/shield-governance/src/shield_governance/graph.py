"""LangGraph 1.2.0 4-guardian governance graph — W1 SPINE SKELETON.

Topology (the loop, governance_design.md §4 / master design §1.1)::

    ShieldGuard intent
        -> Defender   (HOT, model-free/local, <500 ms p95, blocking)
        -> Evaluator  (async, latency-tolerant, Sonnet|in-VPC vLLM)
        -> Supervisor (deterministic; LLM arbitrate() ONLY on Defender<->Evaluator
                       conflict) -> {PASS|ALERT|BLOCK|ESCALATE|ROLLBACK|REWRITE}
        -> Auditor    (parallel, never blocks)

§5b code-grounded primitives (verified first-hand against ``Related_Work/``
clones at the design-locked versions, 2026-05-19):

* ``StateGraph`` — ``langgraph/libs/langgraph/langgraph/graph/state.py:130``.
* Guardian nodes = ``create_react_agent(model=Callable[...])`` factory form,
  ``langgraph/libs/prebuilt/langgraph/prebuilt/chat_agent_executor.py:278-307``;
  the ``model`` factory is supplied by :class:`ShieldModelRouter` so the node
  code is identical across the cloud / air-gapped profiles.
  DRIFT (reported to team-lead): in LangGraph 1.x ``create_react_agent`` is
  deprecated in favour of ``langchain.agents.create_agent``; the Callable
  ``model``-factory seam is unchanged on both, so the moat is unaffected.
* Supervisor routing = ``Command(goto=..., update=...)``,
  ``langgraph/libs/langgraph/langgraph/types.py:749``.
* Escalate(HITL) = ``interrupt()``,
  ``langgraph/libs/langgraph/langgraph/types.py:801``.
* Rollback (time-travel) = ``get_state_history`` /``update_state``,
  ``langgraph/libs/langgraph/langgraph/pregel/main.py:1478`` / ``:2486``.

W1 ships ONLY the skeleton: the typed state, the node signatures, the wiring
contract, and the verified-API references. There is NO live graph — the real
nodes (Defender hot path wrapping :mod:`shield_governance.defender.rules` +
LlamaFirewall + Invariant ``LocalPolicy``; Evaluator; Supervisor; Auditor) and
``build_graph`` / ``decide`` are wired at W2/W3 behind
``POST /v1/governance/decide``. Importing this module never requires langgraph.
"""

from __future__ import annotations

from typing import Any, TypedDict

from shield_sdk.schema import GovernanceVerdict  # frozen §4 type — imported, never redeclared

#: Guardian execution order along the spine.
GUARDIAN_TOPOLOGY: tuple[str, ...] = ("defender", "evaluator", "supervisor", "auditor")


class GovernanceState(TypedDict, total=False):
    """Shared LangGraph state threaded through the 4 guardians.

    Keys are populated progressively along :data:`GUARDIAN_TOPOLOGY`. The
    incoming/outgoing wire types are the FROZEN §4 ``ShieldActionRecord`` /
    ``GovernanceVerdict`` (carried as the validated pydantic objects; declared
    here as ``object`` to avoid importing the not-yet-frozen stub field set
    into the skeleton's type surface).
    """

    record: object  # incoming ShieldActionRecord (frozen §4)
    defender: dict[str, Any]  # deterministic + scanner findings (model-free)
    evaluator: dict[str, Any]  # async semantic findings
    auditor: dict[str, Any]  # chain/Merkle/provenance integrity
    conflict: bool  # Defender <-> Evaluator disagreement -> arbitrate()
    risk_score: float
    verdict: GovernanceVerdict


def defender_node(state: GovernanceState) -> dict[str, Any]:  # pragma: no cover
    """HOT path, blocking, model-free: deterministic caps +
    cumulative-per-recipient tracker (:mod:`shield_governance.defender.rules`,
    W1-final) + LlamaFirewall scanners + Invariant ``LocalPolicy`` (W2)."""
    raise NotImplementedError("W2: Defender node wraps the W1 deterministic rules + scanners")


def evaluator_node(state: GovernanceState) -> dict[str, Any]:  # pragma: no cover
    """Async, latency-tolerant: behaviour-drift, exfil, hallucination,
    AgentSafe ReviewMemory. LLM via ``ShieldModelRouter.model_factory``."""
    raise NotImplementedError("W3: Evaluator node")


def supervisor_node(state: GovernanceState) -> dict[str, Any]:  # pragma: no cover
    """Deterministic weighted risk + hard overrides; ``Command(goto,update)``
    routing; ``interrupt()`` HITL; time-travel rollback; ``arbitrate()`` LLM
    ONLY on Defender<->Evaluator conflict."""
    raise NotImplementedError("W3: Supervisor node")


def auditor_node(state: GovernanceState) -> dict[str, Any]:  # pragma: no cover
    """Parallel, never blocks: SHA-256/Ed25519 chain + Merkle verify, networkx
    correlation_id provenance DAG, compliance report (incl. signed egress=0)."""
    raise NotImplementedError("W3: Auditor node")


def build_graph(checkpointer: object | None = None) -> object:
    """Compile the 4-guardian ``StateGraph``. W2/W3 — no live graph at W1.

    langgraph is imported lazily here so importing this module (the skeleton)
    never pulls the W2/W3-pinned framework.
    """
    raise NotImplementedError(  # pragma: no cover
        "W2/W3: compile the LangGraph 4-guardian StateGraph "
        "(StateGraph graph/state.py:130; nodes via ShieldModelRouter.model_factory; "
        "Command/interrupt types.py:749/:801; rollback pregel/main.py:1478/:2486)"
    )


def decide(record: object) -> GovernanceVerdict:
    """Synchronous entry for ``POST /v1/governance/decide``. W3."""
    raise NotImplementedError("W3: real multi-guardian verdict")  # pragma: no cover
