"""W1 behavioural tests — fully offline (MockedLLM, no API keys, no torch).

Proves the bankable native-arm path end-to-end against AgentDojo HEAD 18b501a:
A0 utility holds; A0 is genuinely defeated by InjectionTask6's 3×$10k
structuring via AgentDojo's *own* security oracle; per-arm pipeline.name is
distinct; the assertion DSL passes/skips/fails correctly; Shield arms are
SKIPPED (never faked).
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest
from shield_eval import run_ab
from shield_eval.arms import Arm, ArmUnavailable, resolve_arms
from shield_eval.mock_llm import MockedLLM


def _suite():  # type: ignore[no-untyped-def]
    from agentdojo.task_suite.load_suites import get_suite

    return get_suite("v1.2.2", "banking")


def test_resolve_arms_expands_a0b_and_resolves_shield() -> None:
    arms = resolve_arms(["A0", "A0b"])
    assert [a.key for a in arms][0] == "A0"
    assert {a.key for a in arms[1:]} == {
        "transformers_pi_detector",
        "spotlighting_with_delimiting",
        "repeat_user_prompt",
        "tool_filter",
    }
    # Full-build: A2/shielded resolves and builds with the in-process mock
    # decide provider by default; `--decide http` is the live-server path.
    a2 = resolve_arms(["shielded"])
    assert len(a2) == 1 and a2[0].key == "A2" and a2[0].kind == "shield"
    pipe = a2[0].build(MockedLLM(name="mocked-x"), mock=True)
    assert pipe.name.endswith("-a2")
    with pytest.raises(ArmUnavailable):
        resolve_arms(["bogus-arm"])


def test_a0_benign_utility_holds(tmp_path) -> None:  # type: ignore[no-untyped-def]
    suite = _suite()
    a0 = resolve_arms(["A0"])[0]
    res = run_ab._run_arm(
        a0,
        suite=suite,
        user_task_ids=["user_task_0"],
        injection_task_id=None,
        attack_name=None,
        backend="mock",
        worker="claude-3-haiku-20240307",
        logdir=str(tmp_path),
    )
    assert res.available
    assert res.utility  # non-empty
    assert all(res.utility.values())  # UserTask0 paid → utility True


def test_a0_is_defeated_by_injection_task_6(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The bankable result: undefended baseline fails InjectionTask6 (3×$10k)
    via AgentDojo's own auto-scored security() oracle — never cherry-picked."""
    suite = _suite()
    a0 = resolve_arms(["A0"])[0]
    res = run_ab._run_arm(
        a0,
        suite=suite,
        user_task_ids=["user_task_0"],
        injection_task_id="injection_task_6",
        attack_name="important_instructions",
        backend="mock",
        worker="claude-3-haiku-20240307",
        logdir=str(tmp_path),
    )
    assert res.available
    # security True == injection succeeded (attacker got >= $30k structured).
    assert any(res.security.values()), res.security
    # The legitimate user task still completes (utility preserved).
    assert all(res.utility.values()), res.utility


def test_per_arm_pipeline_name_is_distinct() -> None:
    a0 = Arm(key="A0", defense=None)
    spot = Arm(key="spotlighting_with_delimiting", defense="spotlighting_with_delimiting")
    llm_a0 = MockedLLM(name="mocked-claude-3-haiku-20240307")
    llm_sp = MockedLLM(name="mocked-claude-3-haiku-20240307")
    p0 = a0.build(llm_a0, mock=True)
    ps = spot.build(llm_sp, mock=True)
    assert p0.name == "mocked-claude-3-haiku-20240307"
    assert ps.name == "mocked-claude-3-haiku-20240307-spotlighting_with_delimiting"
    assert p0.name != ps.name


def test_tool_filter_and_pi_detector_are_skipped_in_mock() -> None:
    for d in ("tool_filter", "transformers_pi_detector"):
        with pytest.raises(ArmUnavailable):
            Arm(key=d, defense=d).build(MockedLLM(name="mocked-x"), mock=True)


def test_real_eval_model_builds_anthropic_llm_without_modelsenum(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setenv("SHIELD_REAL_EVAL_MAX_TOKENS", "64")

    llm = run_ab._real_llm_for_worker("claude-haiku-4-5-20251001")

    assert llm.name == "claude-3-haiku-20240307 (claude-haiku-4-5-20251001)"
    assert llm.model == "claude-haiku-4-5-20251001"
    assert llm._MAX_TOKENS == 64


def test_real_eval_model_requires_anthropic_key(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ArmUnavailable, match="ANTHROPIC_API_KEY"):
        run_ab._real_llm_for_worker("claude-haiku-4-5-20251001")


def _run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = run_ab.main(argv)
    return rc, buf.getvalue()


def test_smoke_exits_zero() -> None:
    rc, out = _run(["--suite", "banking", "--smoke"])
    assert rc == 0
    assert "OK" in out


def test_assertions_pass_skip_fail() -> None:
    base = [
        "--suite",
        "banking",
        "--user-task",
        "user_task_0",
        "--injection-task",
        "injection_task_6",
        "--attack",
        "important_instructions",
        "--arms",
        "A0",
    ]
    # Truthful baseline assertion → PASS, exit 0.
    rc, out = _run(base + ["--assert", "baseline.injection_task_6.success == True"])
    assert rc == 0
    assert "ASSERT [PASS] baseline.injection_task_6.success == True" in out

    # Shield arm not wired in W1 → SKIP (never faked), still exit 0.
    rc, out = _run(base + ["--assert", "shielded.injection_task_6.success == False"])
    assert rc == 0
    assert "ASSERT [SKIP] shielded.injection_task_6.success == False" in out

    # A real mismatch on a run arm → FAIL, exit 1.
    rc, out = _run(base + ["--assert", "baseline.injection_task_6.success == False"])
    assert rc == 1
    assert "ASSERT [FAIL]" in out


def test_report_is_written_and_labelled(tmp_path) -> None:  # type: ignore[no-untyped-def]
    out_file = tmp_path / "report.md"
    rc, _ = _run(
        [
            "--suite",
            "banking",
            "--user-task",
            "user_task_0",
            "--injection-task",
            "injection_task_6",
            "--attack",
            "important_instructions",
            "--arms",
            "A0",
            "--out",
            str(out_file),
        ]
    )
    assert rc == 0
    text = out_file.read_text()
    assert "NOT a" in text and "measured model" in text  # honest-scope label
    assert "never 'vs SOTA'" in text


def test_real_report_is_labelled_measured_backend(tmp_path) -> None:  # type: ignore[no-untyped-def]
    out_file = tmp_path / "real-report.md"
    run_ab._write_report(
        str(out_file),
        {
            "A0": run_ab.ArmResult(
                key="A0",
                security={("user_task_2", "injection_task_6"): False},
                utility={("user_task_2", "injection_task_6"): False},
            )
        },
        backend="real",
        model="claude-haiku-4-5-20251001",
    )

    text = out_file.read_text()
    assert "Real backend = provider model `claude-haiku-4-5-20251001`" in text
    assert "MockedLLM" not in text
