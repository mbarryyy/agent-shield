"""AgentDojo Shield elements — the two-phase gate (code-verified rev 18b501a).

Three `BasePipelineElement`s dropped into `ToolsExecutionLoop.elements`
(constructor `tool_execution.py:130-132`, iterated `:154-155`):

  * ``ShieldGuard``           — BEFORE ``ToolsExecutor``: builds+signs the
    ``pre_exec`` record, snapshots ``env.model_copy(deep=True)``, calls
    ``POST /v1/governance/decide`` under the 500 ms ``concurrent.futures``
    budget + per-tool fail policy, writes the verdict into
    ``extra_args["shield"]``.
  * ``ShieldedToolsExecutor`` — replaces stock ``ToolsExecutor``: enforces the
    §4.2 decision table immediately before the money-line
    ``tool_execution.py:103`` using the in-repo skip-and-synthesize precedent
    (``:75-96``). PASS/ALERT/REWRITE → run; BLOCK/ESCALATE/ROLLBACK →
    skip+synthesize; ROLLBACK additionally restores the Layer-1
    ``env.model_copy`` snapshot.
  * ``ShieldRecorder``        — AFTER ``ToolsExecutor``: builds+signs the
    ``post_exec`` record (real result/error, ``verdict_ref``, paired by
    ``correlation_id``) and submits it on Channel-2 (best-effort, async).

`extra_args["shield"]` is the in-pipeline bus — element-internal ONLY. The
server never sees ``extra_args``; the sole server coupling is the FROZEN §4
HTTP body (``ShieldActionRecord``) / response (``GovernanceVerdict``).
"""

from __future__ import annotations

import contextlib
import dataclasses
from ast import literal_eval
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.agent_pipeline.llms.google_llm import EMPTY_FUNCTION_NAME
from agentdojo.agent_pipeline.tool_execution import ToolsExecutor, is_string_list
from agentdojo.functions_runtime import EmptyEnv
from agentdojo.types import ChatToolResultMessage, text_content_block_from_string

from ...canonical import derive_chain_hash, finalize_record
from ...crypto import GENESIS_CHAIN_HASH, generate_uuidv7, jcs_canonicalize, sha256_base64url
from ...policy import FailMode, FailPolicy, synthetic_degraded_verdict
from ...schema import (
    ActionContext,
    ActionPayload,
    ActionRef,
    ActionType,
    Decision,
    GovernanceVerdict,
    Phase,
    ShieldActionRecord,
)
from ...sdk import ShieldClient

_EMPTY_ENV = EmptyEnv()


@dataclasses.dataclass
class ShieldElementConfig:
    """Wiring shared by the three elements (the eval custom runner builds it)."""

    client: ShieldClient
    agent_private_key_b64url: str
    agent_pubkey_kid: str = "agentdojo-banking-v1-key-v1"
    org_id: str = "demo-org"
    agent_id: str = "agentdojo-banking-v1"
    workflow_id: str = "banking"
    run_id: str | None = None
    # W3 dual-substrate ROLLBACK (C2): the Layer-2-owned LangGraph thread for
    # this run. The SDK only STAMPS it onto context.langgraph_thread_id so the
    # signed chain carries the rewind correlation key; governance OWNS/actuates
    # the checkpointer rewind and emits obligations.rollback.langgraph_checkpoint_id.
    langgraph_thread_id: str | None = None
    decision_budget_ms: int = 500
    fail_policy: FailPolicy = dataclasses.field(default_factory=FailPolicy.ratified)
    # Non-interactive batch degradation for ESCALATE (live HITL interrupt() is
    # Layer-2/LangGraph, out of element scope). eval-builder owns the fixture.
    escalate_mode: Literal["block", "approve"] = "block"


@dataclasses.dataclass
class _ShieldDecision:
    key: str
    pre_record: ShieldActionRecord
    verdict: GovernanceVerdict
    env_snapshot: Any
    degraded: bool
    executed: bool = False
    result: Any = None
    error: str | None = None
    recorded: bool = False


def _tool_call_key(tool_call: Any, index: int) -> str:
    """Stable per-tool_call key shared by all three elements.

    `FunctionCall.id` is `str | None` (functions_runtime.py:48); fall back to a
    positional key so a None id never collides.
    """
    return tool_call.id if tool_call.id is not None else f"__shield_idx_{index}"


