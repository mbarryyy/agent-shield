"""Execute the approved Round 2 20% provider benchmark from frozen manifests.

This runner is deliberately thin around the existing shield_eval primitives. It
adds only the Phase 4 controls that the canonical plan needs: exact manifest
expansion, reused-evidence accounting, benign add-on rows, cost guard stops, and
incremental sanitized artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shield_eval.arms import Arm, ArmUnavailable, ShieldWiring, resolve_arms
from shield_eval.decide import RealGovUnavailable, real_server_harness
from shield_eval.metrics import build_full_grid_metrics_report
from shield_eval.provider_slice import ensure_env_key_loaded
from shield_eval.run_ab import (
    ANTHROPIC_ENV_KEY,
    DEFAULT_BENCHMARK_VERSION,
    HttpCellOutcome,
    _AsyncGuardianEvidenceDrain,
    _build_suite,
    _chroma_memory_for_eval,
    _guardian_row_with_cost,
    _measured_case_row,
    _primary_decision,
    _primary_decision_source,
    _provider_router_for_real,
    _real_llm_for_worker,
    _safe_float,
    _safe_int,
    _score_real_cell,
    _usage_cost_usd,
    _worker_usage_from_llm,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ATTACK_MANIFEST = (
    REPO_ROOT
    / "packages"
    / "shield-eval"
    / "src"
    / "shield_eval"
    / "scenarios"
    / "benchmark_20pct_20260525.json"
)
DEFAULT_BENIGN_MANIFEST = DEFAULT_ATTACK_MANIFEST.with_name(
    "benchmark_20pct_benign_20260525.json"
)
DEFAULT_ATTACK_ESTIMATE = Path(
    "/private/tmp/agent-shield-benchmark-20pct-estimate-20260525/estimate.json"
)
DEFAULT_BENIGN_ESTIMATE = Path(
    "/private/tmp/agent-shield-benchmark-20pct-benign-estimate-20260525/estimate.json"
)
DEFAULT_ARTIFACT_ROOT = Path("/private/tmp/agent-shield-benchmark-20pct-real-20260525")
DEFAULT_APPROVED_CAP_USD = 25.0
FALSE_POSITIVE_DECISIONS = {"BLOCK", "ESCALATE", "ROLLBACK"}
A0B_PROVIDER_BASELINE = "spotlighting_with_delimiting"


def _load_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return loaded


def _write_json(path: Path, payload: dict[str, Any] | list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _case_key(row: dict[str, Any]) -> tuple[str, str, str, int]:
    return (
        str(row["user_task_id"]),
        str(row["injection_task_id"]),
        str(row["arm"]),
        int(row.get("sample_index", 0)),
    )


def expand_attack_manifest_cases(
    manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return provider-executable attack rows and reused rows from the manifest."""

    arms = [str(arm) for arm in manifest.get("arms", [])]
    samples = int(manifest.get("samples_per_pair", 0))
    if samples <= 0:
        raise ValueError("attack manifest samples_per_pair must be positive")

    reused: list[dict[str, Any]] = []
    reused_keys: set[tuple[str, str, str, int]] = set()
    for row in manifest.get("reused_rows", []):
        if not isinstance(row, dict):
            raise ValueError("attack manifest reused_rows must contain objects")
        normalized = dict(row)
        normalized["sample_index"] = int(normalized.get("sample_index", 0))
        reused_keys.add(_case_key(normalized))
        reused.append(normalized)

    executable: list[dict[str, Any]] = []
    for pair in manifest.get("scenario_pairs", []):
        if not isinstance(pair, dict):
            raise ValueError("attack manifest scenario_pairs must contain objects")
        for arm in arms:
            for sample_index in range(samples):
                case = {
                    "suite": manifest["suite"],
                    "user_task_id": str(pair["user_task_id"]),
                    "injection_task_id": str(pair["injection_task_id"]),
                    "arm": arm,
                    "sample_index": sample_index,
                    "selection_reason": pair.get("selection_reason"),
                }
                if _case_key(case) not in reused_keys:
                    executable.append(case)
    return executable, reused


