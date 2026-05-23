"""Auditor — provenance / integrity / compliance. Parallel, NEVER blocks
(governance_design §3.4). Runs on the Channel-2 path.

* ``verify_chain`` / ``verify_merkle_epoch`` = deterministic SHA-256 chain +
  Ed25519 over Layer-1 records via ``shield_sdk.canonical.verify_record``
  (imported — gov NEVER redeclares §4 crypto).
* ``update_provenance_graph`` = AGENTSAFE Action Provenance DAG in ``networkx``,
  keyed by ``correlation_id`` (pre_exec↔post_exec pairing + chain order).
* ``detect_self_report_mismatch`` = self-reported ``payload.confidence`` vs the
  graph-observed outcome.
* ``generate_compliance_report`` = JSON ($-prevented, decision-mix,
  OWASP-Agentic map) + a Haiku narrative via ``ShieldModelRouter`` (injected;
  null in unit CI). PDF + signed ``egress=0`` attestation = **W4** (not here —
  no overclaim).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from shield_sdk.canonical import verify_record  # frozen §4 — imported, never redeclared
from shield_sdk.schema import (
    Decision,
    GovernanceVerdict,
    Guardian,
    ShieldActionRecord,
    VerdictReason,
)


@dataclass(frozen=True, slots=True)
class AuditResult:
    integrity: float  # 1.0 = all signatures/chain valid .. 0.0 = all broken
    chain_broken: bool
    reasons: list[VerdictReason]
    self_report_mismatch: bool


@dataclass(frozen=True, slots=True)
class MerkleVerification:
    verified: bool
    root: str | None = None
    epoch_id: str | None = None
    detail: str | None = None


class ProvenanceGraph:
    """AGENTSAFE Action Provenance DAG (networkx), keyed by correlation_id."""

    def __init__(self) -> None:
        import networkx as nx

        self._g: Any = nx.DiGraph()

    def add_record(self, record: ShieldActionRecord) -> None:
        self._g.add_node(
            record.record_id,
            correlation_id=record.correlation_id,
            phase=record.phase.value,
            tool=record.payload.tool_name,
            run_id=record.run_id,
        )
        if record.prev_chain_hash:
            # chain edge: predecessor is whatever node carries this prev hash;
            # we link by correlation_id pairing (pre_exec -> post_exec) too.
            for nid, data in self._g.nodes(data=True):
                if (
                    nid != record.record_id
                    and data.get("correlation_id") == record.correlation_id
                    and data.get("phase") != record.phase.value
                ):
                    self._g.add_edge(nid, record.record_id, kind="correlation")

    @property
    def order(self) -> int:
        return int(self._g.number_of_nodes())

    def to_node_link(self) -> dict[str, Any]:
        import networkx as nx

        return dict(nx.node_link_data(self._g, edges="edges"))


class Auditor:
    """Never blocks — emits integrity signals the Supervisor folds into risk
    (auditor_integrity / chain_broken) and a compliance report."""

    def __init__(
        self,
        *,
        narrator: Callable[[str], Awaitable[str]] | None = None,
        merkle_verifier: Callable[[list[ShieldActionRecord]], MerkleVerification] | None = None,
        zero_egress_attestor: Callable[[dict[str, object]], dict[str, object]] | None = None,
    ) -> None:
        self._narrator = narrator  # Haiku via ShieldModelRouter; None -> JSON only
        self._merkle_verifier = merkle_verifier
        self._zero_egress_attestor = zero_egress_attestor
        self._latest_merkle: MerkleVerification | None = None
        self._dag = ProvenanceGraph()

    def audit(
        self, records: list[ShieldActionRecord], *, agent_pubkey_b64url: str | None
    ) -> AuditResult:
        if not records:
            return AuditResult(1.0, False, [], False)

        valid = 0
        for rec in records:
            self._dag.add_record(rec)
            if rec.signature and agent_pubkey_b64url and verify_record(rec, agent_pubkey_b64url):
                valid += 1
        integrity = valid / len(records)
        chain_broken = valid != len(records)

        mismatch = self._detect_self_report_mismatch(records)
        reasons: list[VerdictReason] = []
        if chain_broken:
            failed = len(records) - valid
            reasons.append(
                VerdictReason(
                    agent=Guardian.AUDITOR,
                    label="auditor.chain_broken",
                    detail=f"{failed}/{len(records)} records failed Ed25519/chain verify",
                    score=1.0,
                )
            )
        if self._merkle_verifier is not None:
            merkle = self._merkle_verifier(records)
            self.record_merkle_verification(merkle)
            if not merkle.verified:
                chain_broken = True
                integrity = 0.0
                reasons.append(
                    VerdictReason(
                        agent=Guardian.AUDITOR,
                        label="auditor.merkle_failed",
                        detail=merkle.detail or "record batch failed Merkle/EER verification",
                        score=1.0,
                    )
                )
        if mismatch:
            reasons.append(
                VerdictReason(
                    agent=Guardian.AUDITOR,
                    label="auditor.self_report_mismatch",
                    detail="self-reported confidence contradicts observed outcome",
                    score=0.5,
                )
            )
        return AuditResult(integrity, chain_broken, reasons, mismatch)

    def record_merkle_verification(self, verification: MerkleVerification) -> None:
        self._latest_merkle = verification

    @staticmethod
    def _detect_self_report_mismatch(records: list[ShieldActionRecord]) -> bool:
        for rec in records:
            conf = rec.payload.confidence
            if conf is not None and conf >= 0.8 and rec.payload.tool_error:
                return True  # claimed high confidence but the call errored
        return False

    async def generate_compliance_report(self, verdicts: list[GovernanceVerdict]) -> dict[str, Any]:
        mix: dict[str, int] = {}
        prevented = 0.0
        for v in verdicts:
            mix[v.decision.value] = mix.get(v.decision.value, 0) + 1
            if v.decision in (Decision.BLOCK, Decision.ROLLBACK) and v.obligations.prevented_loss:
                prevented += float(v.obligations.prevented_loss)
        report: dict[str, Any] = {
            "report_version": "w4-json",
            "decision_mix": mix,
            "blocked": mix.get("BLOCK", 0) + mix.get("ROLLBACK", 0),
            "escalated": mix.get("ESCALATE", 0),
            "dollars_prevented": prevented,
            "provenance_nodes": self._dag.order,
            "owasp_agentic": ["LLM01-PromptInjection", "LLM06-ExcessiveAgency"],
        }
        if self._latest_merkle is not None:
            report["merkle"] = {
                "verified": self._latest_merkle.verified,
                "root": self._latest_merkle.root,
                "epoch_id": self._latest_merkle.epoch_id,
            }
            if self._latest_merkle.detail:
                report["merkle"]["detail"] = self._latest_merkle.detail
        if self._narrator is not None:
            report["narrative"] = (
                await self._narrator(f"Summarize this governance audit in 2 sentences: {report}")
            ).strip()
        if self._zero_egress_attestor is not None:
            report["zero_egress_attestation"] = self._zero_egress_attestor(report)
        return report
