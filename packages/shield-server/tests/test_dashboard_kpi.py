"""Task #31 (b) — server prevented_loss persistence + dashboard KPI read.

Two surfaces under test:

  1. ``governance_verdicts.prevented_loss`` MUST be populated from the §4
     ``GovernanceVerdict.obligations.prevented_loss`` that gov returns
     (not hardcoded 0). End-to-end through ``governance.decide`` with a
     fake gov that returns a BLOCK verdict carrying obligations.prevented_loss
     = $30k → assert the persisted row carries 30000.0.
  2. ``GET /v1/governance/dashboard/kpi`` org-wide rollup returns
     ``prevented_loss_total`` = Σ stored prevented_loss for the principal's
     org. Distinct from run-scoped ``/v1/governance/runs/{run_id}/cost``.
"""

from __future__ import annotations

import asyncio

import shield_sdk.canonical as canonical
import shield_sdk.crypto as crypto
from fastapi.testclient import TestClient
from shield_sdk.schema import (
    Decision,
    GovernanceVerdict,
    Guardian,
    Obligations,
    ShieldActionRecord,
    VerdictReason,
)
from shield_server import agents as agent_svc
from shield_server.app import create_app
from shield_server.config import Settings
from shield_server.governance import decide as gov_decide
from shield_server.models import RegisterAgentRequest
from shield_server.storage import build_memory_storage

PRIV = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
PUB = crypto.get_public_key_base64url(PRIV)


class _FakeBlockWithPreventedLoss:
    """A gov stand-in that returns an UNSIGNED BLOCK verdict with the
    Obligations.prevented_loss field carrying a measured env-diff amount
    (e.g. the InjectionTask6 $30k oracle). The server is responsible for
    forcing identity + signing + persisting; this fake mirrors what the
    real gov-W3 4-guardian aggregate will produce."""

    def __init__(self, amount: float = 30000.0) -> None:
        self._amount = amount

    async def decide(self, rec: ShieldActionRecord) -> GovernanceVerdict:
        return GovernanceVerdict(
            record_id=rec.record_id,
            correlation_id=rec.correlation_id,
            run_id=rec.run_id,
            decision=Decision.BLOCK,
            risk_score=0.93,
            reasons=[
                VerdictReason(
                    agent=Guardian.DEFENDER,
                    label="RECIPIENT_NOT_ALLOWLISTED",
                    score=0.9,
                ),
            ],
            obligations=Obligations(prevented_loss=self._amount, require_human=False),
        )


async def _register_agent(storage, *, agent_id: str = "agentdojo-banking-v1") -> None:
    await agent_svc.register_agent(
        storage,
        RegisterAgentRequest(
            agent_id=agent_id,
            keys=[{"kid": "k", "public_key": PUB}],  # type: ignore[list-item]
        ),
        "demo-org",
    )


def _signed_record(*, agent_id: str = "agentdojo-banking-v1") -> ShieldActionRecord:
    rec = ShieldActionRecord(
        org_id="demo-org",
        agent_id=agent_id,
        agent_pubkey_kid="k",
        phase="pre_exec",
        run_id="run-0001",
    )
    rec.payload.tool_name = "send_money"
    return canonical.finalize_record(rec, PRIV)


# ====================================================================== #
# (1) End-to-end persistence: prevented_loss flows from verdict to PG row.
# ====================================================================== #


def test_prevented_loss_persisted_to_governance_verdicts_row() -> None:
    """End-to-end: gov returns obligations.prevented_loss = $30k →
    governance_verdicts.prevented_loss = 30000.0 (NOT 0)."""

    async def run() -> None:
        storage = build_memory_storage()
        await _register_agent(storage)
        settings = Settings.from_env()
        rec = _signed_record()
        verdict = await gov_decide(
            storage, rec, settings, _FakeBlockWithPreventedLoss(amount=30000.0)
        )
        # gov's obligations carried through into the signed verdict.
        assert verdict.obligations is not None
        assert verdict.obligations.prevented_loss == 30000.0
        # And the governance_verdicts row carries the measured amount.
        rows = list(storage.db.governance_verdicts.values())
        assert len(rows) == 1
        assert rows[0]["prevented_loss"] == 30000.0
        assert rows[0]["org_id"] == "demo-org"
        assert rows[0]["decision"] == "BLOCK"

    asyncio.run(run())


