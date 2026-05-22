"""``python -m shield_eval.run_ab`` — THE canonical A/B runner.

W0 step-6a LOCKED name; conforms to tech_stack §2 layout. Behavioral spec =
``evaluation_plan.md`` §3.

It builds the AgentDojo pipeline **directly** via
``AgentPipeline.from_config(...)`` and calls ``benchmark_suite_with_injections``
/ ``benchmark_suite_without_injections`` itself — it never uses the
``--defense agent_shield --module-to-load`` CLI, which is code-verified
non-functional at AgentDojo HEAD ``18b501a`` (ADR-0005 / C9).

W1 scope (this file): the runner skeleton + the **native, zero-Shield** arms
A0 (no defense) and A0b (the 4 AgentDojo built-in defenses), driven offline by
a deterministic ``MockedLLM`` (no API keys / no torch in PR CI). This is the
bankable fallback that keeps the thesis if Layer-2 slips. The Shield arms
(A1/A2/A3) are wired W2→W3 by sdk/governance builders; assertions that
reference them are **SKIPPED, never faked**.

Honest positioning (locked): comparisons are scoped to "beat the 4 AgentDojo
built-in baselines + the Axis-C governance moat", never "beat SOTA".
``InjectionTask6`` is itself injection-delivered — stated plainly; mock numbers
are deterministic-transcript scaffolding, never reported as measured ASR.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Any

from .arms import Arm, ArmUnavailable, ShieldWiring, arm_alias, resolve_arms
from .mock_llm import MockedLLM

# Eval-plan §5: a mid-tier worker keeps undefended ASR visibly high. The mock
# only uses this to (a) seed the per-arm pipeline.name and (b) let the
# important_instructions attack address the model by prose name
# (get_model_name_from_pipeline matches this substring in pipeline.name).
DEFAULT_WORKER = "claude-3-haiku-20240307"
DEFAULT_BENCHMARK_VERSION = "v1.2.2"  # AgentDojo CLI default; banking = 16u/9i
ANTHROPIC_ENV_KEY = "ANTHROPIC_API_KEY"
REAL_EVAL_MODEL = "claude-haiku-4-5-20251001"


@dataclass
class ArmResult:
    key: str
    available: bool = True
    skip_reason: str | None = None
    # keys: (user_task_id, injection_task_id) with-injection; (uid, "") benign.
    security: dict[tuple[str, str], bool] = field(default_factory=dict)
    utility: dict[tuple[str, str], bool] = field(default_factory=dict)
    # Shield enforced decision per pairing (W2 A1/A2; empty for native arms).
    decisions: dict[tuple[str, str], str] = field(default_factory=dict)


def _real_llm_for_worker(worker: str) -> Any:
    """Build a real AgentDojo-compatible LLM for models absent from ModelsEnum."""

    if worker.startswith("claude-"):
        api_key = os.environ.get(ANTHROPIC_ENV_KEY)
        if not api_key:
            raise ArmUnavailable(
                f"{worker}: {ANTHROPIC_ENV_KEY} is required for real Anthropic eval"
            )
        from agentdojo.agent_pipeline.llms.anthropic_llm import AnthropicLLM
        from anthropic import AsyncAnthropic

        max_tokens = int(os.environ.get("SHIELD_REAL_EVAL_MAX_TOKENS", "1024"))
        llm = AnthropicLLM(
            AsyncAnthropic(api_key=api_key),
            model=worker,
            max_tokens=max_tokens,
        )
        llm.name = f"claude-3-haiku-20240307 ({worker})"
        return llm
    return worker


def _build_suite(version: str, suite_name: str) -> Any:
    from agentdojo.task_suite.load_suites import get_suite

    return get_suite(version, suite_name)


def _run_arm(
    arm: Arm,
    *,
    suite: Any,  # agentdojo TaskSuite (untyped dependency)
    user_task_ids: list[str],
    injection_task_id: str | None,
    attack_name: str | None,
    backend: str,
    worker: str,
    logdir: str,
    shield_wiring: ShieldWiring | None = None,
) -> ArmResult:
    """Run one native arm. Fresh pipeline + MockedLLM bound per user task so the
    deterministic replay stays correct across the suite iteration.

    The ``benchmark_suite_*`` functions construct ``TraceLogger(Logger.get())``
    internally; with an empty logger stack ``Logger.get()`` returns an
    un-entered ``NullLogger`` (no ``.logdir``). AgentDojo's own CLI always wraps
    runs in ``OutputLogger`` — we do the same (headless: ``live=None`` uses
    ``logging``, no TTY). Verified against agentdojo HEAD 18b501a logging.py.
    """
    from agentdojo.attacks import load_attack
    from agentdojo.benchmark import (
        benchmark_suite_with_injections,
        benchmark_suite_without_injections,
    )
    from agentdojo.logging import OutputLogger

    res = ArmResult(key=arm.key)
    mock = backend == "mock"

    for uid in user_task_ids:
        user_task = suite.get_user_task_by_id(uid)
        inj_task = suite.get_injection_task_by_id(injection_task_id) if injection_task_id else None

        llm: Any
        if mock:
            llm = MockedLLM(
                name=f"mocked-{worker}",
                user_task=user_task,
                injection_task=inj_task,
            )
        else:
            llm = _real_llm_for_worker(worker)

        try:
            pipeline = arm.build(llm, mock=mock, shield_wiring=shield_wiring)
        except ArmUnavailable as e:
            res.available = False
            res.skip_reason = str(e)
            return res

        with OutputLogger(logdir):
            if injection_task_id and attack_name:
                attack = load_attack(attack_name, suite, pipeline)
                sr = benchmark_suite_with_injections(
                    pipeline,
                    suite,
                    attack,
                    logdir=None,
                    force_rerun=True,
                    user_tasks=[uid],
                    injection_tasks=[injection_task_id],
                    verbose=False,
                    benchmark_version=DEFAULT_BENCHMARK_VERSION,
                )
            else:
                sr = benchmark_suite_without_injections(
                    pipeline,
                    suite,
                    logdir=None,
                    force_rerun=True,
                    user_tasks=[uid],
                    benchmark_version=DEFAULT_BENCHMARK_VERSION,
                )
        res.security.update(sr["security_results"])
        res.utility.update(sr["utility_results"])
    return res


# --------------------------- assertion DSL -----------------------------------
# Grammar (matches integration.yml verbatim):
#   ARM.TASK.FIELD == <literal|ref>
#   ARM.TASK.FIELD != <literal|ref>
#   ARM.TASK.FIELD in [<literal>, ...]
# ARM ∈ {baseline|A0|<built-in name>|shielded|A1|A2|A3}
# FIELD ∈ {success (security oracle) | utility | decision (Shield verdict)}


@dataclass
class AssertOutcome:
    text: str
    status: str  # PASS | FAIL | SKIP
    detail: str = ""


def _find_arm(token: str, results: dict[str, ArmResult]) -> ArmResult | None:
    for r in results.values():
        if token in arm_alias(r.key) or token == r.key:
            return r
    return None


def _lookup(ref: str, results: dict[str, ArmResult]) -> tuple[str, object]:
    """Resolve ``arm.task.field`` → ("OK", value) | ("SKIP", reason)."""
    parts = ref.split(".")
    if len(parts) != 3:
        return "SKIP", f"unparseable ref '{ref}'"
    arm_tok, task_id, fld = parts
    # W2: shield arms (A1/A2/A3, alias 'shielded') resolve like any arm — they
    # produce a real result when run, or SKIP via ArmUnavailable (sdk-w2 not
    # yet merged). No hardcoded skip; SKIP-not-fake stays honest either way.
    r = _find_arm(arm_tok, results)
    if r is None:
        return "SKIP", f"arm '{arm_tok}' was not run"
    if not r.available:
        return "SKIP", f"arm '{arm_tok}' unavailable: {r.skip_reason}"
    if fld == "decision":
        if not r.decisions:
            return "SKIP", f"no decision captured for task '{task_id}' on arm '{arm_tok}'"
        dvals = [v for (uid, iid), v in r.decisions.items() if task_id in (uid, iid)]
        if not dvals:
            return "SKIP", f"no decision for task '{task_id}' on arm '{arm_tok}'"
        return "OK", dvals[0]
    table = r.security if fld == "success" else r.utility
    vals = [v for (uid, iid), v in table.items() if task_id in (uid, iid)]
    if not vals:
        return "SKIP", f"no result for task '{task_id}' on arm '{arm_tok}'"
    # success: attack succeeded in ANY pairing; utility: held in ALL pairings.
    return "OK", (any(vals) if fld == "success" else all(vals))


def _evaluate_assert(expr: str, results: dict[str, ArmResult]) -> AssertOutcome:
    raw = expr.strip()
    if " in " in raw:
        lhs, _, rhs = raw.partition(" in ")
        op = "in"
    elif "==" in raw:
        lhs, _, rhs = raw.partition("==")
        op = "=="
    elif "!=" in raw:
        lhs, _, rhs = raw.partition("!=")
        op = "!="
    else:
        return AssertOutcome(raw, "FAIL", "no recognised operator (==, !=, in)")
    lhs, rhs = lhs.strip(), rhs.strip()

    lstatus, lval = _lookup(lhs, results)
    if lstatus == "SKIP":
        return AssertOutcome(raw, "SKIP", str(lval))

    # RHS: another ref (arm.task.field, dotted, no brackets/quotes) or a literal.
    is_ref = (
        op != "in" and rhs.count(".") == 2 and "[" not in rhs and "'" not in rhs and '"' not in rhs
    )
    if is_ref:
        rstatus, rval = _lookup(rhs, results)
        if rstatus == "SKIP":
            return AssertOutcome(raw, "SKIP", str(rval))
    else:
        try:
            rval = ast.literal_eval(rhs)
        except (ValueError, SyntaxError) as e:
            return AssertOutcome(raw, "FAIL", f"bad literal '{rhs}': {e}")

    if op == "==":
        ok = lval == rval
    elif op == "!=":
        ok = lval != rval
    else:
        ok = lval in rval  # type: ignore[operator]
    return AssertOutcome(raw, "PASS" if ok else "FAIL", f"lhs={lval!r} {op} rhs={rval!r}")


# ------------------------------- reporting -----------------------------------


def _write_report(
    path: str,
    results: dict[str, ArmResult],
    *,
    backend: str = "mock",
    model: str | None = None,
) -> None:
    if backend == "real":
        scope_note = (
            f"> Source: `shield_eval.run_ab`. **Real backend = provider model "
            f"`{model or 'unknown'}`.** This report stores aggregate security/"
            "> utility booleans only; raw provider traces are not included. "
            "Scope: vs the 4 AgentDojo built-in baselines + the Axis-C "
            "governance moat — never 'vs SOTA'. `InjectionTask6` is itself "
            "injection-delivered (stated plainly)."
        )
    else:
        scope_note = (
            "> Source: `shield_eval.run_ab`. **MockedLLM = deterministic transcript\n"
            "> replayed from AgentDojo's own `ground_truth` (HEAD 18b501a) — NOT a\n"
            "> measured model.** Real, quotable ASR/utility come from real models via\n"
            "> `eval.yml` (W4/W5). Scope: vs the 4 AgentDojo built-in baselines +\n"
            "> the Axis-C governance moat — never 'vs SOTA'. `InjectionTask6` is\n"
            "> itself injection-delivered (stated plainly)."
        )
    lines = [
        "# Agent Shield — A/B run report (W1 native arms)",
        "",
        scope_note,
        "",
        "| Arm | Status | Injection-success (security oracle) | Utility |",
        "|---|---|---|---|",
    ]
    for r in results.values():
        if not r.available:
            lines.append(f"| {r.key} | SKIP — {r.skip_reason} | — | — |")
            continue
        sec = "; ".join(f"{k[0]}×{k[1]}={v}" for k, v in r.security.items() if k[1]) or "—"
        ut = "; ".join(f"{k[0]}={v}" for k, v in r.utility.items()) or "—"
        lines.append(f"| {r.key} | run | {sec} | {ut} |")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _write_metrics_markdown(path: str, report: dict[str, Any]) -> None:
    lines = [
        "# Agent Shield — eval metrics",
        "",
        f"- schema: `{report.get('schema_version')}`",
        f"- label: `{report.get('run_label')}`",
        f"- backend: `{report.get('backend')}`",
        "",
        "| Metric | Value | Unit | Label |",
        "|---|---:|---|---|",
    ]
    for key, item in (report.get("values") or {}).items():
        if isinstance(item, dict):
            lines.append(
                f"| `{key}` | {item.get('value')} | {item.get('unit')} | {item.get('label')} |"
            )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# --------------------------------- CLI ---------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="shield_eval.run_ab")
    p.add_argument("--suite", default="banking")
    p.add_argument("--benchmark-version", default=DEFAULT_BENCHMARK_VERSION)
    p.add_argument("--user-task", dest="user_tasks", action="append", default=[])
    p.add_argument("--injection-task", dest="injection_tasks", action="append", default=[])
    p.add_argument("--attack", default=None)
    p.add_argument("--assert", dest="asserts", action="append", default=[])
    p.add_argument(
        "--arms", default=None, help="comma list: A0,A0b,baseline,A1,A2,A3,shielded,<built-in>"
    )
    p.add_argument("--compare-baselines", default=None, help="comma list of A0b built-ins")
    p.add_argument(
        "--decide",
        dest="decide_mode",
        default=None,
        choices=["noop", "mock", "http"],
        help="Shield-arm /decide provider override (A1=noop, A2=mock|http)",
    )
    p.add_argument("--decide-url", default=None, help="ShieldClient base_url (server /decide host)")
    p.add_argument(
        "--decide-path", default="/v1/governance/decide", help="ShieldClient decide_path"
    )
    p.add_argument(
        "--record-path",
        default="/v1/governance/record",
        help="ShieldClient record_path (Channel-2 post_exec; server-confirmed)",
    )
    p.add_argument(
        "--shield-agent-key",
        default=os.environ.get("SHIELD_AGENT_PRIVATE_KEY_B64URL"),
        help="agent Ed25519 private key (b64url) for the Shield arms",
    )
    p.add_argument(
        "--backend",
        default=os.environ.get("SHIELD_LLM_BACKEND", "mock"),
        choices=["mock", "http", "real"],
    )
    p.add_argument(
        "--model", default=DEFAULT_WORKER, help="worker model (real backend / name seed)"
    )
    p.add_argument("--metrics", default=None)
    p.add_argument("--metrics-out", default=None, help="write metrics JSON artifact")
    p.add_argument("--cases-out", default=None, help="write per-case full-grid JSON rows")
    p.add_argument("--budget-out", default=None, help="write real-runner budget JSON artifact")
    p.add_argument("--samples", type=int, default=1, help="planned real-runner samples")
    p.add_argument(
        "--serialized-prompt-chars",
        type=int,
        default=None,
        help="dry-run prompt chars for real-runner budget estimation",
    )
    p.add_argument("--max-output-tokens", type=int, default=2_000)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--full", action="store_true")
    p.add_argument("--out", default=None)
    p.add_argument(
        "--logdir",
        default=None,
        help="AgentDojo trace/cache dir; ephemeral temp dir if omitted",
    )
    args = p.parse_args(argv)

    suite = _build_suite(args.benchmark_version, args.suite)

    tmp = None if args.logdir else tempfile.TemporaryDirectory(prefix="shield_eval_runs_")
    logdir = args.logdir or (tmp.name if tmp else ".")
    try:
        return _dispatch(args, suite, logdir)
    finally:
        if tmp is not None:
            tmp.cleanup()


def _dispatch(args: argparse.Namespace, suite: Any, logdir: str) -> int:
    if args.full:
        return _dispatch_full(args, suite)

    # --smoke: tiny real offline e2e — A0 + MockedLLM on banking user_task_0,
    # no injection; assert utility holds. Proves the plumbing end-to-end.
    if args.smoke:
        a0 = resolve_arms(["A0"])[0]
        r = _run_arm(
            a0,
            suite=suite,
            user_task_ids=["user_task_0"],
            injection_task_id=None,
            attack_name=None,
            backend="mock",
            worker=args.model,
            logdir=logdir,
        )
        ok = all(r.utility.values()) and bool(r.utility)
        print(
            f"shield_eval.run_ab --smoke: suite={args.suite} arm=A0 "
            f"user_task_0 utility={r.utility} -> {'OK' if ok else 'FAIL'}"
        )
        return 0 if ok else 1

    # Resolve arms (default A0 + A0b). --compare-baselines narrows A0b.
    arm_tokens: list[str]
    if args.arms:
        arm_tokens = [t for t in args.arms.split(",") if t]
    elif args.compare_baselines:
        arm_tokens = ["A0"] + [t for t in args.compare_baselines.split(",") if t]
    else:
        arm_tokens = ["A0", "A0b"]

    arms: list[Arm] = []
    skipped: list[AssertOutcome] = []
    for tok in arm_tokens:
        try:
            arms.extend(resolve_arms([tok], decide_mode=args.decide_mode))
        except ArmUnavailable as e:
            skipped.append(AssertOutcome(f"arm:{tok}", "SKIP", str(e)))

    injection_task_id = args.injection_tasks[0] if args.injection_tasks else None
    user_task_ids = args.user_tasks or ["user_task_0"]

    shield_wiring = ShieldWiring(
        base_url=args.decide_url,
        decide_path=args.decide_path,
        record_path=args.record_path,
        agent_private_key_b64url=args.shield_agent_key,
    )

    results: dict[str, ArmResult] = {}
    for arm in arms:
        results[arm.key] = _run_arm(
            arm,
            suite=suite,
            user_task_ids=user_task_ids,
            injection_task_id=injection_task_id,
            attack_name=args.attack,
            backend=args.backend,
            worker=args.model,
            logdir=logdir,
            shield_wiring=shield_wiring,
        )

    print(
        f"shield_eval.run_ab: suite={args.suite} arms={[a.key for a in arms]} "
        f"users={user_task_ids} injection={injection_task_id} attack={args.attack} "
        f"backend={args.backend}"
    )
    for s in skipped:
        print(f"  ARM  [SKIP] {s.text}: {s.detail}")
    for r in results.values():
        if not r.available:
            print(f"  arm {r.key}: [SKIP] {r.skip_reason}")
        else:
            print(f"  arm {r.key}: security={r.security} utility={r.utility}")

    if args.out:
        _write_report(args.out, results, backend=args.backend, model=args.model)

    exit_code = 0
    for expr in args.asserts:
        outcome = _evaluate_assert(expr, results)
        print(f"  ASSERT [{outcome.status}] {outcome.text}  ({outcome.detail})")
        if outcome.status == "FAIL":
            exit_code = 1
    return exit_code


def _real_prompt_char_estimate(args: argparse.Namespace) -> int:
    if args.serialized_prompt_chars is not None:
        return max(0, int(args.serialized_prompt_chars))
    user_tasks = args.user_tasks or ["user_task_2"]
    injection_tasks = args.injection_tasks or ["injection_task_6"]
    payload = {
        "suite": args.suite,
        "attack": args.attack or "important_instructions",
        "user_tasks": user_tasks,
        "injection_tasks": injection_tasks,
        "model": args.model,
        "arms": args.arms or args.compare_baselines or "A0,A0b,A1,A2,A3",
    }
    return len(json.dumps(payload, sort_keys=True)) + 2_000


def _dispatch_full(args: argparse.Namespace, suite: Any) -> int:
    from .metrics import (
        build_full_grid_artifacts,
        build_provider_slice_artifact,
        build_real_runner_budget_artifact,
        print_summary,
        write_json,
    )

    arm_tokens = [t for t in (args.arms or "A0,A0b,A1,A2,A3").split(",") if t]
    user_tasks = args.user_tasks or list(suite.user_tasks.keys())
    injection_tasks = args.injection_tasks or list(suite.injection_tasks.keys())

    if args.backend == "real":
        artifact = build_real_runner_budget_artifact(
            arms=arm_tokens,
            user_tasks=user_tasks,
            injection_tasks=injection_tasks,
            samples=args.samples,
            serialized_prompt_chars=_real_prompt_char_estimate(args),
            max_output_tokens=args.max_output_tokens,
        )
        slice_artifact = build_provider_slice_artifact(
            user_task_id=user_tasks[0],
            injection_task_id=injection_tasks[0],
            attack_variant=args.attack or "important_instructions",
            provider="anthropic",
            model_router_profile="cloud",
            hard_cap_usd=artifact["hard_cap_usd"],
            estimated_cost_usd=artifact["estimated_cost_usd"],
            api_call_status="SKIPPED",
            skip_reason=artifact.get("skip_reason") or "REAL_EVAL_IMPLEMENTATION_ONLY",
        )
        if args.budget_out:
            write_json(args.budget_out, artifact)
        if args.metrics_out:
            write_json(args.metrics_out, slice_artifact)
        print(json.dumps(artifact, indent=2, sort_keys=True))
        print(
            "shield_eval.run_ab --full real: "
            f"{artifact['status_label']} cost=${artifact['estimated_cost_usd']:.6f}; "
            "Anthropic API call SKIPPED"
        )
        return 0

    if args.backend == "http":
        report, cases = build_full_grid_artifacts(
            suite=args.suite,
            user_task_ids=user_tasks,
            injection_task_ids=injection_tasks,
            arms=arm_tokens,
            backend="http",
            attack_variant=args.attack or "important_instructions",
        )
        if args.metrics_out:
            write_json(args.metrics_out, report)
        if args.cases_out:
            write_json(args.cases_out, cases)
        if args.out:
            _write_metrics_markdown(args.out, report)
        print(
            f"shield_eval.run_ab --full: suite={args.suite} "
            f"arms={report['arms']} backend=http label={report['run_label']} "
            f"skip_reason={report.get('skip_reason')}"
        )
        print_summary(report)
        return 0

    # Mock-only full benchmark artifact: deterministic money-shot + benign FPR.
    # This is intentionally not quotable as measured model ASR.
    report, cases = build_full_grid_artifacts(
        suite=args.suite,
        user_task_ids=user_tasks,
        injection_task_ids=injection_tasks,
        arms=arm_tokens,
        backend="mock",
        attack_variant=args.attack or "important_instructions",
    )
    if args.metrics_out:
        write_json(args.metrics_out, report)
    if args.cases_out:
        write_json(args.cases_out, cases)
    if args.out:
        _write_metrics_markdown(args.out, report)
    print(
        f"shield_eval.run_ab --full: suite={args.suite} "
        f"arms={arm_tokens} backend=mock label={report['run_label']}"
    )
    print_summary(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
