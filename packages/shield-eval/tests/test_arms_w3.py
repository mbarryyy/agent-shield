"""W3 — deterministic shield arms (local provider) + native-mirroring loop."""

from __future__ import annotations

import pytest
from shield_eval.arms import Arm, ArmUnavailable, ShieldWiring, _frozen_test_key, resolve_arms
from shield_eval.decide import MockDecide, NoopDecide
from shield_eval.mock_llm import MockedLLM


def test_frozen_test_key_loads_from_golden_vectors() -> None:
    k = _frozen_test_key()
    assert isinstance(k, str) and len(k) > 16  # b64url Ed25519 private key


def test_shield_arm_builds_deterministically_with_local_provider() -> None:
    a2 = resolve_arms(["A2"])[0]
    pipe = a2.build(
        MockedLLM(name="mocked-claude-3-haiku-20240307"),
        mock=True,
        shield_wiring=ShieldWiring(local_provider=MockDecide()),
    )
    # Native-mirroring composition: top-level [sys, init, llm, loop];
    # loop = [ShieldGuard, ShieldedToolsExecutor, ShieldRecorder, llm] — the
    # LLM is LAST in the loop (process-then-generate, like AgentDojo native).
    assert len(pipe.elements) == 4
    loop = pipe.elements[3]
    names = [type(e).__name__ for e in loop.elements]
    assert names[0] == "ShieldGuard"
    assert names[1] == "ShieldedToolsExecutor"
    assert names[2] == "ShieldRecorder"
    assert names[3] != "ShieldRecorder"  # the LLM/worker is last, not the recorder
    assert pipe.name.endswith("-a2")


def test_a3_is_resolvable_and_builds() -> None:
    a3 = resolve_arms(["A3"])[0]
    assert a3.key == "A3" and a3.kind == "shield"
    pipe = a3.build(
        MockedLLM(name="m"), mock=True, shield_wiring=ShieldWiring(local_provider=NoopDecide())
    )
    assert pipe.name.endswith("-a3")


def test_shield_arm_without_wiring_still_skips_not_fakes() -> None:
    # No local provider AND no real base_url/key ⇒ ArmUnavailable (SKIP), the
    # honest behaviour for an unconfigured real path.
    a2 = resolve_arms(["A2"])[0]
    with pytest.raises(ArmUnavailable) as ei:
        a2.build(MockedLLM(name="m"), mock=True, shield_wiring=ShieldWiring())
    assert "A2" in str(ei.value) and "never faked" in str(ei.value)


def test_native_arms_unaffected() -> None:
    a0 = resolve_arms(["A0"])[0]
    assert isinstance(a0, Arm) and a0.kind == "native"
    p = a0.build(MockedLLM(name="mocked-x"), mock=True)
    assert p.name == "mocked-x"
