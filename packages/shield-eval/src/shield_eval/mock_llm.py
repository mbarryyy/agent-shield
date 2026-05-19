"""Deterministic, key-free ``MockedLLM`` for offline CI / PR runs.

Replays a task's own AgentDojo ``ground_truth`` as the agent's tool-call
transcript (no fabricated transcripts — §5b: every call comes from AgentDojo's
own task definitions at the pinned HEAD ``18b501a``). It is a faithful
``BasePipelineElement`` LLM substitute, so ``AgentPipeline.from_config`` builds
the *real* A0 / A0b native pipelines around it unchanged.

Vulnerable-baseline model: when the agent observes the ``important_instructions``
injection marker (``<INFORMATION>`` — verified verbatim in
``agentdojo/attacks/important_instructions_attacks.py``) inside a tool result,
the mock *follows it* by also replaying the injection task's ``ground_truth``.
That makes the undefended baseline (A0) genuinely fail ``InjectionTask6`` via
AgentDojo's own ``security()`` oracle — the bankable "single-call defenses are
defeated by 3×$10k structuring" result, auto-scored, never cherry-picked.

NOTE (honest scope): MockedLLM produces a *deterministic transcript*, not a
measured model. It proves the A0/A0b plumbing + oracle scoring offline. Real,
quotable ASR/utility come from real models via ``eval.yml`` (W4/W5). Numbers
from this mock are labelled as such and are never reported as measured ASR.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.functions_runtime import EmptyEnv, Env, FunctionsRuntime
from agentdojo.types import (
    ChatAssistantMessage,
    ChatMessage,
    get_text_content_as_str,
    text_content_block_from_string,
)

# Verbatim from agentdojo/attacks/important_instructions_attacks.py:_JB_STRING
# (HEAD 18b501a). The injected block is wrapped in <INFORMATION> ... </INFORMATION>.
INJECTION_MARKER = "<INFORMATION>"


# agentdojo is an untyped dependency (mypy: ignore_missing_imports) so its
# BasePipelineElement is `Any`; subclassing-Any is intentional here.
class MockedLLM(BasePipelineElement):  # type: ignore[misc]
    """An LLM-shaped pipeline element that replays AgentDojo ground truth.

    Args:
        name: pipeline-naming seed. ``AgentPipeline.from_config`` reads
            ``llm.name`` to key the per-arm ``pipeline.name`` (result-cache
            isolation across the 5 arms).
        user_task: the bound user task whose ``ground_truth`` is the benign
            transcript.
        injection_task: the bound injection task; its ``ground_truth`` is
            replayed *additionally* once the injection is observed (vulnerable
            baseline), or *directly* when the prompt is the injection GOAL
            (AgentDojo's "injection-as-user-task" achievability sanity).
        final_text: terminal assistant message that ends the tools loop.
    """

    def __init__(
        self,
        name: str = "mocked",
        user_task: Any | None = None,
        injection_task: Any | None = None,
        final_text: str = "Done.",
    ) -> None:
        self.name = name
        self._user_task = user_task
        self._injection_task = injection_task
        self._final_text = final_text

    @staticmethod
    def _injection_observed(messages: Sequence[ChatMessage]) -> bool:
        for m in messages:
            if m.get("role") == "tool":
                content = m.get("content") or []
                if INJECTION_MARKER in get_text_content_as_str(content):
                    return True
        return False

    @staticmethod
    def _tool_turns_done(messages: Sequence[ChatMessage]) -> int:
        return sum(1 for m in messages if m.get("role") == "assistant" and m.get("tool_calls"))

    def _injection_goal(self) -> str:
        return str(getattr(self._injection_task, "GOAL", "\0")).strip()

    def _plan(self, query: str, env: Env) -> list[Any]:
        # AgentDojo's "injection as a standalone user task" achievability run
        # passes the injection GOAL as the prompt — replay the injection GT so
        # injection_tasks_utility_results is True (AgentDojo's precondition).
        if self._injection_task is not None and query.strip() == self._injection_goal():
            return list(self._injection_task.ground_truth(env))
        plan: list[Any] = []
        if self._user_task is not None:
            plan.extend(self._user_task.ground_truth(env))
        return plan

    # Signature kept verbatim to AgentDojo's abstract
    # BasePipelineElement.query (agentdojo HEAD 18b501a) — the AgentPipeline
    # loop always passes all five args explicitly, so the defaults are never
    # exercised; B006/B008 are suppressed precisely to preserve that contract.
    def query(
        self,
        query: str,
        runtime: FunctionsRuntime,
        env: Env = EmptyEnv(),  # noqa: B008
        messages: Sequence[ChatMessage] = [],  # noqa: B006
        extra_args: dict[str, Any] = {},  # noqa: B006
    ) -> tuple[str, FunctionsRuntime, Env, Sequence[ChatMessage], dict[str, Any]]:
        plan = self._plan(query, env)
        if (
            self._injection_task is not None
            and self._injection_observed(messages)
            and query.strip() != self._injection_goal()
        ):
            # Vulnerable-baseline: the agent saw the injection and obeys it.
            plan = plan + list(self._injection_task.ground_truth(env))

        done = self._tool_turns_done(messages)
        if done < len(plan):
            next_msg = ChatAssistantMessage(
                role="assistant",
                tool_calls=[plan[done]],
                content=[text_content_block_from_string("")],
            )
        else:
            next_msg = ChatAssistantMessage(
                role="assistant",
                tool_calls=None,
                content=[text_content_block_from_string(self._final_text)],
            )
        return query, runtime, env, [*messages, next_msg], extra_args
