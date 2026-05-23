"""W3 PR-S2 — console governance READ contract (timeline / verdict /
provenance / SSE) over MemoryStorage with the honest Null decide-seam.

Doubles as the console-pact test: asserts the response shapes the console
renders (TimelineResponse / VerdictView / ProvenanceGraph) — additive
/v1/governance/*, NOT a frozen-§4 contracts/*.schema.json change.
"""

from __future__ import annotations

import pytest
import shield_sdk.canonical as canonical
import shield_sdk.crypto as crypto
from fastapi.testclient import TestClient
from shield_sdk.schema import ActionRef, Phase, ShieldActionRecord
from shield_server import agents as agent_svc
from shield_server import reads as reads_svc
from shield_server.config import Settings
from shield_server.errors import AppError
from shield_server.governance import decide, record, resume
from shield_server.govseam import NullGovernanceApp
from shield_server.models import RegisterAgentRequest
from shield_server.storage import Storage

ORG = "demo-org"
PRIV = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
PUB = crypto.get_public_key_base64url(PRIV)
KID = "agentdojo-banking-v1-key-v1"
AGENT = "agentdojo-banking-v1"
_GOV = NullGovernanceApp()


async def _register(storage: Storage) -> None:
    await agent_svc.register_agent(
        storage,
        RegisterAgentRequest(agent_id=AGENT, keys=[{"kid": KID, "public_key": PUB}]),  # type: ignore[list-item]
        ORG,
    )


def _rec(*, phase: Phase, prev: str, nonce: str, **over: object) -> ShieldActionRecord:
    rec = ShieldActionRecord(
        org_id=ORG,
        agent_id=AGENT,
        agent_pubkey_kid=KID,
        phase=phase,
        run_id="run-0001",
        prev_chain_hash=prev,
        nonce=nonce,
        action=ActionRef(tool="send_money", args_digest="sha256:abc"),
        **over,  # type: ignore[arg-type]
    )
    rec.payload.tool_name = "send_money"
    return canonical.finalize_record(rec, PRIV)


async def _seed_pre_post(storage: Storage, settings: Settings) -> tuple[str, str]:
    """One pre_exec gate + its paired post_exec on the same chain."""
    await _register(storage)
    pre = _rec(phase=Phase.PRE_EXEC, prev="A" * 43, nonce="nPRE000000000000000000")
    v = await decide(storage, pre, settings, _GOV)
    op = await storage.db.fetchrow(
        "SELECT * FROM operations WHERE operation_id = $1 AND org_id = $2",
        pre.record_id,
        ORG,
    )
    post = ShieldActionRecord(
        org_id=ORG,
        agent_id=AGENT,
        agent_pubkey_kid=KID,
        phase=Phase.POST_EXEC,
        run_id="run-0001",
        correlation_id=pre.correlation_id,  # pair to the gate
        verdict_ref=v.verdict_id,
        prev_chain_hash=str(op["chain_hash"]),
        nonce="nPOST00000000000000000",
    )
    post.payload.tool_name = "send_money"
    post = canonical.finalize_record(post, PRIV)
    await record(storage, post, settings)
    return pre.correlation_id, v.verdict_id


async def test_timeline_paginates_newest_first(storage: Storage, settings: Settings) -> None:
    await _register(storage)
    prev = "A" * 43
    for i in range(3):
        r = _rec(phase=Phase.PRE_EXEC, prev=prev, nonce=f"n{i}aaaaaaaaaaaaaaaaaaaa")
        v = await decide(storage, r, settings, _GOV)
        op = await storage.db.fetchrow(
            "SELECT * FROM operations WHERE operation_id = $1 AND org_id = $2",
            v.record_id,
            ORG,
        )
        prev = str(op["chain_hash"])

    page1 = await reads_svc.timeline(storage, ORG, "run-0001", None, 2)
    assert page1.total_count == 3
    assert len(page1.rows) == 2
    assert page1.cursor is not None
    assert all(row.decision == "PASS" for row in page1.rows)

    page2 = await reads_svc.timeline(storage, ORG, "run-0001", page1.cursor, 2)
    assert len(page2.rows) == 1 and page2.cursor is None
    seen = {r.verdict_id for r in [*page1.rows, *page2.rows]}
    assert len(seen) == 3  # no overlap, full coverage


