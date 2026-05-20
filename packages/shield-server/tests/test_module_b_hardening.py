"""Module B hardening interface tests.

These tests lock the server-owned governance publication boundary, Merkle
behavior, and read/export route shapes before implementation.
"""

from __future__ import annotations

import hashlib
import json

import shield_sdk.canonical as canonical
import shield_sdk.crypto as crypto
from fastapi.testclient import TestClient
from shield_sdk.schema import ActionRef, Decision, GovernanceVerdict, Phase, ShieldActionRecord
from shield_server import agents as agent_svc
from shield_server import governance as governance_svc
from shield_server.config import CONSUMER_GROUPS, Settings
from shield_server.governance import record
from shield_server.merkle import merkle_root
from shield_server.models import RegisterAgentRequest
from shield_server.storage import Storage

ORG = "demo-org"
PRIV = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
PUB = crypto.get_public_key_base64url(PRIV)
KID = "agentdojo-banking-v1-key-v1"
AGENT = "agentdojo-banking-v1"


async def _register(storage: Storage) -> None:
    await agent_svc.register_agent(
        storage,
        RegisterAgentRequest(agent_id=AGENT, keys=[{"kid": KID, "public_key": PUB}]),  # type: ignore[list-item]
        ORG,
    )


def _signed_record(
    *, phase: Phase = Phase.POST_EXEC, prev: str = "A" * 43, nonce: str = "moduleBnonce00000000"
) -> ShieldActionRecord:
    rec = ShieldActionRecord(
        org_id=ORG,
        agent_id=AGENT,
        agent_pubkey_kid=KID,
        phase=phase,
        run_id="run-module-b",
        prev_chain_hash=prev,
        nonce=nonce,
        action=ActionRef(tool="send_money", args_digest="sha256:module-b"),
    )
    rec.payload.tool_name = "send_money"
    rec.payload.tool_args = {"recipient": "ATTACKER-IBAN", "amount": 10000.0}
    return canonical.finalize_record(rec, PRIV)


def test_binary_merkle_root_sorts_leaves_and_duplicates_odd_level() -> None:
    a = hashlib.sha256(b"a").digest()
    b = hashlib.sha256(b"b").digest()
    c = hashlib.sha256(b"c").digest()
    ordered = sorted([c, a, b])
    left = hashlib.sha256(ordered[0] + ordered[1]).digest()
    right = hashlib.sha256(ordered[2] + ordered[2]).digest()
    expected = hashlib.sha256(left + right).digest()

    assert merkle_root([c, a, b]) == expected
    assert merkle_root([]) == hashlib.sha256(b"").digest()
    assert merkle_root([b]) == b


async def test_async_verdict_publication_is_signed_persisted_and_streamed(
    storage: Storage, settings: Settings
) -> None:
    await _register(storage)
    rec = _signed_record()
    await record(storage, rec, settings)

    unsigned = GovernanceVerdict(
        record_id="wrong-record",
        correlation_id="wrong-correlation",
        run_id="wrong-run",
        decision=Decision.ALERT,
        risk_score=0.61,
    )
    signed = await governance_svc.publish_async_verdict(storage, rec, unsigned, settings)

    assert signed.record_id == rec.record_id
    assert signed.correlation_id == rec.correlation_id
    assert signed.run_id == rec.run_id
    assert signed.shield_kid == "shield-server-key-v1"
    assert signed.served_at is not None
    assert signed.latency_ms is not None
    assert signed.signature_by_shield
    assert canonical.verify_verdict(
        signed, crypto.get_public_key_base64url(settings.server_signing_key)
    )

    rows = await storage.db.fetch("SELECT * FROM governance_verdicts")
    assert len(rows) == 1
    row = rows[0]
    assert row["verdict_id"] == signed.verdict_id
    assert row["record_id"] == rec.record_id
    assert row["correlation_id"] == rec.correlation_id
    assert row["run_id"] == rec.run_id
    assert row["decision"] == "ALERT"
    assert row["prevented_loss"] == 0.0
    assert json.loads((await storage.objects.get(str(row["r2_verdict_key"]))).decode())[
        "signature_by_shield"
    ]

    entries = storage.cache.streams["shield:verdicts:banking"]  # type: ignore[attr-defined]
    assert len(entries) == 1
    fields = entries[0][1]
    assert set(fields) == {
        "verdict_id",
        "record_id",
        "correlation_id",
        "run_id",
        "decision",
        "risk_score",
        "phase",
        "verdict",
    }
    assert fields["phase"] == "post_exec"
    assert json.loads(fields["verdict"])["signature_by_shield"]
    for group in CONSUMER_GROUPS:
        assert ("shield:verdicts:banking", group) in storage.cache.groups  # type: ignore[attr-defined]


def test_epoch_routes_return_epoch_and_signed_eer_shape(client: TestClient) -> None:
    client.post(
        "/v1/agents/register",
        json={"agent_id": AGENT, "keys": [{"kid": KID, "public_key": PUB}]},
    )
    rec = _signed_record(phase=Phase.PRE_EXEC)
    assert client.post("/v1/governance/decide", json=rec.model_dump(mode="json")).status_code == 200

    listed = client.get("/v1/epochs")
    assert listed.status_code == 200
    epochs = listed.json()["epochs"]
    assert len(epochs) == 1
    epoch = epochs[0]
    assert set(epoch) == {
        "epoch_id",
        "org_id",
        "start_time",
        "end_time",
        "root_hash",
        "leaf_count",
        "r2_epoch_key",
        "created_at",
    }
    assert epoch["org_id"] == ORG
    assert epoch["leaf_count"] == 1
    assert epoch["root_hash"]

    detail = client.get(f"/v1/epochs/{epoch['epoch_id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["epoch"] == epoch
    assert set(body["eer"]) == {
        "epoch_id",
        "org_id",
        "start_time",
        "end_time",
        "leaf_count",
        "root_hash",
        "hash_alg",
        "signature_by_elydora",
    }
    assert body["eer"]["hash_alg"] == "sha256-binary-merkle-v1"
    assert body["eer"]["signature_by_elydora"]


def test_compliance_export_is_completed_and_downloadable_json(client: TestClient) -> None:
    client.post(
        "/v1/agents/register",
        json={"agent_id": AGENT, "keys": [{"kid": KID, "public_key": PUB}]},
    )
    rec = _signed_record(phase=Phase.PRE_EXEC)
    assert client.post("/v1/governance/decide", json=rec.model_dump(mode="json")).status_code == 200

    created = client.post(
        "/v1/exports",
        json={"start_time": 0, "end_time": 9_999_999_999_999, "format": "json"},
    )
    assert created.status_code == 201
    export = created.json()["export"]
    assert export["status"] == "done"
    assert export["r2_export_key"]
    assert export["completed_at"] is not None

    listed = client.get("/v1/exports")
    assert [row["export_id"] for row in listed.json()["exports"]] == [export["export_id"]]

    got = client.get(f"/v1/exports/{export['export_id']}")
    assert got.status_code == 200
    assert got.json()["export"] == export
    assert got.json()["download_url"] == f"/v1/exports/{export['export_id']}/download"

    download = client.get(f"/v1/exports/{export['export_id']}/download")
    assert download.status_code == 200
    payload = download.json()
    assert set(payload) == {
        "export_id",
        "org_id",
        "query",
        "generated_at",
        "operations",
        "governance_verdicts",
        "epochs",
    }
    assert len(payload["operations"]) == 1
    assert len(payload["governance_verdicts"]) == 1
