"""Agent registry service (Elydora agent-service parity)."""

from __future__ import annotations

import pytest
from shield_server import agents as svc
from shield_server.errors import AppError
from shield_server.models import RegisterAgentRequest
from shield_server.storage import Storage

ORG = "demo-org"


def _req(agent_id: str = "a1") -> RegisterAgentRequest:
    return RegisterAgentRequest(
        agent_id=agent_id,
        display_name="Banking Agent",
        keys=[{"kid": "k1", "public_key": "PUBKEY"}],  # type: ignore[list-item]
    )


async def test_register_get_list(storage: Storage) -> None:
    res = await svc.register_agent(storage, _req(), ORG)
    assert res.agent.agent_id == "a1"
    assert res.agent.status == "active"
    assert res.keys[0].kid == "k1"

    got = await svc.get_agent(storage, "a1", ORG)
    assert got.agent.display_name == "Banking Agent"
    assert len(got.keys) == 1

    listed = await svc.list_agents(storage, ORG)
    assert [a.agent_id for a in listed.agents] == ["a1"]


async def test_register_duplicate(storage: Storage) -> None:
    await svc.register_agent(storage, _req(), ORG)
    with pytest.raises(AppError) as ei:
        await svc.register_agent(storage, _req(), ORG)
    assert ei.value.error_code == "VALIDATION_ERROR"


async def test_freeze_unfreeze_status(storage: Storage) -> None:
    await svc.register_agent(storage, _req(), ORG)
    frozen = await svc.set_agent_status(storage, "a1", "frozen", ORG)
    assert frozen.status == "frozen"
    active = await svc.set_agent_status(storage, "a1", "active", ORG)
    assert active.status == "active"


async def test_update_integration_type(storage: Storage) -> None:
    await svc.register_agent(storage, _req(), ORG)
    updated = await svc.update_integration_type(storage, "a1", "claudecode", ORG)
    assert updated.integration_type == "claudecode"


async def test_revoke_key(storage: Storage) -> None:
    await svc.register_agent(storage, _req(), ORG)
    await svc.revoke_key(storage, "a1", "k1", ORG)
    got = await svc.get_agent(storage, "a1", ORG)
    assert got.keys[0].status == "revoked"
    with pytest.raises(AppError) as ei:
        await svc.revoke_key(storage, "a1", "missing", ORG)
    assert ei.value.error_code == "NOT_FOUND"


async def test_delete_agent(storage: Storage) -> None:
    await svc.register_agent(storage, _req(), ORG)
    await svc.delete_agent(storage, "a1", ORG)
    with pytest.raises(AppError) as ei:
        await svc.get_agent(storage, "a1", ORG)
    assert ei.value.error_code == "UNKNOWN_AGENT"


async def test_unknown_agent_ops(storage: Storage) -> None:
    for fn in (
        lambda: svc.get_agent(storage, "nope", ORG),
        lambda: svc.set_agent_status(storage, "nope", "frozen", ORG),
        lambda: svc.update_integration_type(storage, "nope", "sdk", ORG),
        lambda: svc.delete_agent(storage, "nope", ORG),
    ):
        with pytest.raises(AppError):
            await fn()


async def test_register_requires_agent_id(storage: Storage) -> None:
    with pytest.raises(AppError):
        await svc.register_agent(storage, RegisterAgentRequest(agent_id="", keys=[]), ORG)
