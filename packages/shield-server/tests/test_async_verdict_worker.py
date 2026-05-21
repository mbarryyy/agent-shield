"""Background Channel-2 async verdict worker tests."""

from __future__ import annotations

import json

import pytest
import shield_sdk.canonical as canonical
import shield_sdk.crypto as crypto
from shield_governance.auditor import Auditor
from shield_governance.channel2 import InMemoryChannel2Transport, StreamEntry, stream_key
from shield_governance.evaluator import Evaluator, EvaluatorConfig
from shield_governance.supervisor import Supervisor
from shield_sdk.schema import ActionRef, GovernanceVerdict, Phase, ShieldActionRecord
from shield_server import agents as agent_svc
from shield_server.async_verdict_worker import (
    AsyncVerdictWorker,
    CacheChannel2Transport,
)
from shield_server.config import Settings
from shield_server.governance import record
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
    *,
    phase: Phase = Phase.POST_EXEC,
    prev: str = "A" * 43,
    nonce: str = "asyncWorkerNonce000001",
    run_id: str = "run-worker",
    verdict_ref: str | None = None,
) -> ShieldActionRecord:
    rec = ShieldActionRecord(
        org_id=ORG,
        agent_id=AGENT,
        agent_pubkey_kid=KID,
        phase=phase,
        run_id=run_id,
        prev_chain_hash=prev,
        nonce=nonce,
        verdict_ref=verdict_ref,
        action=ActionRef(tool="send_money", args_digest="sha256:async-worker"),
    )
    rec.payload.tool_name = "send_money"
    rec.payload.tool_args = {"recipient": "ATTACKER-IBAN", "amount": 10_000.0}
    return canonical.finalize_record(rec, PRIV)


def _worker(
    storage: Storage,
    settings: Settings,
    transport: InMemoryChannel2Transport | CacheChannel2Transport,
) -> AsyncVerdictWorker:
    return AsyncVerdictWorker(
        storage=storage,
        settings=settings,
        transport=transport,
        evaluator=Evaluator(EvaluatorConfig(run_invariant=False, run_hallucination=False)),
        auditor=Auditor(),
        supervisor=Supervisor(),
    )


@pytest.mark.asyncio
async def test_worker_signs_persists_and_publishes_verdict_from_fake_action_stream(
    storage: Storage, settings: Settings
) -> None:
    rec = _signed_record()
    transport = InMemoryChannel2Transport()
    transport.publish(stream_key(rec.workflow_id), rec)

    handled = await _worker(storage, settings, transport).run_once(rec.workflow_id, block_ms=0)

    assert handled == 1
    rows = await storage.db.fetch("SELECT * FROM governance_verdicts")
    assert len(rows) == 1
    row = rows[0]
    assert row["record_id"] == rec.record_id
    assert row["correlation_id"] == rec.correlation_id

    published = storage.cache.streams["shield:verdicts:banking"]  # type: ignore[attr-defined]
    assert len(published) == 1
    fields = published[0][1]
    assert fields["record_id"] == rec.record_id
    assert fields["phase"] == "post_exec"
    signed_json = json.loads(fields["verdict"])
    assert signed_json["signature_by_shield"]
    assert canonical.verify_verdict(
        GovernanceVerdict.model_validate(signed_json),
        crypto.get_public_key_base64url(settings.server_signing_key),
    )


@pytest.mark.asyncio
async def test_post_exec_record_stream_produces_late_signed_verdict(
    storage: Storage, settings: Settings
) -> None:
    await _register(storage)
    rec = _signed_record(verdict_ref="sync-verdict-1")
    await record(storage, rec, settings)

    handled = await _worker(storage, settings, CacheChannel2Transport(storage.cache)).run_once(
        rec.workflow_id, block_ms=0
    )

    assert handled == 1
    published = storage.cache.streams["shield:verdicts:banking"]  # type: ignore[attr-defined]
    assert len(published) == 1
    fields = published[0][1]
    assert fields["correlation_id"] == rec.correlation_id
    assert fields["run_id"] == rec.run_id
    assert fields["phase"] == "post_exec"
    assert json.loads(fields["verdict"])["signature_by_shield"]


@pytest.mark.asyncio
async def test_worker_skips_bad_entries_and_deduplicates_record_publication(
    storage: Storage, settings: Settings
) -> None:
    rec = _signed_record()
    transport = InMemoryChannel2Transport()
    stream = stream_key(rec.workflow_id)
    transport._streams.setdefault(stream, []).append(  # noqa: SLF001 - test poison entry
        StreamEntry(id="poison-0", fields={"record": "{bad json"})
    )
    first = transport.publish(stream, rec)
    duplicate = transport.publish(stream, rec)

    handled = await _worker(storage, settings, transport).run_once(rec.workflow_id, block_ms=0)

    assert handled == 2
    assert len(await storage.db.fetch("SELECT * FROM governance_verdicts")) == 1
    assert len(storage.cache.streams["shield:verdicts:banking"]) == 1  # type: ignore[attr-defined]
    acked = transport.acked_ids(stream, "shield-evaluator")
    assert first in acked
    assert duplicate in acked
    assert "poison-0" not in acked