def test_prevented_loss_zero_when_obligations_unset() -> None:
    """If gov returns a verdict without an obligations.prevented_loss value,
    the row carries 0.0 (NOT NULL) — the `or 0.0` fallback in governance.py
    keeps the column NOT NULL clean for downstream aggregation."""

    class _GovWithoutPreventedLoss:
        async def decide(self, rec: ShieldActionRecord) -> GovernanceVerdict:
            return GovernanceVerdict(
                record_id=rec.record_id,
                correlation_id=rec.correlation_id,
                run_id=rec.run_id,
                decision=Decision.PASS,
                risk_score=0.0,
                reasons=[
                    VerdictReason(agent=Guardian.DEFENDER, label="STUB_PASS", score=0.0),
                ],
            )

    async def run() -> None:
        storage = build_memory_storage()
        await _register_agent(storage)
        settings = Settings.from_env()
        rec = _signed_record()
        await gov_decide(storage, rec, settings, _GovWithoutPreventedLoss())
        rows = list(storage.db.governance_verdicts.values())
        assert len(rows) == 1
        assert rows[0]["prevented_loss"] == 0.0

    asyncio.run(run())


# ====================================================================== #
# (2) Dashboard KPI endpoint: org-wide rollup.
# ====================================================================== #


def _client() -> TestClient:
    storage = build_memory_storage()
    app = create_app(storage=storage)
    c = TestClient(app)
    c.app_storage = storage  # type: ignore[attr-defined]
    return c


def test_dashboard_kpi_returns_org_wide_total() -> None:
    """Dashboard KPI sums prevented_loss across ALL verdicts in the org."""
    client = _client()
    storage = client.app_storage  # type: ignore[attr-defined]

    async def seed() -> None:
        settings = Settings.from_env()
        # Use 3 distinct agents so each /decide starts a fresh per-agent
        # chain (no chain-hash threading needed). Each agent registered
        # separately under the same org.
        for amount, agent_id in (
            (30000.0, "agent-a"),
            (15000.0, "agent-b"),
            (5000.0, "agent-c"),
        ):
            await _register_agent(storage, agent_id=agent_id)
            rec = ShieldActionRecord(
                org_id="demo-org",
                agent_id=agent_id,
                agent_pubkey_kid="k",
                phase="pre_exec",
                run_id=f"run-{int(amount)}",
            )
            rec.payload.tool_name = "send_money"
            rec = canonical.finalize_record(rec, PRIV)
            await gov_decide(storage, rec, settings, _FakeBlockWithPreventedLoss(amount=amount))

    asyncio.run(seed())
    with client:
        r = client.get("/v1/governance/dashboard/kpi")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["prevented_loss_total"] == 50000.0
    assert body["total_verdicts"] == 3
    # All 6 §4 Decision keys present; BLOCK = 3, others 0.
    assert set(body["decision_mix"].keys()) == {d.value for d in Decision}
    assert body["decision_mix"]["BLOCK"] == 3
    assert body["decision_mix"]["PASS"] == 0


def test_dashboard_kpi_zero_when_no_verdicts() -> None:
    """Empty storage → 0.0 total + all-zero decision_mix + 0 count."""
    client = _client()
    with client:
        r = client.get("/v1/governance/dashboard/kpi")
    assert r.status_code == 200
    body = r.json()
    assert body["prevented_loss_total"] == 0.0
    assert body["total_verdicts"] == 0
    assert all(v == 0 for v in body["decision_mix"].values())


def test_dashboard_kpi_excludes_other_orgs() -> None:
    """org_A's dashboard MUST NOT include org_B's verdicts (org-scoped)."""
    client = _client()
    storage = client.app_storage  # type: ignore[attr-defined]
    # Seed two verdicts for org B directly (bypassing the full decide flow
    # since the dashboard is a pure READ over governance_verdicts).
    storage.db.governance_verdicts["v-org-b-1"] = {
        "verdict_id": "v-org-b-1",
        "record_id": "r-1",
        "correlation_id": "c-1",
        "run_id": "run-x",
        "org_id": "other-org",
        "agent_id": "ag-1",
        "decision": "BLOCK",
        "risk_score": 0.9,
        "latency_ms": 12.0,
        "prevented_loss": 99000.0,  # should NOT appear in demo-org dashboard
        "r2_verdict_key": "k",
        "created_at": 1,
    }
    # Seed one verdict for demo-org (the principal's org under open mode).
    storage.db.governance_verdicts["v-demo-1"] = {
        "verdict_id": "v-demo-1",
        "record_id": "r-2",
        "correlation_id": "c-2",
        "run_id": "run-y",
        "org_id": "demo-org",
        "agent_id": "ag-2",
        "decision": "BLOCK",
        "risk_score": 0.9,
        "latency_ms": 12.0,
        "prevented_loss": 1000.0,
        "r2_verdict_key": "k",
        "created_at": 2,
    }
    with client:
        r = client.get("/v1/governance/dashboard/kpi")
    assert r.status_code == 200
    body = r.json()
    # Only the demo-org row contributes; other-org's $99k is excluded.
    assert body["prevented_loss_total"] == 1000.0
    assert body["total_verdicts"] == 1
