"""Regenerate the frozen ``contracts/`` artifacts from the v1.1 schema (O5).

Authoritative regenerator for the §4 v1.1 freeze (C11 / ADR-0007). Emits, from
the single source of truth ``shield_sdk.schema``:

  * ``contracts/shield_action_record.schema.json``
  * ``contracts/governance_verdict.schema.json``  (both ``additionalProperties:
    false`` on every closed object — pydantic ``extra="forbid"`` — so the
    snapshot-diff firewall actually bites; open maps stay open by design)
  * ``contracts/examples/{pre_exec,post_exec,verdict,verdict_escalate}.json``
    (real, internally-consistent v1.1 envelopes; pre/post are signed with the
    frozen golden test keypair so the byte-exact crypto is exercised)

NOT committed on the SDK feature branch — the regenerated ``contracts/``
artifacts land via the dedicated all-owner ADR-0007 ritual PR (team-lead).
This tool itself ships with shield-sdk because the SoT owner owns the
regenerator. Re-runnable, deterministic. Not pytest-collected; mypy-excluded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shield_sdk import canonical, crypto
from shield_sdk.schema import (
    ActionPayload,
    ActionRef,
    Decision,
    GovernanceVerdict,
    Guardian,
    Obligations,
    Phase,
    RollbackObligation,
    ServedVia,
    ShieldActionRecord,
    VerdictReason,
)

_SEED = bytes(range(32))  # the frozen golden test seed (see gen_golden_vectors)


def _snapshot(model: type[Any], title: str, status: str) -> dict[str, Any]:
    schema = model.model_json_schema()
    head: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://agent-shield/contracts/{title}.schema.json",
        "title": model.__name__,
        "x-status": status,
        "x-shield-version": "1.1",
    }
    head.update(schema)
    return head


def main() -> int:
    repo = Path(__file__).resolve().parents[4]
    contracts = repo / "contracts"

    status = (
        "FROZEN §4 v1.1 (C11/ADR-0007). Regenerated from shield_sdk.schema "
        "(the single pydantic source of truth) via "
        "packages/shield-sdk/tests/_tools/gen_contract_snapshots.py. "
        "additionalProperties:false on every closed object; tool_args/subject "
        "are intentionally open maps."
    )

    sar = _snapshot(ShieldActionRecord, "shield_action_record", status)
    gv = _snapshot(GovernanceVerdict, "governance_verdict", status)
    (contracts / "shield_action_record.schema.json").write_text(json.dumps(sar, indent=2) + "\n")
    (contracts / "governance_verdict.schema.json").write_text(json.dumps(gv, indent=2) + "\n")

    priv = crypto.base64url_encode(_SEED)

    pre = ShieldActionRecord(
        record_id="0193aaaa-bbbb-7ccc-8ddd-000000000001",
        correlation_id="0193aaaa-bbbb-7ccc-8ddd-000000000002",
        run_id="run-0001",
        step_index=4,
        issued_at=1747526400000,
        nonce="AAAAAAAAAAAAAAAAAAAAAA",
        phase=Phase.PRE_EXEC,
        action=ActionRef(tool="send_money", args_digest="sha256:deadbeef"),
        payload=ActionPayload(
            tool_name="send_money",
            tool_args={
                "recipient": "ATTACKER-IBAN",
                "amount": 10000.0,
                "subject": "exfil",
                "date": "2026-05-18",
            },
        ),
    )
    pre = canonical.finalize_record(pre, priv)

    post = ShieldActionRecord(
        record_id="0193aaaa-bbbb-7ccc-8ddd-000000000004",
        correlation_id="0193aaaa-bbbb-7ccc-8ddd-000000000002",
        run_id="run-0001",
        step_index=5,
        issued_at=1747526400500,
        nonce="BBBBBBBBBBBBBBBBBBBBBB",
        phase=Phase.POST_EXEC,
        action=ActionRef(tool="send_money", args_digest="sha256:deadbeef"),
        payload=ActionPayload(
            tool_name="send_money",
            tool_args={
                "recipient": "ATTACKER-IBAN",
                "amount": 10000.0,
                "subject": "exfil",
                "date": "2026-05-18",
            },
            tool_result={"blocked": True},
        ),
        verdict_ref="0193aaaa-bbbb-7ccc-8ddd-000000000003",
        prev_chain_hash=canonical.derive_chain_hash(crypto.GENESIS_CHAIN_HASH, pre),
    )
    post = canonical.finalize_record(post, priv)

    verdict = canonical.finalize_verdict(
        GovernanceVerdict(
            verdict_id="0193aaaa-bbbb-7ccc-8ddd-000000000003",
            record_id=pre.record_id,
            correlation_id=pre.correlation_id,
            run_id="run-0001",
            decision=Decision.BLOCK,
            risk_score=0.93,
            reasons=[
                VerdictReason(
                    agent=Guardian.DEFENDER,
                    label="RECIPIENT_NOT_ALLOWLISTED",
                    detail="IBAN never seen for this user",
                    score=0.9,
                    model_id=None,
                    served_via=ServedVia.LOCAL,
                ),
                VerdictReason(
                    agent=Guardian.EVALUATOR,
                    label="STRUCTURING",
                    detail="3x$10k -> $30k cumulative across run_id",
                    score=0.95,
                    model_id="claude-sonnet",
                    served_via=ServedVia.CLOUD,
                ),
            ],
            obligations=Obligations(require_human=True, prevented_loss=30000.0),
            latency_ms=740.0,
            served_at=1747526400740,
            shield_kid="shield-server-key-v1",
        ),
        priv,
    )

    escalate = canonical.finalize_verdict(
        GovernanceVerdict(
            verdict_id="0193aaaa-bbbb-7ccc-8ddd-000000000005",
            record_id="0193aaaa-bbbb-7ccc-8ddd-000000000001",
            correlation_id="0193aaaa-bbbb-7ccc-8ddd-000000000002",
            run_id="run-0001",
            decision=Decision.ESCALATE,
            risk_score=0.71,
            reasons=[
                VerdictReason(
                    agent=Guardian.EVALUATOR,
                    label="CUMULATIVE_STRUCTURING",
                    detail="cumulative send_money crosses cap across calls",
                    score=0.71,
                    served_via=ServedVia.LOCAL,
                )
            ],
            obligations=Obligations(
                require_human=True,
                rollback=RollbackObligation(
                    langgraph_checkpoint_id="ckpt_01J", env_snapshot_ref="rec_pre_01J"
                ),
            ),
            latency_ms=240.0,
            served_at=1747526400240,
            shield_kid="shield-server-key-v1",
        ),
        priv,
    )

    examples = contracts / "examples"
    (examples / "pre_exec.json").write_text(
        json.dumps(pre.model_dump(mode="json"), indent=2) + "\n"
    )
    (examples / "post_exec.json").write_text(
        json.dumps(post.model_dump(mode="json"), indent=2) + "\n"
    )
    (examples / "verdict.json").write_text(
        json.dumps(verdict.model_dump(mode="json"), indent=2) + "\n"
    )
    # No "x-note" inside the envelope: the v1.1 snapshot is
    # additionalProperties:false (O5), so examples must be pure, valid
    # GovernanceVerdicts. The ESCALATE-degrades-deterministically-in-batch
    # rule (eval-builder-owned) is documented in contracts/test_schema_frozen.py
    # and ADR-0007, not smuggled into the schema-validated example.
    (examples / "verdict_escalate.json").write_text(
        json.dumps(escalate.model_dump(mode="json"), indent=2) + "\n"
    )

    print("regenerated contracts/ snapshots + examples at v1.1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