def _state(extra_args: dict[str, Any], cfg: ShieldElementConfig) -> dict[str, Any]:
    st = extra_args.get("shield")
    if st is None:
        run_id = cfg.run_id or extra_args.get("shield_run_id") or generate_uuidv7()
        st = {
            "decisions": {},
            "_chain_head": GENESIS_CHAIN_HASH,
            "_step": 0,
            "_run_id": run_id,
            "_rollback_signals": [],
        }
        extra_args["shield"] = st
    return st


def _next_step(state: dict[str, Any]) -> int:
    step = int(state["_step"])
    state["_step"] = step + 1
    return step


def _args_digest(args: dict[str, Any]) -> str:
    return "sha256:" + sha256_base64url(jcs_canonicalize(args))


def _is_assistant_with_tool_calls(messages: Sequence[Any]) -> bool:
    if len(messages) == 0:
        return False
    last = messages[-1]
    if last["role"] != "assistant":
        return False
    return bool(last["tool_calls"])


class ShieldGuard(BasePipelineElement):  # type: ignore[misc]  # agentdojo base is untyped
    """BEFORE ToolsExecutor: pre_exec record + snapshot + sync decide gate."""

    name = "shield_guard"

    def __init__(self, config: ShieldElementConfig) -> None:
        self.cfg = config
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="shield")

    def query(
        self,
        query: str,
        runtime: Any,
        env: Any = _EMPTY_ENV,
        messages: Sequence[Any] = (),
        extra_args: dict[str, Any] | None = None,
    ) -> tuple[str, Any, Any, Sequence[Any], dict[str, Any]]:
        extra_args = {} if extra_args is None else extra_args
        if not _is_assistant_with_tool_calls(messages):
            return query, runtime, env, messages, extra_args

        cfg = self.cfg
        state = _state(extra_args, cfg)
        budget_s = cfg.decision_budget_ms / 1000.0

        for idx, tc in enumerate(messages[-1]["tool_calls"]):
            key = _tool_call_key(tc, idx)
            args = dict(tc.args)
            rec_id = generate_uuidv7()
            pre = ShieldActionRecord(
                record_id=rec_id,
                correlation_id=generate_uuidv7(),
                org_id=cfg.org_id,
                agent_id=cfg.agent_id,
                workflow_id=cfg.workflow_id,
                run_id=state["_run_id"],
                step_index=_next_step(state),
                phase=Phase.PRE_EXEC,
                action_type=ActionType.TOOL_CALL,
                subject={"agentdojo_tool_call_id": tc.id},
                action=ActionRef(tool=tc.function, args_digest=_args_digest(args)),
                payload=ActionPayload(tool_name=tc.function, tool_args=args),
                # W3 dual-substrate ROLLBACK keys (C2 / §4.1 L149-153):
                #  - env_snapshot_ref = this record_id  -> Layer-1-owned key for
                #    the env.model_copy snapshot restored on ROLLBACK.
                #  - langgraph_thread_id -> Layer-2-owned thread (SDK stamps it
                #    so the signed chain carries the rewind correlation key).
                #  - checkpoint_id stays None: governance OWNS/actuates the
                #    LangGraph checkpointer rewind and emits the target via
                #    verdict.obligations.rollback.langgraph_checkpoint_id.
                context=ActionContext(
                    env_snapshot_ref=rec_id,
                    langgraph_thread_id=cfg.langgraph_thread_id,
                ),
                prev_chain_hash=state["_chain_head"],
                agent_pubkey_kid=cfg.agent_pubkey_kid,
            )
            pre = finalize_record(pre, cfg.agent_private_key_b64url)
            snapshot = env.model_copy(deep=True) if hasattr(env, "model_copy") else env

            degraded = False
            future = self._pool.submit(cfg.client.decide, pre)
            try:
                verdict = future.result(timeout=budget_s)
            except Exception as exc:  # noqa: BLE001 - timeout/any error => fail policy
                degraded = True
                mode: FailMode = cfg.fail_policy.fail_mode_for(tc.function)
                verdict = synthetic_degraded_verdict(
                    pre, mode, detail=f"{type(exc).__name__}: {exc}"
                )

            state["_chain_head"] = derive_chain_hash(state["_chain_head"], pre)
            state["decisions"][key] = _ShieldDecision(
                key=key,
                pre_record=pre,
                verdict=verdict,
                env_snapshot=snapshot,
                degraded=degraded,
            )

        return query, runtime, env, messages, extra_args


