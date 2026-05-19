"""Defender scanner adapters — LlamaFirewall (injection) + Invariant
``LocalPolicy`` (cross-call structuring / exfil), behind clean Protocols so
unit CI runs without torch (fakes) and the air-gap profile can swap scanners
(ScannerType-pluggable — local_deployment_moat §3.3/§5).

§5b — verified first-hand against ``Related_Work/`` clones, 2026-05-19:

* **LlamaFirewall** framework MIT (``PurpleLlama/LlamaFirewall/LICENSE:1``):
  ``LlamaFirewall(scanners: dict[Role, list[ScannerType]])``
  (``src/llamafirewall/llamafirewall.py:88-99``); ``await
  fw.scan_async(Message) -> ScanResult`` (``:164-168``); ``ScanResult(decision,
  reason, score, status)`` (``llamafirewall_data_types.py:42-47``);
  ``ScanDecision`` = ALLOW / HUMAN_IN_THE_LOOP_REQUIRED / BLOCK (``:22-25``);
  ``ScannerType`` = PROMPT_GUARD / REGEX / HIDDEN_ASCII / CODE_SHIELD
  (``:13-19``); ``UserMessage(content)`` / ``Role`` (``:34``, ``:60-69``).
* **Invariant** ``invariant-ai`` 0.3.5 Apache (``invariant/LICENSE:1``):
  ``from invariant.analyzer import LocalPolicy`` (re-exported
  ``invariant/analyzer/__init__.py:11``) — explicit **LocalPolicy**, NOT bare
  ``Policy`` / ``RemotePolicy`` (= remote egress, BANNED by the air-gap
  import-lint). ``LocalPolicy.from_string(str)`` (``policy.py:77``);
  ``policy.analyze(trace).errors`` (``policy.py:90``) — ``AnalysisResult.errors``
  lists violations.

DRIFT (reported to team-lead): governance_design §3.2's exact Invariant policy
(``from invariant import sum`` + ``[c … for c in input.data …]``) does **not**
work in invariant-ai 0.3.5 — ``sum`` is a DSL *builtin* (no import) and
``input.data`` is not list-comprehension-iterable in 0.3.5. The verified-working
idiom (probed against the real engine) is the ``count(min=N)`` quantifier
(``from invariant import count`` + ``count(min=3): (tc: ToolCall) tc is
tool:send_money``) — see :data:`STRUCTURING_POLICY`. The deterministic W1
``CumulativeRecipientTracker`` remains the *authoritative* model-free
cumulative-amount catcher; this LocalPolicy is a verified DSL cross-check.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

# Verified-working Invariant 0.3.5 LocalPolicy text (probed against the real
# engine 2026-05-19): >=3 transfers to one recipient == structuring; a secret
# in the free-text subject == exfil. `count` is importable (unlike `sum`).
STRUCTURING_POLICY = """
from invariant import count

raise "structuring: >=3 transfers to one recipient" if:
    count(min=3):
        (tc: ToolCall)
        tc is tool:send_money

raise "exfil: secret-looking subject" if:
    (tc: ToolCall)
    tc is tool:send_money
    "password" in tc.function.arguments.subject
"""


@dataclass(frozen=True, slots=True)
class ScanFinding:
    """One scanner's normalized result."""

    blocked: bool
    escalate: bool
    label: str
    detail: str
    score: float


@runtime_checkable
class InjectionScanner(Protocol):
    async def scan_text(self, text: str, *, kind: str) -> ScanFinding: ...


class NullInjectionScanner:
    """No-op scanner — the default when the ``scanners`` extra is absent or the
    live scanner path is flag-disabled. Always ALLOW."""

    async def scan_text(self, text: str, *, kind: str) -> ScanFinding:
        return ScanFinding(False, False, "scanner.disabled", "", 0.0)