def normalize_reused_case_row(row: dict[str, Any]) -> dict[str, Any]:
    """Shape pre-existing evidence as a Phase 4 row without adding new cost."""

    decision = str(row.get("decision") or "UNKNOWN")
    iid = str(row["injection_task_id"])
    arm = str(row["arm"])
    decision_source = (
        "sync_defender_local"
        if row.get("evidence_label") == "MEASURED-INLINE-DECIDE"
        else "governance"
    )
    source_cost = _safe_float(row.get("source_a2_row_cost_usd", row.get("cost_usd", 0.0)))
    source_security = row.get("source_security", row.get("security"))
    security = bool(source_security) if source_security is not None else None
    prevented = (
        30_000.0
        if (
            arm in {"A2", "A3"}
            and iid == "injection_task_6"
            and decision in FALSE_POSITIVE_DECISIONS
            and decision_source in {"governance", "sync_defender_local"}
        )
        else 0.0
    )
    return {
        "schema_version": "eval-case-v1",
        "suite": "agentdojo_banking_security",
        "user_task_id": str(row["user_task_id"]),
        "injection_task_id": iid,
        "attack_variant": "important_instructions",
        "arm": arm,
        "backend": "real",
        "sample_index": int(row.get("sample_index", 0)),
        "evidence_label": str(row.get("evidence_label") or "REUSED"),
        "api_call_status": "REUSED",
        "reused_from": str(row["reused_from"]),
        "source_actual_cost_usd": _safe_float(row.get("source_actual_cost_usd")),
        "new_actual_cost_usd": 0.0,
        "security": security,
        "utility": None,
        "decision": decision,
        "decision_source": decision_source,
        "latency_ms": _safe_float(row.get("latency_ms")),
        "prompt_tokens": _safe_int(row.get("prompt_tokens")),
        "completion_tokens": _safe_int(row.get("completion_tokens")),
        "cost_usd": source_cost,
        "prevented_loss_usd": prevented,
        "per_guardian": [],
        "errors": [],
        "result_note": row.get("result_note"),
    }


@dataclass
class CostGuard:
    cap_usd: float
    per_case_estimate_usd: float

    actual_cost_usd: float = 0.0
    stop_reason: str | None = None

    @property
    def scenario_spike_threshold_usd(self) -> float:
        return round(self.per_case_estimate_usd * 3, 6)

    def record_row(self, row: dict[str, Any]) -> str | None:
        if str(row.get("api_call_status", "")).upper() != "EXECUTED":
            return self.stop_reason
        row_cost = _safe_float(row.get("cost_usd"))
        self.actual_cost_usd = round(self.actual_cost_usd + row_cost, 6)
        if row_cost > self.scenario_spike_threshold_usd:
            self.stop_reason = "SINGLE_SCENARIO_COST_SPIKE"
        if self.actual_cost_usd > self.cap_usd:
            self.stop_reason = "APPROVED_CAP_EXCEEDED"
        return self.stop_reason


@dataclass
class ProviderErrorTracker:
    max_errors: int = 3

    error_count: int = 0
    by_class: Counter[str] | None = None

    def __post_init__(self) -> None:
        if self.by_class is None:
            self.by_class = Counter()

    def record_errors(self, errors: list[dict[str, Any]]) -> str | None:
        for error in errors:
            self.error_count += 1
            error_class = str(error.get("error_class") or "ProviderError")
            self.by_class[error_class] += 1
        if self.error_count >= self.max_errors:
            return "REPEATED_PROVIDER_ERRORS"
        return None


def _error_row(exc: BaseException, *, context: str) -> dict[str, Any]:
    return {
        "error_class": exc.__class__.__name__,
        "error_message": str(exc)[:500],
        "context": context,
    }


def _arm_for_case(arm_key: str) -> tuple[Arm, str | None]:
    """Resolve one logical arm and return the concrete implementation label."""

    if arm_key == "A0b":
        return resolve_arms([A0B_PROVIDER_BASELINE])[0], A0B_PROVIDER_BASELINE
    if arm_key == "A2":
        return resolve_arms([arm_key], decide_mode="http")[0], None
    return resolve_arms([arm_key])[0], None


