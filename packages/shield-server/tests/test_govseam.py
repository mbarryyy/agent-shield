"""W3 PR-S1 — gov↔server decide-seam + pre-warm.

Proves the ownership split: GOVERNANCE owns the (UNSIGNED) decision; SERVER
owns ingest + the chained-record identity + signing (shield-server key) +
intervention_log + Channel-2. Default = honest NullGovernanceApp (UNSIGNED
PASS, explicitly a staged stub) until gov Task #21 lands.
"""

from __future__ import annotations

import sys
import types

import pytest
import shield_sdk.canonical as canonical
import shield_sdk.crypto as crypto
from shield_sdk.schema import (
    Decision,
    GovernanceVerdict,
    Guardian,
    ShieldActionRecord,
    VerdictReason,
)
from shield_server import agents as agent_svc
from shield_server.config import Settings
from shield_server.errors import AppError
from shield_server.governance import decide, resume
from shield_server.govseam import (
    NullGovernanceApp,
    _GovSeamAdapter,
    load_governance_app,
)
from shield_server.models import RegisterAgentRequest
from shield_server.storage import Storage, build_memory_storage

PRIV = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
PUB = crypto.get_public_key_base64url(PRIV)


async def test_null_gov_app_returns_unsigned_pass() -> None:
    rec = ShieldActionRecord(
        org_id="demo-org",
        agent_id="a",
        agent_pubkey_kid="k",
        phase="pre_exec",
        run_id="r",
    )
    v = await NullGovernanceApp().decide(rec)
    assert v.decision is Decision.PASS
    assert v.signature_by_shield is None  # UNSIGNED — server signs
    assert v.reasons[0].label == "STUB_PASS"
    assert v.record_id == rec.record_id


def test_loader_falls_back_to_null_when_gov_surface_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # State-robust: deterministically exercise the gov-ABSENT Null-fallback
    # branch regardless of whether shield_governance (gov W3) is present in the
    # workspace. Binding sys.modules[name]=None makes `import name` raise
    # ImportError (CPython import-machinery contract), which
    # load_governance_app() catches → the honest NullGovernanceApp default.
    #
    # Was premised on "gov Task #21 hasn't shipped build_decide_app/decide
    # yet"; gov-W3 ships that surface, so the *ambient* loader now correctly
    # returns a _GovSeamAdapter. Simulating the precondition restores
    # determinism (same spirit as the Task #25 govseam.py state-robust
    # hotfix) while STILL genuinely guarding the Null-fallback branch —
    # coverage is not weakened.
    monkeypatch.setitem(sys.modules, "shield_governance", None)
    app = load_governance_app()
    assert isinstance(app, NullGovernanceApp)


def test_loader_returns_adapter_when_gov_surface_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # State-robust counterpart: SIMULATE the converged gov-W3 surface (Task #21
    # landing build_decide_app/decide/resume) via an injected stub module, so
    # the real _GovSeamAdapter wiring path is exercised deterministically
    # whether or not gov-W3 is present in the workspace.
    fake = types.ModuleType("shield_governance")

    async def _decide(app: object, rec: object) -> object:  # pragma: no cover
        raise AssertionError("loader must not invoke decide")

    async def _resume(
        app: object, incident_id: str, decision: str, payload: object
    ) -> object:  # pragma: no cover
        raise AssertionError("loader must not invoke resume")

    fake.build_decide_app = lambda: object()
    fake.decide = _decide
    fake.resume = _resume
    monkeypatch.setitem(sys.modules, "shield_governance", fake)
    app = load_governance_app()
    assert isinstance(app, _GovSeamAdapter)


class _FakeBlockGov:
    """A gov stand-in returning an UNSIGNED BLOCK with deliberately WRONG ids,
    to prove the server forces the chained-record identity and signs."""

    async def decide(self, rec: ShieldActionRecord) -> GovernanceVerdict:
        return GovernanceVerdict(
            record_id="WRONG",
            correlation_id="WRONG",
            run_id="WRONG",
            decision=Decision.BLOCK,
            risk_score=0.93,
            reasons=[
                VerdictReason(agent=Guardian.DEFENDER, label="RECIPIENT_NOT_ALLOWLISTED", score=0.9)
            ],
        )


async def test_server_signs_and_forces_identity_on_gov_verdict() -> None:
    storage: Storage = build_memory_storage()
    await agent_svc.register_agent(
        storage,
        RegisterAgentRequest(
            agent_id="agentdojo-banking-v1",
            keys=[{"kid": "k", "public_key": PUB}],  # type: ignore[list-item]
        ),
        "demo-org",
    )
    rec = ShieldActionRecord(
        org_id="demo-org",
        agent_id="agentdojo-banking-v1",
        agent_pubkey_kid="k",
        phase="pre_exec",
        run_id="run-0001",
    )
    rec.payload.tool_name = "send_money"
    rec = canonical.finalize_record(rec, PRIV)

    settings = Settings.from_env()
    verdict = await decide(storage, rec, settings, _FakeBlockGov())

    # Governance owns the DECISION ...
    assert verdict.decision is Decision.BLOCK
    assert verdict.risk_score == 0.93
    # ... server owns the chained-record IDENTITY (gov's WRONG ids overridden) ...
    assert verdict.record_id == rec.record_id
    assert verdict.correlation_id == rec.correlation_id
    assert verdict.run_id == rec.run_id
    # ... and SIGNING (gov returned it UNSIGNED; server attaches the sig).
    assert verdict.shield_kid == "shield-server-key-v1"
    assert verdict.latency_ms is not None and verdict.served_at is not None
    server_pub = crypto.get_public_key_base64url(settings.server_signing_key)
    assert verdict.signature_by_shield is not None
    assert canonical.verify_verdict(verdict, server_pub) is True

    # The decision is logged + chained under the server-forced identity.
    log = storage.db.intervention_log  # type: ignore[attr-defined]
    assert len(log) == 1
    assert log[0]["decision"] == "BLOCK" and log[0]["record_id"] == rec.record_id


async def test_null_resume_unsigned_stub() -> None:
    v = await NullGovernanceApp().resume("inc-1", "accept", None)
    assert v.decision.value == "PASS"
    assert v.signature_by_shield is None  # UNSIGNED — server signs
    assert v.correlation_id == "inc-1"
    assert v.reasons[0].label == "HITL_RESUME_STUB"


async def test_resume_signs_and_validates_decision() -> None:
    settings = Settings.from_env()
    storage = build_memory_storage()
    v = await resume(storage, settings, NullGovernanceApp(), "inc-9", "accept", {"note": "ok"})
    assert v.decision.value == "PASS"
    assert v.shield_kid == "shield-server-key-v1"
    assert v.served_at is not None and v.latency_ms is not None
    server_pub = crypto.get_public_key_base64url(settings.server_signing_key)
    assert v.signature_by_shield is not None
    assert canonical.verify_verdict(v, server_pub) is True

    with pytest.raises(AppError) as ei:
        await resume(storage, settings, NullGovernanceApp(), "inc-9", "not-a-decision", None)
    assert ei.value.error_code == "VALIDATION_ERROR"
