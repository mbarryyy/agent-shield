from __future__ import annotations

import base64

import shield_sdk.canonical as canonical
import shield_sdk.crypto as crypto
from fastapi.testclient import TestClient
from shield_sdk.schema import (
    ActionRef,
    Decision,
    GovernanceVerdict,
    Guardian,
    Obligations,
    Phase,
    ShieldActionRecord,
    VerdictReason,
)
from shield_server import agents as agent_svc
from shield_server import reads as reads_svc
from shield_server.config import Settings
from shield_server.governance import decide
from shield_server.models import CreateExportRequest, RegisterAgentRequest
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


def _signed_record(*, run_id: str = "run-export-pdf") -> ShieldActionRecord:
    rec = ShieldActionRecord(
        org_id=ORG,
        agent_id=AGENT,
        agent_pubkey_kid=KID,
        phase=Phase.PRE_EXEC,
        run_id=run_id,
        action=ActionRef(tool="send_money", args_digest="sha256:redacted-args"),
    )
    rec.payload.tool_name = "send_money"
    rec.payload.tool_args = {"recipient": "ATTACKER-IBAN", "amount": 10000.0}
    return canonical.finalize_record(rec, PRIV)


class _FakeBlockGov:
    async def decide(self, rec: ShieldActionRecord) -> GovernanceVerdict:
        return GovernanceVerdict(
            record_id=rec.record_id,
            correlation_id=rec.correlation_id,
            run_id=rec.run_id,
            decision=Decision.BLOCK,
            risk_score=0.91,
            reasons=[
                VerdictReason(
                    agent=Guardian.DEFENDER,
                    label="defender.block_high_value",
                    detail="High-risk transfer blocked by deterministic policy.",
                    score=0.91,
                )
            ],
            obligations=Obligations(prevented_loss=10000.0),
        )


def _inspect_pdf_text(raw: bytes) -> str:
    text = raw.decode("latin-1", errors="ignore")
    return text.replace("\\(", "(").replace("\\)", ")")


def test_json_compliance_export_download_contract_regression(client: TestClient) -> None:
    client.post(
        "/v1/agents/register",
        json={"agent_id": AGENT, "keys": [{"kid": KID, "public_key": PUB}]},
    )
    rec = _signed_record(run_id="run-export-json")
    assert client.post("/v1/governance/decide", json=rec.model_dump(mode="json")).status_code == 200

    created = client.post(
        "/v1/exports",
        json={"start_time": 0, "end_time": 9_999_999_999_999, "format": "json"},
    )
    assert created.status_code == 201
    export = created.json()["export"]
    assert export["status"] == "done"
    assert export["r2_export_key"].endswith(".json")

    download = client.get(f"/v1/exports/{export['export_id']}/download")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/json")
    payload = download.json()
    assert set(payload) == {
        "export_id",
        "org_id",
        "query",
        "generated_at",
        "operations",
        "governance_verdicts",
        "epochs",
    }
    assert payload["query"]["format"] == "json"
    assert len(payload["operations"]) == 1
    assert len(payload["governance_verdicts"]) == 1


async def test_pdf_compliance_export_generates_valid_human_readable_artifact(
    storage: Storage, settings: Settings
) -> None:
    await _register(storage)
    rec = _signed_record()
    await decide(storage, rec, settings, _FakeBlockGov())  # type: ignore[arg-type]

    result = await reads_svc.create_export(
        storage,
        ORG,
        CreateExportRequest(start_time=0, end_time=9_999_999_999_999, format="pdf"),
    )

    assert result.export.status == "done"
    assert result.export.r2_export_key is not None
    assert result.export.r2_export_key.endswith(".pdf")
    raw = await storage.objects.get(result.export.r2_export_key)
    assert raw is not None
    assert raw.startswith(b"%PDF-")

    text = _inspect_pdf_text(raw)
    assert "Agent Shield Compliance Export" in text
    assert "Compliance summary" in text
    assert "Generated at" in text
    assert f"Organization: {ORG}" in text
    assert f"Agent: {AGENT}" in text
    assert "Run: run-export-pdf" in text
    assert rec.record_id in text
    assert rec.correlation_id in text
    assert "Decision: BLOCK" in text
    assert "Risk score: 0.91" in text
    assert "Evidence: defender.block_high_value" in text
    assert "Cost: prompt_tokens=0 completion_tokens=0 total_tokens=0" in text
    assert "Latency" in text
    assert "Limitations and verification labels" in text
    assert "GENERATED_FROM_SERVER_READ_MODEL" in text
    assert "NOT_A_BENCHMARK" in text
    assert "ZERO_EGRESS_NOT_VERIFIED" in text
    assert "PRODUCTION_READINESS_NOT_ASSERTED" in text
    assert "Raw tool arguments are excluded" in text
    assert "ATTACKER-IBAN" not in text

    download = await reads_svc.download_export(storage, ORG, result.export.export_id)
    assert download["content_type"] == "application/pdf"
    assert base64.b64decode(download["body_base64"]).startswith(b"%PDF-")
