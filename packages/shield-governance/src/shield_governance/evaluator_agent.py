"""Phase B — real ``create_agent`` Evaluator LLM agent (plan + tools + self-correct).

This module is the M2 / Phase B substance for course requirement #1
("plan / use tools / correct its own errors"): the Evaluator's hallucination
seam is upgraded from a single-prompt LLM call to a LangChain ``create_agent``
LLM agent that decides which tools to call, reads their results, and can
re-call (self-correct) before producing a final verdict.

It is bound to **two real tools** — both wrap existing, deterministic code
inside ``shield_governance``:

* :func:`eval_invariant_policies` wraps
  :class:`shield_governance.evaluator.LocalPolicyStructuringAnalyzer`, which
  runs the Invariant LocalPolicy structuring detector on the accumulated
  trace (the same code path the deterministic Evaluator uses when
  ``run_invariant=True``).
* :func:`recall_similar_incidents` looks up similar records through the
  configured incident-memory backend. The final delivery backend is local
  persistent Chroma; the process-local short-window remains available only as
  an explicitly labelled fallback for tests/degraded development runs.

Layering note: the Evaluator path owns the first tool-calling agent loop.
Supervisor/Auditor loops are added in the Module 7 pass.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import tool
from shield_sdk.schema import ShieldActionRecord

from shield_governance.defender.scanners import LocalPolicyStructuringAnalyzer
from shield_governance.memory.tools import build_recall_similar_incidents_tool
from shield_governance.model_router import ShieldModelRouter


@dataclass(frozen=True, slots=True)
class IncidentSummary:
    """One row in the in-memory short-window memory."""

    record_id: str
    tool_name: str | None
    recipient: str | None
    amount: float | None


class EvaluatorAgentMemory:
    """Bounded process-local short-window fallback.

    This is not Module 6 completion evidence. The deliverable memory backend is
    ``ChromaIncidentMemory``; this class is retained for tests and explicitly
    labelled degraded/development paths.
    """

    def __init__(self, capacity: int = 128) -> None:
        self._records: deque[IncidentSummary] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def remember(self, summary: IncidentSummary) -> None:
        with self._lock:
            self._records.append(summary)

    def recall(
        self,
        *,
        tool_name: str | None = None,
        recipient: str | None = None,
        limit: int = 5,
    ) -> list[IncidentSummary]:
        with self._lock:
            ordered = reversed(self._records)  # most-recent first
            matches: list[IncidentSummary] = []
            for row in ordered:
                if tool_name and row.tool_name != tool_name:
                    continue
                if recipient and row.recipient != recipient:
                    continue
                matches.append(row)
                if len(matches) >= limit:
                    break
            return matches

    def reset(self) -> None:
        with self._lock:
            self._records.clear()


def _summarize(record: ShieldActionRecord) -> IncidentSummary:
    args = record.payload.tool_args or {}
    recipient_raw = args.get("recipient")
    amount_raw = args.get("amount")
    try:
        amount = float(amount_raw) if amount_raw is not None else None
    except (TypeError, ValueError):
        amount = None
    return IncidentSummary(
        record_id=record.record_id,
        tool_name=record.payload.tool_name,
        recipient=str(recipient_raw) if recipient_raw is not None else None,
        amount=amount,
    )


def _build_evaluator_tools(
    *,
    record: ShieldActionRecord,
    trace: list[dict[str, Any]],
    analyzer: LocalPolicyStructuringAnalyzer,
    memory: Any,
    tool_call_log: list[str] | None = None,
    memory_evidence_log: list[dict[str, object]] | None = None,
) -> list[Any]:
    """Return the two tools the Evaluator agent can call.

    Both close over ``(record, trace, analyzer, memory)`` so the tool body
    has access to the actual per-call context; the LLM's tool args are
    minimal hint strings (the real signal is the closure). ``tool_call_log``
    is an optional spy hook used by the discriminative tests.
    """

    @tool
    def eval_invariant_policies(_hint: str = "") -> dict[str, Any]:
        """Run the Invariant LocalPolicy structuring detector on the
        Evaluator's accumulated trace for the current run.

        Returns ``{"fired": bool, "violations": [{"label": str, "detail": str}, ...]}``.
        Fires when the policy detects e.g. ≥3 ``send_money`` transfers to the
        same recipient in the same run (structuring/exfil pattern).
        Use this BEFORE concluding GROUNDED on a transfer-like tool call.
        The ``_hint`` argument is ignored; the tool reads the live trace.
        """
        if tool_call_log is not None:
            tool_call_log.append("eval_invariant_policies")
        violations_raw = analyzer.analyze(trace)
        violations = [{"label": v.label, "detail": v.detail or ""} for v in violations_raw]
        return {"fired": bool(violations), "violations": violations}

    recall_tool = build_recall_similar_incidents_tool(
        record=record,
        memory=memory,
        tool_call_log=tool_call_log,
        memory_evidence_log=memory_evidence_log,
        name="recall_similar_incidents",
    )
    legacy_recall_tool = build_recall_similar_incidents_tool(
        record=record,
        memory=memory,
        tool_call_log=tool_call_log,
        memory_evidence_log=memory_evidence_log,
        name="recall_similar_local_incidents",
    )

    return [eval_invariant_policies, recall_tool, legacy_recall_tool]


EVALUATOR_SYSTEM_PROMPT = (
    "You are the Agent Shield Evaluator guardian. You are reviewing one "
    "tool-call record from a worker agent.\n\n"
    "Your job is to decide whether the worker's claimed action is GROUNDED "
    "(consistent with its arguments and prior trace) or HALLUCINATED "
    "(misaligned, suspicious, or evidence of injection/structuring).\n\n"
    "You MUST use the provided tools — do not decide from the prompt alone:\n"
    "  * `eval_invariant_policies` runs the cross-step structuring detector.\n"
    "  * `recall_similar_incidents` looks up similar prior records in Chroma "
    "when configured.\n\n"
    "If a tool result is ambiguous or low-confidence, CALL ANOTHER TOOL "
    "(self-correction) before answering. Only after gathering tool evidence, "
    "reply on a single line in this exact format:\n\n"
    "DECISION: <GROUNDED|HALLUCINATED>\n"
    "REASON: <one-line justification grounded in the tool evidence>"
)


def make_evaluator_agent(
    router: ShieldModelRouter,
    *,
    record: ShieldActionRecord,
    trace: list[dict[str, Any]],
    analyzer: LocalPolicyStructuringAnalyzer | None = None,
    memory: Any | None = None,
    tool_call_log: list[str] | None = None,
    memory_evidence_log: list[dict[str, object]] | None = None,
    system_prompt: str | None = None,
) -> Any:
    """Build a per-call ``create_agent`` Evaluator agent.

    The factory is per-call (not cached): each ``Evaluator`` invocation
    gets a fresh closure over the current ``(record, trace)`` so the tools
    operate on the current step's context. The underlying ``BaseChatModel``
    instance IS cached by :class:`ShieldModelRouter._client_for`, so the
    only per-call cost is the agent topology assembly.
    """
    analyzer = analyzer or LocalPolicyStructuringAnalyzer()
    memory = memory or EvaluatorAgentMemory()
    tools = _build_evaluator_tools(
        record=record,
        trace=trace,
        analyzer=analyzer,
        memory=memory,
        tool_call_log=tool_call_log,
        memory_evidence_log=memory_evidence_log,
    )
    # ``model_factory`` is typed ``Callable[[object, object], object]`` for
    # back-compat with the W1 stub; after the Phase B / ADR-0009 ChatModel
    # adapter it actually returns a LangChain ``BaseChatModel`` (or a
    # test fake that quacks like one). ``create_agent`` accepts both.
    from typing import cast

    from langchain_core.language_models import BaseChatModel

    raw_model = router.model_factory("evaluator")({}, object())
    return create_agent(
        model=cast(BaseChatModel, raw_model),
        tools=tools,
        system_prompt=system_prompt or EVALUATOR_SYSTEM_PROMPT,
    )


def parse_evaluator_decision(text: str) -> tuple[bool, str]:
    """Parse the agent's final message into ``(hallucinated, reason)``.

    Looks for ``DECISION: HALLUCINATED`` / ``DECISION: GROUNDED`` (case-
    insensitive) on any line; the reason comes from the ``REASON:`` line
    if present, else the trimmed message text. Defaults to GROUNDED when
    the model fails to follow the format — fail-OPEN here is appropriate
    because the deterministic ``Defender`` and the Invariant LocalPolicy
    pass (run via the Evaluator's existing path) already gate the hot
    path; the LLM agent is the *late* path's second opinion, not the
    primary safety boundary.
    """
    upper = text.upper()
    hallucinated = "DECISION: HALLUCINATED" in upper or upper.startswith("HALLUCINATED")

    reason = text.strip()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("REASON:"):
            reason = stripped.split(":", 1)[1].strip() or reason
            break

    return hallucinated, reason
