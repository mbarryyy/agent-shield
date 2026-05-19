"""``shield:verdicts`` producer (Channel-2 outbound).

The Auditor/console consume async outcomes via ``shield:verdicts``. The EXACT
stream-entry field-map is the server PR-S3 seam — team-lead relays the locked
map (mirroring the W2 ``shield:actions`` 7-field envelope). Until then this
publishes a TOLERANT envelope: a full ``verdict`` JSON blob + flat scalar
mirrors (``verdict_id``/``correlation_id``/``record_id``/``decision``/
``risk_score``), exactly the W2 pattern — converging to the locked PR-S3 map is
a one-line change in :func:`verdict_fields`. NOT guessed/finalized.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from shield_sdk.schema import GovernanceVerdict

DEFAULT_VERDICTS_PREFIX = "shield:verdicts"


def verdict_stream_key(workflow_id: str, *, prefix: str = DEFAULT_VERDICTS_PREFIX) -> str:
    return f"{prefix}:{workflow_id}"


def verdict_fields(verdict: GovernanceVerdict, *, phase: str) -> dict[str, str]:
    """The server PR-S3 **LOCKED** FLAT 8-field envelope (str values,
    ``decode_responses=True``): ``{verdict_id, record_id, correlation_id,
    run_id, decision, risk_score(str), phase, verdict(GovernanceVerdict
    JSON)}``. ``phase`` comes from the record (not on the verdict). Converged
    to the team-lead-relayed locked map — server-builder confirms it in-code
    from PR-S3; team-lead brokers any deviation before the rebase converge."""
    return {
        "verdict_id": verdict.verdict_id,
        "record_id": verdict.record_id or "",
        "correlation_id": verdict.correlation_id,
        "run_id": verdict.run_id or "",
        "decision": verdict.decision.value,
        "risk_score": str(verdict.risk_score),
        "phase": phase,
        "verdict": verdict.model_dump_json(),
    }


@runtime_checkable
class VerdictTransport(Protocol):
    async def publish(self, stream: str, fields: dict[str, str]) -> str: ...


class InMemoryVerdictTransport:
    """Deterministic in-proc double for unit tests (no Redis)."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, str]]] = []
        self._seq = 0

    async def publish(self, stream: str, fields: dict[str, str]) -> str:
        self._seq += 1
        self.published.append((stream, fields))
        return f"{self._seq}-0"


class RedisVerdictTransport:
    """Real ``redis.asyncio`` XADD. ``redis`` imported lazily (no unit-CI dep)."""

    def __init__(self, redis_client: Any) -> None:
        self._r = redis_client

    @classmethod
    async def connect(cls, url: str) -> RedisVerdictTransport:
        from redis.asyncio import from_url

        return cls(from_url(url, decode_responses=True))

    async def publish(self, stream: str, fields: dict[str, str]) -> str:
        return str(await self._r.xadd(stream, fields))


class VerdictPublisher:
    """Emit a GovernanceVerdict onto ``shield:verdicts:{workflow_id}``."""

    def __init__(
        self, transport: VerdictTransport, *, prefix: str = DEFAULT_VERDICTS_PREFIX
    ) -> None:
        self._t = transport
        self._prefix = prefix

    async def publish(self, workflow_id: str, verdict: GovernanceVerdict, *, phase: str) -> str:
        return await self._t.publish(
            verdict_stream_key(workflow_id, prefix=self._prefix),
            verdict_fields(verdict, phase=phase),
        )
