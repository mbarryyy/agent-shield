"""The eval arms and how each pipeline is *assembled* (the load-bearing ~60 LOC).

ADR-0005 / C9 (code-verified at AgentDojo HEAD 18b501a): the
``--defense agent_shield --module-to-load`` CLI path is **non-functional**
(``DEFENSES`` is a static literal bound by ``click.Choice`` at import; there is
no ``register_defense`` hook; ``from_config`` raises ``ValueError`` on an
unknown defense). So we never go through that CLI. We construct pipelines
directly via the public ``AgentPipeline.from_config(PipelineConfig(...))``,
which also sets a distinct ``pipeline.name`` per arm (result-cache isolation —
``benchmark.py`` keys log dir + cache on ``agent_pipeline.name``).

W1 scope = the **native, zero-Shield** arms (bankable immediately, the fallback
that keeps the thesis if Layer-2 slips):

* ``A0``    — no defense (``defense=None``): the true ungoverned baseline.
* ``A0b``   — the 4 AgentDojo built-in defenses we must measurably beat:
              ``transformers_pi_detector`` · ``spotlighting_with_delimiting`` ·
              ``repeat_user_prompt`` · ``tool_filter``.

``A1``/``A2``/``A3`` (Shield Free / Paid / deterministic-only) are wired W2→W3
by sdk/governance builders and are *not* part of this skeleton — requesting
them here returns ``ArmUnavailable`` so the runner SKIPs (never fakes) them.

Honest positioning (locked): all comparisons here are scoped to "beat the 4
AgentDojo built-in baselines + the Axis-C governance moat" — never "beat SOTA".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentdojo.agent_pipeline import AgentPipeline, PipelineConfig
from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement

# A0b: the exact 4 built-ins from agentdojo/agent_pipeline/agent_pipeline.py:DEFENSES.
NATIVE_BASELINES: tuple[str, ...] = (
    "transformers_pi_detector",
    "spotlighting_with_delimiting",
    "repeat_user_prompt",
    "tool_filter",
)

# Built-ins that need a heavy/incompatible backend and are therefore N/A under
# the offline MockedLLM (only runnable in the real-model eval.yml, W4/W5):
#   * transformers_pi_detector → needs agentdojo[transformers] (torch + a HF
#     model download); even *constructing* the arm triggers the download.
#   * tool_filter → from_config raises ValueError unless the llm is an OpenAILLM.
_MOCK_INCOMPATIBLE: dict[str, str] = {
    "transformers_pi_detector": (
        "needs agentdojo[transformers] (torch + HF model) — real-model eval only"
    ),
    "tool_filter": "from_config restricts tool_filter to OpenAI models — real-model eval only",
}

# Arms whose enforcement is owned by sdk/governance builders (W2→W3).
_SHIELD_ARMS = {"A1", "A2", "A3", "shielded"}


class ArmUnavailable(RuntimeError):
    """Raised when a requested arm cannot run in this phase/backend (SKIP, not FAIL)."""


@dataclass(frozen=True)
class Arm:
    """One A/B condition. ``defense=None`` ⇒ A0; otherwise an A0b built-in."""

    key: str
    defense: str | None

    def build(self, llm: BasePipelineElement | str, *, mock: bool) -> AgentPipeline:
        """Assemble the real pipeline via ``AgentPipeline.from_config``.

        ``from_config`` sets ``pipeline.name`` to ``llm_name`` (A0) or
        ``f"{llm_name}-{defense}"`` (A0b) — the per-arm distinct name the
        result cache needs.
        """
        if self.defense is not None and mock and self.defense in _MOCK_INCOMPATIBLE:
            raise ArmUnavailable(f"{self.key} ({self.defense}): {_MOCK_INCOMPATIBLE[self.defense]}")
        config = PipelineConfig(
            llm=llm,
            model_id=None,
            defense=self.defense,
            system_message_name=None,
            system_message=None,
        )
        try:
            return AgentPipeline.from_config(config)
        except ValueError as e:  # e.g. tool_filter on a non-OpenAI llm
            raise ArmUnavailable(f"{self.key} ({self.defense}): {e}") from e


def resolve_arms(requested: list[str]) -> list[Arm]:
    """Map CLI/assert arm tokens to concrete native arms (W1 = A0 + A0b only).

    Accepts: ``A0``/``baseline``, ``A0b`` (expands to the 4 built-ins), an
    individual built-in name, or ``all``. Shield arms raise ``ArmUnavailable``.
    """
    out: list[Arm] = []
    seen: set[str] = set()

    def _add(key: str, defense: str | None) -> None:
        if key not in seen:
            seen.add(key)
            out.append(Arm(key=key, defense=defense))

    tokens = requested or ["A0", "A0b"]
    for tok in tokens:
        t = tok.strip()
        if t in _SHIELD_ARMS:
            raise ArmUnavailable(
                f"{t}: Shield arm wired W2→W3 (sdk/governance) — not in the W1 skeleton"
            )
        if t in ("A0", "baseline", "none"):
            _add("A0", None)
        elif t in ("A0b", "baselines", "all"):
            for d in NATIVE_BASELINES:
                _add(d, d)
        elif t in NATIVE_BASELINES:
            _add(t, t)
        else:
            raise ArmUnavailable(
                f"{t}: unknown arm (expected A0|A0b|baseline|{'|'.join(NATIVE_BASELINES)})"
            )
    return out


def arm_alias(arm_key: str) -> set[str]:
    """Assertion-token aliases an arm answers to (e.g. A0 also answers 'baseline')."""
    if arm_key == "A0":
        return {"A0", "baseline", "none"}
    return {arm_key}


def ground_truth_calls(task: Any, env: Any) -> list[Any]:
    """Thin helper kept for symmetry/tests: a task's scripted tool calls."""
    return list(task.ground_truth(env))
