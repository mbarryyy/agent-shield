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
    assert client.get("/v1/exports/x1/download").status_code == 404
    created = client.post("/v1/exports", json={"format": "json"})
    assert created.status_code == 400


def test_governance_decide_returns_signed_pass(client: TestClient) -> None:
    import shield_sdk.canonical as canonical
    import shield_sdk.crypto as crypto
    from shield_sdk.schema import ShieldActionRecord

    priv = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
    pub = crypto.get_public_key_base64url(priv)
    reg = client.post(
        "/v1/agents/register",
        json={
            "agent_id": "agentdojo-banking-v1",
            "keys": [{"kid": "agentdojo-banking-v1-key-v1", "public_key": pub}],
        },
    )
    assert reg.status_code == 201

    rec = ShieldActionRecord(
        org_id="demo-org",
        agent_id="agentdojo-banking-v1",
        agent_pubkey_kid="agentdojo-banking-v1-key-v1",
        phase="pre_exec",
        run_id="run-0001",
    )
    rec.payload.tool_name = "send_money"
    rec = canonical.finalize_record(rec, priv)

    r = client.post("/v1/governance/decide", json=rec.model_dump(mode="json"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "PASS"
    assert body["record_id"] == rec.record_id
    assert body["signature_by_shield"]
    assert r.headers["X-Elydora-Protocol-Version"] == "1.0"


def test_governance_decide_rejects_garbage(client: TestClient) -> None:
    r = client.post("/v1/governance/decide", json={"not": "a-record"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_governance_record_post_exec_acks_202(client: TestClient) -> None:
    import shield_sdk.canonical as canonical
    import shield_sdk.crypto as crypto
    from shield_sdk.schema import Phase, ShieldActionRecord

    priv = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
    pub = crypto.get_public_key_base64url(priv)
    assert (
        client.post(
            "/v1/agents/register",
            json={
                "agent_id": "agentdojo-banking-v1",
                "keys": [{"kid": "agentdojo-banking-v1-key-v1", "public_key": pub}],
            },
        ).status_code
        == 201
    )

    rec = ShieldActionRecord(
        org_id="demo-org",
        agent_id="agentdojo-banking-v1",
        agent_pubkey_kid="agentdojo-banking-v1-key-v1",
        phase=Phase.POST_EXEC,
        run_id="run-0001",
        verdict_ref="vrd-1",
    )
    rec.payload.tool_name = "send_money"
    rec = canonical.finalize_record(rec, priv)

    r = client.post("/v1/governance/record", json=rec.model_dump(mode="json"))
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["accepted"] is True
    assert body["record_id"] == rec.record_id
    assert body["seq_no"] == 1
    assert "signature_by_shield" not in body  # async post_exec: no verdict


def test_governance_hitl_resume_route(client: TestClient) -> None:
    ok = client.post(
        "/v1/governance/incidents/inc-42/resume",
        json={"decision": "accept", "payload": {"note": "approved"}},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["decision"] == "PASS"
    assert body["correlation_id"] == "inc-42"
    assert body["signature_by_shield"]  # server-signed
    assert (
        client.post(
            "/v1/governance/incidents/inc-42/resume", json={"decision": "bogus"}
        ).status_code
        == 400
    )
    assert client.post("/v1/governance/incidents/inc-42/resume", json={}).status_code == 400


def test_governance_hitl_resume_route_resolves_real_incident_verdict_id() -> None:
    import shield_sdk.canonical as canonical
    import shield_sdk.crypto as crypto
    from langgraph.checkpoint.memory import InMemorySaver
    from shield_governance.defender.engine import DefenderConfig
    from shield_governance.defender.rules import DefenderPolicy
    from shield_governance.graph import (
        build_decide_app,
    )
    from shield_governance.graph import (
        decide as gov_decide,
    )
    from shield_governance.graph import (
        resume as gov_resume,
    )
    from shield_sdk.schema import ActionRef, Phase, ShieldActionRecord
    from shield_server.app import create_app
    from shield_server.config import Settings
    from shield_server.storage import build_memory_storage

    class RealGov:
        def __init__(self) -> None:
            self._app = build_decide_app(
                defender_config=DefenderConfig(
                    enabled=True,
                    policy=DefenderPolicy(
                        amount_cap=10_000,
                        cumulative_cap=20_000,
                        review_floor=5_000,
                    ),
                ),
                checkpointer=InMemorySaver(),
            )

        async def decide(self, rec: ShieldActionRecord):
            return await gov_decide(self._app, rec)

        async def resume(self, incident_id: str, decision: str, payload: dict[str, object] | None):
            return await gov_resume(self._app, incident_id, decision, payload)

    priv = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
    pub = crypto.get_public_key_base64url(priv)
    app = create_app(
        storage=build_memory_storage(),
        settings=Settings.from_env(),
        governance=RealGov(),
    )
    with TestClient(app) as real_client:
        reg = real_client.post(
            "/v1/agents/register",
            json={
                "agent_id": "agentdojo-banking-v1",
                "keys": [{"kid": "agentdojo-banking-v1-key-v1", "public_key": pub}],
            },
        )
        assert reg.status_code == 201
        rec = ShieldActionRecord(
            agent_id="agentdojo-banking-v1",
            agent_pubkey_kid="agentdojo-banking-v1-key-v1",
            phase=Phase.PRE_EXEC,
            run_id="run-hitl-real",
            action=ActionRef(tool="send_money", args_digest="sha256:redacted-args"),
        )
        rec.payload.tool_name = "send_money"
        rec.payload.tool_args = {
            "recipient": "NEW-VENDOR",
            "amount": 6_000.0,
            "subject": "Invoice",
        }
        rec = canonical.finalize_record(rec, priv)
        gate = real_client.post("/v1/governance/decide", json=rec.model_dump(mode="json"))
        assert gate.status_code == 200, gate.text
        gate_body = gate.json()
        assert gate_body["decision"] == "ESCALATE"
        incident_id = gate_body["verdict_id"]

        incidents = real_client.get("/v1/governance/incidents?run_id=run-hitl-real")
        assert incidents.status_code == 200
        assert incidents.json()["incidents"][0]["incident_id"] == incident_id

        resumed = real_client.post(
            f"/v1/governance/incidents/{incident_id}/resume",
            json={"decision": "accept", "payload": {"note": "approved"}},
        )
        assert resumed.status_code == 200, resumed.text
        body = resumed.json()
        assert body["decision"] == "PASS"
        assert body["signature_by_shield"]

        after = real_client.get("/v1/governance/incidents?run_id=run-hitl-real")
        assert after.json()["incidents"][0]["status"] == "resolved"
        assert after.json()["incidents"][0]["resolution"] == "accept"
