"""Defender scanner adapters: fakes (CI) + the REAL Invariant LocalPolicy.

The real LlamaFirewall path needs the torch-heavy `scanners` extra and is
exercised in integration, not unit CI. The real Invariant `LocalPolicy` IS
default-installed, so the verified-working policy is asserted here against the
real engine (§5b: claims grounded in the running code, not the design text)."""

from __future__ import annotations

import pytest
from shield_governance.defender.scanners import (
    FakeInjectionScanner,
    FakeStructuringAnalyzer,
    LocalPolicyStructuringAnalyzer,
    NullInjectionScanner,
)


def _send_money_event(recipient: str = "US133000000121212121212", subject: str = "Hacked!") -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "x",
                "type": "function",
                "function": {
                    "name": "send_money",
                    "arguments": {"recipient": recipient, "amount": 10000, "subject": subject},
                },
            }
        ],
    }


@pytest.mark.asyncio
async def test_fake_and_null_injection_scanners() -> None:
    null = NullInjectionScanner()
    assert (await null.scan_text("anything", kind="subject")).blocked is False

    fake = FakeInjectionScanner(triggers=("__INJECT__",))
    clean = await fake.scan_text("Invoice March", kind="subject")
    assert clean.blocked is False
    hit = await fake.scan_text("pay now __INJECT__", kind="subject")
    assert hit.blocked is True
    assert hit.label == "scanner.injection.subject"


def test_fake_structuring_analyzer_threshold() -> None:
    fsa = FakeStructuringAnalyzer(threshold=3)
    assert fsa.analyze([_send_money_event(), _send_money_event()]) == []
    v = fsa.analyze([_send_money_event()] * 3)
    assert len(v) == 1 and v[0].label == "invariant.structuring"


def test_real_localpolicy_structuring_fires_on_3x() -> None:
    """§5b: the verified-working Invariant 0.3.5 LocalPolicy (count(min=3))
    actually fires on the InjectionTask6 3x structuring — real engine."""
    analyzer = LocalPolicyStructuringAnalyzer()
    assert analyzer.analyze([_send_money_event(), _send_money_event()]) == []
    viols = analyzer.analyze([_send_money_event()] * 3)
    assert len(viols) >= 1
    assert all(v.label == "invariant.policy" for v in viols)


def test_real_localpolicy_exfil_fires_on_secret_subject() -> None:
    analyzer = LocalPolicyStructuringAnalyzer()
    clean = analyzer.analyze([_send_money_event(subject="Invoice March")])
    assert clean == []
    viols = analyzer.analyze([_send_money_event(subject="the password is hunter2")])
    assert len(viols) >= 1