async def test_timeline_org_scoped_and_bad_cursor(storage: Storage, settings: Settings) -> None:
    await _seed_pre_post(storage, settings)
    assert (await reads_svc.timeline(storage, "other-org", "run-0001")).rows == []
    with pytest.raises(AppError) as ei:
        await reads_svc.timeline(storage, ORG, "run-0001", "@@bad@@")
    assert ei.value.error_code == "VALIDATION_ERROR"


async def test_verdict_by_correlation_pairs_pre_post(storage: Storage, settings: Settings) -> None:
    corr, _vid = await _seed_pre_post(storage, settings)
    view = await reads_svc.verdict_by_correlation(storage, ORG, corr)
    assert view.correlation_id == corr
    assert view.verdict is not None
    assert view.verdict["decision"] == "PASS"
    assert view.verdict["signature_by_shield"]  # server-signed
    assert view.pre_exec is not None and view.pre_exec["phase"] == "pre_exec"
    assert view.post_exec is not None and view.post_exec["phase"] == "post_exec"

    with pytest.raises(AppError) as ei:
        await reads_svc.verdict_by_correlation(storage, ORG, "no-such-corr")
    assert ei.value.error_code == "NOT_FOUND"


async def test_provenance_dag_chain_and_correlation_edges(
    storage: Storage, settings: Settings
) -> None:
    corr, _vid = await _seed_pre_post(storage, settings)
    g = await reads_svc.provenance(storage, ORG, "run-0001")
    assert g.run_id == "run-0001"
    phases = sorted(n.phase or "" for n in g.nodes)
    assert phases == ["post_exec", "pre_exec"]
    pre = next(n for n in g.nodes if n.phase == "pre_exec")
    assert pre.decision == "PASS" and pre.correlation_id == corr
    kinds = sorted(e.kind for e in g.edges)
    assert "chain" in kinds and "correlation" in kinds
    corr_edge = next(e for e in g.edges if e.kind == "correlation")
    assert corr_edge.src == pre.record_id


def test_console_pact_http_shapes(client: TestClient) -> None:
    """The locked console-pact: endpoints exist + return the DTO key sets."""
    import shield_sdk.canonical as c
    import shield_sdk.crypto as k
    from shield_sdk.schema import ShieldActionRecord as SAR

    priv = PRIV
    pub = k.get_public_key_base64url(priv)
    client.post(
        "/v1/agents/register",
        json={"agent_id": AGENT, "keys": [{"kid": KID, "public_key": pub}]},
    )
    rec = SAR(
        org_id=ORG,
        agent_id=AGENT,
        agent_pubkey_kid=KID,
        phase="pre_exec",
        run_id="run-pact",
    )
    rec.payload.tool_name = "send_money"
    rec = c.finalize_record(rec, priv)
    dec = client.post("/v1/governance/decide", json=rec.model_dump(mode="json"))
    assert dec.status_code == 200, dec.text
    corr = dec.json()["correlation_id"]

    tl = client.get("/v1/governance/runs/run-pact/timeline")
    assert tl.status_code == 200
    assert set(tl.json()) == {"rows", "cursor", "total_count"}
    assert tl.json()["total_count"] == 1
    assert set(tl.json()["rows"][0]) == {
        "verdict_id",
        "record_id",
        "correlation_id",
        "run_id",
        "decision",
        "risk_score",
        "latency_ms",
        "created_at",
    }

    vv = client.get(f"/v1/governance/verdicts/{corr}")
    assert vv.status_code == 200
    assert set(vv.json()) == {
        "correlation_id",
        "verdict",
        "pre_exec",
        "post_exec",
        "guardian_evidence",
    }
    assert vv.json()["verdict"]["decision"] == "PASS"
    assert vv.json()["guardian_evidence"] == []

    pr = client.get("/v1/governance/runs/run-pact/provenance")
    assert pr.status_code == 200
    assert set(pr.json()) == {"run_id", "nodes", "edges"}

    sse = client.get("/v1/governance/stream?workflow_id=banking")
    assert sse.status_code == 200
    assert sse.headers["content-type"].startswith("text/event-stream")
    assert "event: action" in sse.text  # the decide() XADD'd a shield:actions entry