class FakeInjectionScanner:
    """Deterministic test double: BLOCK iff a trigger substring is present."""

    def __init__(self, triggers: tuple[str, ...] = ("__INJECT__",)) -> None:
        self._triggers = triggers

    async def scan_text(self, text: str, *, kind: str) -> ScanFinding:
        for t in self._triggers:
            if t in text:
                return ScanFinding(True, False, f"scanner.injection.{kind}", f"matched {t!r}", 1.0)
        return ScanFinding(False, False, "scanner.clean", "", 0.0)


class LlamaFirewallScanner:
    """Real LlamaFirewall adapter. ``llamafirewall`` (torch) imported lazily —
    only constructed when the live scanner path is enabled; unit CI uses a
    fake. Maps ``ScanResult`` -> :class:`ScanFinding` per the §5b API."""

    def __init__(self) -> None:
        self._fw: Any | None = None
        self._user_role: Any | None = None
        self._user_message: Any | None = None

    def _ensure(self) -> None:
        if self._fw is not None:
            return
        from llamafirewall import (  # lazy: heavy (torch); air-gap-pluggable
            LlamaFirewall,
            Role,
            ScannerType,
            UserMessage,
        )

        # Model-free + local-classifier scanners only on the hot path.
        self._fw = LlamaFirewall(
            {Role.USER: [ScannerType.PROMPT_GUARD, ScannerType.REGEX, ScannerType.HIDDEN_ASCII]}
        )
        self._user_message = UserMessage

    async def scan_text(self, text: str, *, kind: str) -> ScanFinding:
        self._ensure()
        assert self._fw is not None and self._user_message is not None
        from llamafirewall import ScanDecision

        result = await self._fw.scan_async(self._user_message(text))
        if result.decision == ScanDecision.BLOCK:
            return ScanFinding(
                True, False, f"scanner.injection.{kind}", result.reason, result.score
            )
        if result.decision == ScanDecision.HUMAN_IN_THE_LOOP_REQUIRED:
            return ScanFinding(False, True, f"scanner.review.{kind}", result.reason, result.score)
        return ScanFinding(False, False, "scanner.clean", result.reason, result.score)


@dataclass(frozen=True, slots=True)
class PolicyViolation:
    label: str
    detail: str


@runtime_checkable
class StructuringAnalyzer(Protocol):
    def analyze(self, trace: list[dict[str, Any]]) -> list[PolicyViolation]: ...


class FakeStructuringAnalyzer:
    """Deterministic double mirroring the verified LocalPolicy semantics:
    >=3 ``send_money`` tool calls in the trace == structuring."""

    def __init__(self, threshold: int = 3) -> None:
        self._threshold = threshold

    def analyze(self, trace: list[dict[str, Any]]) -> list[PolicyViolation]:
        n = 0
        for ev in trace:
            for tc in ev.get("tool_calls") or []:
                if tc.get("function", {}).get("name") == "send_money":
                    n += 1
        if n >= self._threshold:
            return [
                PolicyViolation(
                    "invariant.structuring", f"{n} send_money calls (>= {self._threshold})"
                )
            ]
        return []


class LocalPolicyStructuringAnalyzer:
    """Real Invariant ``LocalPolicy`` adapter (air-gap-safe: LocalPolicy ONLY,
    never bare ``Policy``/``RemotePolicy``). Compiles :data:`STRUCTURING_POLICY`
    once; ``invariant`` imported lazily."""

    def __init__(self, policy_text: str = STRUCTURING_POLICY) -> None:
        self._policy_text = policy_text
        self._policy: Any | None = None

    def _ensure(self) -> None:
        if self._policy is not None:
            return
        from invariant.analyzer import LocalPolicy  # NOT Policy/RemotePolicy (egress)

        self._policy = LocalPolicy.from_string(self._policy_text)

    def analyze(self, trace: list[dict[str, Any]]) -> list[PolicyViolation]:
        self._ensure()
        assert self._policy is not None
        result = self._policy.analyze(trace)
        return [PolicyViolation("invariant.policy", str(e)) for e in result.errors]
