"""ADR-0013 SDK auth-v1 — ShieldClient ``api_key`` ctor kwarg + Bearer header.

Four contract tests:

1. **back-compat / byte-identical-to-today**: ``api_key=None`` (the default,
   ``SHIELD_AUTH_MODE=open`` path) sends NO ``Authorization`` header — every
   existing W3 test + ``real_server_transport()`` + eval's keyed
   ``run_ab --decide http`` recipe is wire-unchanged.
2. **enterprise opt-in**: ``api_key="as_test_..."`` ⇒ every outgoing request
   on every endpoint (decide + submit) carries ``Authorization: Bearer …``.
3. **header is connection-pooled, not per-call**: the header is set ONCE on
   the persistent ``httpx.Client`` at ctor time (visible BEFORE any call) and
   the request count under load doesn't matter — zero per-call cost.
4. **§A8 (e) orthogonality** — the SDK-side mirror of server's orthogonality
   test: the api_key MUST NOT influence the FROZEN §4 Ed25519 record signing
   path. ``canonical.finalize_record`` produces byte-identical signatures
   regardless of which (or whether any) ``ShieldClient`` exists; the
   record's signed JCS bytes never mention the api_key. Proves the two
   authorities (transport Bearer credential + record Ed25519 signature) are
   genuinely orthogonal gates.
"""

from __future__ import annotations

import httpx
import respx
from shield_sdk import canonical, crypto
from shield_sdk.schema import (
    ActionPayload,
    ActionRef,
    Decision,
    GovernanceVerdict,
    Phase,
    ShieldActionRecord,
)
from shield_sdk.sdk import ShieldClient

# W1 golden test keypair (frozen, byte-identical to contracts/golden/vectors.json).
_PRIV = crypto.base64url_encode(bytes(range(32)))
_PUB = crypto.get_public_key_base64url(_PRIV)

_API_KEY = "as_test_" + "x" * 32  # opaque high-entropy shape, prefix-tagged


def _pre_record() -> ShieldActionRecord:
    """A deterministic pre_exec record (no implicit env / time dependence)."""
    return ShieldActionRecord(
        record_id="0193aaaa-bbbb-7ccc-8ddd-000000000001",
        correlation_id="0193aaaa-bbbb-7ccc-8ddd-000000000002",
        run_id="run-auth-v1",
        issued_at=1747526400000,
        nonce="AAAAAAAAAAAAAAAAAAAAAA",
        phase=Phase.PRE_EXEC,
        action=ActionRef(tool="send_money", args_digest="sha256:dead"),
        payload=ActionPayload(tool_name="send_money", tool_args={"amount": 1.0}),
    )


def _verdict_for(rec: ShieldActionRecord) -> dict[str, object]:
    return GovernanceVerdict(
        record_id=rec.record_id,
        correlation_id=rec.correlation_id,
        run_id=rec.run_id,
        decision=Decision.PASS,
    ).model_dump(mode="json")


# --------------------------------------------------------------------------- #
# (1) back-compat: api_key=None ⇒ no Authorization header (byte-identical)
# --------------------------------------------------------------------------- #


@respx.mock
def test_no_api_key_no_authz_header() -> None:
    rec = _pre_record()
    decide_route = respx.post("http://srv/v1/governance/decide").mock(
        return_value=httpx.Response(200, json=_verdict_for(rec))
    )
    record_route = respx.post("http://srv/v1/governance/record").mock(
        return_value=httpx.Response(202, json={"accepted": True})
    )

    with ShieldClient("http://srv") as c:  # api_key default = None
        assert "authorization" not in c._client.headers  # not configured on client
        c.decide(rec)
        c.submit(rec)

    # No Authorization header on EITHER outgoing request — proves
    # SHIELD_AUTH_MODE=open is byte-identical to the pre-auth-v1 wire.
    for call in (decide_route.calls.last, record_route.calls.last):
        assert "authorization" not in call.request.headers


# --------------------------------------------------------------------------- #
# (2) enterprise opt-in: api_key="as_test_..." ⇒ Bearer on every request
# --------------------------------------------------------------------------- #