def test_verdict_not_found_http(client: TestClient) -> None:
    r = client.get("/v1/governance/verdicts/missing")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


class _FakeGovPrevented:
    """gov stand-in: UNSIGNED BLOCK carrying the MEASURED env-diff
    prevented_loss (the money-shot $30k); server stores, /cost reads it."""

    async def decide(self, rec):  # type: ignore[no-untyped-def]
        from shield_sdk.schema import (
            Decision,
            GovernanceVerdict,
            Obligations,
        )

        return GovernanceVerdict(
            record_id=rec.record_id,
            correlation_id=rec.correlation_id,
            run_id=rec.run_id,
            decision=Decision.BLOCK,
            risk_score=0.93,
            obligations=Obligations(prevented_loss=30000.0),
        )


async def test_cost_rollup_locked_shape(storage: Storage, settings: Settings) -> None:
    await _register(storage)
    prev = "A" * 43
    for i in range(2):
        r = _rec(phase=Phase.PRE_EXEC, prev=prev, nonce=f"c{i}aaaaaaaaaaaaaaaaaaaa")
        v = await decide(storage, r, settings, _FakeGovPrevented())  # type: ignore[arg-type]
        op = await storage.db.fetchrow(
            "SELECT * FROM operations WHERE operation_id = $1 AND org_id = $2",
            v.record_id,
            ORG,
        )
        prev = str(op["chain_hash"])

    c = await reads_svc.cost(storage, ORG, "run-0001")
    # Exact LOCKED seam-4 shape.
    assert c.tokens.prompt == 0 and c.tokens.completion == 0 and c.tokens.total == 0
    assert set(c.decision_mix) == {"PASS", "ALERT", "BLOCK", "ESCALATE", "ROLLBACK", "REWRITE"}
    assert c.decision_mix["BLOCK"] == 2 and c.decision_mix["PASS"] == 0
    # Σ of the STORED §4 obligations.prevented_loss (MEASURED; no recompute).
    assert c.prevented_loss_total == 60000.0
    assert isinstance(c.latency_p50_ms, float)
    assert isinstance(c.latency_p95_ms, float)
    # org-scoped
    empty = await reads_svc.cost(storage, "other-org", "run-0001")
    assert empty.decision_mix["BLOCK"] == 0 and empty.prevented_loss_total == 0.0


def test_cost_http_locked_pact(client: TestClient) -> None:
    import shield_sdk.canonical as c
    import shield_sdk.crypto as k
    from shield_sdk.schema import ShieldActionRecord as SAR

    pub = k.get_public_key_base64url(PRIV)
    client.post(
        "/v1/agents/register",
        json={"agent_id": AGENT, "keys": [{"kid": KID, "public_key": pub}]},
    )
    rec = SAR(
        org_id=ORG,
        agent_id=AGENT,
        agent_pubkey_kid=KID,
        phase="pre_exec",
        run_id="run-cost",
    )
    rec.payload.tool_name = "send_money"
    rec = c.finalize_record(rec, PRIV)
    assert client.post("/v1/governance/decide", json=rec.model_dump(mode="json")).status_code == 200

    r = client.get("/v1/governance/runs/run-cost/cost")
    assert r.status_code == 200
    body = r.json()
    # Byte-for-byte LOCKED seam-4 key contract (eval mirrors this exact shape).
    assert set(body) == {
        "tokens",
        "decision_mix",
        "prevented_loss_total",
        "latency_p50_ms",
        "latency_p95_ms",
    }
    assert set(body["tokens"]) == {"prompt", "completion", "total"}
    assert set(body["decision_mix"]) == {
        "PASS",
        "ALERT",
        "BLOCK",
        "ESCALATE",
        "ROLLBACK",
        "REWRITE",
    }
    assert body["decision_mix"]["PASS"] == 1
    assert isinstance(body["prevented_loss_total"], (int, float))
    assert isinstance(body["latency_p50_ms"], (int, float))
    assert isinstance(body["latency_p95_ms"], (int, float))


