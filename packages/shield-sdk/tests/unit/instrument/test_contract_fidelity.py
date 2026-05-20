"""Module C contract-fidelity tests for Layer-1 enforcement behavior."""

from __future__ import annotations

import time
from typing import Any

from agentdojo.functions_runtime import FunctionCall, TaskEnvironment
from shield_sdk import crypto
from shield_sdk.instrument.agentdojo import ShieldElementConfig, build_shield_elements
from shield_sdk.schema import (
    Decision,
    GovernanceVerdict,
    Obligations,
    RollbackObligation,
    ShieldActionRecord,
)

_PRIV = crypto.base64url_encode(bytes(range(32)))


class _FakeClient:
    def __init__(self, decide_fn: Any) -> None:
        self._decide_fn = decide_fn
        self.submitted: list[ShieldActionRecord] = []

    def decide(self, record: ShieldActionRecord) -> GovernanceVerdict:
        return self._decide_fn(record)  # type: ignore[no-any-return]

    def submit(self, record: ShieldActionRecord) -> None:
        self.submitted.append(record)


class _Fn:
    def __init__(self, name: str) -> None:
        self.name = name


class _Runtime:
    def __init__(self, names: list[str]) -> None:
        self.functions = {name: _Fn(name) for name in names}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run_function(self, env: Any, function: str, kwargs: Any) -> tuple[Any, str | None]:
        self.calls.append((function, dict(kwargs)))
        return {"ok": function, "args": dict(kwargs)}, None


class _Env(TaskEnvironment):
    balance: float = 100.0


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
        client=client,
        agent_private_key_b64url=_PRIV,
        run_id="run-contract-fidelity",
        **kw,
    )


def _run(
    cfg: ShieldElementConfig, runtime: Any, env: Any, calls: list[FunctionCall]
) -> tuple[Any, list[dict[str, Any]], dict[str, Any]]:
    guard, executor, recorder = build_shield_elements(cfg)
    extra: dict[str, Any] = {}
    messages: Any = _assistant(calls)
    _, _, env, messages, extra = guard.query("q", runtime, env, messages, extra)
    _, _, env, messages, extra = executor.query("q", runtime, env, messages, extra)
    _, _, env, messages, extra = recorder.query("q", runtime, env, messages, extra)
    return env, messages, extra


def test_rewrite_executes_and_records_sanitized_args() -> None:
    obligations = Obligations(
        rewrite_args={"recipient": "SAFE-IBAN", "amount": 1.0, "subject": "clean"}
    )
    client = _FakeClient(_verdict(Decision.REWRITE, obligations=obligations))
    runtime = _Runtime(["send_money"])

    _run(
        _cfg(client),
        runtime,
        TaskEnvironment(),
        [
            FunctionCall(
                function="send_money",
                args={"recipient": "ATTACKER-IBAN", "amount": 30000.0, "subject": "leak"},
                id="call-rewrite",
            )
        ],
    )

    sanitized = {"recipient": "SAFE-IBAN", "amount": 1.0, "subject": "clean"}
    assert runtime.calls == [("send_money", sanitized)]
    assert client.submitted[0].payload.tool_args == sanitized


def test_escalate_live_hitl_seam_can_approve_execution() -> None:
    hitl_calls: list[tuple[str, str, dict[str, Any]]] = []

    def approve(
        verdict: GovernanceVerdict, pre_record: ShieldActionRecord, tool_args: dict[str, Any]
    ) -> bool:
        hitl_calls.append((pre_record.payload.tool_name or "", verdict.decision.value, tool_args))
        return True

    runtime = _Runtime(["send_money"])
    _, _, extra = _run(
        _cfg(
            _FakeClient(_verdict(Decision.ESCALATE)),
            escalate_mode="live",
            escalation_handler=approve,
        ),
        runtime,
        TaskEnvironment(),
        [FunctionCall(function="send_money", args={"amount": 10.0}, id="call-hitl")],
    )

    assert runtime.calls == [("send_money", {"amount": 10.0})]
    assert hitl_calls == [("send_money", "ESCALATE", {"amount": 10.0})]
    assert extra["shield"]["_hitl_signals"] == [
        {
            "record_id": extra["shield"]["decisions"]["call-hitl"].pre_record.record_id,
            "correlation_id": extra["shield"]["decisions"]["call-hitl"].pre_record.correlation_id,
            "approved": True,
        }
    ]


