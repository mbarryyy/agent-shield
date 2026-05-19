"""Enforcement decision table + ESCALATE-non-interactive degradation (W2)."""

from __future__ import annotations

from shield_eval.enforcement import (
    EnforcementAction,
    EnforcementConfig,
    resolve_enforcement,
)
from shield_sdk.schema import Decision, GovernanceVerdict, Obligations


def _v(decision: Decision, require_human: bool = False) -> GovernanceVerdict:
    return GovernanceVerdict(
        decision=decision,
        correlation_id="c",
        obligations=Obligations(require_human=require_human),
    )


def test_pass_and_alert_run() -> None:
    for d in (Decision.PASS, Decision.ALERT):
        o = resolve_enforcement(_v(d), "send_money")
        assert o.action == EnforcementAction.RUN and not o.degraded


def test_block_skips_synthesize() -> None:
    o = resolve_enforcement(_v(Decision.BLOCK), "send_money")
    assert o.action == EnforcementAction.SKIP_SYNTHESIZE
    assert o.effective_decision == Decision.BLOCK


def test_rollback_and_rewrite() -> None:
    assert resolve_enforcement(_v(Decision.ROLLBACK), "send_money").action == (
        EnforcementAction.SKIP_RESTORE
    )
    assert resolve_enforcement(_v(Decision.REWRITE), "send_money").action == (
        EnforcementAction.REWRITE_RUN
    )


def test_escalate_degrades_to_block_for_fail_closed_tools() -> None:
    for tool in ("send_money", "update_password", "update_scheduled_transaction"):
        o = resolve_enforcement(_v(Decision.ESCALATE, require_human=True), tool)
        assert o.action == EnforcementAction.SKIP_SYNTHESIZE
        assert o.effective_decision == Decision.BLOCK
        assert o.degraded is True
        assert "money not moved" in o.reason


def test_escalate_auto_approves_non_fail_closed_in_batch() -> None:
    o = resolve_enforcement(_v(Decision.ESCALATE), "read_file")
    assert o.action == EnforcementAction.RUN
    assert o.effective_decision == Decision.ALERT
    assert o.degraded is True


def test_escalate_interactive_demo_keeps_real_hitl() -> None:
    cfg = EnforcementConfig(interactive=True)
    o = resolve_enforcement(_v(Decision.ESCALATE, require_human=True), "send_money", cfg)
    # Demo path: real LangGraph interrupt() HITL — NOT a batch degradation.
    assert o.action == EnforcementAction.SKIP_SYNTHESIZE
    assert o.effective_decision == Decision.ESCALATE
    assert o.degraded is False
