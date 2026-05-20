"""Model-free deterministic Defender rules (no LLM, microseconds)."""

from __future__ import annotations

from shield_governance.defender import (
    CumulativeRecipientTracker,
    DefenderPolicy,
    check_amount_cap,
    check_iban_allowlist,
    check_iban_format,
    evaluate_send_money,
    is_valid_iban,
    scan_subject_secrets,
)
from shield_sdk.schema import Decision


def test_is_valid_iban() -> None:
    # Canonical mod-97-valid IBANs.
    assert is_valid_iban("GB82WEST12345698765432")
    assert is_valid_iban("DE89 3704 0044 0532 0130 00")  # spaces tolerated
    # Broken check digits / malformed.
    assert not is_valid_iban("GB00WEST12345698765432")
    assert not is_valid_iban("not-an-iban")
    assert not is_valid_iban("")


def test_iban_format_and_allowlist_are_orthogonal() -> None:
    assert check_iban_format("GB82WEST12345698765432").decision is Decision.PASS
    assert check_iban_format("GB00WEST12345698765432").decision is Decision.BLOCK
    # No allowlist configured -> allowlist rule is a no-op (PASS).
    assert check_iban_allowlist("GB82WEST12345698765432", None).decision is Decision.PASS
    allow = frozenset({"GB82WEST12345698765432"})
    assert check_iban_allowlist("GB82WEST12345698765432", allow).decision is Decision.PASS
    assert check_iban_allowlist("DE89370400440532013000", allow).decision is Decision.BLOCK


def test_amount_cap_per_call_only() -> None:
    assert check_amount_cap(9_999, 10_000).decision is Decision.PASS
    assert check_amount_cap(10_000, 10_000).decision is Decision.PASS  # boundary inclusive
    assert check_amount_cap(10_001, 10_000).decision is Decision.BLOCK
    assert check_amount_cap(1e9, None).decision is Decision.PASS  # disabled


def test_scan_subject_secrets_catches_exfil() -> None:
    assert scan_subject_secrets("Invoice March").decision is Decision.PASS
    assert scan_subject_secrets("the password is hunter2").decision is Decision.BLOCK
    assert scan_subject_secrets("ping GB82WEST12345698765432").decision is Decision.BLOCK
    assert scan_subject_secrets("key sk-ABCDEFGHIJKLMNOPQRSTUVWX").decision is Decision.BLOCK
    assert scan_subject_secrets("SSN 123-45-6789").decision is Decision.BLOCK


def test_cumulative_tracker_state_and_strict_gt() -> None:
    t = CumulativeRecipientTracker()
    assert t.total("A") == 0.0
    # strict '>' mirrors the Invariant LocalPolicy DSL.
    assert t.evaluate("A", 10_000, cap=10_000).decision is Decision.PASS
    t.commit("A", 10_000)
    assert t.total("A") == 10_000
    assert t.evaluate("A", 1, cap=10_000).decision is Decision.BLOCK  # 10001 > 10000
    assert t.evaluate("A", 10_000, cap=None).decision is Decision.PASS  # disabled
    # Per-recipient isolation.
    assert t.evaluate("B", 5_000, cap=10_000).decision is Decision.PASS


def test_evaluate_send_money_takes_worst_outcome() -> None:
    policy = DefenderPolicy(amount_cap=10_000, cumulative_cap=20_000)
    t = CumulativeRecipientTracker()
    ok = evaluate_send_money(
        {"recipient": "ACME", "amount": 5_000, "subject": "Invoice"},
        policy=policy,
        tracker=t,
    )
    assert ok.decision is Decision.PASS
    bad = evaluate_send_money(
        {"recipient": "ACME", "amount": 5_000, "subject": "password: x"},
        policy=policy,
        tracker=t,
    )
    assert bad.decision is Decision.BLOCK
    assert bad.label.startswith("subject.secret")


def test_evaluate_send_money_iban_policy_paths() -> None:
    """require_valid_iban + iban_allowlist gates wired through the public
    Defender entrypoint (end-to-end, not just the unit rules)."""
    valid = "GB82WEST12345698765432"
    tracker = CumulativeRecipientTracker()
    strict = DefenderPolicy(require_valid_iban=True, iban_allowlist=frozenset({valid}))

    ok = evaluate_send_money(
        {"recipient": valid, "amount": 100, "subject": "ok"}, policy=strict, tracker=tracker
    )
    assert ok.decision is Decision.PASS

    bad_fmt = evaluate_send_money(
        {"recipient": "NOTANIBAN", "amount": 100, "subject": "ok"},
        policy=strict,
        tracker=tracker,
    )
    assert bad_fmt.decision is Decision.BLOCK
    assert bad_fmt.label == "iban.invalid"

    off_list = evaluate_send_money(
        {"recipient": "DE89370400440532013000", "amount": 100, "subject": "ok"},
        policy=strict,
        tracker=tracker,
    )
    assert off_list.decision is Decision.BLOCK
    assert off_list.label == "iban.not_allowlisted"


