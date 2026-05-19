"""ESCALATE-non-interactive contract e2e (eval-OWNED; seam #3, sdk+gov review).

Consumes the FROZEN ``contracts/examples/verdict_escalate.json`` **read-only**
(no contracts/ edit) as the canonical ESCALATE verdict shape, then asserts the
eval-owned degradation policy: in a non-interactive AgentDojo batch an ESCALATE
on a fail-CLOSED money tool degrades deterministically to BLOCK so money never
moves; the live demo path keeps the real LangGraph ``interrupt()`` HITL and is
never exercised through ``benchmark_suite()`` (AgentDojo has no HITL primitive
— grep-verified at HEAD 18b501a).
"""

from __future__ import annotations

import json
from pathlib import Path

from shield_eval.enforcement import (
    EnforcementAction,
    EnforcementConfig,
    resolve_enforcement,
)
from shield_sdk.schema import Decision, GovernanceVerdict

# <repo>/packages/shield-eval/tests/this -> parents[3] == repo root
_CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "examples" / "verdict_escalate.json"


def _load_frozen_escalate() -> GovernanceVerdict:
    raw = json.loads(_CONTRACT.read_text(encoding="utf-8"))
    return GovernanceVerdict.model_validate(raw)


def test_frozen_contract_is_a_valid_escalate_verdict() -> None:
    assert _CONTRACT.exists(), f"frozen contract missing: {_CONTRACT}"
    v = _load_frozen_escalate()
    assert v.shield_version == "1.1"
    assert v.decision == Decision.ESCALATE
    assert v.obligations.require_human is True


def test_escalate_degrades_to_block_in_non_interactive_batch() -> None:
    v = _load_frozen_escalate()
    o = resolve_enforcement(v, "send_money")  # fail-CLOSED money tool
    assert o.action == EnforcementAction.SKIP_SYNTHESIZE
    assert o.effective_decision == Decision.BLOCK
    assert o.degraded is True
    assert "money not moved" in o.reason
    assert "interrupt()" in o.reason  # documents the demo HITL is retained


def test_same_escalate_keeps_real_hitl_on_demo_path() -> None:
    v = _load_frozen_escalate()
    o = resolve_enforcement(v, "send_money", EnforcementConfig(interactive=True))
    assert o.effective_decision == Decision.ESCALATE  # real interrupt() pause
    assert o.degraded is False
