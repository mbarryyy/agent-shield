"""Supervisor — deterministic aggregate + hard overrides + thresholds."""

from __future__ import annotations

from shield_governance.supervisor import (
    GuardianSignals,
    Supervisor,
    SupervisorPolicy,
    signals_from_defender,
)
from shield_sdk.schema import (
    ActionPayload,
    Decision,
    Guardian,
    Phase,
    ShieldActionRecord,
    VerdictReason,
)


def _rec(phase: Phase = Phase.PRE_EXEC) -> ShieldActionRecord:
    return ShieldActionRecord(
        run_id="run-1",
        phase=phase,
        payload=ActionPayload(tool_name="send_money", tool_args={"recipient": "A", "amount": 1}),
    )


def test_clean_pass() -> None:
    v = Supervisor().decide(GuardianSignals(), record=_rec())
    assert v.decision is Decision.PASS
    assert v.risk_score < 0.10
    assert v.correlation_id and v.signature_by_shield is None  # gov never signs


def test_defender_block_hard_override() -> None:
    sig = GuardianSignals(defender_decision=Decision.BLOCK)
    v = Supervisor().decide(sig, record=_rec())
    assert v.decision is Decision.BLOCK


def test_defender_block_post_exec_becomes_rollback_with_obligation() -> None:
    rec = _rec(Phase.POST_EXEC)
    rec.context.checkpoint_id = "ckpt-9"
    rec.context.env_snapshot_ref = "rec-9"
    sig = GuardianSignals(defender_decision=Decision.BLOCK, post_exec=True)
    v = Supervisor().decide(sig, record=rec)
    assert v.decision is Decision.ROLLBACK
    assert v.obligations.rollback is not None
    assert v.obligations.rollback.langgraph_checkpoint_id == "ckpt-9"
    assert v.obligations.rollback.env_snapshot_ref == "rec-9"


def test_structuring_exfil_block_escalate() -> None:
    v = Supervisor().decide(GuardianSignals(structuring_or_exfil=True), record=_rec())
    assert v.decision is Decision.BLOCK
    assert v.obligations.require_human is True


def test_chain_broken_block_escalate() -> None:
    v = Supervisor().decide(GuardianSignals(chain_broken=True), record=_rec())
    assert v.decision is Decision.BLOCK
    assert v.obligations.require_human is True


def test_risk_threshold_bands() -> None:
    sup = Supervisor(SupervisorPolicy())
    # high evaluator anomaly with no hard override -> risk crosses bands
    v_block = sup.decide(GuardianSignals(evaluator_anomaly=1.0), record=_rec())
    assert v_block.decision in (Decision.BLOCK, Decision.ESCALATE)
    v_mid = sup.decide(GuardianSignals(evaluator_anomaly=0.5), record=_rec())
    assert v_mid.decision in (Decision.ALERT, Decision.ESCALATE)


def test_conflict_triggers_injected_arbiter() -> None:
    calls: list[int] = []

    def arbiter(s: GuardianSignals) -> Decision:
        calls.append(1)
        return Decision.BLOCK

    sup = Supervisor(arbiter=arbiter)
    # Conflict is only meaningful once the Evaluator has actually run (async
    # path): Defender PASS but Evaluator anomaly very high -> arbitrate.
    sig = GuardianSignals(
        defender_decision=Decision.PASS, evaluator_anomaly=0.95, evaluator_ran=True
    )
    v = sup.decide(sig, record=_rec())
    assert calls == [1]
    assert v.decision is Decision.BLOCK
    assert any(r.label == "supervisor.arbitrated" for r in v.reasons)


def test_no_conflict_on_sync_hot_path_even_with_defender_block() -> None:
    """HG#5: on the sync path evaluator_ran=False, so a Defender BLOCK takes
    the hard override with NO arbiter/LLM (0 LLM tokens)."""

    def boom(s: GuardianSignals) -> Decision:
        raise AssertionError("HG#5: arbiter must NOT run on the model-free hot path")

    sup = Supervisor(arbiter=boom)
    v = sup.decide(
        GuardianSignals(defender_decision=Decision.BLOCK, structuring_or_exfil=True),
        record=_rec(),
    )
    assert v.decision is Decision.BLOCK


