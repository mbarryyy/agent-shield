"""W3 contract tests — U1 dual-substrate ROLLBACK wiring + U2 REWRITE /
cost-field fidelity locks. Self-contained (no cross-test imports).

U1: pre_exec carries context.{env_snapshot_ref=record_id, langgraph_thread_id};
ROLLBACK fires BOTH substrates (Layer-1 env restore + the structured Layer-2
signal, even when the verdict's obligations.rollback is None/partial).
U2: REWRITE arg-mutation edge cases + GovernanceVerdict cost fields
(reasons[].{model_id,served_via}, obligations.prevented_loss) round-trip
byte-faithfully (the "ALREADY in frozen v1.1, W3 only wires" guarantee).
"""

from __future__ import annotations

from typing import Any

import httpx
import respx
from agentdojo.agent_pipeline.tool_execution import ToolsExecutionLoop
from agentdojo.functions_runtime import FunctionCall, TaskEnvironment
from shield_sdk import crypto
from shield_sdk.instrument.agentdojo import (
    ShieldElementConfig,
    build_shield_elements,
    shield_loop_elements,
)
from shield_sdk.schema import (
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
from shield_sdk.sdk import ShieldClient

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


class _Rt:
    def __init__(self, names: list[str]) -> None:
        self.functions = {n: _Fn(n) for n in names}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run_function(self, env: Any, fn: str, kw: Any) -> tuple[Any, str | None]:
        self.calls.append((fn, dict(kw)))
        return {"ok": fn}, None


def _verdict(decision: Decision, **kw: Any) -> Any:
    def _fn(rec: ShieldActionRecord) -> GovernanceVerdict:
        return GovernanceVerdict(
            record_id=rec.record_id,
            correlation_id=rec.correlation_id,
            run_id=rec.run_id,
            decision=decision,
            **kw,
        )

    return _fn


def _assistant(calls: list[FunctionCall]) -> list[dict[str, Any]]:
    return [{"role": "assistant", "content": None, "tool_calls": calls}]


def _cfg(client: Any, **kw: Any) -> ShieldElementConfig:
    return ShieldElementConfig(client=client, agent_private_key_b64url=_PRIV, run_id="run-w3", **kw)


def _run(cfg: ShieldElementConfig, rt: Any, env: Any, calls: list[FunctionCall]) -> Any:
    guard, ex, rec = build_shield_elements(cfg)
    extra: dict[str, Any] = {}
    msgs: Any = _assistant(calls)
    _, _, env, msgs, extra = guard.query("q", rt, env, msgs, extra)
    _, _, env, msgs, extra = ex.query("q", rt, env, msgs, extra)
    _, _, env, msgs, extra = rec.query("q", rt, env, msgs, extra)
    return env, msgs, extra


# ---- U1: context wiring -------------------------------------------------- #


def test_pre_exec_context_env_snapshot_ref_equals_record_id() -> None:
    cfg = _cfg(_FakeClient(_verdict(Decision.PASS)), langgraph_thread_id="thr_42")
    _, _, extra = _run(
        cfg, _Rt(["t"]), TaskEnvironment(), [FunctionCall(function="t", args={}, id="c")]
    )
    pre = extra["shield"]["decisions"]["c"].pre_record
    assert pre.context.env_snapshot_ref == pre.record_id  # Layer-1-owned key
    assert pre.context.langgraph_thread_id == "thr_42"  # SDK stamps Layer-2 thread
    assert pre.context.checkpoint_id is None  # governance owns/actuates


def test_langgraph_thread_id_defaults_none_when_not_configured() -> None:
    cfg = _cfg(_FakeClient(_verdict(Decision.PASS)))
    _, _, extra = _run(
        cfg, _Rt(["t"]), TaskEnvironment(), [FunctionCall(function="t", args={}, id="c")]
    )
    assert extra["shield"]["decisions"]["c"].pre_record.context.langgraph_thread_id is None


# ---- U1: dual-substrate ROLLBACK (BOTH fire) ----------------------------- #


class _Env(TaskEnvironment):
    balance: float = 100.0


def test_rollback_fires_both_substrates_with_full_obligation() -> None:
    obl = Obligations(
        rollback=RollbackObligation(
            langgraph_checkpoint_id="ckpt_99", env_snapshot_ref="ignored-by-l1"
        )
    )
    cfg = _cfg(
        _FakeClient(_verdict(Decision.ROLLBACK, obligations=obl)), langgraph_thread_id="thr_7"
    )
    env = _Env()
    rt = _Rt(["send_money"])
    out_env, msgs, extra = _run(
        cfg, rt, env, [FunctionCall(function="send_money", args={"amount": 50.0}, id="c")]
    )
    assert rt.calls == []  # ROLLBACK skips :103
    assert out_env.balance == 100.0  # Layer-1 substrate: env restored
    sig = extra["shield"]["_rollback_signals"]
    assert len(sig) == 1
    s = sig[0]
    pre = extra["shield"]["decisions"]["c"].pre_record
    assert s["env_snapshot_ref"] == pre.record_id  # Layer-1 key
    assert s["layer1_env_restored"] is True
    assert s["langgraph_thread_id"] == "thr_7"  # Layer-2 correlation
    assert s["langgraph_checkpoint_id"] == "ckpt_99"  # Layer-2 rewind target (gov)
    assert any("Rolled back" in (m.get("error") or "") for m in msgs)


def test_rollback_signal_emitted_even_when_obligation_is_none() -> None:
    cfg = _cfg(_FakeClient(_verdict(Decision.ROLLBACK)))  # no obligations.rollback
    rt = _Rt(["send_money"])
    out_env, _, extra = _run(
        cfg, rt, _Env(), [FunctionCall(function="send_money", args={"amount": 9.0}, id="c")]
    )
    s = extra["shield"]["_rollback_signals"][0]
    assert s["layer1_env_restored"] is True  # Layer-1 still fires
    assert s["langgraph_checkpoint_id"] is None  # gov emitted no target
    assert s["env_snapshot_ref"] == extra["shield"]["decisions"]["c"].pre_record.record_id


# ---- U2: REWRITE arg-mutation edges -------------------------------------- #


def test_rewrite_with_args_replaces_in_place() -> None:
    obl = Obligations(rewrite_args={"recipient": "SAFE", "amount": 1.0})
    cfg = _cfg(_FakeClient(_verdict(Decision.REWRITE, obligations=obl)))
    rt = _Rt(["send_money"])
    _run(
        cfg,
        rt,
        TaskEnvironment(),
        [FunctionCall(function="send_money", args={"recipient": "BAD", "amount": 9e9}, id="c")],
    )
    assert rt.calls == [("send_money", {"recipient": "SAFE", "amount": 1.0})]


def test_rewrite_with_none_args_runs_original() -> None:
    cfg = _cfg(_FakeClient(_verdict(Decision.REWRITE, obligations=Obligations())))
    rt = _Rt(["send_money"])
    _run(
        cfg,
        rt,
        TaskEnvironment(),
        [FunctionCall(function="send_money", args={"amount": 5.0}, id="c")],
    )
    assert rt.calls == [("send_money", {"amount": 5.0})]  # no rewrite_args -> original


def test_rewrite_then_mask_args_redacts_after_rewrite() -> None:
    obl = Obligations(
        rewrite_args={"amount": 1.0, "subject": "leaked"},
        mask_args=["payload.tool_args.subject"],
    )
    cfg = _cfg(_FakeClient(_verdict(Decision.REWRITE, obligations=obl)))
    rt = _Rt(["send_money"])
    _run(
        cfg,
        rt,
        TaskEnvironment(),
        [FunctionCall(function="send_money", args={"amount": 9.0, "subject": "x"}, id="c")],
    )
    assert rt.calls[0][1] == {"amount": 1.0, "subject": "***REDACTED***"}


# ---- U2: cost-field fidelity (frozen v1.1; W3 only wires, no schema change) #


def test_cost_fields_round_trip_through_decision() -> None:
    obl = Obligations(prevented_loss=30000.0)
    reasons = [
        VerdictReason(
            agent=Guardian.DEFENDER,
            label="STRUCTURING",
            model_id="claude-sonnet",
            served_via=ServedVia.CLOUD,
        ),
        VerdictReason(
            agent=Guardian.EVALUATOR,
            label="CUMULATIVE",
            model_id="qwen2.5-32b",
            served_via=ServedVia.LOCAL,
        ),
    ]
    cfg = _cfg(_FakeClient(_verdict(Decision.BLOCK, obligations=obl, reasons=reasons)))
    _, _, extra = _run(
        cfg,
        _Rt(["send_money"]),
        TaskEnvironment(),
        [FunctionCall(function="send_money", args={"amount": 3e4}, id="c")],
    )
    v = extra["shield"]["decisions"]["c"].verdict
    assert v.obligations.prevented_loss == 30000.0
    assert [r.model_id for r in v.reasons] == ["claude-sonnet", "qwen2.5-32b"]
    assert [r.served_via for r in v.reasons] == [ServedVia.CLOUD, ServedVia.LOCAL]


@respx.mock
def test_cost_fields_survive_real_client_http_decode() -> None:
    verdict = GovernanceVerdict(
        correlation_id="c",
        decision=Decision.ROLLBACK,
        reasons=[
            VerdictReason(
                agent=Guardian.SUPERVISOR,
                label="L",
                model_id="m",
                served_via=ServedVia.LOCAL,
            )
        ],
        obligations=Obligations(prevented_loss=12345.67),
    )
    respx.post("http://srv/v1/governance/decide").mock(
        return_value=httpx.Response(200, json=verdict.model_dump(mode="json"))
    )
    with ShieldClient("http://srv") as c:
        got = c.decide(ShieldActionRecord(phase=Phase.PRE_EXEC, run_id="x"))
    assert got.obligations.prevented_loss == 12345.67
    assert got.reasons[0].model_id == "m"
    assert got.reasons[0].served_via is ServedVia.LOCAL


# ---- SEAM-#3: canonical ToolsExecutionLoop order (no double-generate) ----- #


class _MockLLM:
    """A terminal LLM element: appends one assistant message with NO
    tool_calls so the real ToolsExecutionLoop breaks after processing."""

    name = "mock_llm"

    def __init__(self) -> None:
        self.calls = 0

    def query(
        self, q: str, rt: Any, env: Any, msgs: Any, extra: Any
    ) -> tuple[str, Any, Any, Any, Any]:
        self.calls += 1
        terminal = {"role": "assistant", "content": [], "tool_calls": None}
        return q, rt, env, [*msgs, terminal], extra


def _drive_loop(cfg: ShieldElementConfig, rt: Any, env: Any, tc: FunctionCall) -> tuple[Any, Any]:
    llm = _MockLLM()
    loop = ToolsExecutionLoop(shield_loop_elements(cfg, llm))
    msgs: Any = [{"role": "assistant", "content": None, "tool_calls": [tc]}]
    _, _, env, msgs, _ = loop.query("q", rt, env, msgs, {})
    return (msgs, llm), env


def test_canonical_order_processes_pending_call_exactly_once() -> None:
    """Real ToolsExecutionLoop @ the canonical order: the pre-loop
    assistant+tool_calls is executed exactly once (no double-generate, not
    skipped) and the loop terminates."""
    rt = _Rt(["send_money"])
    cfg = _cfg(_FakeClient(_verdict(Decision.PASS)))
    (msgs, llm), _ = _drive_loop(
        cfg,
        rt,
        TaskEnvironment(),
        FunctionCall(function="send_money", args={"amount": 5.0}, id="c"),
    )
    assert rt.calls == [("send_money", {"amount": 5.0})]  # exactly once
    assert llm.calls == 1  # llm generated AFTER processing (process-then-generate)
    roles = [m["role"] for m in msgs]
    assert roles == ["assistant", "tool", "assistant"]  # no double-generate


def test_canonical_order_enforces_before_execute_and_terminates() -> None:
    """BLOCK consulted BEFORE the executor's money-line: tool never runs, a
    synthesized result is emitted, loop still terminates via the llm."""
    rt = _Rt(["send_money"])
    cfg = _cfg(_FakeClient(_verdict(Decision.BLOCK)))
    (msgs, llm), _ = _drive_loop(
        cfg,
        rt,
        TaskEnvironment(),
        FunctionCall(function="send_money", args={"amount": 30000.0}, id="c"),
    )
    assert rt.calls == []  # ShieldGuard verdict enforced before :103
    assert any("Agent Shield: Blocked" in (m.get("error") or "") for m in msgs)
    assert llm.calls == 1 and [m["role"] for m in msgs][-1] == "assistant"
