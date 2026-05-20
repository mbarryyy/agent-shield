"""Agent Shield Layer-2 governance.

All LLM calls route through :class:`~shield_governance.model_router.ShieldModelRouter`;
one YAML swap turns the cloud demo into the zero-egress air-gapped SKU (moat #7).

W1: ShieldModelRouter + model-free deterministic Defender + InjectionTask6
thesis. W2: live spine wired to Channel-2, flag-gated DefenderEngine,
token-counter hook#1. W3/W4: real 4-guardian — un-flagged Defender +
Supervisor + Evaluator + Auditor; ``build_decide_app``/``decide`` (server
PR-S1, UNSIGNED canonical-stable), ``resume`` (HITL, PR-S5), async verdict
handoff to the server signing/publish boundary.
"""

from __future__ import annotations

from shield_governance.auditor import Auditor, AuditResult, MerkleVerification, ProvenanceGraph
from shield_governance.channel2 import Channel2Consumer
from shield_governance.defender.engine import DefenderConfig, DefenderEngine
from shield_governance.evaluator import (
    BehaviorDriftConfigurationError,
    DriftScore,
    Evaluator,
    EvaluatorConfig,
    EvaluatorResult,
    SbertChromaDriftDetector,
)
from shield_governance.graph import (
    GovApp,
    build_decide_app,
    build_graph,
    decide,
    make_async_channel2_handler,
    make_channel2_handler,
    resume,
)
from shield_governance.model_router import ResolvedModel, ShieldModelRouter
from shield_governance.supervisor import (
    GuardianSignals,
    Supervisor,
    SupervisorPolicy,
)
from shield_governance.token_counter import InterventionTokenRow, TokenCounter
from shield_governance.verdicts import AsyncVerdictHandoff

__all__ = [
    "AuditResult",
    "Auditor",
    "BehaviorDriftConfigurationError",
    "Channel2Consumer",
    "DefenderConfig",
    "DefenderEngine",
    "DriftScore",
    "Evaluator",
    "EvaluatorConfig",
    "EvaluatorResult",
    "GovApp",
    "GuardianSignals",
    "InterventionTokenRow",
    "MerkleVerification",
    "ProvenanceGraph",
    "ResolvedModel",
    "SbertChromaDriftDetector",
    "ShieldModelRouter",
    "Supervisor",
    "SupervisorPolicy",
    "TokenCounter",
    "AsyncVerdictHandoff",
    "build_decide_app",
    "build_graph",
    "decide",
    "make_async_channel2_handler",
    "make_channel2_handler",
    "resume",
]
