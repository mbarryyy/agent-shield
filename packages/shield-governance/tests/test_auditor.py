"""Auditor — chain/Merkle verify (via shield_sdk.canonical), provenance DAG,
compliance report. Never blocks."""

from __future__ import annotations

import pytest
from shield_governance.auditor import Auditor, MerkleVerification, ProvenanceGraph
from shield_sdk.schema import (
    ActionPayload,
    Decision,
    GovernanceVerdict,
    Obligations,
    Phase,
    ShieldActionRecord,
)


def _rec(
    phase: Phase = Phase.PRE_EXEC,
    *,
    corr: str = "c1",
    err: str | None = None,
    conf: float | None = None,
) -> ShieldActionRecord:
    return ShieldActionRecord(
        run_id="run-1",
        correlation_id=corr,
        phase=phase,
        payload=ActionPayload(
            tool_name="send_money", tool_args={"recipient": "A"}, tool_error=err, confidence=conf
        ),
    )


def test_unsigned_records_flag_chain_broken() -> None:
    a = Auditor()
    res = a.audit([_rec(), _rec()], agent_pubkey_b64url="irrelevant-no-sig")
    assert res.integrity == 0.0
    assert res.chain_broken is True
    assert any(r.label == "auditor.chain_broken" for r in res.reasons)


def test_empty_is_clean() -> None:
    res = Auditor().audit([], agent_pubkey_b64url="x")
    assert res.integrity == 1.0 and res.chain_broken is False and res.reasons == []


def test_self_report_mismatch() -> None:
    a = Auditor()
    res = a.audit([_rec(conf=0.95, err="boom")], agent_pubkey_b64url="x")
    assert res.self_report_mismatch is True
    assert any(r.label == "auditor.self_report_mismatch" for r in res.reasons)


def test_provenance_dag_pairs_pre_post_by_correlation() -> None:
    g = ProvenanceGraph()
    g.add_record(_rec(Phase.PRE_EXEC, corr="cc"))
    g.add_record(_rec(Phase.POST_EXEC, corr="cc"))
    assert g.order == 2
    nl = g.to_node_link()
    assert "nodes" in nl and len(nl["nodes"]) == 2
    assert len(nl["edges"]) >= 1  # pre<->post correlation edge


def test_merkle_verification_seam_adds_auditor_reason() -> None:
    def merkle(records: list[ShieldActionRecord]) -> MerkleVerification:
        return MerkleVerification(
            verified=False,
            root="root-1",
            epoch_id="epoch-1",
            detail="record absent from epoch",
        )

    res = Auditor(merkle_verifier=merkle).audit([_rec()], agent_pubkey_b64url="x")
    reason = next(rr for rr in res.reasons if rr.label == "auditor.merkle_failed")
    assert reason.detail == "record absent from epoch"


@pytest.mark.asyncio
async def test_compliance_report_json_and_narrative() -> None:
    a = Auditor()
    a.audit([_rec()], agent_pubkey_b64url="x")  # populate DAG
    verdicts = [
        GovernanceVerdict(
            decision=Decision.BLOCK,
            correlation_id="c1",
            obligations=Obligations(prevented_loss=30000.0),
        ),
        GovernanceVerdict(decision=Decision.PASS, correlation_id="c2"),
    ]
    rep = await a.generate_compliance_report(verdicts)
    assert rep["blocked"] == 1
    assert rep["dollars_prevented"] == 30000.0
    assert rep["decision_mix"] == {"BLOCK": 1, "PASS": 1}
    assert rep["report_version"] == "w4-json"
    assert "narrative" not in rep  # no narrator injected

    async def narrator(prompt: str) -> str:
        return "All structuring attempts blocked; chain intact."

    a2 = Auditor(narrator=narrator)
    rep2 = await a2.generate_compliance_report(verdicts)
    assert "narrative" in rep2 and rep2["narrative"].startswith("All structuring")


@pytest.mark.asyncio
async def test_compliance_report_includes_merkle_and_zero_egress_attestation() -> None:
    def signer(report: dict[str, object]) -> dict[str, object]:
        return {"profile": "local", "egress": 0, "signature": "signed-report"}

    a = Auditor(zero_egress_attestor=signer)
    a.record_merkle_verification(
        MerkleVerification(verified=True, root="root-ok", epoch_id="epoch-ok")
    )
    rep = await a.generate_compliance_report(
        [GovernanceVerdict(decision=Decision.PASS, correlation_id="c-ok")]
    )
    assert rep["merkle"] == {"verified": True, "root": "root-ok", "epoch_id": "epoch-ok"}
    assert rep["zero_egress_attestation"] == {
        "profile": "local",
        "egress": 0,
        "signature": "signed-report",
    }
