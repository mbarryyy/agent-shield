"""Emit the Round 2 20% benchmark estimate without provider calls."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from shield_eval.metrics import build_real_runner_budget_artifact

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = (
    REPO_ROOT
    / "packages"
    / "shield-eval"
    / "src"
    / "shield_eval"
    / "scenarios"
    / "benchmark_20pct_20260525.json"
)
DEFAULT_BENIGN_MANIFEST = DEFAULT_MANIFEST.with_name("benchmark_20pct_benign_20260525.json")
DEFAULT_OUT = Path("/private/tmp/agent-shield-benchmark-20pct-estimate-20260525/estimate.json")
DEFAULT_BENIGN_OUT = Path(
    "/private/tmp/agent-shield-benchmark-20pct-benign-estimate-20260525/estimate.json"
)
DEFAULT_COMBINED_OUT = DEFAULT_BENIGN_OUT.with_name("combined-summary.json")
HISTORICAL_ACTUAL_USD = 0.044649
HISTORICAL_ESTIMATE_USD = 0.234216
UTILIZATION_SOURCE_ARTIFACT = "/private/tmp/agent-shield-cloud-rerun-latest-models-20260524/"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expect_list(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        raise ValueError(f"manifest field {key!r} must be a list")
    return value


def _validate_manifest(manifest: dict[str, Any]) -> None:
    pairs = _expect_list(manifest, "scenario_pairs")
    arms = _expect_list(manifest, "arms")
    samples = int(manifest.get("samples_per_pair", 0))
    if len(pairs) != 29:
        raise ValueError(f"expected 29 scenario pairs, got {len(pairs)}")
    if len(arms) != 5:
        raise ValueError(f"expected 5 logical arms, got {len(arms)}")
    if samples != 2:
        raise ValueError(f"expected samples_per_pair=2, got {samples}")
    users = {str(pair.get("user_task_id")) for pair in pairs if isinstance(pair, dict)}
    injections = {
        str(pair.get("injection_task_id")) for pair in pairs if isinstance(pair, dict)
    }
    expected_users = {f"user_task_{i}" for i in range(16)}
    expected_injections = {f"injection_task_{i}" for i in range(9)}
    if not expected_users.issubset(users):
        raise ValueError(f"manifest missing users: {sorted(expected_users - users)}")
    if not expected_injections.issubset(injections):
        raise ValueError(
            f"manifest missing injections: {sorted(expected_injections - injections)}"
        )


def _validate_benign_manifest(manifest: dict[str, Any]) -> None:
    cases = _expect_list(manifest, "cases")
    arms = [str(arm) for arm in _expect_list(manifest, "arms")]
    samples = int(manifest.get("samples_per_user_task", 0))
    users = {str(row.get("user_task_id")) for row in cases if isinstance(row, dict)}
    expected_users = {f"user_task_{i}" for i in range(16)}
    expected_count = len(expected_users) * len(arms) * samples
    if manifest.get("suite") != "agentdojo_banking_without_injections":
        raise ValueError("benign manifest must use agentdojo_banking_without_injections")
    if samples != 1:
        raise ValueError(f"expected samples_per_user_task=1, got {samples}")
    if len(arms) != 5:
        raise ValueError(f"expected 5 logical arms, got {len(arms)}")
    if len(cases) != expected_count:
        raise ValueError(f"expected {expected_count} benign cases, got {len(cases)}")
    if users != expected_users:
        raise ValueError(f"benign manifest users mismatch: {sorted(users ^ expected_users)}")
    for row in cases:
        if not isinstance(row, dict):
            raise ValueError("benign case rows must be objects")
        if row.get("benign_marker") is not True:
            raise ValueError("benign case row missing benign_marker=true")
        if "injection_task_id" in row:
            raise ValueError("benign case row must not contain injection_task_id")


def _budget_for_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    pairs = _expect_list(manifest, "scenario_pairs")
    arms = [str(arm) for arm in _expect_list(manifest, "arms")]
    profile = manifest.get("model_profile")
    if not isinstance(profile, dict):
        raise ValueError("manifest field 'model_profile' must be an object")
    return build_real_runner_budget_artifact(
        arms=arms,
        user_tasks=[f"selected_pair_{i:02d}" for i in range(len(pairs))],
        injection_tasks=["selected_pair"],
        samples=int(manifest["samples_per_pair"]),
        serialized_prompt_chars=3000,
        max_output_tokens=2000,
        model=str(profile["worker_model"]),
        model_router_profile=str(profile["model_router_profile"]),
        hard_cap_usd=999.0,
        planning_threshold_usd=999.0,
        allow_plan_shrink=False,
    )


def _budget_for_benign_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    cases = _expect_list(manifest, "cases")
    arms = [str(arm) for arm in _expect_list(manifest, "arms")]
    profile = manifest.get("model_profile")
    if not isinstance(profile, dict):
        raise ValueError("manifest field 'model_profile' must be an object")
    users = sorted({str(row["user_task_id"]) for row in cases if isinstance(row, dict)})
    return build_real_runner_budget_artifact(
        arms=arms,
        user_tasks=users,
        injection_tasks=["benign_marker"],
        samples=int(manifest["samples_per_user_task"]),
        serialized_prompt_chars=3000,
        max_output_tokens=2000,
        model=str(profile["worker_model"]),
        model_router_profile=str(profile["model_router_profile"]),
        hard_cap_usd=999.0,
        planning_threshold_usd=999.0,
        allow_plan_shrink=False,
    )


def _benign_add_on_estimate(manifest: dict[str, Any]) -> dict[str, Any] | None:
    add_on = manifest.get("benign_subset_add_on")
    if not isinstance(add_on, dict) or not add_on.get("enabled_by_phase0"):
        return None
    profile = manifest.get("model_profile")
    if not isinstance(profile, dict):
        raise ValueError("manifest field 'model_profile' must be an object")
    user_task_ids = [str(user) for user in _expect_list(add_on, "user_task_ids")]
    budget = build_real_runner_budget_artifact(
        arms=[str(arm) for arm in _expect_list(add_on, "arms")],
        user_tasks=user_task_ids,
        injection_tasks=["no_injection"],
        samples=int(add_on.get("samples", 1)),
        serialized_prompt_chars=3000,
        max_output_tokens=2000,
        model=str(profile["worker_model"]),
        model_router_profile=str(profile["model_router_profile"]),
        hard_cap_usd=999.0,
        planning_threshold_usd=999.0,
        allow_plan_shrink=False,
    )
    return {
        "included_in_attack_arm_case_budget": False,
        "case_count": budget["requested_units"],
        "conservative_estimate_usd": budget["requested_cost_usd"],
        "purpose": add_on.get("purpose"),
    }


def _base_estimate_fields(
    *,
    manifest: dict[str, Any],
    manifest_path: Path,
    budget: dict[str, Any],
    full_case_count: int,
    reused_case_count: int,
    conservative_estimate: float,
    mean_prediction: float,
) -> dict[str, Any]:
    utilization = HISTORICAL_ACTUAL_USD / HISTORICAL_ESTIMATE_USD
    to_be_executed = full_case_count - reused_case_count
    return {
        "manifest_id": manifest["manifest_id"],
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "api_call_status": "SKIPPED",
        "api_call_reason": "estimate only; no Anthropic/OpenAI/provider API call was made",
        "suite": manifest["suite"],
        "arms": manifest["arms"],
        "full_manifest_case_count": full_case_count,
        "reused_case_count": reused_case_count,
        "to_be_executed_case_count": to_be_executed,
        "model_profile": manifest["model_profile"],
        "conservative_estimate_usd": conservative_estimate,
        "mean_prediction_usd": mean_prediction,
        "historical_utilization_rate": round(utilization, 6),
        "utilization_source_artifact": UTILIZATION_SOURCE_ARTIFACT,
        "utilization_calculation": {
            "actual_usd": HISTORICAL_ACTUAL_USD,
            "estimate_usd": HISTORICAL_ESTIMATE_USD,
            "formula": "actual_usd / estimate_usd",
        },
        "cost_basis": {
            "estimator": "shield_eval.metrics.build_real_runner_budget_artifact",
            "serialized_prompt_chars": 3000,
            "max_output_tokens": 2000,
            "price_source": budget["price_source"],
            "formula": budget["formula"],
        },
        "estimator_rollup": {
            "requested_input_tokens": budget["requested_input_tokens"],
            "requested_output_tokens": budget["requested_output_tokens"],
            "worker_estimate": budget["worker_estimate"],
            "per_guardian_cost_estimates": budget["per_guardian_cost_estimates"],
        },
    }


def build_estimate(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    _validate_manifest(manifest)
    budget = _budget_for_manifest(manifest)
    reused_rows = _expect_list(manifest, "reused_rows")
    full_case_count = int(budget["requested_units"])
    reused_case_count = len(reused_rows)
    to_be_executed = full_case_count - reused_case_count
    if to_be_executed <= 0:
        raise ValueError("to-be-executed case count must be positive")
    full_estimate = float(budget["requested_cost_usd"])
    per_case_estimate = full_estimate / full_case_count
    conservative_estimate = round(per_case_estimate * to_be_executed, 6)
    utilization = HISTORICAL_ACTUAL_USD / HISTORICAL_ESTIMATE_USD
    mean_prediction = round(conservative_estimate * utilization, 6)

    return {
        "schema_version": "benchmark-20pct-estimate.v1",
        **_base_estimate_fields(
            manifest=manifest,
            manifest_path=manifest_path,
            budget=budget,
            full_case_count=full_case_count,
            reused_case_count=reused_case_count,
            conservative_estimate=conservative_estimate,
            mean_prediction=mean_prediction,
        ),
        "attack_variant": manifest["attack_variant"],
        "samples_per_pair": manifest["samples_per_pair"],
        "scenario_pair_count": len(manifest["scenario_pairs"]),
        "selected_fraction_of_full_design": manifest["scope"][
            "selected_fraction_of_full_design"
        ],
        "reused_rows": reused_rows,
        "reused_artifact_paths": sorted({str(row["reused_from"]) for row in reused_rows}),
        "full_manifest_conservative_estimate_usd": round(full_estimate, 6),
        "per_arm_case_conservative_estimate_usd": round(per_case_estimate, 6),
        "recommended_hard_cap_usd": 20.0,
        "benign_subset_add_on": _benign_add_on_estimate(manifest),
    }


def build_benign_estimate(manifest_path: Path = DEFAULT_BENIGN_MANIFEST) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    _validate_benign_manifest(manifest)
    budget = _budget_for_benign_manifest(manifest)
    reused_rows = _expect_list(manifest, "reused_rows")
    full_case_count = int(budget["requested_units"])
    reused_case_count = len(reused_rows)
    conservative_estimate = round(float(budget["requested_cost_usd"]), 6)
    utilization = HISTORICAL_ACTUAL_USD / HISTORICAL_ESTIMATE_USD
    mean_prediction = round(conservative_estimate * utilization, 6)
    return {
        "schema_version": "benchmark-20pct-benign-estimate.v1",
        **_base_estimate_fields(
            manifest=manifest,
            manifest_path=manifest_path,
            budget=budget,
            full_case_count=full_case_count,
            reused_case_count=reused_case_count,
            conservative_estimate=conservative_estimate,
            mean_prediction=mean_prediction,
        ),
        "benign_marker": True,
        "samples_per_user_task": manifest["samples_per_user_task"],
        "user_task_count": 16,
        "case_count": len(manifest["cases"]),
        "reused_rows": reused_rows,
        "reused_artifact_paths": [],
        "recommended_hard_cap_usd": 5.0,
        "execution_recommendation": {
            "run_shape": (
                "separate benign sub-run and artifact inside the same approved "
                "Phase 4 execution"
            ),
            "order": "run benign add-on first, then attack subset",
            "reason": (
                "Benign is lower cost and validates utility/FPR plumbing before the "
                "higher-risk attack spend. Separate artifacts keep FPR and ASR "
                "evidence independently auditable while sharing the same cap guard."
            ),
        },
    }


def build_combined_summary(
    attack: dict[str, Any], benign: dict[str, Any]
) -> dict[str, Any]:
    combined_conservative = round(
        float(attack["conservative_estimate_usd"])
        + float(benign["conservative_estimate_usd"]),
        6,
    )
    combined_mean = round(
        float(attack["mean_prediction_usd"]) + float(benign["mean_prediction_usd"]),
        6,
    )
    return {
        "schema_version": "benchmark-20pct-combined-summary.v1",
        "api_call_status": "SKIPPED",
        "api_call_reason": "summary only; no Anthropic/OpenAI/provider API call was made",
        "attack_subset": {
            "manifest_id": attack["manifest_id"],
            "conservative_estimate_usd": attack["conservative_estimate_usd"],
            "mean_prediction_usd": attack["mean_prediction_usd"],
            "to_be_executed_case_count": attack["to_be_executed_case_count"],
            "reused_case_count": attack["reused_case_count"],
        },
        "benign_add_on": {
            "manifest_id": benign["manifest_id"],
            "conservative_estimate_usd": benign["conservative_estimate_usd"],
            "mean_prediction_usd": benign["mean_prediction_usd"],
            "to_be_executed_case_count": benign["to_be_executed_case_count"],
            "reused_case_count": benign["reused_case_count"],
        },
        "combined_conservative_estimate_usd": combined_conservative,
        "combined_mean_prediction_usd": combined_mean,
        "recommended_combined_cap_usd": 25.0,
        "execution_plan": {
            "single_phase4_approval": True,
            "artifact_shape": "two sub-run artifacts plus one combined summary",
            "recommended_order": ["benign_add_on", "attack_subset"],
            "cost_guard_reason": (
                "Running benign first consumes the smaller budget item and can stop "
                "early if utility/FPR plumbing is broken. The attack subset then "
                "runs with the remaining approved cap and preserves its own ASR "
                "artifact."
            ),
            "stop_policy": [
                "stop if combined actual cost exceeds approved cap",
                "stop if a single scenario exceeds 3x its per-scenario estimate",
                "stop if repeated provider errors appear",
            ],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--benign-manifest", type=Path, default=DEFAULT_BENIGN_MANIFEST)
    parser.add_argument("--benign-out", type=Path, default=None)
    parser.add_argument("--combined-out", type=Path, default=None)
    args = parser.parse_args(argv)

    estimate = build_estimate(args.manifest)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(estimate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "estimate_only "
        f"manifest_cases={estimate['full_manifest_case_count']} "
        f"provider_executed={estimate['to_be_executed_case_count']} "
        f"conservative=${estimate['conservative_estimate_usd']:.6f} "
        f"mean_prediction=${estimate['mean_prediction_usd']:.6f} "
        f"out={args.out}"
    )
    if args.benign_out or args.combined_out:
        benign = build_benign_estimate(args.benign_manifest)
        benign_out = args.benign_out or DEFAULT_BENIGN_OUT
        benign_out.parent.mkdir(parents=True, exist_ok=True)
        benign_out.write_text(
            json.dumps(benign, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        combined = build_combined_summary(estimate, benign)
        combined_out = args.combined_out or DEFAULT_COMBINED_OUT
        combined_out.parent.mkdir(parents=True, exist_ok=True)
        combined_out.write_text(
            json.dumps(combined, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(
            "benign_estimate_only "
            f"manifest_cases={benign['full_manifest_case_count']} "
            f"provider_executed={benign['to_be_executed_case_count']} "
            f"conservative=${benign['conservative_estimate_usd']:.6f} "
            f"mean_prediction=${benign['mean_prediction_usd']:.6f} "
            f"out={benign_out}"
        )
        print(
            "combined_estimate_only "
            f"conservative=${combined['combined_conservative_estimate_usd']:.6f} "
            f"mean_prediction=${combined['combined_mean_prediction_usd']:.6f} "
            f"recommended_cap=${combined['recommended_combined_cap_usd']:.2f} "
            f"out={combined_out}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