def test_no_conflict_does_not_call_arbiter() -> None:
    def boom(s: GuardianSignals) -> Decision:
        raise AssertionError("arbiter must NOT be called when guardians agree")

    sup = Supervisor(arbiter=boom)
    v = sup.decide(
        GuardianSignals(defender_decision=Decision.PASS, evaluator_anomaly=0.0), record=_rec()
    )
    assert v.decision is Decision.PASS


def test_signals_from_defender_detects_structuring() -> None:
    dv_reason = VerdictReason(agent=Guardian.DEFENDER, label="cumulative.structuring", score=1.0)
    from shield_sdk.schema import GovernanceVerdict

    dverdict = GovernanceVerdict(decision=Decision.BLOCK, correlation_id="c", reasons=[dv_reason])
    s = signals_from_defender(dverdict, phase=Phase.PRE_EXEC)
    assert s.defender_decision is Decision.BLOCK
    assert s.structuring_or_exfil is True
    assert s.post_exec is False


def test_escalate_band_sets_require_human() -> None:
    # Tighten thresholds so a mid anomaly lands in the ESCALATE band.
    sup = Supervisor(SupervisorPolicy(t_alert=0.05, t_escalate=0.10, t_block=0.95))
    v = sup.decide(GuardianSignals(evaluator_anomaly=0.5), record=_rec())
    assert v.decision is Decision.ESCALATE
    assert v.obligations.require_human is True


# --------------------------------------------------------------------------- #
# A.4 / Task #31 — Supervisor preserves Defender's env-diff $ into the FINAL
# frozen §4.2 Obligations.prevented_loss on BLOCK/ROLLBACK.
# --------------------------------------------------------------------------- #


def test_supervisor_preserves_prevented_loss_on_block() -> None:
    sig = GuardianSignals(defender_decision=Decision.BLOCK, prevented_loss=50_000.0)
    v = Supervisor().decide(sig, record=_rec())
    assert v.decision is Decision.BLOCK
    assert v.obligations.prevented_loss == 50_000.0


def test_supervisor_preserves_prevented_loss_on_rollback() -> None:
    """post-exec BLOCK → ROLLBACK; Auditor counts {BLOCK, ROLLBACK}, so
    prevented_loss must carry through ROLLBACK too (auditor.py:138-139)."""
    rec = _rec(Phase.POST_EXEC)
    sig = GuardianSignals(defender_decision=Decision.BLOCK, prevented_loss=30_000.0, post_exec=True)
    v = Supervisor().decide(sig, record=rec)
    assert v.decision is Decision.ROLLBACK
    assert v.obligations.prevented_loss == 30_000.0
    assert v.obligations.rollback is not None  # dual-substrate ROLLBACK still set


def test_supervisor_pass_does_not_set_prevented_loss() -> None:
    """A.4 honesty: PASS never carries a prevented_loss $."""
    v = Supervisor().decide(GuardianSignals(prevented_loss=999.0), record=_rec())
    assert v.decision is Decision.PASS
    assert v.obligations.prevented_loss is None  # NEVER set on PASS


def test_supervisor_block_with_no_prevented_loss_leaves_none() -> None:
    """A.4 honesty: BLOCK without a clear env-diff $ (e.g. exfil) → None.
    Server falls back to 0.0 on None (governance.py:315) — no fabrication."""
    sig = GuardianSignals(defender_decision=Decision.BLOCK, prevented_loss=None)
    v = Supervisor().decide(sig, record=_rec())
    assert v.decision is Decision.BLOCK
    assert v.obligations.prevented_loss is None


def test_signals_from_defender_pulls_prevented_loss_through() -> None:
    from shield_sdk.schema import GovernanceVerdict, Obligations

    dverdict = GovernanceVerdict(
        decision=Decision.BLOCK,
        correlation_id="c",
        reasons=[VerdictReason(agent=Guardian.DEFENDER, label="cumulative.structuring", score=1.0)],
        obligations=Obligations(prevented_loss=30_000.0),
    )
    s = signals_from_defender(dverdict, phase=Phase.PRE_EXEC)
    assert s.prevented_loss == 30_000.0
