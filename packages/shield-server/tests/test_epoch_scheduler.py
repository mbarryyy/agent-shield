from __future__ import annotations

import json

from fastapi.testclient import TestClient
from shield_server.config import Settings
from shield_server.epoch_scheduler import run_epoch_once
from shield_server.models import EER, Epoch
from shield_server.storage import Storage

ORG = "demo-org"
AGENT = "agentdojo-banking-v1"


async def _insert_operation(
    storage: Storage,
    *,
    operation_id: str = "rec-epoch-1",
    chain_hash: str = "chain-hash-1",
    created_at: int = 1_700_000_000_000,
) -> None:
    await storage.db.execute(
        "INSERT INTO operations (operation_id, org_id, agent_id, seq_no, "
        "operation_type, issued_at, ttl_ms, nonce, subject, action, "
        "payload_hash, prev_chain_hash, chain_hash, agent_pubkey_kid, "
        "signature, r2_payload_key, created_at, correlation_id, run_id, "
        "phase) VALUES "
        "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)",
        operation_id,
        ORG,
        AGENT,
        1,
        "tool_call",
        created_at,
        60_000,
        f"nonce-{operation_id}",
        "{}",
        "{}",
        f"payload-{operation_id}",
        "prev",
        chain_hash,
        "kid-1",
        "sig",
        f"{ORG}/{AGENT}/{operation_id}",
        created_at,
        f"corr-{operation_id}",
        "run-epoch",
        "pre_exec",
    )


async def _persist_epoch(storage: Storage) -> Epoch:
    epoch = Epoch(
        epoch_id="epoch_persisted",
        org_id=ORG,
        start_time=10,
        end_time=20,
        root_hash="persisted-root",
        leaf_count=7,
        r2_epoch_key=f"{ORG}/epochs/epoch_persisted.json",
        created_at=30,
    )
    eer = EER(
        epoch_id=epoch.epoch_id,
        org_id=epoch.org_id,
        start_time=epoch.start_time,
        end_time=epoch.end_time,
        leaf_count=epoch.leaf_count,
        root_hash=epoch.root_hash,
        hash_alg="sha256-binary-merkle-v1",
        signature_by_elydora="persisted-signature",
    )
    await storage.objects.put(
        epoch.r2_epoch_key,
        json.dumps(
            {"epoch": epoch.model_dump(mode="json"), "eer": eer.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
        "application/json",
    )
    await storage.db.execute(
        "INSERT INTO epochs (epoch_id, org_id, start_time, end_time, root_hash, "
        "leaf_count, r2_epoch_key, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
        epoch.epoch_id,
        epoch.org_id,
        epoch.start_time,
        epoch.end_time,
        epoch.root_hash,
        epoch.leaf_count,
        epoch.r2_epoch_key,
        epoch.created_at,
    )
    return epoch


async def test_run_once_creates_persisted_epoch_from_stored_governance_records(
    storage: Storage, settings: Settings
) -> None:
    await _insert_operation(storage)

    result = await run_epoch_once(storage, ORG, settings.server_signing_key)

    assert result.status == "created"
    assert result.epoch is not None
    assert result.eer is not None
    assert result.epoch.leaf_count == 1
    assert result.eer.signature_by_elydora
    rows = await storage.db.fetch("SELECT * FROM epochs")
    assert [row["epoch_id"] for row in rows] == [result.epoch.epoch_id]
    artifact = await storage.objects.get(result.epoch.r2_epoch_key)
    assert artifact is not None
    assert json.loads(artifact)["eer"]["signature_by_elydora"] == result.eer.signature_by_elydora


async def test_epoch_read_route_returns_persisted_epoch(
    client: TestClient, storage: Storage
) -> None:
    epoch = await _persist_epoch(storage)
    await _insert_operation(storage, chain_hash="newer-on-demand-chain", created_at=40)

    listed = client.get("/v1/epochs")

    assert listed.status_code == 200
    assert listed.json()["epochs"] == [epoch.model_dump(mode="json")]

    detail = client.get(f"/v1/epochs/{epoch.epoch_id}")
    assert detail.status_code == 200
    assert detail.json()["epoch"] == epoch.model_dump(mode="json")
    assert detail.json()["eer"]["signature_by_elydora"] == "persisted-signature"


async def test_epoch_read_route_falls_back_to_on_demand_when_persisted_absent(
    client: TestClient, storage: Storage
) -> None:
    await _insert_operation(storage)

    listed = client.get("/v1/epochs")

    assert listed.status_code == 200
    epochs = listed.json()["epochs"]
    assert len(epochs) == 1
    assert epochs[0]["org_id"] == ORG
    assert epochs[0]["leaf_count"] == 1
    assert await storage.db.fetch("SELECT * FROM epochs") == []

    detail = client.get(f"/v1/epochs/{epochs[0]['epoch_id']}")
    assert detail.status_code == 200
    assert detail.json()["epoch"] == epochs[0]
    assert detail.json()["eer"]["signature_by_elydora"]


async def test_run_once_empty_data_is_labelled_skipped_not_attested(
    storage: Storage, settings: Settings
) -> None:
    result = await run_epoch_once(storage, ORG, settings.server_signing_key)

    assert result.status == "skipped_empty"
    assert result.reason == "no_operations"
    assert result.epoch is None
    assert result.eer is None
    assert await storage.db.fetch("SELECT * FROM epochs") == []
