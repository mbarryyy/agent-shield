"""FastAPI app factory.

W0 STUB. W1: 12-step ingest + /v1/{operations,agents,audit}. W2: the synchronous
POST /v1/governance/decide gate (stub -> PASS) + Channel-2 Redis Streams.
"""

from __future__ import annotations

from shield_sdk.schema import GovernanceVerdict  # the frozen §4 type, imported not redeclared


def create_app() -> object:
    raise NotImplementedError("W1: FastAPI app + 12-step ingest")  # pragma: no cover


def stub_pass_verdict(correlation_id: str) -> GovernanceVerdict:
    """W2 wires this behind POST /v1/governance/decide so eval/console integrate day 1."""
    from shield_sdk.schema import Decision

    return GovernanceVerdict(decision=Decision.PASS, correlation_id=correlation_id, latency_ms=0.0)
