"""API-key issue/list/revoke scoping tests for auth-v1."""

from __future__ import annotations

from fastapi.testclient import TestClient
from shield_server.auth.api_keys import issue_api_key, lookup_api_key
from shield_server.auth.utils import now_ms

from .conftest import bootstrap_admin_via_storage


def _seed_agent(client: TestClient, *, org_id: str, agent_id: str) -> None:
    import asyncio

    storage = client.app_storage  # type: ignore[attr-defined]

    async def run() -> None:
        await storage.db.execute(
            "INSERT INTO agents (agent_id, org_id, display_name, "
            "responsible_entity, integration_type, status, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            agent_id,
            org_id,
            agent_id,
            "owner",
            "sdk",
            "active",
            now_ms(),
            now_ms(),
        )

    asyncio.run(run())


def test_issue_api_key_rejects_agent_outside_principal_org(client: TestClient) -> None:
    bootstrap_admin_via_storage(client, email="owner-a@example.com", org_id="org-A")
    _seed_agent(client, org_id="org-B", agent_id="agent-B")

    response = client.post(
        "/v1/auth/api-keys",
        json={"display_name": "bad-scope", "prefix": "as_test_", "agent_id": "agent-B"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_api_keys_never_leaks_other_org_keys(client: TestClient) -> None:
    import asyncio

    bootstrap_admin_via_storage(client, email="owner-list@example.com", org_id="org-A")
    storage = client.app_storage  # type: ignore[attr-defined]

    async def seed() -> None:
        await issue_api_key(storage.db, org_id="org-B", created_by="u-b", prefix="as_test_")
        await issue_api_key(storage.db, org_id="org-A", created_by="u-a", prefix="as_test_")

    asyncio.run(seed())

    response = client.get("/v1/auth/api-keys")

    assert response.status_code == 200
    listed = response.json()["api_keys"]
    assert len(listed) == 1
    assert listed[0]["created_by"] == "u-a"


def test_revoke_api_key_cannot_revoke_other_org_key(client: TestClient) -> None:
    import asyncio

    bootstrap_admin_via_storage(client, email="owner-revoke@example.com", org_id="org-A")
    storage = client.app_storage  # type: ignore[attr-defined]

    async def seed():
        return await issue_api_key(storage.db, org_id="org-B", created_by="u-b", prefix="as_test_")

    issued = asyncio.run(seed())

    response = client.delete(f"/v1/auth/api-keys/{issued.row.api_key_id}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert asyncio.run(lookup_api_key(storage.db, raw_key=issued.raw_key)) is not None
