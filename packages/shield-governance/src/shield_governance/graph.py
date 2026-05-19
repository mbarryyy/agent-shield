"""LangGraph 4-guardian graph: Defender (hot, model-free, <500ms) / Evaluator
(async) / Supervisor (deterministic + arbitrate-on-conflict) / Auditor (parallel).

W0 STUB. W1: spine skeleton + Defender deterministic-rule unit tests + the
InjectionTask6 oracle unit test. W2/W3: real graph behind /decide.
"""

from __future__ import annotations

from shield_sdk.schema import GovernanceVerdict  # frozen §4 type, imported not redeclared


def build_graph() -> object:
    raise NotImplementedError("W2/W3: LangGraph 4-guardian graph")  # pragma: no cover


def decide(record: object) -> GovernanceVerdict:
    raise NotImplementedError("W3: real verdict")  # pragma: no cover