def _score_real_benign_cell(
    *,
    arm: Arm,
    suite: Any,
    user_task_id: str,
    worker: str,
    logdir: str,
    shield_wiring: ShieldWiring | None,
    guardian_evidence_drain: Any | None = None,
) -> HttpCellOutcome:
    from agentdojo.benchmark import benchmark_suite_without_injections
    from agentdojo.logging import OutputLogger
    from shield_eval.money_shot import _DecisionSink, _DecisionTap

    sink = _DecisionSink()
    user_task = suite.get_user_task_by_id(user_task_id)
    try:
        llm: Any = _real_llm_for_worker(worker)
    except ArmUnavailable as exc:
        return HttpCellOutcome(
            arm=arm.key,
            injection_task_id="",
            available=False,
            skip_reason=str(exc),
            security={},
            utility={},
            decisions={},
            decision_sources={},
            decision_mix={},
            latencies_ms=[],
            per_guardian=[],
        )
    try:
        pipeline = arm.build(llm, mock=False, shield_wiring=shield_wiring)
    except ArmUnavailable as exc:
        return HttpCellOutcome(
            arm=arm.key,
            injection_task_id="",
            available=False,
            skip_reason=str(exc),
            security={},
            utility={},
            decisions={},
            decision_sources={},
            decision_mix={},
            latencies_ms=[],
            per_guardian=[],
        )

    if arm.kind == "shield":
        tapped = type(pipeline)(
            [*pipeline.elements, _DecisionTap(sink)],
            shared_extra_args=getattr(pipeline, "_extra_args", None),
        )
        tapped.name = pipeline.name
        pipeline = tapped

    _ = user_task
    with OutputLogger(logdir):
        sr = benchmark_suite_without_injections(
            pipeline,
            suite,
            logdir=None,
            force_rerun=True,
            user_tasks=[user_task_id],
            benchmark_version=DEFAULT_BENCHMARK_VERSION,
        )

    if (
        guardian_evidence_drain is not None
        and _primary_decision_source(sink.decisions, sink.decision_sources) == "governance"
    ):
        for row in guardian_evidence_drain():
            rec_id = str(row.get("record_id", ""))
            guardian_name = str(row.get("guardian", "unknown"))
            seen_key = (rec_id, guardian_name)
            if seen_key in sink._seen_guardian_rows:
                continue
            sink._seen_guardian_rows.add(seen_key)
            sink.per_guardian.append(row)

    decision_mix: dict[str, int] = {}
    for decision in sink.decisions.values():
        decision_mix[decision] = decision_mix.get(decision, 0) + 1
    prompt_tokens, completion_tokens, cost_usd = _worker_usage_from_llm(llm, worker)
    return HttpCellOutcome(
        arm=arm.key,
        injection_task_id="",
        available=True,
        skip_reason=None,
        security={},
        utility=dict(sr["utility_results"]),
        decisions=dict(sink.decisions),
        decision_sources=dict(sink.decision_sources),
        decision_mix=decision_mix,
        latencies_ms=list(sink.latencies_ms),
        per_guardian=list(sink.per_guardian),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=round(cost_usd, 6),
        model_id=worker,
    )


def build_benign_case_row(
    *,
    suite: str,
    case: dict[str, Any],
    evidence_label: str,
    outcome: HttpCellOutcome | Any | None,
    backend: str,
    errors: list[dict[str, Any]],
    skip_reason: str | None = None,
) -> dict[str, Any]:
    uid = str(case["user_task_id"])
    arm = str(case["arm"])
    sample_index = int(case.get("sample_index", 0))
    if outcome is None or skip_reason:
        row: dict[str, Any] = {
            "schema_version": "eval-case-v1",
            "suite": suite,
            "user_task_id": uid,
            "benign_marker": True,
            "arm": arm,
            "backend": backend,
            "sample_index": sample_index,
            "evidence_label": "SKIPPED" if outcome is None else evidence_label,
            "api_call_status": "SKIPPED",
            "security": None,
            "utility": None,
            "decision": "SKIPPED",
            "decision_source": "skipped",
            "false_positive": None,
            "latency_ms": 0.0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0,
            "new_actual_cost_usd": 0.0,
            "per_guardian": [],
            "errors": list(errors),
        }
        if skip_reason:
            row["skip_reason"] = skip_reason
        return row

    decision = _primary_decision(outcome.decisions)
    decision_source = _primary_decision_source(outcome.decisions, outcome.decision_sources)
    utility = outcome.utility.get((uid, ""), None)
    per_guardian = (
        [_guardian_row_with_cost(row) for row in outcome.per_guardian]
        if decision_source == "governance"
        else []
    )
    guardian_prompt_tokens = sum(_safe_int(row.get("prompt_tokens")) for row in per_guardian)
    guardian_completion_tokens = sum(
        _safe_int(row.get("completion_tokens")) for row in per_guardian
    )
    guardian_cost_usd = sum(_safe_float(row.get("cost_usd")) for row in per_guardian)
    worker_prompt_tokens = _safe_int(getattr(outcome, "prompt_tokens", 0))
    worker_completion_tokens = _safe_int(getattr(outcome, "completion_tokens", 0))
    worker_cost_usd = _safe_float(getattr(outcome, "cost_usd", 0.0))
    if worker_cost_usd == 0.0:
        worker_cost_usd = _usage_cost_usd(
            getattr(outcome, "model_id", None),
            worker_prompt_tokens,
            worker_completion_tokens,
        )
    cost_usd = round(worker_cost_usd + guardian_cost_usd, 6)
    return {
        "schema_version": "eval-case-v1",
        "suite": suite,
        "user_task_id": uid,
        "benign_marker": True,
        "arm": arm,
        "backend": backend,
        "sample_index": sample_index,
        "evidence_label": evidence_label,
        "api_call_status": "EXECUTED",
        "security": None,
        "utility": bool(utility) if utility is not None else None,
        "decision": decision,
        "decision_source": decision_source,
        "false_positive": decision in FALSE_POSITIVE_DECISIONS,
        "latency_ms": (
            sum(outcome.latencies_ms) / len(outcome.latencies_ms)
            if outcome.latencies_ms
            else 0.0
        ),
        "prompt_tokens": worker_prompt_tokens + guardian_prompt_tokens,
        "completion_tokens": worker_completion_tokens + guardian_completion_tokens,
        "cost_usd": cost_usd,
        "new_actual_cost_usd": cost_usd,
        "per_guardian": per_guardian,
        "errors": list(errors),
    }


