"""Agent registry — port of Elydora agent-service.ts behaviour.

Register / list / get / update / freeze / unfreeze / revoke-key / delete. The
console (`lib/api.ts` agents.*) is the contract for the request/response shapes
(api.ts: RegisterAgent*, GetAgentResponse, ListAgentsResponse, ...).
"""

from __future__ import annotations

import time

from .errors import AppError
from .models import (
    Agent,
    AgentKey,
    GetAgentResponse,
    ListAgentsResponse,
    RegisterAgentRequest,
    RegisterAgentResponse,
)
from .storage import Storage


def _now() -> int:
    return int(time.time() * 1000)


async def register_agent(
    storage: Storage, req: RegisterAgentRequest, org_id: str
) -> RegisterAgentResponse:
    if not req.agent_id:
        raise AppError(400, "VALIDATION_ERROR", "Missing agent_id.")
    now = _now()
    existing = await storage.db.fetchrow(
        "SELECT * FROM agents WHERE agent_id = $1 AND org_id = $2",
        req.agent_id,
        org_id,
    )
    if existing is not None:
        raise AppError(400, "VALIDATION_ERROR", "Agent already registered.")

    agent = Agent(
        agent_id=req.agent_id,
        org_id=org_id,
        display_name=req.display_name or req.agent_id,
        responsible_entity=req.responsible_entity or "unspecified",
        integration_type=req.integration_type or "sdk",
        status="active",
        created_at=now,
        updated_at=now,
    )
    async with storage.db.transaction() as tx:
        await tx.execute(
            "INSERT INTO agents (agent_id, org_id, display_name, "
            "responsible_entity, integration_type, status, created_at, "
            "updated_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            agent.agent_id,
            agent.org_id,
            agent.display_name,
            agent.responsible_entity,
            agent.integration_type,
            agent.status,
            agent.created_at,
            agent.updated_at,
        )
        keys: list[AgentKey] = []
        for k in req.keys:
            ak = AgentKey(
                kid=k.kid,
                agent_id=req.agent_id,
                public_key=k.public_key,
                algorithm="ed25519",
                status="active",
                created_at=now,
                retired_at=None,
            )
            keys.append(ak)
            await tx.execute(
                "INSERT INTO agent_keys (kid, agent_id, public_key, algorithm, "
                "status, created_at, retired_at) VALUES ($1,$2,$3,$4,$5,$6,$7)",
                ak.kid,
                ak.agent_id,
                ak.public_key,
                ak.algorithm,
                ak.status,
                ak.created_at,
                ak.retired_at,
            )
    return RegisterAgentResponse(agent=agent, keys=keys)


async def list_agents(storage: Storage, org_id: str) -> ListAgentsResponse:
    rows = await storage.db.fetch("SELECT * FROM agents")
    agents = [Agent.model_validate(r) for r in rows if r["org_id"] == org_id]
    agents.sort(key=lambda a: a.created_at, reverse=True)
    return ListAgentsResponse(agents=agents)


async def _require_agent(storage: Storage, agent_id: str, org_id: str) -> Agent:
    row = await storage.db.fetchrow(
        "SELECT * FROM agents WHERE agent_id = $1 AND org_id = $2",
        agent_id,
        org_id,
    )
    if row is None:
        raise AppError(404, "UNKNOWN_AGENT")
    return Agent.model_validate(row)


async def get_agent(storage: Storage, agent_id: str, org_id: str) -> GetAgentResponse:
    agent = await _require_agent(storage, agent_id, org_id)
    key_rows = await storage.db.fetch("SELECT * FROM agent_keys WHERE agent_id = $1", agent_id)
    return GetAgentResponse(agent=agent, keys=[AgentKey.model_validate(k) for k in key_rows])


async def update_integration_type(
    storage: Storage, agent_id: str, integration_type: str, org_id: str
) -> Agent:
    await _require_agent(storage, agent_id, org_id)
    await storage.db.execute(
        "UPDATE agents SET integration_type = $1, updated_at = $2 WHERE agent_id = $3",
        integration_type,
        _now(),
        agent_id,
    )
    return await _require_agent(storage, agent_id, org_id)


async def set_agent_status(storage: Storage, agent_id: str, status: str, org_id: str) -> Agent:
    await _require_agent(storage, agent_id, org_id)
    await storage.db.execute(
        "UPDATE agents SET status = $1, updated_at = $2 WHERE agent_id = $3",
        status,
        _now(),
        agent_id,
    )
    return await _require_agent(storage, agent_id, org_id)


async def revoke_key(storage: Storage, agent_id: str, kid: str, org_id: str) -> None:
    await _require_agent(storage, agent_id, org_id)
    key = await storage.db.fetchrow(
        "SELECT * FROM agent_keys WHERE kid = $1 AND agent_id = $2", kid, agent_id
    )
    if key is None:
        raise AppError(404, "NOT_FOUND", "Signing key not found.")
    await storage.db.execute(
        "UPDATE agent_keys SET status = $1, retired_at = $2 WHERE kid = $3",
        "revoked",
        _now(),
        kid,
    )


async def delete_agent(storage: Storage, agent_id: str, org_id: str) -> None:
    await _require_agent(storage, agent_id, org_id)
    async with storage.db.transaction() as tx:
        await tx.execute("DELETE FROM agent_keys WHERE agent_id = $1", agent_id)
        await tx.execute("DELETE FROM agents WHERE agent_id = $1", agent_id)