class _FakeEscalateGov:
    """gov stand-in returning an UNSIGNED ESCALATE (a HITL incident)."""

    async def decide(self, rec):  # type: ignore[no-untyped-def]
        from shield_sdk.schema import Decision, GovernanceVerdict

        return GovernanceVerdict(
            record_id=rec.record_id,
            correlation_id=rec.correlation_id,
            run_id=rec.run_id,
            decision=Decision.ESCALATE,
            risk_score=0.42,
        )


async def _chain_decide(storage: Storage, settings: Settings, gov, prev: str, nonce: str):  # type: ignore[no-untyped-def]
    """decide() on the agent chain; returns (verdict, new prev chain_hash)."""
    r = _rec(phase=Phase.PRE_EXEC, prev=prev, nonce=nonce)
    v = await decide(storage, r, settings, gov)
    op = await storage.db.fetchrow(
        "SELECT * FROM operations WHERE operation_id = $1 AND org_id = $2",
        v.record_id,
        ORG,
    )
    return v, str(op["chain_hash"])


async def test_incidents_list_pending_then_resolved(storage: Storage, settings: Settings) -> None:
    await _register(storage)
    r = _rec(phase=Phase.PRE_EXEC, prev="A" * 43, nonce="iESC00000000000000000")
    v = await decide(storage, r, settings, _FakeEscalateGov())  # type: ignore[arg-type]
    inc_id = v.verdict_id  # incident_id == ESCALATE gate verdict_id

    lst = await reads_svc.incidents(storage, ORG, "run-0001")
    assert lst.total_count == 1
    row = lst.incidents[0]
    assert row.incident_id == inc_id
    assert row.decision == "ESCALATE" and row.status == "pending"
    assert row.resolution is None
    assert row.correlation_id == r.correlation_id

    # Operator resumes on the SAME id → status flips resolved (server-auth).
    await resume(storage, settings, NullGovernanceApp(), inc_id, "accept", None)
    after = await reads_svc.incidents(storage, ORG, "run-0001")
    assert after.incidents[0].status == "resolved"
    assert after.incidents[0].resolution == "accept"

    # status filter
    assert (await reads_svc.incidents(storage, ORG, "run-0001", "pending")).total_count == 0
    assert (await reads_svc.incidents(storage, ORG, "run-0001", "resolved")).total_count == 1


async def test_incidents_excludes_non_escalate_and_scopes(
    storage: Storage, settings: Settings
) -> None:
    await _register(storage)
    # A PASS gate is NOT an incident.
    _v, prev = await _chain_decide(
        storage, settings, NullGovernanceApp(), "A" * 43, "iPASS0000000000000000"
    )
    assert (await reads_svc.incidents(storage, ORG, "run-0001")).total_count == 0
    # An ESCALATE on the same chain IS an incident — but org-scoped out for others.
    await _chain_decide(
        storage,
        settings,
        _FakeEscalateGov(),  # type: ignore[arg-type]
        prev,
        "iESC20000000000000000",
    )
    assert (await reads_svc.incidents(storage, ORG, "run-0001")).total_count == 1
    assert (await reads_svc.incidents(storage, "other-org", "run-0001")).total_count == 0
    with pytest.raises(AppError) as ei:
        await reads_svc.incidents(storage, ORG, "run-0001", "bogus")
    assert ei.value.error_code == "VALIDATION_ERROR"


def test_incidents_http_locked_pact(client: TestClient) -> None:
    r = client.get("/v1/governance/incidents?run_id=none&status=pending")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"incidents", "cursor", "total_count"}
    assert body["total_count"] == 0
    # row shape contract (asserted on a seeded incident via the route below)
    bad = client.get("/v1/governance/incidents?status=nope")
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "VALIDATION_ERROR"