def _run_one_case(
    *,
    suite: Any,
    case: dict[str, Any],
    worker: str,
    model_router_profile: str,
    attack_variant: str | None,
    backend_suite_label: str,
) -> dict[str, Any]:
    arm_key = str(case["arm"])
    try:
        arm, implementation = _arm_for_case(arm_key)
    except (ValueError, ArmUnavailable) as exc:
        errors = [_error_row(exc, context=f"resolve_arm:{arm_key}")]
        return _skipped_row(case, backend_suite_label, attack_variant, errors, str(exc))

    tmpdir = tempfile.TemporaryDirectory(prefix="shield_eval_phase4_case_")
    harness: Any | None = None
    memory_tmp: tempfile.TemporaryDirectory[str] | None = None
    evidence_drain: _AsyncGuardianEvidenceDrain | None = None
    errors: list[dict[str, Any]] = []
    try:
        wiring: ShieldWiring | None = None
        if arm_key == "A2":
            harness = real_server_harness()
            memory, memory_tmp = _chroma_memory_for_eval()
            evidence_drain = _AsyncGuardianEvidenceDrain(
                harness,
                router=_provider_router_for_real(model_router_profile),
                memory=memory,
            )
            wiring = ShieldWiring(
                base_url=harness.base_url,
                agent_private_key_b64url=harness.agent_private_key_b64url,
                shared_extra_args={},
            )

        if case.get("benign_marker") is True:
            outcome = _score_real_benign_cell(
                arm=arm,
                suite=suite,
                user_task_id=str(case["user_task_id"]),
                worker=worker,
                logdir=tmpdir.name,
                shield_wiring=wiring,
                guardian_evidence_drain=(
                    evidence_drain.drain if evidence_drain is not None else None
                ),
            )
            if evidence_drain is not None:
                errors.extend(evidence_drain.errors)
            row = build_benign_case_row(
                suite=backend_suite_label,
                case=case,
                evidence_label="MEASURED-REAL-MODEL" if outcome.available else "SKIPPED",
                outcome=outcome,
                backend="real",
                errors=errors,
                skip_reason=outcome.skip_reason if not outcome.available else None,
            )
        else:
            outcome = _score_real_cell(
                arm=arm,
                suite=suite,
                user_task_ids=[str(case["user_task_id"])],
                injection_task_id=str(case["injection_task_id"]),
                attack_name=str(attack_variant or "important_instructions"),
                worker=worker,
                logdir=tmpdir.name,
                shield_wiring=wiring,
                guardian_evidence_drain=(
                    evidence_drain.drain if evidence_drain is not None else None
                ),
            )
            if evidence_drain is not None:
                errors.extend(evidence_drain.errors)
            row = _measured_case_row(
                suite=backend_suite_label,
                uid=str(case["user_task_id"]),
                iid=str(case["injection_task_id"]),
                attack_variant=str(attack_variant or "important_instructions"),
                arm=arm_key,
                evidence_label="MEASURED-REAL-MODEL" if outcome.available else "SKIPPED",
                outcome=outcome,
                skip_reason=outcome.skip_reason,
                backend="real",
            )
            row["sample_index"] = int(case.get("sample_index", 0))
            row["errors"] = errors
            row["new_actual_cost_usd"] = (
                row["cost_usd"] if row.get("api_call_status") == "EXECUTED" else 0.0
            )

        if implementation:
            row["arm_implementation"] = implementation
        return row
    except Exception as exc:  # noqa: BLE001 - preserve failed artifact row
        errors.append(_error_row(exc, context=f"case:{arm_key}"))
        return _failed_row(case, backend_suite_label, attack_variant, errors)
    finally:
        if evidence_drain is not None:
            errors.extend(evidence_drain.errors)
        if memory_tmp is not None:
            memory_tmp.cleanup()
        if harness is not None:
            harness.close()
        tmpdir.cleanup()


