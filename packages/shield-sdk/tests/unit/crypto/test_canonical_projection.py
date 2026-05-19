"""The FROZEN §4 signable-field projection — the rule server-builder mirrors.

Pins: present-null ≡ absent ≡ omitted; ``signature``/``chain_hash`` excluded
from records; ``signature_by_shield`` excluded from verdicts; empty containers
kept; sign/verify + tamper rejection for both records and verdicts; the
finalize -> verify happy path.
"""

from __future__ import annotations

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

_PRIV = crypto.base64url_encode(bytes(range(32)))
_PUB = crypto.get_public_key_base64url(_PRIV)


def _rec(**kw: object) -> ShieldActionRecord:
    base: dict[str, object] = dict(
        run_id="run-1",
        phase=Phase.PRE_EXEC,
        issued_at=1747526400000,
        nonce="AAAAAAAAAAAAAAAAAAAAAA",
        record_id="0193aaaa-bbbb-7ccc-8ddd-000000000001",
        correlation_id="0193aaaa-bbbb-7ccc-8ddd-000000000002",
    )
    base.update(kw)
    return ShieldActionRecord(**base)  # type: ignore[arg-type]


def test_signature_and_chain_hash_excluded_from_record_signable() -> None:
    rec = _rec(chain_hash="SERVER-SET-VALUE", signature="CLIENT-SIG")
    d = canonical.record_signable_dict(rec)
    assert "signature" not in d
    assert "chain_hash" not in d
    # A server later attaching chain_hash must NOT invalidate the signature.
    signed = canonical.finalize_record(_rec(), _PRIV)
    after = signed.model_copy(deep=True)
    after.chain_hash = "DERIVED-BY-SERVER"
    assert canonical.verify_record(after, _PUB) is True


def test_present_null_equals_absent_equals_omitted() -> None:
    explicit_none = _rec(
        payload=ActionPayload(
            tool_name="t",
            tool_args={"a": 1},
            tool_result=None,
            tool_error=None,
            llm=None,
            confidence=None,
        )
    )
    absent = _rec(payload=ActionPayload(tool_name="t", tool_args={"a": 1}))
    assert canonical.record_signing_string(explicit_none) == canonical.record_signing_string(absent)
    # And no JSON null leaks into the signed bytes.
    assert "null" not in canonical.record_signing_string(explicit_none)


def test_empty_containers_are_kept() -> None:
    s = canonical.record_signing_string(_rec())
    assert '"subject":{}' in s
    assert '"context":{}' in s


def test_verdict_signable_excludes_only_signature_by_shield() -> None:
    v = GovernanceVerdict(
        correlation_id="c",
        decision=Decision.PASS,
        signature_by_shield="SHOULD-NOT-BE-SIGNED",
    )
    d = canonical.verdict_signable_dict(v)
    assert "signature_by_shield" not in d
    assert d["decision"] == "PASS"


def test_finalize_and_verify_record_happy_path() -> None:
    rec = _rec(
        action=ActionRef(tool="send_money", args_digest="sha256:x"),
        payload=ActionPayload(tool_name="send_money", tool_args={"amount": 10000.0}),
    )
    signed = canonical.finalize_record(rec, _PRIV)
    assert signed.payload_hash and signed.signature
    assert signed.chain_hash is None  # server-derived; finalize never sets it
    assert canonical.verify_record(signed, _PUB) is True


def test_record_tamper_is_rejected() -> None:
    signed = canonical.finalize_record(
        _rec(payload=ActionPayload(tool_name="send_money", tool_args={"amount": 10000.0})),
        _PRIV,
    )
    tampered = signed.model_copy(deep=True)
    tampered.payload.tool_args["amount"] = 1.0
    assert canonical.verify_record(tampered, _PUB) is False


def test_unsigned_record_does_not_verify() -> None:
    assert canonical.verify_record(_rec(), _PUB) is False


def test_finalize_and_verify_verdict_with_rollback() -> None:
    v = GovernanceVerdict(
        record_id="0193aaaa-bbbb-7ccc-8ddd-000000000001",
        correlation_id="0193aaaa-bbbb-7ccc-8ddd-000000000002",
        run_id="run-1",
        decision=Decision.ROLLBACK,
        risk_score=0.91,
        reasons=[
            VerdictReason(
                agent=Guardian.EVALUATOR,
                label="STRUCTURING",
                detail="3x10k",
                score=0.95,
                model_id="m",
                served_via=ServedVia.CLOUD,
            )
        ],
        obligations=Obligations(
            require_human=True,
            rollback=RollbackObligation(
                langgraph_checkpoint_id="ckpt_1", env_snapshot_ref="rec_pre_1"
            ),
            prevented_loss=30000.0,
        ),
    )
    signed = canonical.finalize_verdict(v, _PRIV)
    assert canonical.verify_verdict(signed, _PUB) is True
    tampered = signed.model_copy(deep=True)
    tampered.obligations.prevented_loss = 0.0
    assert canonical.verify_verdict(tampered, _PUB) is False


def test_unsigned_verdict_does_not_verify() -> None:
    v = GovernanceVerdict(correlation_id="c", decision=Decision.PASS)
    assert canonical.verify_verdict(v, _PUB) is False


# --------------------------------------------------------------------------- #
# W3 U3 — verify_ingest is a PURE byte-identical pass-through to verify_record
# (HG#1 server single-ingest call-site; parity guaranteed by construction).
# --------------------------------------------------------------------------- #


def test_verify_ingest_is_pure_passthrough() -> None:
    signed = canonical.finalize_record(
        _rec(payload=ActionPayload(tool_name="send_money", tool_args={"amount": 30000.0})),
        _PRIV,
    )
    tampered = signed.model_copy(deep=True)
    tampered.payload.tool_args["amount"] = 1.0
    unsigned = _rec()
    wrong_pub = crypto.get_public_key_base64url(crypto.base64url_encode(bytes(range(1, 33))))

    # Identical result to verify_record for every case (valid / tamper /
    # unsigned / wrong key) — no independent logic in verify_ingest.
    for rec, pub in [
        (signed, _PUB),
        (tampered, _PUB),
        (unsigned, _PUB),
        (signed, wrong_pub),
    ]:
        assert canonical.verify_ingest(rec, pub) == canonical.verify_record(rec, pub)

    assert canonical.verify_ingest(signed, _PUB) is True
    assert canonical.verify_ingest(tampered, _PUB) is False
    assert canonical.verify_ingest(unsigned, _PUB) is False