def _apply_mask_args(tool_args: Any, mask_args: list[str] | None) -> None:
    """Redact `payload.tool_args.<k>` paths in place before any execution."""
    if not mask_args:
        return
    prefix = "payload.tool_args."
    for path in mask_args:
        if path.startswith(prefix):
            k = path[len(prefix) :]
            if k in tool_args:
                tool_args[k] = "***REDACTED***"


def _coerce_string_lists(tool_args: Any) -> None:
    """AgentDojo tool_execution.py:98-101 parity for the run paths."""
    for arg_k, arg_v in list(tool_args.items()):
        if isinstance(arg_v, str) and is_string_list(arg_v):
            tool_args[arg_k] = literal_eval(arg_v)


class ShieldedToolsExecutor(ToolsExecutor):  # type: ignore[misc]  # agentdojo base is untyped
    """Replaces stock ToolsExecutor: enforce the §4.2 table before :103."""

    name = "shielded_tools_executor"

    def __init__(self, config: ShieldElementConfig, **kw: Any) -> None:
        super().__init__(**kw)
        self.cfg = config

    def query(
        self,
        query: str,
        runtime: Any,
        env: Any = _EMPTY_ENV,
        messages: Sequence[Any] = (),
        extra_args: dict[str, Any] | None = None,
    ) -> tuple[str, Any, Any, Sequence[Any], dict[str, Any]]:
        extra_args = {} if extra_args is None else extra_args
        if not _is_assistant_with_tool_calls(messages):
            return query, runtime, env, messages, extra_args

        st = extra_args.get("shield")
        decisions: dict[str, _ShieldDecision] = st["decisions"] if st else {}
        results: list[ChatToolResultMessage] = []
        out_env = env

        for idx, tc in enumerate(messages[-1]["tool_calls"]):
            # Stock guards, byte-faithful to tool_execution.py:75-96.
            if tc.function == EMPTY_FUNCTION_NAME:
                results.append(
                    ChatToolResultMessage(
                        role="tool",
                        content=[text_content_block_from_string("")],
                        tool_call_id=tc.id,
                        tool_call=tc,
                        error="Empty function name provided. Provide a valid function name.",
                    )
                )
                continue
            if tc.function not in (t.name for t in runtime.functions.values()):
                results.append(
                    ChatToolResultMessage(
                        role="tool",
                        content=[text_content_block_from_string("")],
                        tool_call_id=tc.id,
                        tool_call=tc,
                        error=f"Invalid tool {tc.function} provided.",
                    )
                )
                continue

            dec = decisions.get(_tool_call_key(tc, idx))
            verdict = dec.verdict if dec else None
            decision = verdict.decision if verdict else Decision.PASS
            obligations = verdict.obligations if verdict else None
            reason = ""
            if verdict and verdict.reasons:
                reason = verdict.reasons[0].label

            if decision in (Decision.PASS, Decision.ALERT) or (
                decision is Decision.ESCALATE and self.cfg.escalate_mode == "approve"
            ):
                run = True
            elif decision is Decision.REWRITE:
                if obligations and obligations.rewrite_args is not None:
                    tc.args.clear()
                    tc.args.update(obligations.rewrite_args)
                run = True
            else:  # BLOCK / ESCALATE(block) / ROLLBACK -> skip + synthesize
                run = False

            if run:
                if obligations:
                    _apply_mask_args(tc.args, obligations.mask_args)
                _coerce_string_lists(tc.args)
                tool_result, error = runtime.run_function(env, tc.function, tc.args)
                if dec:
                    dec.executed, dec.result, dec.error = True, tool_result, error
                results.append(
                    ChatToolResultMessage(
                        role="tool",
                        content=[
                            text_content_block_from_string(self.output_formatter(tool_result))
                        ],
                        tool_call_id=tc.id,
                        tool_call=tc,
                        error=error,
                    )
                )
                continue

            # skip + synthesize (the :75-96 precedent applied before :103)
            if decision is Decision.ROLLBACK:
                glyph, verb, outcome = "↩", "Rolled back", {"rolled_back": True}
                # Dual-substrate ROLLBACK (C2 / master §2.2 L134): BOTH fire.
                # (1) Layer-1-owned: restore the env.model_copy snapshot, keyed
                #     by the pre_exec record_id (= context.env_snapshot_ref).
                layer1_restored = False
                if dec is not None and hasattr(dec.env_snapshot, "model_copy"):
                    out_env = dec.env_snapshot.model_copy(deep=True)
                    layer1_restored = True
                # (2) Layer-2-owned: governance actuates the LangGraph
                #     checkpointer rewind; the SDK only carries the correlation
                #     keys + the gov-emitted target. ALWAYS record a structured
                #     dual-substrate signal (even if obligations.rollback is
                #     None/partial) so "both substrates fire" is auditable and
                #     eval/console can assert it.
                if st is not None and dec is not None:
                    ctx = dec.pre_record.context
                    ckpt = (
                        obligations.rollback.langgraph_checkpoint_id
                        if obligations and obligations.rollback is not None
                        else None
                    )
                    st["_rollback_signals"].append(
                        {
                            "record_id": dec.pre_record.record_id,
                            "correlation_id": dec.pre_record.correlation_id,
                            "env_snapshot_ref": ctx.env_snapshot_ref,
                            "layer1_env_restored": layer1_restored,
                            "langgraph_thread_id": ctx.langgraph_thread_id,
                            "langgraph_checkpoint_id": ckpt,
                        }
                    )
            elif decision is Decision.ESCALATE:
                glyph, verb, outcome = "🛑", "Escalated", {"escalated": True}
            else:
                glyph, verb, outcome = "🛑", "Blocked", {"blocked": True}

            msg = f"{glyph} Agent Shield: {verb} — {reason or decision.value}"
            if dec:
                dec.executed, dec.result, dec.error = False, outcome, msg
            results.append(
                ChatToolResultMessage(
                    role="tool",
                    content=[text_content_block_from_string("")],
                    tool_call_id=tc.id,
                    tool_call=tc,
                    error=msg,
                )
            )

        return query, runtime, out_env, [*messages, *results], extra_args