def _skipped_row(
    case: dict[str, Any],
    suite: str,
    attack_variant: str | None,
    errors: list[dict[str, Any]],
    skip_reason: str,
) -> dict[str, Any]:
    if case.get("benign_marker") is True:
        return build_benign_case_row(
            suite=suite,
            case=case,
            evidence_label="SKIPPED",
            outcome=None,
            backend="real",
            errors=errors,
            skip_reason=skip_reason,
        )
    row = _measured_case_row(
        suite=suite,
        uid=str(case["user_task_id"]),
        iid=str(case["injection_task_id"]),
        attack_variant=str(attack_variant or "important_instructions"),
        arm=str(case["arm"]),
        evidence_label="SKIPPED",
        outcome=None,
        skip_reason=skip_reason,
        backend="real",
    )
    row["sample_index"] = int(case.get("sample_index", 0))
    row["errors"] = errors
    row["new_actual_cost_usd"] = 0.0
    return row


def _failed_row(
    case: dict[str, Any],
    suite: str,
    attack_variant: str | None,
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    if case.get("benign_marker") is True:
        row = build_benign_case_row(
            suite=suite,
            case=case,
            evidence_label="FAILED",
            outcome=None,
            backend="real",
            errors=errors,
            skip_reason="provider execution failed",
        )
    else:
        row = _skipped_row(
            case,
            suite,
            attack_variant,
            errors,
            "provider execution failed",
        )
        row["evidence_label"] = "FAILED"
    row["api_call_status"] = "EXECUTED"
    row["new_actual_cost_usd"] = _safe_float(row.get("cost_usd"))
    return row


def _summarize_benign(
    *,
    manifest: dict[str, Any],
    cases: list[dict[str, Any]],
    guard: CostGuard,
    stop_reason: str | None,
) -> dict[str, Any]:
    scored = [row for row in cases if row.get("false_positive") is not None]
    false_positive_count = sum(1 for row in scored if row.get("false_positive") is True)
    utility_total = sum(1 for row in cases if row.get("utility") is not None)
    utility_ok = sum(1 for row in cases if row.get("utility") is True)
    prompt_tokens = sum(_safe_int(row.get("prompt_tokens")) for row in cases)
    completion_tokens = sum(_safe_int(row.get("completion_tokens")) for row in cases)
    actual_cost_usd = _sum_new_actual_cost(cases)
    return {
        "schema_version": "benchmark-20pct-benign-real.v1",
        "manifest_id": manifest["manifest_id"],
        "suite": manifest["suite"],
        "backend": "real",
        "api_call_status": "EXECUTED" if any(
            row.get("api_call_status") == "EXECUTED" for row in cases
        ) else "SKIPPED",
        "evidence_label": "MEASURED-REAL-MODEL",
        "case_row_count": len(cases),
        "executed_case_count": sum(1 for row in cases if row.get("api_call_status") == "EXECUTED"),
        "failed_case_count": sum(1 for row in cases if row.get("evidence_label") == "FAILED"),
        "false_positive_count": false_positive_count,
        "fpr": false_positive_count / len(scored) if scored else None,
        "utility_retention": utility_ok / utility_total if utility_total else None,
        "actual_cost_usd": actual_cost_usd,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "cost_guard": {
            "approved_cap_usd": guard.cap_usd,
            "actual_cost_usd": guard.actual_cost_usd,
            "per_case_estimate_usd": guard.per_case_estimate_usd,
            "scenario_spike_threshold_usd": guard.scenario_spike_threshold_usd,
            "stop_reason": stop_reason,
        },
    }


def _summarize_attack(
    *,
    manifest: dict[str, Any],
    cases: list[dict[str, Any]],
    guard: CostGuard,
    stop_reason: str | None,
) -> dict[str, Any]:
    new_actual_cost_usd = _sum_new_actual_cost(cases)
    reused_source_cost_usd = round(
        sum(
            _safe_float(row.get("cost_usd"))
            for row in cases
            if row.get("api_call_status") == "REUSED"
        ),
        6,
    )
    report = build_full_grid_metrics_report(
        suite=manifest["suite"],
        user_task_ids=sorted({str(row["user_task_id"]) for row in cases}),
        injection_task_ids=sorted(
            {str(row["injection_task_id"]) for row in cases if "injection_task_id" in row}
        ),
        arms=[str(arm) for arm in manifest["arms"]],
        backend="real",
        evidence_label="MEASURED-REAL-MODEL",
        cases=cases,
        errors=[error for row in cases for error in row.get("errors", [])],
    )
    report["schema_version"] = "benchmark-20pct-attack-real.v1"
    report["manifest_id"] = manifest["manifest_id"]
    report["case_row_count"] = len(cases)
    report["executed_case_count"] = sum(
        1 for row in cases if row.get("api_call_status") == "EXECUTED"
    )
    report["reused_case_count"] = sum(1 for row in cases if row.get("api_call_status") == "REUSED")
    report["failed_case_count"] = sum(1 for row in cases if row.get("evidence_label") == "FAILED")
    report["actual_cost_usd"] = new_actual_cost_usd
    report["new_actual_cost_usd"] = new_actual_cost_usd
    report["reused_source_cost_usd"] = reused_source_cost_usd
    report["cost_guard"] = {
        "approved_cap_usd": guard.cap_usd,
        "actual_cost_usd": guard.actual_cost_usd,
        "per_case_estimate_usd": guard.per_case_estimate_usd,
        "scenario_spike_threshold_usd": guard.scenario_spike_threshold_usd,
        "stop_reason": stop_reason,
    }
    return report


def _sum_new_actual_cost(cases: list[dict[str, Any]]) -> float:
    return round(
        sum(
            _safe_float(row.get("new_actual_cost_usd", row.get("cost_usd")))
            for row in cases
            if row.get("api_call_status") == "EXECUTED"
        ),
        6,
    )


def _combined_summary(
    *,
    attack_summary: dict[str, Any],
    benign_summary: dict[str, Any],
    guard: CostGuard,
    stop_reason: str | None,
    started_at: str,
    finished_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": "benchmark-20pct-combined-real.v1",
        "started_at": started_at,
        "finished_at": finished_at,
        "execution_order": ["benign", "attack"],
        "approved_phrase": "批准 20% benchmark cloud combined $20.61 cap $25",
        "api_call_status": "EXECUTED",
        "actual_new_cost_usd": guard.actual_cost_usd,
        "approved_cap_usd": guard.cap_usd,
        "stop_reason": stop_reason,
        "attack": {
            "case_row_count": attack_summary.get("case_row_count", 0),
            "executed_case_count": attack_summary.get("executed_case_count", 0),
            "reused_case_count": attack_summary.get("reused_case_count", 0),
            "failed_case_count": attack_summary.get("failed_case_count", 0),
            "new_actual_cost_usd": attack_summary.get("new_actual_cost_usd", 0.0),
        },
        "benign": {
            "case_row_count": benign_summary.get("case_row_count", 0),
            "executed_case_count": benign_summary.get("executed_case_count", 0),
            "failed_case_count": benign_summary.get("failed_case_count", 0),
            "actual_cost_usd": benign_summary.get("actual_cost_usd", 0.0),
            "fpr": benign_summary.get("fpr"),
        },
        "cost_guard": {
            "approved_cap_usd": guard.cap_usd,
            "actual_cost_usd": guard.actual_cost_usd,
            "per_case_estimate_usd": guard.per_case_estimate_usd,
            "scenario_spike_threshold_usd": guard.scenario_spike_threshold_usd,
            "stop_reason": stop_reason,
        },
    }


def _per_case_estimate(attack_estimate: dict[str, Any], benign_estimate: dict[str, Any]) -> float:
    attack_cases = int(attack_estimate["to_be_executed_case_count"])
    benign_cases = int(benign_estimate["to_be_executed_case_count"])
    attack_cost = float(attack_estimate["conservative_estimate_usd"])
    benign_cost = float(benign_estimate["conservative_estimate_usd"])
    total_cases = attack_cases + benign_cases
    if total_cases <= 0:
        raise ValueError("estimate artifacts must include executable cases")
    return round((attack_cost + benign_cost) / total_cases, 6)


def _persist_run(
    *,
    artifact_root: Path,
    attack_manifest: dict[str, Any],
    benign_manifest: dict[str, Any],
    attack_cases: list[dict[str, Any]],
    benign_cases: list[dict[str, Any]],
    guard: CostGuard,
    stop_reason: str | None,
    started_at: str,
    finished_at: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    benign_summary = _summarize_benign(
        manifest=benign_manifest,
        cases=benign_cases,
        guard=guard,
        stop_reason=stop_reason,
    )
    attack_summary = _summarize_attack(
        manifest=attack_manifest,
        cases=attack_cases,
        guard=guard,
        stop_reason=stop_reason,
    )
    combined = _combined_summary(
        attack_summary=attack_summary,
        benign_summary=benign_summary,
        guard=guard,
        stop_reason=stop_reason,
        started_at=started_at,
        finished_at=finished_at,
    )
    _write_json(artifact_root / "benign" / "cases.json", benign_cases)
    _write_json(artifact_root / "benign" / "summary.json", benign_summary)
    _write_json(artifact_root / "attack" / "cases.json", attack_cases)
    _write_json(artifact_root / "attack" / "summary.json", attack_summary)
    _write_json(artifact_root / "combined-summary.json", combined)
    return benign_summary, attack_summary, combined


def run_phase4(
    *,
    attack_manifest_path: Path = DEFAULT_ATTACK_MANIFEST,
    benign_manifest_path: Path = DEFAULT_BENIGN_MANIFEST,
    attack_estimate_path: Path = DEFAULT_ATTACK_ESTIMATE,
    benign_estimate_path: Path = DEFAULT_BENIGN_ESTIMATE,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
    cap_usd: float = DEFAULT_APPROVED_CAP_USD,
) -> dict[str, Any]:
    ensure_env_key_loaded(ANTHROPIC_ENV_KEY)
    if not os.environ.get(ANTHROPIC_ENV_KEY):
        raise RuntimeError(f"{ANTHROPIC_ENV_KEY} is required for approved Phase 4 execution")

    attack_manifest = _load_json(attack_manifest_path)
    benign_manifest = _load_json(benign_manifest_path)
    attack_estimate = _load_json(attack_estimate_path)
    benign_estimate = _load_json(benign_estimate_path)
    worker = str(attack_manifest["model_profile"]["worker_model"])
    model_router_profile = str(attack_manifest["model_profile"]["model_router_profile"])
    if worker != str(benign_manifest["model_profile"]["worker_model"]):
        raise ValueError("attack and benign manifests must use the same worker model")
    if model_router_profile != str(benign_manifest["model_profile"]["model_router_profile"]):
        raise ValueError("attack and benign manifests must use the same router profile")

    per_case_estimate = _per_case_estimate(attack_estimate, benign_estimate)
    guard = CostGuard(cap_usd=cap_usd, per_case_estimate_usd=per_case_estimate)
    error_tracker = ProviderErrorTracker()
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    attack_executable, attack_reused = expand_attack_manifest_cases(attack_manifest)
    benign_executable = [dict(row) for row in benign_manifest["cases"]]
    attack_cases = [normalize_reused_case_row(row) for row in attack_reused]
    benign_cases: list[dict[str, Any]] = []
    stop_reason: str | None = None

    banking_suite = _build_suite(DEFAULT_BENCHMARK_VERSION, "banking")
    artifact_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        artifact_root / "RUNNING.json",
        {
            "schema_version": "benchmark-20pct-phase4-running.v1",
            "started_at": started_at,
            "approved_cap_usd": cap_usd,
            "per_case_estimate_usd": per_case_estimate,
            "execution_order": ["benign", "attack"],
            "attack_to_execute": len(attack_executable),
            "attack_reused": len(attack_reused),
            "benign_to_execute": len(benign_executable),
        },
    )

    for case in benign_executable:
        row = _run_one_case(
            suite=banking_suite,
            case=case,
            worker=worker,
            model_router_profile=model_router_profile,
            attack_variant=None,
            backend_suite_label=benign_manifest["suite"],
        )
        benign_cases.append(row)
        stop_reason = guard.record_row(row)
        stop_reason = stop_reason or error_tracker.record_errors(row.get("errors", []))
        _persist_run(
            artifact_root=artifact_root,
            attack_manifest=attack_manifest,
            benign_manifest=benign_manifest,
            attack_cases=attack_cases,
            benign_cases=benign_cases,
            guard=guard,
            stop_reason=stop_reason,
            started_at=started_at,
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        print(
            "phase4 benign "
            f"{len(benign_cases)}/{len(benign_executable)} "
            f"arm={row.get('arm')} uid={row.get('user_task_id')} "
            f"decision={row.get('decision')} cost=${_safe_float(row.get('cost_usd')):.6f} "
            f"actual=${guard.actual_cost_usd:.6f}",
            flush=True,
        )
        if stop_reason:
            break

    if stop_reason is None:
        for case in attack_executable:
            row = _run_one_case(
                suite=banking_suite,
                case=case,
                worker=worker,
                model_router_profile=model_router_profile,
                attack_variant=str(attack_manifest["attack_variant"]),
                backend_suite_label=attack_manifest["suite"],
            )
            attack_cases.append(row)
            stop_reason = guard.record_row(row)
            stop_reason = stop_reason or error_tracker.record_errors(row.get("errors", []))
            _persist_run(
                artifact_root=artifact_root,
                attack_manifest=attack_manifest,
                benign_manifest=benign_manifest,
                attack_cases=attack_cases,
                benign_cases=benign_cases,
                guard=guard,
                stop_reason=stop_reason,
                started_at=started_at,
                finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
            print(
                "phase4 attack "
                f"{len(attack_cases) - len(attack_reused)}/{len(attack_executable)} "
                f"arm={row.get('arm')} uid={row.get('user_task_id')} "
                f"iid={row.get('injection_task_id')} sample={row.get('sample_index')} "
                f"decision={row.get('decision')} cost=${_safe_float(row.get('cost_usd')):.6f} "
                f"actual=${guard.actual_cost_usd:.6f}",
                flush=True,
            )
            if stop_reason:
                break

    finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    benign_summary, attack_summary, combined = _persist_run(
        artifact_root=artifact_root,
        attack_manifest=attack_manifest,
        benign_manifest=benign_manifest,
        attack_cases=attack_cases,
        benign_cases=benign_cases,
        guard=guard,
        stop_reason=stop_reason,
        started_at=started_at,
        finished_at=finished_at,
    )
    _write_json(
        artifact_root / "COMPLETED.json",
        {
            "schema_version": "benchmark-20pct-phase4-completed.v1",
            "finished_at": finished_at,
            "stop_reason": stop_reason,
            "actual_new_cost_usd": guard.actual_cost_usd,
            "artifact_paths": {
                "benign_cases": str(artifact_root / "benign" / "cases.json"),
                "benign_summary": str(artifact_root / "benign" / "summary.json"),
                "attack_cases": str(artifact_root / "attack" / "cases.json"),
                "attack_summary": str(artifact_root / "attack" / "summary.json"),
                "combined_summary": str(artifact_root / "combined-summary.json"),
            },
        },
    )
    return {
        "benign_summary": benign_summary,
        "attack_summary": attack_summary,
        "combined_summary": combined,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts/benchmark/run_20pct_provider.py")
    parser.add_argument("--attack-manifest", type=Path, default=DEFAULT_ATTACK_MANIFEST)
    parser.add_argument("--benign-manifest", type=Path, default=DEFAULT_BENIGN_MANIFEST)
    parser.add_argument("--attack-estimate", type=Path, default=DEFAULT_ATTACK_ESTIMATE)
    parser.add_argument("--benign-estimate", type=Path, default=DEFAULT_BENIGN_ESTIMATE)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--cap-usd", type=float, default=DEFAULT_APPROVED_CAP_USD)
    args = parser.parse_args(argv)
    try:
        result = run_phase4(
            attack_manifest_path=args.attack_manifest,
            benign_manifest_path=args.benign_manifest,
            attack_estimate_path=args.attack_estimate,
            benign_estimate_path=args.benign_estimate,
            artifact_root=args.artifact_root,
            cap_usd=args.cap_usd,
        )
    except (RealGovUnavailable, ArmUnavailable, RuntimeError, ValueError) as exc:
        print(f"phase4 benchmark failed before completion: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result["combined_summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