def test_cumulative_would_exceed_predicate() -> None:
    t = CumulativeRecipientTracker()
    t.commit("A", 8_000)
    assert t.would_exceed("A", 3_000, cap=10_000) is True  # 11000 > 10000
    assert t.would_exceed("A", 2_000, cap=10_000) is False  # 10000 not > 10000
    assert t.would_exceed("B", 1, cap=10_000) is False


def test_evaluate_send_money_unparseable_amount_blocks() -> None:
    # ValueError path (str that is not a number).
    out = evaluate_send_money(
        {"recipient": "A", "amount": "lots", "subject": ""},
        policy=DefenderPolicy(),
        tracker=CumulativeRecipientTracker(),
    )
    assert out.decision is Decision.BLOCK
    assert out.label == "amount.unparseable"
    # TypeError path (non-scalar amount) — reviewer N1: cover both except arms.
    out2 = evaluate_send_money(
        {"recipient": "A", "amount": [1, 2], "subject": ""},
        policy=DefenderPolicy(),
        tracker=CumulativeRecipientTracker(),
    )
    assert out2.decision is Decision.BLOCK
    assert out2.label == "amount.unparseable"


def test_rule_outcome_maps_to_frozen_v11_verdict_reason() -> None:
    """v1.1 adoption proof: a Defender RuleOutcome projects onto the FROZEN
    §4.2 VerdictReason using the v1.1 names label/detail/agent/score, with the
    cost-hook-#2 fields set to the model-free Defender semantics."""
    from shield_sdk.schema import Guardian, ServedVia, VerdictReason

    vr = scan_subject_secrets("the password is hunter2").to_verdict_reason()
    assert isinstance(vr, VerdictReason)
    assert vr.agent is Guardian.DEFENDER
    assert vr.label.startswith("subject.secret")
    assert vr.detail and "exfil" in vr.detail
    assert vr.score == 1.0
    # Defender is model-free -> no LLM token spend attributed to this reason.
    assert vr.served_via is ServedVia.LOCAL
    assert vr.model_id is None
    # PASS outcomes carry empty detail -> projected as None (schema-clean).
    assert scan_subject_secrets("Invoice March").to_verdict_reason().detail is None


# --------------------------------------------------------------------------- #
# A.4 / Task #31 — prevented_loss env-diff $ on the deterministic Defender
# rules (downstream populates frozen §4.2 Obligations.prevented_loss).
# --------------------------------------------------------------------------- #


def test_amount_cap_pass_carries_no_prevented_loss() -> None:
    assert check_amount_cap(9_999, 10_000).prevented_loss is None
    assert check_amount_cap(10_000, 10_000).prevented_loss is None
    assert check_amount_cap(1e9, None).prevented_loss is None


def test_amount_cap_block_carries_transfer_amount() -> None:
    """A.4 single_cap rule: prevented_loss = the over-cap transfer's amount."""
    out = check_amount_cap(50_000, 10_000)
    assert out.decision is Decision.BLOCK
    assert out.prevented_loss == 50_000.0
    assert isinstance(out.prevented_loss, float)


def test_cumulative_tracker_block_carries_projected_sigma_at_fire() -> None:
    """A.4 structuring rule: prevented_loss = projected Σ-at-fire (= the total
    Σ that WOULD have flowed to the recipient if the BLOCKed call had run)."""
    t = CumulativeRecipientTracker()
    t.commit("A", 10_000)
    t.commit("A", 10_000)  # already at 20_000
    out = t.evaluate("A", 10_000, cap=20_000)  # 3rd $10k -> projected 30_000 > 20_000
    assert out.decision is Decision.BLOCK
    assert out.prevented_loss == 30_000.0  # matches AgentDojo oracle `sum >= 30000`


def test_cumulative_tracker_pass_carries_no_prevented_loss() -> None:
    t = CumulativeRecipientTracker()
    assert t.evaluate("A", 5_000, cap=10_000).prevented_loss is None
    assert t.evaluate("A", 5_000, cap=None).prevented_loss is None


def test_exfil_block_carries_no_prevented_loss() -> None:
    """No fabrication: exfil subject.secret.* BLOCK has no clear env-diff $."""
    out = scan_subject_secrets("password: hunter2")
    assert out.decision is Decision.BLOCK
    assert out.prevented_loss is None