class ShieldRecorder(BasePipelineElement):  # type: ignore[misc]  # agentdojo base is untyped
    """AFTER ToolsExecutor: build+sign post_exec, submit on Channel-2."""

    name = "shield_recorder"

    def __init__(self, config: ShieldElementConfig) -> None:
        self.cfg = config

    def query(
        self,
        query: str,
        runtime: Any,
        env: Any = _EMPTY_ENV,
        messages: Sequence[Any] = (),
        extra_args: dict[str, Any] | None = None,
    ) -> tuple[str, Any, Any, Sequence[Any], dict[str, Any]]:
        extra_args = {} if extra_args is None else extra_args
        st = extra_args.get("shield")
        if not st:
            return query, runtime, env, messages, extra_args

        cfg = self.cfg
        for dec in st["decisions"].values():
            if dec.recorded:
                continue
            pre = dec.pre_record
            post = ShieldActionRecord(
                record_id=generate_uuidv7(),
                correlation_id=pre.correlation_id,  # pairs pre <-> post
                org_id=pre.org_id,
                agent_id=pre.agent_id,
                workflow_id=pre.workflow_id,
                run_id=pre.run_id,
                step_index=_next_step(st),
                phase=Phase.POST_EXEC,
                action_type=ActionType.TOOL_CALL,
                subject=dict(pre.subject),
                action=pre.action.model_copy(deep=True),
                payload=ActionPayload(
                    tool_name=pre.payload.tool_name,
                    tool_args=dict(pre.payload.tool_args),
                    tool_result=dec.result,
                    tool_error=dec.error,
                ),
                prev_chain_hash=st["_chain_head"],
                agent_pubkey_kid=pre.agent_pubkey_kid,
                verdict_ref=dec.verdict.verdict_id,
            )
            post = finalize_record(post, cfg.agent_private_key_b64url)
            st["_chain_head"] = derive_chain_hash(st["_chain_head"], post)
            # Channel-2 is async / at-least-once: a submit failure must never
            # crash the AgentDojo worker (post_exec is replayable).
            with contextlib.suppress(Exception):
                cfg.client.submit(post)
            dec.recorded = True

        return query, runtime, env, messages, extra_args


def build_shield_elements(
    config: ShieldElementConfig,
) -> tuple[ShieldGuard, ShieldedToolsExecutor, ShieldRecorder]:
    """The 3 elements in pipeline order: insert into ``ToolsExecutionLoop``
    as ``[..., LLM, ShieldGuard, ShieldedToolsExecutor, ShieldRecorder]``
    (ShieldGuard BEFORE the executor; ShieldRecorder AFTER it)."""
    return (
        ShieldGuard(config),
        ShieldedToolsExecutor(config),
        ShieldRecorder(config),
    )
