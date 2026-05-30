"""DefenderEngine wires the deterministic scan_code scanner (governance_design
§3.1) on the free-text subject — model-free, real engine, no key.

Proves the scanner is actually REACHED via DefenderEngine.assess (not just
defined), that a code-injection subject BLOCKs, and that a normal finance
subject on the §1 wedge does NOT false-positive.
"""

from __future__ import annotations

import pytest
from shield_governance.defender import DefenderConfig, DefenderEngine
from shield_sdk.schema import ActionPayload, Decision, Phase, ShieldActionRecord


def _record(subject: str, *, amount: float = 100, run_id: str = "run-cs") -> ShieldActionRecord:
    return ShieldActionRecord(
        run_id=run_id,
        step_index=0,
        phase=Phase.PRE_EXEC,
        payload=ActionPayload(
            tool_name="send_money",
            tool_args={"recipient": "acct-1", "amount": amount, "subject": subject},
        ),
    )


@pytest.mark.asyncio
async def test_engine_blocks_code_injection_in_subject() -> None:
    engine = DefenderEngine(DefenderConfig(enabled=True))
    verdict = await engine.assess(_record("os.system('rm -rf /')"))
    assert verdict.decision == Decision.BLOCK
    assert any(r.label.startswith("scanner.code") for r in verdict.reasons)


@pytest.mark.asyncio
async def test_engine_clean_finance_subject_not_flagged_by_code_scanner() -> None:
    engine = DefenderEngine(DefenderConfig(enabled=True))
    verdict = await engine.assess(_record("Q1 travel reimbursement for the Auckland offsite"))
    # No code-scanner reason on a normal finance subject (low false-positive).
    assert not any(r.label.startswith("scanner.code.subject") for r in verdict.reasons)


@pytest.mark.asyncio
async def test_engine_code_scanner_can_be_disabled() -> None:
    engine = DefenderEngine(DefenderConfig(enabled=True, run_code_scanner=False))
    verdict = await engine.assess(_record("exec(malicious)"))
    assert not any(r.label.startswith("scanner.code") for r in verdict.reasons)
