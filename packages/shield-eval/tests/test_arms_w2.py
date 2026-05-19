"""W2 arm resolution: A1/A2/A3 shield arms + clean-switch SKIP discipline."""

from __future__ import annotations

import pytest
from shield_eval.arms import ArmUnavailable, arm_alias, resolve_arms
from shield_eval.mock_llm import MockedLLM


def test_shield_arms_resolve_with_decide_modes() -> None:
    a1 = resolve_arms(["A1"])[0]
    assert a1.key == "A1" and a1.kind == "shield" and a1.decide_mode == "noop"
    a2 = resolve_arms(["A2"])[0]
    assert a2.key == "A2" and a2.decide_mode == "mock"
    a3 = resolve_arms(["A3"])[0]
    assert a3.key == "A3" and a3.decide_mode == "mock"


def test_shielded_is_alias_for_a2() -> None:
    assert resolve_arms(["shielded"])[0].key == "A2"
    assert arm_alias("A2") == {"A2", "shielded"}
    assert "baseline" in arm_alias("A0")


def test_decide_mode_override() -> None:
    a2 = resolve_arms(["A2"], decide_mode="http")[0]
    assert a2.decide_mode == "http"


def test_shield_build_skips_until_sdk_w2(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shield elements are sdk-builder's module; absent from main until sdk-w2.
    Arm.build must raise ArmUnavailable (SKIP-not-fake), naming the dependency."""
    a2 = resolve_arms(["A2"])[0]
    with pytest.raises(ArmUnavailable) as ei:
        a2.build(MockedLLM(name="mocked-x"), mock=True)
    msg = str(ei.value)
    assert "A2" in msg and ("sdk-w2" in msg or "shield_sdk.instrument.agentdojo" in msg)


def test_native_arms_unaffected_by_w2() -> None:
    a0 = resolve_arms(["A0"])[0]
    p = a0.build(MockedLLM(name="mocked-claude-3-haiku-20240307"), mock=True)
    assert p.name == "mocked-claude-3-haiku-20240307"
    assert {a.key for a in resolve_arms(["A0b"])} == {
        "transformers_pi_detector",
        "spotlighting_with_delimiting",
        "repeat_user_prompt",
        "tool_filter",
    }


def test_mixed_native_and_shield_resolution() -> None:
    arms = resolve_arms(["A0", "A2"])
    assert [a.key for a in arms] == ["A0", "A2"]
    assert arms[0].kind == "native" and arms[1].kind == "shield"
