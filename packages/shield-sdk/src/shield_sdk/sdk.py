"""Free SDK client — Channel-1 sync gate + Channel-2 record submit.

`decide()` is the synchronous `POST /v1/governance/decide` round-trip (ADR-0004:
the verdict IS the HTTP response). The 500 ms budget + per-tool fail policy is
NOT enforced here — it is owned by `ShieldGuard`, which wraps `decide()` in a
`concurrent.futures` future with `.result(timeout=...)` so a slow/hung Layer-2
never blocks the AgentDojo worker. The client stays thin and synchronous
(AgentDojo's pipeline is fully synchronous — verified rev 18b501a).

`submit()` is the Channel-2 path: the async `post_exec` (and any) record is
POSTed to `POST /v1/governance/record` (server-builder confirmed route — NOT
`/v1/operations`, which is the W1 Elydora-EOR shape with no Channel-2 XADD;
`/decide` is pre_exec-only). The server verifies it via the SAME frozen
`shield_sdk.canonical` projection, persists it, `XADD
shield:actions:{workflow_id}`, and returns a `202` ack
(`{record_id, chain_hash, seq_no, accepted}` — no verdict). The FROZEN §4
schema / HTTP body is unchanged; this is purely the route string.

ADR-0013 transport authentication (auth-v1): an optional ``api_key`` Bearer
credential is configured ONCE on the persistent ``httpx.Client`` so it rides
every request (decide / submit / future endpoints) at zero per-call cost.
Cleanly ORTHOGONAL to the agent's Ed25519 record signing — the api_key
authenticates the *caller of the API* at the HTTPS boundary; the Ed25519
record signature (built in ``shield_sdk.canonical.finalize_record``)
authenticates the *record* and is independent of the transport credential.
Both gates must validate under enterprise auth; either alone is insufficient.
"""

from __future__ import annotations

from typing import Any

import httpx

from .schema import GovernanceVerdict, ShieldActionRecord

DEFAULT_DECIDE_PATH = "/v1/governance/decide"  # pre_exec (Channel-1, returns verdict)
DEFAULT_RECORD_PATH = "/v1/governance/record"  # post_exec (Channel-2, returns 202 ack)


class ShieldClient:
    """Thin synchronous transport to the shield server.

    Args:
        base_url: server base URL; trailing slash normalized away.
        timeout_s: httpx timeout (ShieldGuard owns the hard 500 ms decision
            budget via a ``concurrent.futures`` future, independent of this).
        decide_path: Channel-1 route (default ``/v1/governance/decide``).
        record_path: Channel-2 route (default ``/v1/governance/record``).
        transport: optional injected httpx transport (test / in-process ASGI).
        api_key: ADR-0013 transport Bearer credential. When ``None`` (default)
            NO ``Authorization`` header is sent — byte-identical to the
            pre-auth-v1 wire (``SHIELD_AUTH_MODE=open``; preserves all
            existing tests + ``real_server_transport()`` + eval's keyed
            ``run_ab`` recipe). When non-None, the persistent
            ``httpx.Client`` is constructed once with
            ``Authorization: Bearer <api_key>`` and the header rides every
            request — no per-call branching, no per-call header build.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 2.0,
        decide_path: str = DEFAULT_DECIDE_PATH,
        record_path: str = DEFAULT_RECORD_PATH,
        transport: httpx.BaseTransport | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._decide_path = decide_path
        self._record_path = record_path
        # ADR-0013: the Authorization header is set ONCE on the persistent
        # client (connection-pooled) — applied to every request to every
        # route. When api_key is None the client is constructed WITHOUT
        # passing a `headers` kwarg, so the wire is byte-identical to the
        # pre-auth-v1 path (`SHIELD_AUTH_MODE=open`).
        client_kwargs: dict[str, Any] = {
            "base_url": self.base_url,
            "timeout": timeout_s,
            "transport": transport,
        }
        if api_key is not None:
            client_kwargs["headers"] = {"Authorization": f"Bearer {api_key}"}
        self._client = httpx.Client(**client_kwargs)

    def decide(self, record: ShieldActionRecord) -> GovernanceVerdict:
        """Channel-1: submit the pre_exec record, return the signed verdict."""
        resp = self._client.post(self._decide_path, json=record.model_dump(mode="json"))
        resp.raise_for_status()
        body: Any = resp.json()
        return GovernanceVerdict.model_validate(body)

    def submit(self, record: ShieldActionRecord) -> None:
        """Channel-2: best-effort async ingest of a (post_exec) record."""
        resp = self._client.post(self._record_path, json=record.model_dump(mode="json"))
        resp.raise_for_status()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ShieldClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
