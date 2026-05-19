"""Agent Shield Layer-2 governance.

All LLM calls route through :class:`~shield_governance.model_router.ShieldModelRouter`;
one YAML swap turns the cloud demo into the zero-egress air-gapped SKU (moat #7).

W1: ShieldModelRouter + the model-free deterministic Defender core + the
LangGraph 4-guardian spine skeleton + the InjectionTask6 thesis test. The live
graph lands at W2/W3 behind ``POST /v1/governance/decide``.
"""

from __future__ import annotations

from shield_governance.model_router import ResolvedModel, ShieldModelRouter

__all__ = ["ResolvedModel", "ShieldModelRouter"]
