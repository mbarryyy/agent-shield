"""Agent Shield Layer-2 governance.

All LLM calls route through :class:`~shield_governance.model_router.ShieldModelRouter`;
one YAML swap turns the cloud demo into the zero-egress air-gapped SKU (moat #7).

W1: ShieldModelRouter + the model-free deterministic Defender core + the
spine skeleton + the InjectionTask6 thesis test. W2: the live LangGraph spine
wired to consume Channel-2, the flag-gated real :class:`DefenderEngine`, and
the per-decision token counter (cost hook #1). W3: Evaluator/Supervisor/Auditor
+ the ``/decide`` swap.
"""

from __future__ import annotations

from shield_governance.channel2 import Channel2Consumer
from shield_governance.defender.engine import DefenderConfig, DefenderEngine
from shield_governance.graph import build_graph, make_channel2_handler
from shield_governance.model_router import ResolvedModel, ShieldModelRouter
from shield_governance.token_counter import InterventionTokenRow, TokenCounter

__all__ = [
    "Channel2Consumer",
    "DefenderConfig",
    "DefenderEngine",
    "InterventionTokenRow",
    "ResolvedModel",
    "ShieldModelRouter",
    "TokenCounter",
    "build_graph",
    "make_channel2_handler",
]