def test_rollback_invokes_env_and_langgraph_checkpoint_hooks() -> None:
    env_hook_calls: list[tuple[str | None, float]] = []
    checkpoint_hook_calls: list[tuple[str | None, str | None, str]] = []

    def env_hook(env_snapshot_ref: str | None, restored_env: Any) -> None:
        env_hook_calls.append((env_snapshot_ref, restored_env.balance))

    def checkpoint_hook(
        langgraph_thread_id: str | None,
        langgraph_checkpoint_id: str | None,
        verdict: GovernanceVerdict,
    ) -> None:
        checkpoint_hook_calls.append(
            (langgraph_thread_id, langgraph_checkpoint_id, verdict.decision.value)
        )

    obligations = Obligations(
        rollback=RollbackObligation(langgraph_checkpoint_id="ckpt-7")
    )
    out_env, _, extra = _run(
        _cfg(
            _FakeClient(_verdict(Decision.ROLLBACK, obligations=obligations)),
            langgraph_thread_id="thread-7",
            env_restore_hook=env_hook,
            langgraph_checkpoint_hook=checkpoint_hook,
        ),
        _Runtime(["send_money"]),
        _Env(),
        [FunctionCall(function="send_money", args={"amount": 50.0}, id="call-rollback")],
    )

    pre = extra["shield"]["decisions"]["call-rollback"].pre_record
    assert out_env.balance == 100.0
    assert env_hook_calls == [(pre.context.env_snapshot_ref, 100.0)]
    assert checkpoint_hook_calls == [("thread-7", "ckpt-7", "ROLLBACK")]


def test_decision_failure_detail_is_sanitized() -> None:
    secret_bits = ["ATTACKER-IBAN", "TOKEN_VALUE_SHOULD_NOT_APPEAR", "subject=private"]

    def fail(_record: ShieldActionRecord) -> GovernanceVerdict:
        raise RuntimeError(
            "recipient=ATTACKER-IBAN token=TOKEN_VALUE_SHOULD_NOT_APPEAR subject=private"
        )

    _, _, extra = _run(
        _cfg(_FakeClient(fail), decision_budget_ms=50),
        _Runtime(["send_money"]),
        TaskEnvironment(),
        [FunctionCall(function="send_money", args={"amount": 1.0}, id="call-fail")],
    )

    detail = extra["shield"]["decisions"]["call-fail"].verdict.reasons[0].detail or ""
    assert "RuntimeError" in detail
    for secret in secret_bits:
        assert secret not in detail


def test_fail_policy_closed_tools_timeout_to_block_and_low_risk_opens() -> None:
    def slow(_record: ShieldActionRecord) -> GovernanceVerdict:
        time.sleep(0.2)
        return GovernanceVerdict(correlation_id="late", decision=Decision.PASS)

    high_risk = ["send_money", "update_password", "update_scheduled_transaction"]
    for tool_name in high_risk:
        runtime = _Runtime([tool_name])
        _run(
            _cfg(_FakeClient(slow), decision_budget_ms=10),
            runtime,
            TaskEnvironment(),
            [FunctionCall(function=tool_name, args={}, id=tool_name)],
        )
        assert runtime.calls == []

    low_risk_runtime = _Runtime(["get_balance"])
    _run(
        _cfg(_FakeClient(slow), decision_budget_ms=10),
        low_risk_runtime,
        TaskEnvironment(),
        [FunctionCall(function="get_balance", args={}, id="get_balance")],
    )
    assert low_risk_runtime.calls == [("get_balance", {})]
