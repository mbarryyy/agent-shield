"""W0 smoke: shield-server compiles against the frozen shield_sdk.schema."""

from __future__ import annotations

from shield_sdk.schema import Decision
from shield_server.app import stub_pass_verdict


def test_stub_pass_verdict() -> None:
    v = stub_pass_verdict("corr-1")
    assert v.decision is Decision.PASS
    assert v.correlation_id == "corr-1"
