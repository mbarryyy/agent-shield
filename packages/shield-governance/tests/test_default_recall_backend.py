"""Wave-2 chunk #2: the router-backed guardian path defaults to REAL local
Chroma recall when a persist directory is configured — instead of silently
falling back to the process-local short-window memory.

The injection seam (``memory=``) is preserved: an explicit memory wins; and
when NEITHER a memory nor a persist dir is given, the process-local fallback
still applies (so tests that don't have a persist dir keep working).
"""

from __future__ import annotations

import pytest
import shield_sdk.canonical as canonical
import shield_sdk.crypto as crypto
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from shield_governance.evaluator import EvaluatorConfig
from shield_governance.evidence import GuardianEvidenceRecorder
from shield_governance.memory import (
    ChromaIncidentMemory,
    ChromaVectorStore,
    ChromaVectorStoreConfig,
)
from shield_governance.model_router import GUARDIAN_ROLES, ResolvedModel, ShieldModelRouter
from shield_governance.router_guardians import (
    build_router_backed_guardians,
    make_router_backed_async_channel2_handler,
    resolve_default_memory,
)
from shield_governance.verdicts import AsyncVerdictHandoff
from shield_sdk.schema import ActionPayload, Decision, Guardian, Phase, ShieldActionRecord

PRIV = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
PUB = crypto.get_public_key_base64url(PRIV)


class _ToolableFake(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):  # type: ignore[override,no-untyped-def]  # noqa: ARG002
        return self


def _eval_recall_sequence() -> list[AIMessage]:
    return [
        AIMessage(
            content="",
            tool_calls=[{"name": "recall_similar_incidents", "args": {}, "id": "tc-recall"}],
        ),
        AIMessage(content="DECISION: GROUNDED\nREASON: memory reviewed"),
    ]


def _router() -> ShieldModelRouter:
    def builder(resolved: ResolvedModel, api_key: str | None) -> object:  # noqa: ARG001
        if resolved.role == "evaluator":
            return _ToolableFake(responses=_eval_recall_sequence())
        return _ToolableFake(responses=[AIMessage(content="PASS")])

    guardians = {
        role: {"provider": "local", "model": f"{role}-model", "served_via": "local"}
        for role in GUARDIAN_ROLES
    }
    return ShieldModelRouter(
        {"profile": "test", "guardians": guardians},
        client_builders={"local": builder},
    )


def _record(*, run_id: str = "default-recall-run") -> ShieldActionRecord:
    rec = ShieldActionRecord(
        run_id=run_id,
        phase=Phase.POST_EXEC,
        agent_pubkey_kid=PUB,
        payload=ActionPayload(
            tool_name="send_money",
            tool_args={"recipient": "repeat-iban", "amount": 10_000.0, "subject": "x"},
        ),
    )
    return canonical.finalize_record(rec, PRIV)


def test_resolve_default_memory_explicit_wins(tmp_path) -> None:
    sentinel = object()
    assert resolve_default_memory(sentinel, tmp_path) is sentinel


def test_resolve_default_memory_chroma_when_persist_dir(tmp_path) -> None:
    mem = resolve_default_memory(None, tmp_path)
    assert isinstance(mem, ChromaIncidentMemory)
    assert mem.collection_name == "incidents"


def test_resolve_default_memory_process_local_when_nothing(tmp_path) -> None:  # noqa: ARG001
    from shield_governance.evaluator_agent import EvaluatorAgentMemory

    mem = resolve_default_memory(None, None)
    assert isinstance(mem, EvaluatorAgentMemory)


def test_build_guardians_defaults_to_chroma_with_persist_dir(tmp_path) -> None:
    guardians = build_router_backed_guardians(
        _router(),
        evidence_recorder=GuardianEvidenceRecorder(),
        evaluator_config=EvaluatorConfig(run_invariant=False, run_hallucination=True),
        memory_persist_directory=tmp_path,
    )
    # The evaluator's hallucination checker now holds a real Chroma incident memory.
    checker_memory = guardians.evaluator._hallucination._memory  # type: ignore[attr-defined]
    assert isinstance(checker_memory, ChromaIncidentMemory)
    assert checker_memory.collection_name == "incidents"


@pytest.mark.asyncio
async def test_async_handler_uses_chroma_recall_by_default(tmp_path) -> None:
    # Seed prior incident on the shared incidents collection.
    store = ChromaVectorStore(ChromaVectorStoreConfig(persist_directory=tmp_path))
    store.incident_memory().remember_record(
        _record(run_id="prior-async"), decision=Decision.ALERT, reasons=("evaluator.drift",)
    )

    seen: list[AsyncVerdictHandoff] = []

    async def sink(handoff: AsyncVerdictHandoff) -> None:
        seen.append(handoff)

    handler = make_router_backed_async_channel2_handler(
        router=_router(),
        evidence_recorder=GuardianEvidenceRecorder(),
        evaluator_config=EvaluatorConfig(run_invariant=False, run_hallucination=True),
        memory_persist_directory=tmp_path,
        on_verdict=sink,
        key_resolver=lambda kid: kid,
    )
    await handler(_record(run_id="current-async"))

    assert len(seen) == 1
    by_guardian = {row.guardian: row for row in seen[0].guardian_evidence}
    evaluator_row = by_guardian[Guardian.EVALUATOR]
    assert evaluator_row.memory is not None
    # Default recall hit the REAL Chroma incidents collection, not process-local.
    assert evaluator_row.memory["memory_backend"] == "chroma"
    assert evaluator_row.memory["collection"] == "incidents"
    assert evaluator_row.tool_calls == ("recall_similar_incidents",)
