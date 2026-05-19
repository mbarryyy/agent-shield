"""The eval arms and how each pipeline is *assembled* (the load-bearing core).

ADR-0005 / C9 (code-verified at AgentDojo HEAD 18b501a): the
``--defense agent_shield --module-to-load`` CLI path is **non-functional**
(``DEFENSES`` is a static literal bound by ``click.Choice`` at import; there is
no ``register_defense`` hook; ``from_config`` raises ``ValueError`` on an
unknown defense). So we never go through that CLI. Native arms are constructed
via the public ``AgentPipeline.from_config(PipelineConfig(...))``, which also
sets a distinct ``pipeline.name`` per arm (result-cache isolation —
``benchmark.py`` keys log dir + cache on ``agent_pipeline.name``).

Native, zero-Shield arms (W1, bankable immediately — the fallback that keeps
the thesis if Layer-2 slips):

* ``A0``    — no defense (``defense=None``): the true ungoverned baseline.
* ``A0b``   — the 4 AgentDojo built-in defenses we must measurably beat:
              ``transformers_pi_detector`` · ``spotlighting_with_delimiting`` ·
              ``repeat_user_prompt`` · ``tool_filter``.

Shield arms (W2 wiring; the enforcement element is sdk-builder's module):

* ``A1``    — Shield installed, ``/decide`` → ``PASS`` (Free no-op gate).
* ``A2``    — Shield installed, ``/decide`` → real verdict (``mock`` fallback
              or the live ``http`` server). ``shielded`` is an alias for A2.
* ``A3``    — Shield installed, deterministic-only (rules, no LLM) ablation.

The Shield pipeline elements (``ShieldGuard`` / ``ShieldedToolsExecutor`` /
``ShieldRecorder``) are **sdk-builder's** module
(``shield_sdk.instrument.agentdojo``); eval imports them, never redeclares
them. Until sdk-w2 merges they are absent from ``main`` → the Shield arms
raise ``ArmUnavailable`` so the runner **SKIPs (never fakes)** them. The
``/decide`` source and the ESCALATE-degradation policy are eval-owned
(``decide.py`` / ``enforcement.py``) and fully tested standalone now, so the
arms switch in cleanly the moment sdk-w2 lands (dependency order sdk→…→eval).

Honest positioning (locked): comparisons are scoped to "beat the 4 AgentDojo
built-in baselines + the Axis-C governance moat" — never "beat SOTA".
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

# Shield arm → conceptual /decide endpoint (reporting + W3 wiring). A1 Free =
# the server stub /decide returns PASS; A2 Paid = real Layer-2 (or the
# eval-owned mock fallback served over HTTP); A3 = deterministic-only. Per the
# CANONICAL sdk contract (PR #11), A1 vs A2 is *where ShieldClient points* —
# ZERO element changes — so this is a label/wiring hint, not injected logic.
_SHIELD_DECIDE: dict[str, str] = {"A1": "noop", "A2": "mock", "A3": "mock"}


class ArmUnavailable(RuntimeError):
    """Raised when a requested arm cannot run in this phase/backend (SKIP, not FAIL)."""


@dataclass(frozen=True)
class ShieldWiring:
    """Where the sdk ``ShieldClient`` points + the agent signing key.

    Threaded from the CLI. Routes are the **server-confirmed** values relayed
    by team-lead (no schema/contract change — route strings only): pre_exec
    ``/v1/governance/decide``, post_exec/Channel-2 ``/v1/governance/record``.
    """

    base_url: str | None = None
    decide_path: str = "/v1/governance/decide"  # server-confirmed (team-lead)
    record_path: str = "/v1/governance/record"  # server-confirmed (team-lead, PR#12)
    agent_private_key_b64url: str | None = None


@dataclass(frozen=True)
class Arm:
    """One A/B condition.

    ``kind="native"``  → ``defense`` is None (A0) or an A0b built-in.
    ``kind="shield"``  → A1/A2/A3; ``decide_mode`` selects the eval-owned
                         ``/decide`` provider (overridable from the CLI).
    """

    key: str
    defense: str | None = None
    kind: str = "native"
    decide_mode: str | None = None

    # ---- native (W1) ----
    def _build_native(self, llm: BasePipelineElement | str, *, mock: bool) -> AgentPipeline:
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

    # ---- shield (W2) — aligned to the CANONICAL sdk contract (PR #11) ----
    def _build_shield(
        self, llm: BasePipelineElement | str, wiring: ShieldWiring | None
    ) -> AgentPipeline:
        """Assemble the Shield pipeline via sdk-builder's CANONICAL factory.

        AUTHORITATIVE contract (sdk-w2 PR #11, sdl §3.1 L93-107/§4.2/§4.4):

        * ``from shield_sdk.instrument.agentdojo import ShieldElementConfig,
          build_shield_elements`` and ``from shield_sdk.sdk import
          ShieldClient``.
        * ``build_shield_elements(ShieldElementConfig(client=ShieldClient(
          base_url=…, decide_path=…, [record_path=…]),
          agent_private_key_b64url=…, …defaults OK…))`` →
          ``(ShieldGuard, ShieldedToolsExecutor, ShieldRecorder)``.
        * Loop element order is ``[…, <LLM>, ShieldGuard,
          ShieldedToolsExecutor, ShieldRecorder]``.
        * A1 Free vs A2 Paid = WHERE ``ShieldClient`` points (A1 → stub
          ``/decide`` PASS; A2 → real Layer-2 / eval mock fallback). ZERO
          element changes — ``decide.py`` providers map cleanly as the
          served fallback ``/decide`` logic.
        * The verdict is NOT bare at ``extra_args["shield"]``; it is
          ``extra_args["shield"]["decisions"][key].verdict`` (frozen v1.1
          ``GovernanceVerdict``) with ``key = tool_call.id if tool_call.id is
          not None else f"__shield_idx_{index}"``.

        Until sdk-w2 + server-w2 merge the symbols are absent from ``main`` →
        ``ArmUnavailable`` so the runner SKIPs (never fakes). The
        ArmUnavailable-on-mismatch safety net is retained but should now
        resolve cleanly (no mismatch) once aligned + merged.
        """
        try:
            # attr-defined ignored on purpose: these symbols do not exist on
            # the W0/W1 stub modules until sdk-w2 (PR #11) merges; this is
            # runtime-guarded by `except ImportError` → ArmUnavailable (SKIP).
            from shield_sdk.instrument.agentdojo import (
                ShieldElementConfig,
                build_shield_elements,
            )
            from shield_sdk.sdk import ShieldClient
        except ImportError as e:  # pragma: no cover - until sdk-w2 lands
            raise ArmUnavailable(
                f"{self.key}: canonical Shield API lands with sdk-w2 "
                f"(shield_sdk.instrument.agentdojo + shield_sdk.sdk.ShieldClient) "
                f"— SKIP until merged ({e})"
            ) from e

        w = wiring or ShieldWiring()
        if not w.base_url or not w.agent_private_key_b64url:
            raise ArmUnavailable(
                f"{self.key}: shield wiring not configured "
                "(needs --decide-url + --shield-agent-key; live at W3 once "
                "server-w2 /decide is up) — SKIP, never faked"
            )
        try:
            from agentdojo.agent_pipeline.tool_execution import ToolsExecutionLoop

            # Server-confirmed route strings (team-lead relay): pre_exec
            # /v1/governance/decide, post_exec/Channel-2 /v1/governance/record.
            # **kwargs construction: the canonical ShieldClient signature
            # (base_url/decide_path/record_path) ships with sdk-w2 (PR #11);
            # main's stub differs, so we build against the canonical API
            # without a static signature dependency on the stub.
            client_kw: dict[str, Any] = {
                "base_url": w.base_url,
                "decide_path": w.decide_path,
                "record_path": w.record_path,
            }
            cfg = ShieldElementConfig(
                client=ShieldClient(**client_kw),
                agent_private_key_b64url=w.agent_private_key_b64url,
                run_id=None,  # org_id/agent_id/workflow_id/budget/fail_policy: defaults OK
            )
            guard, executor, recorder = build_shield_elements(cfg)

            base = self._build_native(llm, mock=isinstance(llm, BasePipelineElement))
            sysmsg, initq, worker = base.elements[0], base.elements[1], base.elements[2]
            loop = ToolsExecutionLoop([worker, guard, executor, recorder])
            pipeline = AgentPipeline([sysmsg, initq, worker, loop])
            pipeline.name = f"{getattr(worker, 'name', 'shield')}-{self.key.lower()}"
            return pipeline
        except (TypeError, AttributeError) as e:  # pragma: no cover - contract drift
            raise ArmUnavailable(
                f"{self.key}: Shield element integration contract mismatch vs sdk-w2 "
                f"({e!r}) — FLAGGED; eval SKIPs until reconciled"
            ) from e

    def build(
        self,
        llm: BasePipelineElement | str,
        *,
        mock: bool,
        shield_wiring: ShieldWiring | None = None,
    ) -> AgentPipeline:
        if self.kind == "shield":
            return self._build_shield(llm, shield_wiring)
        return self._build_native(llm, mock=mock)


def resolve_arms(requested: list[str], *, decide_mode: str | None = None) -> list[Arm]:
    """Map CLI/assert arm tokens to concrete arms.

    Native: ``A0``/``baseline``, ``A0b`` (→ the 4 built-ins), a built-in name.
    Shield: ``A1``/``A2``/``A3``; ``shielded`` is an alias for ``A2``.
    ``decide_mode`` (if given) overrides the per-arm ``/decide`` provider
    (e.g. ``--decide http`` to hit the live server instead of the mock).
    """
    out: list[Arm] = []
    seen: set[str] = set()

    def _add(arm: Arm) -> None:
        if arm.key not in seen:
            seen.add(arm.key)
            out.append(arm)

    tokens = requested or ["A0", "A0b"]
    for tok in tokens:
        t = tok.strip()
        if t in ("A0", "baseline", "none"):
            _add(Arm(key="A0", defense=None))
        elif t in ("A0b", "baselines", "all"):
            for d in NATIVE_BASELINES:
                _add(Arm(key=d, defense=d))
        elif t in NATIVE_BASELINES:
            _add(Arm(key=t, defense=t))
        elif t in ("A1", "A2", "A3", "shielded"):
            key = "A2" if t == "shielded" else t
            _add(Arm(key=key, kind="shield", decide_mode=decide_mode or _SHIELD_DECIDE[key]))
        else:
            raise ArmUnavailable(
                f"{t}: unknown arm (expected A0|A0b|baseline|A1|A2|A3|shielded|"
                f"{'|'.join(NATIVE_BASELINES)})"
            )
    return out


def arm_alias(arm_key: str) -> set[str]:
    """Assertion-token aliases an arm answers to."""
    if arm_key == "A0":
        return {"A0", "baseline", "none"}
    if arm_key == "A2":
        return {"A2", "shielded"}
    return {arm_key}


def ground_truth_calls(task: Any, env: Any) -> list[Any]:
    """Thin helper kept for symmetry/tests: a task's scripted tool calls."""
    return list(task.ground_truth(env))
