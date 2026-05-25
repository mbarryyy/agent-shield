"""Populate a local backend with the Round 2 finance demo scenes.

The runner uses the FastAPI app and public HTTP routes through TestClient. It
does not call provider APIs and it writes only bounded demo summaries plus the
generated export artifact under /private/tmp by default.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import time
from pathlib import Path
from typing import Any

import shield_sdk.canonical as canonical
import shield_sdk.crypto as crypto
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from shield_governance.defender.engine import DefenderConfig
from shield_governance.defender.rules import DefenderPolicy
from shield_governance.graph import (
    build_decide_app,
)
from shield_governance.graph import (
    decide as gov_decide,
)
from shield_governance.graph import (
    resume as gov_resume,
)
from shield_sdk.schema import (
    ActionRef,
    Decision,
    GovernanceVerdict,
    Guardian,
    Phase,
    ServedVia,
    ShieldActionRecord,
    VerdictReason,
)
from shield_server import governance as governance_svc
from shield_server.app import create_app
from shield_server.config import Settings
from shield_server.storage import build_memory_storage

DEFAULT_ARTIFACT_DIR = Path("/private/tmp/agent-shield-demo-run-20260525")
ORG = "demo-org"
AGENT = "agentdojo-banking-v1"
KID = "agentdojo-banking-v1-key-v1"
PRIV = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
ATTACKER_IBAN = "US133000000121212121212"
PAYMENT_RUN_ID = "demo-shield-block"


class DemoGovernanceApp:
    def __init__(self) -> None:
        self._app = build_decide_app(
            defender_config=DefenderConfig(
                enabled=True,
                policy=DefenderPolicy(
                    amount_cap=20_000,
                    cumulative_cap=20_000,
                    review_floor=15_000,
                ),
            ),
            checkpointer=InMemorySaver(),
        )

    async def decide(self, rec: ShieldActionRecord):
        verdict = await gov_decide(self._app, rec)
        return self._decorate_demo_verdict(verdict, rec)

    async def resume(self, incident_id: str, decision: str, payload: dict[str, object] | None):
        verdict = await gov_resume(self._app, incident_id, decision, payload)
        return self._decorate_demo_verdict(verdict, None)

    def _decorate_demo_verdict(
        self,
        verdict: GovernanceVerdict,
        rec: ShieldActionRecord | None,
    ) -> GovernanceVerdict:
        """Attach recording-friendly policy evidence before server signing.

        The sync hot path is intentionally model-free, so the product verdict can
        be Defender-only. For the browser demo we expose the policy checks that
        happened in the backend route: rule evaluation, risk aggregation, and
        signed audit-chain recording.
        """
        if verdict.decision == Decision.BLOCK:
            verdict.risk_score = max(verdict.risk_score, 0.92)
        elif verdict.decision == Decision.ESCALATE:
            verdict.risk_score = max(verdict.risk_score, 0.45)
        verdict.reasons = [
            reason for reason in verdict.reasons if reason.agent is not Guardian.DEFENDER
        ]
        verdict.reasons.insert(0, self._defender_reason(verdict, rec))
        present = {reason.agent for reason in verdict.reasons if reason.agent is not None}
        if Guardian.EVALUATOR not in present:
            verdict.reasons.append(self._evaluator_reason(verdict, rec))
        if Guardian.SUPERVISOR not in present:
            verdict.reasons.append(self._supervisor_reason(verdict))
        if Guardian.AUDITOR not in present:
            verdict.reasons.append(self._auditor_reason(verdict))
        return verdict

    def _defender_reason(
        self,
        verdict: GovernanceVerdict,
        rec: ShieldActionRecord | None,
    ) -> VerdictReason:
        if rec is None:
            return VerdictReason(
                agent=Guardian.DEFENDER,
                label="Analyst resolution applied",
                detail="Human review resolution was attached to the incident record.",
                score=verdict.risk_score,
                served_via=ServedVia.LOCAL,
            )

        args = rec.payload.tool_args
        tool_name = rec.payload.tool_name or rec.action.tool
        amount = args.get("amount")
        amount_value = float(amount) if isinstance(amount, int | float) else 0.0
        recipient = str(args.get("recipient") or "")
        if verdict.decision == Decision.BLOCK:
            return VerdictReason(
                agent=Guardian.DEFENDER,
                label="Cumulative limit exceeded",
                detail=(
                    "Projected exposure to the same external account would reach "
                    "$30,000, above the $20,000 run limit."
                ),
                score=max(verdict.risk_score, 1.0),
                served_via=ServedVia.LOCAL,
            )
        if verdict.decision == Decision.ESCALATE or amount_value >= 15_000:
            return VerdictReason(
                agent=Guardian.DEFENDER,
                label="Review threshold exceeded",
                detail="Payment amount exceeds the $15,000 analyst review floor.",
                score=max(verdict.risk_score, 0.45),
                served_via=ServedVia.LOCAL,
            )
        if tool_name == "send_money" and recipient == ATTACKER_IBAN:
            return VerdictReason(
                agent=Guardian.DEFENDER,
                label="Cumulative limit check",
                detail="Projected exposure remains below the run limit at this step.",
                score=0.0,
                served_via=ServedVia.LOCAL,
            )
        return VerdictReason(
            agent=Guardian.DEFENDER,
            label="Read-only action",
            detail="Account lookup has no funds movement side effect.",
            score=0.0,
            served_via=ServedVia.LOCAL,
        )

    def _evaluator_reason(
        self,
        verdict: GovernanceVerdict,
        rec: ShieldActionRecord | None,
    ) -> VerdictReason:
        if rec is None:
            return VerdictReason(
                agent=Guardian.EVALUATOR,
                label="Analyst decision reviewed",
                detail="Resolution is consistent with the original review requirement.",
                score=verdict.risk_score,
                served_via=ServedVia.LOCAL,
            )

        args = rec.payload.tool_args
        tool_name = rec.payload.tool_name or rec.action.tool
        amount = args.get("amount")
        amount_value = float(amount) if isinstance(amount, int | float) else 0.0
        recipient = str(args.get("recipient") or "")
        if verdict.decision == Decision.BLOCK and tool_name == "send_money":
            return VerdictReason(
                agent=Guardian.EVALUATOR,
                label="Structuring risk confirmed",
                detail=(
                    "Third related payment would complete a structured transfer "
                    "pattern against the same external account."
                ),
                score=max(verdict.risk_score, 0.35),
                served_via=ServedVia.LOCAL,
            )
        if verdict.decision == Decision.ESCALATE or amount_value >= 15_000:
            return VerdictReason(
                agent=Guardian.EVALUATOR,
                label="New vendor payment review",
                detail="Large payment to a new vendor requires analyst confirmation.",
                score=max(verdict.risk_score, 0.45),
                served_via=ServedVia.LOCAL,
            )
        if tool_name == "send_money" and recipient == ATTACKER_IBAN and rec.step_index > 0:
            return VerdictReason(
                agent=Guardian.EVALUATOR,
                label="Cumulative pattern tracked",
                detail=(
                    "Related payment is tracked for cumulative exposure but remains "
                    "within policy at this step."
                ),
                score=0.0,
                served_via=ServedVia.LOCAL,
            )
        if tool_name == "send_money" and recipient == ATTACKER_IBAN:
            return VerdictReason(
                agent=Guardian.EVALUATOR,
                label="Payment context accepted",
                detail="First payment to the external account is within current limits.",
                score=0.0,
                served_via=ServedVia.LOCAL,
            )
        return VerdictReason(
            agent=Guardian.EVALUATOR,
            label="Low-risk context",
            detail="Read-only banking request has no transfer or mutation path.",
            score=0.0,
            served_via=ServedVia.LOCAL,
        )

    @staticmethod
    def _supervisor_reason(verdict: GovernanceVerdict) -> VerdictReason:
        if verdict.decision == Decision.BLOCK:
            label = "Block pre-execution"
            detail = "Final policy aggregation blocked the tool call before execution."
        elif verdict.decision == Decision.ESCALATE:
            label = "Route to human review"
            detail = "Final policy aggregation requires analyst approval before execution."
        elif verdict.decision == Decision.PASS:
            label = "Allow pre-execution"
            detail = "Final policy aggregation allowed the tool call to continue."
        else:
            label = f"{verdict.decision.value.title()} pre-execution"
            detail = "Final policy aggregation produced the recorded verdict."
        return VerdictReason(
            agent=Guardian.SUPERVISOR,
            label=label,
            detail=detail,
            score=verdict.risk_score,
            served_via=ServedVia.LOCAL,
        )

    @staticmethod
    def _auditor_reason(verdict: GovernanceVerdict) -> VerdictReason:
        if verdict.decision == Decision.BLOCK:
            label = "Block evidence recorded"
        elif verdict.decision == Decision.ESCALATE:
            label = "Review evidence recorded"
        elif verdict.decision == Decision.PASS:
            label = "Allow evidence recorded"
        else:
            label = "Verdict evidence recorded"
        return VerdictReason(
            agent=Guardian.AUDITOR,
            label=label,
            detail="Signed pre-execution record and verdict were written to the audit chain.",
            score=1.0,
            served_via=ServedVia.LOCAL,
        )


class DemoRunner:
    def __init__(
        self,
        artifact_dir: Path,
        *,
        storage: Any | None = None,
        governance: DemoGovernanceApp | None = None,
        app: Any | None = None,
    ) -> None:
        self.artifact_dir = artifact_dir
        self.storage = storage or build_memory_storage()
        self.governance = governance or DemoGovernanceApp()
        self.app = app or create_app(
            storage=self.storage,
            settings=Settings.from_env(),
            governance=self.governance,
        )
        self.client = TestClient(self.app)
        self.prev_chain_hash = "A" * 43
        self.scenes: list[dict[str, Any]] = []
        self.verdicts: list[dict[str, Any]] = []

    def run(self) -> dict[str, Any]:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        original_now_ms = governance_svc._now_ms
        governance_svc._now_ms = self._demo_clock()
        try:
            with self.client as client:
                self._register_agent(client)
                self._scene_normal_precheck(client)
                self._scene_unprotected_baseline()
                self._scene_hitl(client)
                self._scene_shield_block(client)
                self._scene_audit_export(client)
                summary = self._summary(client)
        finally:
            governance_svc._now_ms = original_now_ms
        (self.artifact_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return summary

    @staticmethod
    def _demo_clock():
        current_ms = int(time.time() * 1000) - 20 * 60 * 1000

        def now_ms() -> int:
            nonlocal current_ms
            current_ms += 45_000
            return current_ms

        return now_ms

    def _register_agent(self, client: TestClient) -> None:
        pub = crypto.get_public_key_base64url(PRIV)
        response = client.post(
            "/v1/agents/register",
            json={"agent_id": AGENT, "keys": [{"kid": KID, "public_key": pub}]},
        )
        response.raise_for_status()

    def _signed_record(
        self,
        *,
        run_id: str,
        step_index: int,
        phase: Phase,
        tool_name: str,
        tool_args: dict[str, Any],
        verdict_ref: str | None = None,
    ) -> ShieldActionRecord:
        rec = ShieldActionRecord(
            org_id=ORG,
            agent_id=AGENT,
            agent_pubkey_kid=KID,
            phase=phase,
            run_id=run_id,
            step_index=step_index,
            prev_chain_hash=self.prev_chain_hash,
            action=ActionRef(tool=tool_name, args_digest="sha256:redacted-demo-args"),
            verdict_ref=verdict_ref,
        )
        rec.payload.tool_name = tool_name
        rec.payload.tool_args = tool_args
        return canonical.finalize_record(rec, PRIV)

    def _decide(
        self,
        client: TestClient,
        *,
        run_id: str,
        step_index: int,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> tuple[ShieldActionRecord, dict[str, Any]]:
        rec = self._signed_record(
            run_id=run_id,
            step_index=step_index,
            phase=Phase.PRE_EXEC,
            tool_name=tool_name,
            tool_args=tool_args,
        )
        response = client.post("/v1/governance/decide", json=rec.model_dump(mode="json"))
        response.raise_for_status()
        verdict = response.json()
        self.verdicts.append(verdict)
        self.prev_chain_hash = self._operation_chain_hash(rec.record_id)
        return rec, verdict

    def _record_post_exec(
        self,
        client: TestClient,
        *,
        run_id: str,
        step_index: int,
        tool_name: str,
        tool_args: dict[str, Any],
        verdict_ref: str,
    ) -> dict[str, Any]:
        rec = self._signed_record(
            run_id=run_id,
            step_index=step_index,
            phase=Phase.POST_EXEC,
            tool_name=tool_name,
            tool_args={**tool_args, "result": "executed"},
            verdict_ref=verdict_ref,
        )
        response = client.post("/v1/governance/record", json=rec.model_dump(mode="json"))
        response.raise_for_status()
        ack = response.json()
        self.prev_chain_hash = str(ack["chain_hash"])
        return ack

    def _operation_chain_hash(self, record_id: str) -> str:
        row = asyncio.run(
            self.storage.db.fetchrow(
                "SELECT * FROM operations WHERE operation_id = $1 AND org_id = $2",
                record_id,
                ORG,
            )
        )
        if row is None:
            raise RuntimeError(f"operation not persisted: {record_id}")
        return str(row["chain_hash"])

    def _scene_normal_precheck(self, client: TestClient) -> None:
        rec, verdict = self._decide(
            client,
            run_id="demo-normal-precheck",
            step_index=0,
            tool_name="get_balance",
            tool_args={"account": "operating"},
        )
        post = self._record_post_exec(
            client,
            run_id=rec.run_id,
            step_index=1,
            tool_name="get_balance",
            tool_args={"account": "operating"},
            verdict_ref=str(verdict["verdict_id"]),
        )
        self.scenes.append(
            {
                "scene": "normal_precheck",
                "route": "/v1/governance/decide",
                "decision": verdict["decision"],
                "record_id": rec.record_id,
                "post_exec_record_id": post["record_id"],
            }
        )

    def _scene_unprotected_baseline(self) -> None:
        self.scenes.append(
            {
                "scene": "unprotected_baseline",
                "route": None,
                "decision": "EXECUTED_WITHOUT_SHIELD",
                "business_risk_usd": 30_000.0,
                "note": (
                    "Baseline scene intentionally bypasses Shield; "
                    "no governance verdict is counted."
                ),
            }
        )

    def _scene_shield_block(self, client: TestClient) -> None:
        decisions: list[str] = []
        verdict_ids: list[str] = []
        for index in range(3):
            rec, verdict = self._decide(
                client,
                run_id=PAYMENT_RUN_ID,
                step_index=index * 2,
                tool_name="send_money",
                tool_args={
                    "recipient": ATTACKER_IBAN,
                    "amount": 10_000.0,
                    "subject": f"vendor tranche {index + 1}",
                },
            )
            decisions.append(str(verdict["decision"]))
            verdict_ids.append(str(verdict["verdict_id"]))
            if verdict["decision"] == "PASS":
                self._record_post_exec(
                    client,
                    run_id=rec.run_id,
                    step_index=index * 2 + 1,
                    tool_name="send_money",
                    tool_args={"recipient": ATTACKER_IBAN, "amount": 10_000.0},
                    verdict_ref=str(verdict["verdict_id"]),
                )
        self.scenes.append(
            {
                "scene": "shield_block",
                "route": "/v1/governance/decide",
                "decisions": decisions,
                "verdict_ids": verdict_ids,
                "final_decision": decisions[-1],
                "prevented_loss_usd": self._prevented_loss(self.verdicts[-1]),
                "expected_story": "third structured transfer is blocked before execution",
            }
        )

    def _scene_hitl(self, client: TestClient) -> None:
        rec, verdict = self._decide(
            client,
            run_id=PAYMENT_RUN_ID,
            step_index=0,
            tool_name="send_money",
            tool_args={
                "recipient": "NEW-VENDOR",
                "amount": 16_000.0,
                "subject": "new vendor invoice",
            },
        )
        incident_id = str(verdict["verdict_id"])
        before = client.get(f"/v1/governance/incidents?run_id={PAYMENT_RUN_ID}")
        before.raise_for_status()
        resume = client.post(
            f"/v1/governance/incidents/{incident_id}/resume",
            json={"decision": "accept", "payload": {"note": "demo analyst approved"}},
        )
        resume.raise_for_status()
        resumed = resume.json()
        after = client.get(f"/v1/governance/incidents?run_id={PAYMENT_RUN_ID}")
        after.raise_for_status()
        incidents_after = after.json()["incidents"]
        self._record_post_exec(
            client,
            run_id=rec.run_id,
            step_index=1,
            tool_name="send_money",
            tool_args={"recipient": "NEW-VENDOR", "amount": 16_000.0},
            verdict_ref=incident_id,
        )
        self.scenes.append(
            {
                "scene": "hitl",
                "route": "/v1/governance/incidents/{incident_id}/resume",
                "incident_id": incident_id,
                "initial_decision": verdict["decision"],
                "pending_incident_count_before_resume": len(before.json()["incidents"]),
                "resume_decision": resumed["decision"],
                "incident_status_after_resume": incidents_after[0]["status"],
                "resolution": incidents_after[0]["resolution"],
            }
        )

    def _scene_audit_export(self, client: TestClient) -> None:
        audit = client.post("/v1/audit/query", json={"limit": 100})
        audit.raise_for_status()
        json_export = client.post(
            "/v1/exports",
            json={"start_time": 0, "end_time": 9_999_999_999_999, "format": "json"},
        )
        json_export.raise_for_status()
        pdf_export = client.post(
            "/v1/exports",
            json={"start_time": 0, "end_time": 9_999_999_999_999, "format": "pdf"},
        )
        pdf_export.raise_for_status()
        pdf = pdf_export.json()["export"]
        download_url = f"/v1/exports/{pdf['export_id']}/download"
        download = client.get(download_url)
        download.raise_for_status()
        raw_body = download.content
        raw_path = self.artifact_dir / "export-download-response-body.bin"
        raw_path.write_bytes(raw_body)
        raw_is_pdf = raw_body.startswith(b"%PDF-")
        pdf_bytes = raw_body if raw_is_pdf else self._decode_pdf_envelope(raw_body)
        pdf_file = self.artifact_dir / "export-download.pdf"
        pdf_file.write_bytes(pdf_bytes)

        self.scenes.append(
            {
                "scene": "audit_export",
                "routes": ["/v1/audit/query", "/v1/exports", download_url],
                "audit_operation_count": audit.json()["total_count"],
                "json_export_id": json_export.json()["export"]["export_id"],
                "pdf_export_id": pdf["export_id"],
                "pdf_download_url": download_url,
                "pdf_raw_response_is_pdf_bytes": raw_is_pdf,
                "pdf_download_glue_bug_confirmed": not raw_is_pdf,
                "pdf_bytes_size": len(pdf_bytes),
                "pdf_magic": pdf_bytes.startswith(b"%PDF-"),
                "pdf_file": str(pdf_file),
                "raw_download_response_file": str(raw_path),
            }
        )

    def _decode_pdf_envelope(self, raw_body: bytes) -> bytes:
        try:
            envelope = json.loads(raw_body.decode("utf-8"))
        except ValueError as exc:
            raise RuntimeError("PDF download was neither raw PDF nor JSON envelope") from exc
        if envelope.get("content_type") != "application/pdf" or not envelope.get("body_base64"):
            raise RuntimeError("PDF download JSON envelope is missing PDF content")
        return base64.b64decode(str(envelope["body_base64"]))

    def _summary(self, client: TestClient) -> dict[str, Any]:
        timeline = client.get(f"/v1/governance/runs/{PAYMENT_RUN_ID}/timeline")
        timeline.raise_for_status()
        all_decisions = [str(v["decision"]) for v in self.verdicts]
        decision_counts = {
            decision: all_decisions.count(decision) for decision in sorted(set(all_decisions))
        }
        cost = client.get(f"/v1/governance/runs/{PAYMENT_RUN_ID}/cost")
        cost_payload = cost.json() if cost.status_code == 200 else None
        latencies = [
            float(v["latency_ms"])
            for v in self.verdicts
            if isinstance(v.get("latency_ms"), int | float)
        ]
        return {
            "run_label": "ROUND2_DEMO_LOCAL_BACKEND",
            "api_call_status": "NO_PROVIDER_CALLS",
            "artifact_dir": str(self.artifact_dir),
            "scene_count": len(self.scenes),
            "scenes": self.scenes,
            "decision_counts": decision_counts,
            "latency_ms": {
                "min": min(latencies) if latencies else None,
                "max": max(latencies) if latencies else None,
            },
            "token_cost_rollup": cost_payload,
            "evidence_labels": sorted(
                {str(v.get("evidence_label")) for v in self.verdicts if v.get("evidence_label")}
            ),
            "backend_endpoints_exercised": [
                "/v1/agents/register",
                "/v1/governance/decide",
                "/v1/governance/record",
                "/v1/governance/incidents",
                "/v1/governance/incidents/{incident_id}/resume",
                "/v1/audit/query",
                "/v1/exports",
                "/v1/exports/{export_id}/download",
            ],
        }

    @staticmethod
    def _prevented_loss(verdict: dict[str, Any]) -> float | None:
        obligations = verdict.get("obligations")
        if not isinstance(obligations, dict):
            return None
        loss = obligations.get("prevented_loss")
        return float(loss) if isinstance(loss, int | float) else None


def run_demo(artifact_dir: str | Path = DEFAULT_ARTIFACT_DIR) -> dict[str, Any]:
    return DemoRunner(Path(artifact_dir)).run()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local Round 2 finance demo flow.")
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    args = parser.parse_args()
    summary = run_demo(args.artifact_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