@respx.mock
def test_with_api_key_bearer_header_set() -> None:
    rec = _pre_record()
    decide_route = respx.post("http://srv/v1/governance/decide").mock(
        return_value=httpx.Response(200, json=_verdict_for(rec))
    )
    record_route = respx.post("http://srv/v1/governance/record").mock(
        return_value=httpx.Response(202, json={"accepted": True})
    )

    with ShieldClient("http://srv", api_key=_API_KEY) as c:
        c.decide(rec)
        c.submit(rec)

    expected = f"Bearer {_API_KEY}"
    # Header on BOTH endpoints — proves the persistent client carries it
    # across every route (decide + submit + any future endpoint).
    assert decide_route.calls.last.request.headers["authorization"] == expected
    assert record_route.calls.last.request.headers["authorization"] == expected


# --------------------------------------------------------------------------- #
# (3) the header is configured ONCE on the connection-pooled client — never
# rebuilt per call (perf assertion + sanity of the ctor wiring).
# --------------------------------------------------------------------------- #


@respx.mock
def test_api_key_header_pooled_not_per_call() -> None:
    rec = _pre_record()
    respx.post("http://srv/v1/governance/decide").mock(
        return_value=httpx.Response(200, json=_verdict_for(rec))
    )
    respx.post("http://srv/v1/governance/record").mock(
        return_value=httpx.Response(202, json={"accepted": True})
    )

    with ShieldClient("http://srv", api_key=_API_KEY) as c:
        expected = f"Bearer {_API_KEY}"
        # Set at ctor time, BEFORE any call.
        assert c._client.headers["authorization"] == expected
        headers_obj_id_before = id(c._client.headers)

        c.decide(rec)
        c.submit(rec)
        c.decide(rec)  # multiple calls — header must not be rebuilt.

        # Same Headers container, same value — connection-pooled, not per-call.
        assert id(c._client.headers) == headers_obj_id_before
        assert c._client.headers["authorization"] == expected


# --------------------------------------------------------------------------- #
# (4) §A8 (e) — ORTHOGONALITY: api_key MUST NOT influence the FROZEN §4
# Ed25519 record signing path. The SDK-side mirror of the server's test.
# --------------------------------------------------------------------------- #


def test_ed25519_record_signing_orthogonal_to_api_key() -> None:
    rec = _pre_record()

    # Sign the record FIRST, with NO client at all in scope.
    signed_no_client = canonical.finalize_record(rec, _PRIV)

    # Now create both flavours of client. Neither construction may touch the
    # record's signed payload (api_key is transport-only, sdk.py-only state).
    with (
        ShieldClient("http://srv", api_key=None) as c_open,
        ShieldClient("http://srv", api_key=_API_KEY) as c_enterprise,
    ):
        # Re-sign — bit-for-bit identical: deterministic Ed25519 over the
        # FROZEN canonical signable projection, which never mentions the
        # api_key (and the function doesn't take a client at all).
        signed_with_open_client = canonical.finalize_record(rec, _PRIV)
        signed_with_enterprise_client = canonical.finalize_record(rec, _PRIV)

        assert (
            signed_no_client.signature
            == signed_with_open_client.signature
            == signed_with_enterprise_client.signature
        )
        assert (
            signed_no_client.payload_hash
            == signed_with_open_client.payload_hash
            == signed_with_enterprise_client.payload_hash
        )

        # The signed JCS bytes never reference the api_key, Bearer scheme, or
        # the Authorization header — the §4 signed body is transport-blind.
        sig_str = canonical.record_signing_string(rec)
        for forbidden in (_API_KEY, "Authorization", "Bearer", "as_test_"):
            assert forbidden not in sig_str

        # And the signature verifies independently of which client exists.
        assert canonical.verify_record(signed_no_client, _PUB) is True
        assert canonical.verify_record(signed_with_enterprise_client, _PUB) is True

        # Sanity: the api_key DOES live on the enterprise client's transport
        # (proves both authorities exist — they're just orthogonal gates).
        assert "authorization" not in c_open._client.headers
        assert c_enterprise._client.headers["authorization"] == f"Bearer {_API_KEY}"
