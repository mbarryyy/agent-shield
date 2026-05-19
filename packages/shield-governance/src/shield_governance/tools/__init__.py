"""Guardian tool surface.

W1: :class:`~shield_governance.model_router.ShieldModelRouter` is final and
re-exported here for convenience. The guardian tool implementations
(LlamaFirewall scanners, Invariant ``LocalPolicy``, Chroma recall, chain
verify) land at W2/W3.
"""

from __future__ import annotations

from shield_governance.model_router import ResolvedModel, ShieldModelRouter

__all__ = ["ResolvedModel", "ShieldModelRouter"]
