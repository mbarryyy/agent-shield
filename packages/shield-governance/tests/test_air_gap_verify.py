"""Module F: operational air-gap verifier.

These tests pin the verifier as an honest proof surface: deterministic local
guards may pass on any host, but egress-deny evidence is only a signed
attestation when a real host smoke check runs and proves egress is blocked.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from shield_governance import air_gap_verify


def test_local_profile_config_routes_every_model_role_locally() -> None:
    results = air_gap_verify.validate_local_profile()

    assert {r.name for r in results} >= {
        "local_profile",
        "local_model_routes",
        "chroma_telemetry",
        "langsmith_telemetry",
        "offline_transformers",
    }
    assert all(r.status == air_gap_verify.CheckStatus.PASS for r in results)


def test_local_profile_config_rejects_cloud_provider_route() -> None:
    cfg_path = air_gap_verify.LOCAL_PROFILE_PATH
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["guardians"]["evaluator"]["provider"] = "anthropic"
    cfg["guardians"]["evaluator"]["served_via"] = "cloud"

    results = air_gap_verify.validate_local_profile_config(cfg)

    failed = [r for r in results if r.status == air_gap_verify.CheckStatus.FAIL]
    assert failed
    assert "evaluator" in failed[0].message
    assert "anthropic" in failed[0].message


def test_source_guard_rejects_direct_cloud_clients_outside_router(tmp_path: Path) -> None:
    (tmp_path / "bad_client.py").write_text("from anthropic import Anthropic\n")

    results = air_gap_verify.scan_source_tree(tmp_path)

    assert (
        air_gap_verify.CheckResult(
            name="direct_cloud_client_imports",
            status=air_gap_verify.CheckStatus.FAIL,
            message=(
                "bad_client.py:1 imports cloud client module 'anthropic' outside model_router.py"
            ),
        )
        in results
    )


def test_source_guard_allows_direct_cloud_client_imports_in_model_router(tmp_path: Path) -> None:
    (tmp_path / "model_router.py").write_text("from openai import OpenAI\n")

    results = air_gap_verify.scan_source_tree(tmp_path)

    assert (
        air_gap_verify.CheckResult(
            name="direct_cloud_client_imports",
            status=air_gap_verify.CheckStatus.PASS,
            message="no direct Anthropic/OpenAI client imports outside ShieldModelRouter",
        )
        in results
    )


def test_source_guard_rejects_invariant_remote_policy(tmp_path: Path) -> None:
    (tmp_path / "bad_policy.py").write_text("from invariant.analyzer import Policy\n")

    results = air_gap_verify.scan_source_tree(tmp_path)

    assert (
        air_gap_verify.CheckResult(
            name="invariant_remote_policy_imports",
            status=air_gap_verify.CheckStatus.FAIL,
            message="bad_policy.py:1 imports remote Invariant Policy; use LocalPolicy only",
        )
        in results
    )


def test_current_governance_source_passes_import_guards() -> None:
    results = air_gap_verify.scan_source_tree(air_gap_verify.GOVERNANCE_SOURCE_ROOT)

    assert all(r.status == air_gap_verify.CheckStatus.PASS for r in results)


def test_darwin_egress_probe_is_skip_not_pass() -> None:
    result = air_gap_verify.detect_host_egress_smoke(system_name="Darwin")

    assert result == air_gap_verify.CheckResult(
        name="host_egress_smoke",
        status=air_gap_verify.CheckStatus.SKIP,
        message="SKIP_HOST_UNSUPPORTED: egress-deny smoke unavailable on Darwin",
    )


def test_skipped_egress_report_never_contains_signed_attestation() -> None:
    report = air_gap_verify.run_air_gap_verification(
        egress_probe=lambda: air_gap_verify.CheckResult(
            name="host_egress_smoke",
            status=air_gap_verify.CheckStatus.SKIP,
            message="SKIP_HOST_UNSUPPORTED: egress-deny smoke unavailable on Darwin",
        ),
        signing_key_b64url="A" * 43,
    )

    assert report.result == "SKIPPED"
    assert report.attestation is None
    assert "ATTESTATION_SKIPPED: egress=0 host smoke not run" in air_gap_verify.format_report(
        report
    )


def test_signed_attestation_requires_passing_egress_smoke() -> None:
    report = air_gap_verify.run_air_gap_verification(
        egress_probe=lambda: air_gap_verify.CheckResult(
            name="host_egress_smoke",
            status=air_gap_verify.CheckStatus.PASS,
            message="egress denied by isolated network namespace",
        ),
        signing_key_b64url="A" * 43,
    )

    assert report.result == "PASS"
    assert report.attestation is not None
    assert report.attestation["egress"] == 0
    assert isinstance(report.attestation["signature"], str)
    assert "SIGNED_ATTESTATION: egress=0" in air_gap_verify.format_report(report)
