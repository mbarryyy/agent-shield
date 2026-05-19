"""HTTP layer via TestClient — Elydora console contract (lib/api.ts)."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient
from shield_server._b64 import b64url_encode
from shield_server.ingest import _signable
from shield_server.models import OperationRecord

from .conftest import FakeCrypto, fake_signature

PUBKEY = b64url_encode(b"\x02" * 32)


def _signed_body(crypto: FakeCrypto) -> dict[str, object]:
    rec = OperationRecord(
        op_version="1.0",
        operation_id="op-http-1",
        org_id="demo-org",
        agent_id="banking",
        issued_at=int(time.time() * 1000),
        ttl_ms=30_000,
        nonce="http-nonce",
        operation_type="tool_call",
        subject={"id": "c1"},
        action={"tool": "send_money"},
        payload={"amount": 1.0},
        payload_hash="ph",
        prev_chain_hash="A" * 43,
        agent_pubkey_kid="k1",
        signature="x",
    )
    rec.signature = fake_signature(PUBKEY, crypto.canonical(_signable(rec)).encode("utf-8"))
    return rec.model_dump()


def test_health_and_protocol_header(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.headers["X-Elydora-Protocol-Version"] == "1.0"
    assert "X-Request-Id" in r.headers


def test_full_operation_flow_over_http(client: TestClient, crypto: FakeCrypto) -> None:
    reg = client.post(
        "/v1/agents/register",
        json={"agent_id": "banking", "keys": [{"kid": "k1", "public_key": PUBKEY}]},
    )
    assert reg.status_code == 201

    sub = client.post("/v1/operations", json=_signed_body(crypto))
    assert sub.status_code == 202, sub.text
    ear = sub.json()["receipt"]
    assert ear["seq_no"] == 1

    got = client.get("/v1/operations/op-http-1")
    assert got.status_code == 200
    assert got.json()["operation"]["operation_id"] == "op-http-1"

    ver = client.post("/v1/operations/op-http-1/verify")
    assert ver.status_code == 200
    assert ver.json()["valid"] is True

    aud = client.post("/v1/audit/query", json={"limit": 10})
    assert aud.status_code == 200
    assert aud.json()["total_count"] == 1


def test_error_response_shape(client: TestClient) -> None:
    r = client.get("/v1/operations/does-not-exist")
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert "request_id" in body["error"]
    assert isinstance(body["error"]["message"], str)


def test_console_boot_endpoints(client: TestClient) -> None:
    assert client.get("/v1/agents").json() == {"agents": []}
    assert client.get("/v1/epochs").json() == {"epochs": []}
    assert client.get("/v1/exports").json() == {"exports": []}
    assert client.get("/.well-known/elydora/jwks.json").json() == {"keys": []}
    tok = client.post("/v1/auth/token", json={"ttl_seconds": 3600})
    assert tok.status_code == 200 and tok.json()["token"]
    assert client.post("/v1/auth/token", json={"ttl_seconds": None}).json()["expires_at"] is None


def test_agent_lifecycle_over_http(client: TestClient) -> None:
    client.post(
        "/v1/agents/register",
        json={"agent_id": "a9", "keys": [{"kid": "k", "public_key": "P"}]},
    )
    assert (
        client.patch("/v1/agents/a9", json={"integration_type": "letta"}).json()["agent"][
            "integration_type"
        ]
        == "letta"
    )
    assert (
        client.post("/v1/agents/a9/freeze", json={"reason": "incident"}).json()["agent"]["status"]
        == "frozen"
    )
    assert (
        client.post("/v1/agents/a9/unfreeze", json={"reason": "cleared"}).json()["agent"]["status"]
        == "active"
    )
    assert client.post("/v1/agents/a9/revoke", json={"kid": "k", "reason": "rot"}).json() == {
        "revoked": True
    }
    assert client.request("DELETE", "/v1/agents/a9").json() == {"deleted": True}


def test_submit_rejects_bodyless(client: TestClient) -> None:
    r = client.post("/v1/operations", json={"not": "an-eor"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_epoch_and_export_not_found(client: TestClient) -> None:
    assert client.get("/v1/epochs/e1").status_code == 404
    assert client.get("/v1/exports/x1").status_code == 404
    assert client.get("/v1/exports/x1/download").status_code == 400
    created = client.post("/v1/exports", json={"format": "json"})
    assert created.status_code == 201
    assert created.json()["export"]["status"] == "queued"
