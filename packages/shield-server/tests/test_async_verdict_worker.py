"""Background Channel-2 async verdict worker tests."""

from __future__ import annotations

import json

import pytest
import shield_sdk.canonical as canonical
import shield_sdk.crypto as crypto
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from shield_governance.auditor import Auditor
from shield_governance.channel2 import InMemoryChannel2Transport, StreamEntry, stream_key
from shield_governance.evaluator import Evaluator, EvaluatorConfig
from shield_governance.model_router import GUARDIAN_ROLES, ResolvedModel, ShieldModelRouter
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
    # The ``subject`` field matches the AgentDojo banking ``send_money`` tool
    # shape and the LocalPolicyStructuringAnalyzer policy expectations — kept
    # in the fixture so the default ``EvaluatorConfig()`` invariant pass does
    # not trip on a dict missing the ``subject`` member.
    rec.payload.tool_args = {
        "recipient": "ATTACKER-IBAN",
        "amount": 10_000.0,
        "subject": "Async worker fixture",
    }
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


class _ToolableFakeChatModel(FakeMessagesListChatModel):
    """``FakeMessagesListChatModel`` + no-op ``bind_tools`` so the Phase B
    Evaluator agent (which calls ``langchain.agents.create_agent`` →
    ``model.bind_tools(...)``) accepts it. Supervisor / Auditor scaffold also
    consume the same model via ``RouterTextClient.invoke``/``ainvoke``.
    """

    def bind_tools(self, tools, **kwargs):  # type: ignore[override,no-untyped-def]  # noqa: ARG002
        return self


def _evaluator_responses() -> list[AIMessage]:
    """Two-turn evaluator: tool_call → final GROUNDED decision.

    The tool result is discarded; we just need the agent loop to terminate.
    """
    return [
        AIMessage(
            content="",
            tool_calls=[{"name": "eval_invariant_policies", "args": {}, "id": "tc-eval-1"}],
            usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        ),
        AIMessage(
            content="DECISION: GROUNDED\nREASON: ok",
            usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        ),
    ]


def _single_message(text: str = "PASS") -> AIMessage:
    return AIMessage(
        content=text,
        usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    )


class _SpyRouter(ShieldModelRouter):
    """``ShieldModelRouter`` variant that records every ``model_factory`` call.

    Used by the A3 discriminative test to prove the worker's default
    production path actually drives ``model_factory("evaluator")`` — i.e. the
    router-backed handler is wired, not the legacy deterministic one.
    """

    def __init__(self, cfg: dict[str, object], **kwargs: object) -> None:
        super().__init__(cfg, **kwargs)  # type: ignore[arg-type]
        self.factory_calls: list[str] = []

    def model_factory(self, role: str):  # type: ignore[no-untyped-def]
        self.factory_calls.append(role)
        return super().model_factory(role)


def _spy_router() -> _SpyRouter:
    """Build a spy router with per-role toolable fake BaseChatModels."""

    def fake_builder(resolved: ResolvedModel, api_key: str | None) -> object:  # noqa: ARG001
        if resolved.role == "evaluator":
            return _ToolableFakeChatModel(responses=_evaluator_responses())
        return _ToolableFakeChatModel(responses=[_single_message("PASS")])

    guardians = {
        role: {"provider": "local", "model": f"{role}-model", "served_via": "local"}
        for role in GUARDIAN_ROLES
    }
    return _SpyRouter(
        {"profile": "test", "guardians": guardians},
        client_builders={"local": fake_builder},
    )


@pytest.mark.asyncio
async def test_default_production_path_drives_router_model_factory(
    storage: Storage, settings: Settings
) -> None:
    """A3 — discriminative wiring test.

    When ``AsyncVerdictWorker`` is constructed without explicit ``evaluator`` /
    ``auditor`` / ``supervisor`` overrides (i.e. the default production
    wiring), every record on the Channel-2 stream MUST flow through the
    router-backed handler — proven here by asserting
    ``ShieldModelRouter.model_factory("evaluator")`` is invoked at least once.

    If a future refactor accidentally restores the legacy
    ``make_async_channel2_handler`` default with the deterministic Evaluator,
    the spy router will record zero ``"evaluator"`` factory calls and this
    test fails — preventing a silent regression to the dormant LLM seam.
    """
    await _register(storage)
    rec = _signed_record()
    transport = InMemoryChannel2Transport()
    transport.publish(stream_key(rec.workflow_id), rec)

    router = _spy_router()
    worker = AsyncVerdictWorker(
        storage=storage,
        settings=settings,
        transport=transport,
        router=router,
    )

    handled = await worker.run_once(rec.workflow_id, block_ms=0)

    assert handled == 1
    assert "evaluator" in router.factory_calls, (
        "default production wiring must drive router.model_factory('evaluator') — "
        f"got factory_calls={router.factory_calls!r}"
    )


@pytest.mark.asyncio
async def test_key_resolver_enables_chain_verify_for_known_kid(
    storage: Storage, settings: Settings
) -> None:
    """A2 — discriminative G-7 fix test.

    Hand the worker a record signed with the registered agent key (kid =
    KID, distinct from the public key). Before the fix the worker passed
    the kid as the public key to ``verify_record`` so verification was
    permanently ``False``. After the fix the worker resolves the kid via
    the server's ``agent_keys`` registry and passes the real public key,
    so verification returns ``True`` and the Auditor reports
    ``chain_broken=False`` for the lone signed record.
    """
    await _register(storage)
    rec = _signed_record()

    auditor = Auditor()
    captured: list[Auditor] = []

    class _CapturingAuditor(Auditor):
        def audit(self, records, *, agent_pubkey_b64url):  # type: ignore[no-untyped-def]
            captured.append(agent_pubkey_b64url)
            return super().audit(records, agent_pubkey_b64url=agent_pubkey_b64url)

    spy_auditor = _CapturingAuditor()
    transport = InMemoryChannel2Transport()
    transport.publish(stream_key(rec.workflow_id), rec)

    worker = AsyncVerdictWorker(
        storage=storage,
        settings=settings,
        transport=transport,
        # Force the legacy path so we can swap in a capturing Auditor and
        # observe the public key that actually reaches ``audit``.
        evaluator=Evaluator(EvaluatorConfig(run_invariant=False, run_hallucination=False)),
        auditor=spy_auditor,
        supervisor=Supervisor(),
    )

    handled = await worker.run_once(rec.workflow_id, block_ms=0)

    assert handled == 1
    assert captured, "auditor.audit was not invoked"
    resolved = captured[-1]
    assert resolved == PUB, (
        f"key_resolver must return the registered public key for kid={KID!r}; "
        f"got {resolved!r} (the bug would have surfaced the kid string here)"
    )
    assert resolved != KID, "regression: kid was passed as the public key (G-7)"
    # mark unused vars used to keep ruff happy
    _ = auditor


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
