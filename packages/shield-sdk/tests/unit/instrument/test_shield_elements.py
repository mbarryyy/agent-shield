"""W2 contract tests — the §4.2 decision table + fail policy + two-phase chain.

Matrix uses a fake runtime/client for exhaustive, fast coverage; one real-seam
test drives a genuine ``agentdojo.functions_runtime`` + ``TaskEnvironment``
through ShieldGuard → ShieldedToolsExecutor → ShieldRecorder to prove the
element slots and ROLLBACK env-restore work against the real AgentDojo types
(rev 18b501a). The real ShieldClient transport is covered with respx.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
import respx
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime, TaskEnvironment
from shield_sdk import canonical, crypto
from shield_sdk.instrument.agentdojo import (
    ShieldElementConfig,
    ShieldGuard,
    build_shield_elements,
)
from shield_sdk.policy import FailMode, FailPolicy, synthetic_degraded_verdict
from shield_sdk.schema import (
    Decision,
    GovernanceVerdict,
    Obligations,
    Phase,
    RollbackObligation,
    ShieldActionRecord,
)
from shield_sdk.sdk import ShieldClient

_PRIV = crypto.base64url_encode(bytes(range(32)))
_PUB = crypto.get_public_key_base64url(_PRIV)


class _FakeClient:
    def __init__(self, decide_fn: Any) -> None:
        self._decide_fn = decide_fn
        self.submitted: list[ShieldActionRecord] = []

    def decide(self, record: ShieldActionRecord) -> GovernanceVerdict:
        return self._decide_fn(record)  # type: ignore[no-any-return]

    def submit(self, record: ShieldActionRecord) -> None:
        self.submitted.append(record)


class _FakeFn:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeRuntime:
    """Minimal stand-in: elements only use .functions.values()[].name and
    .run_function(env, fn, args)."""

    def __init__(self, names: list[str]) -> None:
        self.functions = {n: _FakeFn(n) for n in names}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run_function(self, env: Any, function: str, kwargs: Any) -> tuple[Any, str | None]:
        self.calls.append((function, dict(kwargs)))
        return {"ok": function, "args": dict(kwargs)}, None


def _verdict(decision: Decision, **kw: Any) -> Any:
    def _fn(record: ShieldActionRecord) -> GovernanceVerdict:
        return GovernanceVerdict(
            record_id=record.record_id,
            correlation_id=record.correlation_id,
            run_id=record.run_id,
            decision=decision,
            **kw,
        )

    return _fn


def _assistant(calls: list[FunctionCall]) -> list[dict[str, Any]]:
    return [{"role": "assistant", "content": None, "tool_calls": calls}]


def _cfg(client: Any, **kw: Any) -> ShieldElementConfig:
    return ShieldElementConfig(
        client=client, agent_private_key_b64url=_PRIV, run_id="run-test", **kw
    )


def _run_pipeline(
    cfg: ShieldElementConfig, runtime: Any, env: Any, calls: list[FunctionCall]
) -> tuple[Any, dict[str, Any]]:
    guard, executor, recorder = build_shield_elements(cfg)
    extra: dict[str, Any] = {}
    msgs: Any = _assistant(calls)
    _, _, env, msgs, extra = guard.query("q", runtime, env, msgs, extra)
    _, _, env, msgs, extra = executor.query("q", runtime, env, msgs, extra)
    _, _, env, msgs, extra = recorder.query("q", runtime, env, msgs, extra)
    return (env, msgs), extra


# --------------------------------------------------------------------------- #
# ShieldGuard: signed pre_exec record, snapshot, verdict bus
# --------------------------------------------------------------------------- #


def test_guard_builds_signed_pre_record_and_verdict_bus() -> None:
    cfg = _cfg(_FakeClient(_verdict(Decision.PASS)))
    rt = _FakeRuntime(["send_money"])
    guard = ShieldGuard(cfg)
    extra: dict[str, Any] = {}
    tc = FunctionCall(function="send_money", args={"amount": 10000.0}, id="call_1")
    _, _, _, _, extra = guard.query("q", rt, TaskEnvironment(), _assistant([tc]), extra)

    dec = extra["shield"]["decisions"]["call_1"]
    pre = dec.pre_record
    assert pre.phase is Phase.PRE_EXEC
    assert pre.action.tool == "send_money"
    assert pre.payload.tool_name == "send_money"
    assert pre.payload.tool_args == {"amount": 10000.0}
    assert pre.subject["agentdojo_tool_call_id"] == "call_1"
    assert pre.prev_chain_hash == crypto.GENESIS_CHAIN_HASH
    assert canonical.verify_record(pre, _PUB) is True  # signed by the agent key
    assert dec.verdict.decision is Decision.PASS


# --------------------------------------------------------------------------- #
# §4.2 decision table (fast matrix via the fake runtime)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("decision", "should_run"),
    [
        (Decision.PASS, True),
        (Decision.ALERT, True),
        (Decision.BLOCK, False),
        (Decision.ROLLBACK, False),
    ],
)
def test_decision_table_run_vs_skip(decision: Decision, should_run: bool) -> None:
    rt = _FakeRuntime(["send_money"])
    cfg = _cfg(_FakeClient(_verdict(decision)))
    tc = FunctionCall(function="send_money", args={"amount": 1.0}, id="c1")
    (_, msgs), extra = _run_pipeline(cfg, rt, TaskEnvironment(), [tc])
    assert (len(rt.calls) == 1) is should_run
    last = msgs[-1]
    if should_run:
        assert last["error"] is None
    else:
        assert "Agent Shield" in (last["error"] or "")
    assert extra["shield"]["decisions"]["c1"].executed is should_run


def test_rewrite_substitutes_args_in_place() -> None:
    rt = _FakeRuntime(["send_money"])
    obl = Obligations(rewrite_args={"recipient": "SAFE-IBAN", "amount": 1.0})
    cfg = _cfg(_FakeClient(_verdict(Decision.REWRITE, obligations=obl)))
    tc = FunctionCall(
        function="send_money", args={"recipient": "ATTACKER", "amount": 9999.0}, id="c"
    )
    _run_pipeline(cfg, rt, TaskEnvironment(), [tc])
    assert rt.calls == [("send_money", {"recipient": "SAFE-IBAN", "amount": 1.0})]


def test_mask_args_redacts_before_execution() -> None:
    rt = _FakeRuntime(["send_money"])
    obl = Obligations(mask_args=["payload.tool_args.subject"])
    cfg = _cfg(_FakeClient(_verdict(Decision.ALERT, obligations=obl)))
    tc = FunctionCall(function="send_money", args={"amount": 1.0, "subject": "exfil"}, id="c")
    _run_pipeline(cfg, rt, TaskEnvironment(), [tc])
    assert rt.calls[0][1]["subject"] == "***REDACTED***"


def test_escalate_modes() -> None:
    tc = FunctionCall(function="send_money", args={"amount": 1.0}, id="c")
    rt_block = _FakeRuntime(["send_money"])
    _run_pipeline(_cfg(_FakeClient(_verdict(Decision.ESCALATE))), rt_block, TaskEnvironment(), [tc])
    assert rt_block.calls == []  # default escalate_mode="block" -> skip
    rt_appr = _FakeRuntime(["send_money"])
    _run_pipeline(
        _cfg(_FakeClient(_verdict(Decision.ESCALATE)), escalate_mode="approve"),
        rt_appr,
        TaskEnvironment(),
        [FunctionCall(function="send_money", args={"amount": 1.0}, id="c")],
    )
    assert len(rt_appr.calls) == 1  # auto-approve -> run


# --------------------------------------------------------------------------- #
# Fail policy (timeout / error -> synthetic verdict per the ratified table)
# --------------------------------------------------------------------------- #


def test_fail_open_default_alert_runs() -> None:
    def slow(_r: ShieldActionRecord) -> GovernanceVerdict:
        time.sleep(0.2)
        raise AssertionError("should have timed out")

    rt = _FakeRuntime(["get_balance"])
    cfg = _cfg(_FakeClient(slow), decision_budget_ms=20)
    tc = FunctionCall(function="get_balance", args={}, id="c")
    (_, msgs), extra = _run_pipeline(cfg, rt, TaskEnvironment(), [tc])
    dec = extra["shield"]["decisions"]["c"]
    assert dec.degraded is True
    assert dec.verdict.decision is Decision.ALERT  # fail-open default
    assert len(rt.calls) == 1  # ALERT still runs (flagged)


def test_fail_closed_for_money_tool_blocks() -> None:
    def boom(_r: ShieldActionRecord) -> GovernanceVerdict:
        raise httpx.ConnectError("layer-2 down")

    rt = _FakeRuntime(["send_money"])
    cfg = _cfg(_FakeClient(boom), decision_budget_ms=50)
    tc = FunctionCall(function="send_money", args={"amount": 1.0}, id="c")
    (_, msgs), extra = _run_pipeline(cfg, rt, TaskEnvironment(), [tc])
    dec = extra["shield"]["decisions"]["c"]
    assert dec.degraded is True
    assert dec.verdict.decision is Decision.BLOCK  # send_money is fail-CLOSED
    assert rt.calls == []  # blocked


def test_fail_policy_table_is_runtime_config() -> None:
    fp = FailPolicy.model_validate({"default": "closed", "overrides": {"get_balance": "open"}})
    assert fp.fail_mode_for("anything") is FailMode.CLOSED
    assert fp.fail_mode_for("get_balance") is FailMode.OPEN
    v = synthetic_degraded_verdict(
        ShieldActionRecord(phase=Phase.PRE_EXEC, run_id="r"),
        FailMode.OPEN,
        detail="x",
    )
    assert v.decision is Decision.ALERT and v.signature_by_shield is None


# --------------------------------------------------------------------------- #
# ShieldRecorder: signed post_exec, paired by correlation_id, Channel-2 submit
# --------------------------------------------------------------------------- #


def test_recorder_emits_paired_signed_post_exec() -> None:
    client = _FakeClient(_verdict(Decision.BLOCK))
    cfg = _cfg(client)
    rt = _FakeRuntime(["send_money"])
    tc = FunctionCall(function="send_money", args={"amount": 30000.0}, id="c")
    _, extra = _run_pipeline(cfg, rt, TaskEnvironment(), [tc])

    assert len(client.submitted) == 1
    post = client.submitted[0]
    pre = extra["shield"]["decisions"]["c"].pre_record
    verdict = extra["shield"]["decisions"]["c"].verdict
    assert post.phase is Phase.POST_EXEC
    assert post.correlation_id == pre.correlation_id  # intent <-> outcome pair
    assert post.verdict_ref == verdict.verdict_id
    assert post.payload.tool_result == {"blocked": True}
    assert canonical.verify_record(post, _PUB) is True


def test_recorder_is_idempotent_per_decision() -> None:
    client = _FakeClient(_verdict(Decision.PASS))
    cfg = _cfg(client)
    rt = _FakeRuntime(["t"])
    guard, executor, recorder = build_shield_elements(cfg)
    extra: dict[str, Any] = {}
    msgs: Any = _assistant([FunctionCall(function="t", args={}, id="c")])
    _, _, env, msgs, extra = guard.query("q", rt, TaskEnvironment(), msgs, extra)
    _, _, env, msgs, extra = executor.query("q", rt, env, msgs, extra)
    _, _, env, msgs, extra = recorder.query("q", rt, env, msgs, extra)
    _, _, env, msgs, extra = recorder.query("q", rt, env, msgs, extra)
    assert len(client.submitted) == 1  # not double-submitted


# --------------------------------------------------------------------------- #
# Real-seam: genuine agentdojo runtime + env; ROLLBACK restores the snapshot
# --------------------------------------------------------------------------- #


class _BankEnv(TaskEnvironment):
    balance: float = 100.0


def test_real_agentdojo_seam_pass_then_rollback_restores_env() -> None:
    rt = FunctionsRuntime([])

    @rt.register_function
    def send_money(env: _BankEnv, amount: float) -> str:  # type: ignore[no-untyped-def]
        """Send money.

        :param amount: the amount
        """
        env.balance -= amount
        return f"sent {amount}"

    # call0 PASS (deducts 10), call1 ROLLBACK (skipped + env restored to the
    # ShieldGuard snapshot taken before any execution this turn -> balance 100).
    def decide(record: ShieldActionRecord) -> GovernanceVerdict:
        idx = record.payload.tool_args["amount"]
        d = Decision.PASS if idx == 10.0 else Decision.ROLLBACK
        obl = Obligations(rollback=RollbackObligation(env_snapshot_ref=record.record_id))
        return GovernanceVerdict(
            record_id=record.record_id,
            correlation_id=record.correlation_id,
            decision=d,
            obligations=obl,
        )

    cfg = _cfg(_FakeClient(decide))
    env = _BankEnv()
    calls = [
        FunctionCall(function="send_money", args={"amount": 10.0}, id="c0"),
        FunctionCall(function="send_money", args={"amount": 50.0}, id="c1"),
    ]
    (out_env, msgs), extra = _run_pipeline(cfg, rt, env, calls)

    assert out_env.balance == 100.0  # ROLLBACK restored the Layer-1 snapshot
    assert any("Rolled back" in (m.get("error") or "") for m in msgs)
    assert extra["shield"]["_rollback_signals"]  # Layer-2 substrate signalled


# --------------------------------------------------------------------------- #
# Real ShieldClient transport (Channel-1 decide + Channel-2 submit)
# --------------------------------------------------------------------------- #


@respx.mock
def test_shield_client_decide_and_submit_roundtrip() -> None:
    rec = ShieldActionRecord(phase=Phase.PRE_EXEC, run_id="r")
    verdict = GovernanceVerdict(correlation_id=rec.correlation_id, decision=Decision.PASS)
    respx.post("http://srv/v1/governance/decide").mock(
        return_value=httpx.Response(200, json=verdict.model_dump(mode="json"))
    )
    # post_exec route confirmed by server-builder: /v1/governance/record -> 202
    # ack {record_id, chain_hash, seq_no, accepted} (no verdict).
    respx.post("http://srv/v1/governance/record").mock(
        return_value=httpx.Response(
            202,
            json={
                "record_id": "r1",
                "chain_hash": "h",
                "seq_no": 1,
                "accepted": True,
            },
        )
    )
    with ShieldClient("http://srv") as c:
        got = c.decide(rec)
        assert got.decision is Decision.PASS
        c.submit(rec)  # no raise == Channel-2 accepted (202)
