"""Operational air-gap verifier for the local-serving governance profile.

The verifier is deliberately conservative: deterministic import/config guards
can pass on any host, but a signed ``egress=0`` attestation is emitted only when
the host egress-deny smoke check actually runs and proves egress is blocked.
Unsupported host capabilities produce SKIP, not PASS.
"""

from __future__ import annotations

import ast
import os
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, TextIO
from urllib.parse import urlparse

import yaml
from shield_sdk import crypto
from shield_sdk.schema import ServedVia

from shield_governance.model_router import ShieldModelRouter

GOVERNANCE_SOURCE_ROOT = Path(__file__).parent
LOCAL_PROFILE_PATH = GOVERNANCE_SOURCE_ROOT / "config" / "models.local.yaml"

_LOCAL_ENDPOINT_SUFFIXES = (".svc", ".cluster.local", ".local")
_LOCAL_ENDPOINT_HOSTS = {"localhost", "127.0.0.1", "::1"}
_DIRECT_CLIENT_MODULES = {
    "anthropic",
    "langchain_anthropic",
    "langchain_openai",
    "openai",
}
_REMOTE_INVARIANT_NAMES = {"Policy", "RemotePolicy"}
_HIDDEN_TELEMETRY_MODULES = {"langsmith", "mlflow", "wandb"}
_TRUTHY = {"1", "true", "yes", "on"}


class CheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: CheckStatus
    message: str


@dataclass(frozen=True, slots=True)
class VerificationReport:
    result: Literal["PASS", "FAIL", "SKIPPED"]
    checks: tuple[CheckResult, ...]
    attestation: dict[str, object] | None


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _pass(name: str, message: str) -> CheckResult:
    return CheckResult(name=name, status=CheckStatus.PASS, message=message)


def _fail(name: str, message: str) -> CheckResult:
    return CheckResult(name=name, status=CheckStatus.FAIL, message=message)


def _skip(name: str, message: str) -> CheckResult:
    return CheckResult(name=name, status=CheckStatus.SKIP, message=message)


def _load_local_profile(path: Path = LOCAL_PROFILE_PATH) -> dict[str, Any]:
    parsed = yaml.safe_load(path.read_text())
    if not isinstance(parsed, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return parsed


def validate_local_profile(path: Path = LOCAL_PROFILE_PATH) -> list[CheckResult]:
    return validate_local_profile_config(_load_local_profile(path))


def validate_local_profile_config(cfg: Mapping[str, Any]) -> list[CheckResult]:
    results: list[CheckResult] = []

    try:
        router = ShieldModelRouter(dict(cfg))
    except (TypeError, ValueError) as exc:
        return [_fail("local_profile", f"local profile config is invalid: {exc}")]

    if router.profile != "local":
        results.append(_fail("local_profile", f"profile must be 'local', got {router.profile!r}"))
    else:
        results.append(_pass("local_profile", "models.local.yaml declares profile=local"))

    route_failures: list[str] = []
    for role in router.roles:
        resolved = router.for_role(role)
        if not resolved.enabled:
            continue
        if resolved.provider not in {"local", "openai_compat"}:
            route_failures.append(f"{role}: provider={resolved.provider}")
            continue
        if resolved.served_via is not ServedVia.LOCAL:
            route_failures.append(f"{role}: served_via={resolved.served_via.value}")
        if resolved.provider == "openai_compat":
            if not resolved.base_url or not _is_local_endpoint(resolved.base_url):
                route_failures.append(f"{role}: base_url={resolved.base_url!r}")
            if resolved.api_key_env in {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"}:
                route_failures.append(f"{role}: api_key_env={resolved.api_key_env}")

    if route_failures:
        results.append(
            _fail(
                "local_model_routes",
                "local profile has non-local model routes: " + "; ".join(route_failures),
            )
        )
    else:
        results.append(
            _pass(
                "local_model_routes",
                "all enabled model-backed roles resolve to local/openai_compat endpoints",
            )
        )

    results.extend(_validate_air_gap_telemetry_config(cfg))
    return results


def _is_local_endpoint(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = parsed.hostname
    if parsed.scheme != "http" or host is None:
        return False
    return (
        host in _LOCAL_ENDPOINT_HOSTS
        or host.endswith(_LOCAL_ENDPOINT_SUFFIXES)
        or host.startswith("10.")
        or host.startswith("192.168.")
        or _is_172_private(host)
    )


def _is_172_private(host: str) -> bool:
    parts = host.split(".")
    if len(parts) != 4 or parts[0] != "172":
        return False
    try:
        second = int(parts[1])
    except ValueError:
        return False
    return 16 <= second <= 31


def _validate_air_gap_telemetry_config(cfg: Mapping[str, Any]) -> list[CheckResult]:
    air_gap = cfg.get("air_gap")
    telemetry = air_gap.get("telemetry") if isinstance(air_gap, dict) else None
    if not isinstance(telemetry, dict):
        return [
            _fail(
                "chroma_telemetry",
                "models.local.yaml must define air_gap.telemetry",
            )
        ]

    results: list[CheckResult] = []
    if telemetry.get("chroma_anonymized_telemetry") is False:
        results.append(_pass("chroma_telemetry", "Chroma anonymized telemetry disabled"))
    else:
        results.append(
            _fail(
                "chroma_telemetry",
                "air_gap.telemetry.chroma_anonymized_telemetry must be false",
            )
        )

    if (
        telemetry.get("langsmith_tracing") is False
        and telemetry.get("langchain_tracing_v2") is False
    ):
        results.append(_pass("langsmith_telemetry", "LangSmith/LangChain tracing disabled"))
    else:
        results.append(
            _fail(
                "langsmith_telemetry",
                "LangSmith/LangChain tracing must be disabled in the local profile",
            )
        )

    if (
        telemetry.get("huggingface_hub_offline") is True
        and telemetry.get("transformers_offline") is True
    ):
        results.append(_pass("offline_transformers", "HF Hub and Transformers offline mode set"))
    else:
        results.append(
            _fail(
                "offline_transformers",
                "HF_HUB_OFFLINE and TRANSFORMERS_OFFLINE must be true in the local profile",
            )
        )
    return results


def scan_source_tree(root: Path = GOVERNANCE_SOURCE_ROOT) -> list[CheckResult]:
    direct_client_violations: list[str] = []
    invariant_violations: list[str] = []
    hidden_telemetry_violations: list[str] = []

    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(root)
        try:
            tree = ast.parse(path.read_text(), filename=str(rel))
        except SyntaxError as exc:
            direct_client_violations.append(f"{rel}:{exc.lineno or 1} cannot parse source")
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name
                    if _is_direct_client_import(module) and path.name != "model_router.py":
                        direct_client_violations.append(
                            f"{rel}:{node.lineno} imports cloud client module "
                            f"{_client_root(module)!r} outside model_router.py"
                        )
                    if _is_hidden_telemetry_import(module):
                        hidden_telemetry_violations.append(
                            f"{rel}:{node.lineno} imports hidden telemetry module "
                            f"{_client_root(module)!r}"
                        )
                    if _is_remote_invariant_module_import(module):
                        invariant_violations.append(
                            f"{rel}:{node.lineno} imports remote Invariant Policy; "
                            "use LocalPolicy only"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _is_direct_client_import(module) and path.name != "model_router.py":
                    direct_client_violations.append(
                        f"{rel}:{node.lineno} imports cloud client module "
                        f"{_client_root(module)!r} outside model_router.py"
                    )
                if _is_hidden_telemetry_import(module):
                    hidden_telemetry_violations.append(
                        f"{rel}:{node.lineno} imports hidden telemetry module "
                        f"{_client_root(module)!r}"
                    )
                if module.startswith("invariant"):
                    for alias in node.names:
                        if alias.name in _REMOTE_INVARIANT_NAMES:
                            invariant_violations.append(
                                f"{rel}:{node.lineno} imports remote Invariant "
                                f"{alias.name}; use LocalPolicy only"
                            )

    return [
        _source_result(
            "direct_cloud_client_imports",
            direct_client_violations,
            "no direct Anthropic/OpenAI client imports outside ShieldModelRouter",
        ),
        _source_result(
            "invariant_remote_policy_imports",
            invariant_violations,
            "no remote Invariant Policy imports; LocalPolicy only",
        ),
        _source_result(
            "hidden_telemetry_imports",
            hidden_telemetry_violations,
            "no LangSmith/W&B/MLflow telemetry imports in governance source",
        ),
    ]


def _source_result(name: str, violations: Sequence[str], pass_message: str) -> CheckResult:
    if violations:
        return _fail(name, "; ".join(violations))
    return _pass(name, pass_message)


def _client_root(module: str) -> str:
    if module.startswith("langchain_"):
        return module.split(".", 1)[0]
    return module.split(".", 1)[0]


def _is_direct_client_import(module: str) -> bool:
    root = _client_root(module)
    return root in _DIRECT_CLIENT_MODULES


def _is_hidden_telemetry_import(module: str) -> bool:
    return _client_root(module) in _HIDDEN_TELEMETRY_MODULES


def _is_remote_invariant_module_import(module: str) -> bool:
    if not module.startswith("invariant"):
        return False
    parts = set(module.split("."))
    return bool(parts & _REMOTE_INVARIANT_NAMES)


def validate_runtime_telemetry_env(env: Mapping[str, str] | None = None) -> list[CheckResult]:
    active_env = os.environ if env is None else env
    results: list[CheckResult] = []

    if _env_truthy(active_env, "ANONYMIZED_TELEMETRY"):
        results.append(
            _fail("runtime_chroma_telemetry", "ANONYMIZED_TELEMETRY enables Chroma telemetry")
        )
    else:
        results.append(_pass("runtime_chroma_telemetry", "Chroma telemetry not enabled in env"))

    tracing_keys = ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2")
    enabled = [key for key in tracing_keys if _env_truthy(active_env, key)]
    if enabled:
        results.append(
            _fail(
                "runtime_langsmith_telemetry",
                "LangSmith/LangChain tracing enabled by env key(s): " + ", ".join(enabled),
            )
        )
    else:
        results.append(
            _pass("runtime_langsmith_telemetry", "LangSmith/LangChain tracing not enabled in env")
        )
    return results


def _env_truthy(env: Mapping[str, str], key: str) -> bool:
    return env.get(key, "").strip().lower() in _TRUTHY


def detect_host_egress_smoke(
    *,
    system_name: str | None = None,
    command_exists: Callable[[str], str | None] = shutil.which,
    runner: CommandRunner | None = None,
) -> CheckResult:
    system = system_name or platform.system()
    if system == "Darwin":
        return _skip(
            "host_egress_smoke",
            "SKIP_HOST_UNSUPPORTED: egress-deny smoke unavailable on Darwin",
        )
    if system != "Linux":
        return _skip(
            "host_egress_smoke",
            f"SKIP_HOST_UNSUPPORTED: egress-deny smoke unavailable on {system}",
        )
    if command_exists("unshare") is None:
        return _skip(
            "host_egress_smoke",
            "SKIP_HOST_UNSUPPORTED: egress-deny smoke requires Linux unshare",
        )

    run = runner or _run_command
    capability = run(["unshare", "-rn", "true"])
    if capability.returncode != 0:
        return _skip(
            "host_egress_smoke",
            "SKIP_HOST_UNSUPPORTED: egress-deny smoke requires unprivileged network namespace",
        )

    probe = run(
        [
            "unshare",
            "-rn",
            sys.executable,
            "-c",
            ("import socket; socket.create_connection(('1.1.1.1', 443), timeout=2)"),
        ]
    )
    if probe.returncode == 0:
        return _fail("host_egress_smoke", "egress reachable from isolated network namespace")
    return _pass("host_egress_smoke", "egress denied by isolated network namespace")


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(list(command), returncode=126, stderr=str(exc))


def run_air_gap_verification(
    *,
    egress_probe: Callable[[], CheckResult] = detect_host_egress_smoke,
    signing_key_b64url: str | None = None,
    signing_key_loader: Callable[[], str | None] | None = None,
    env: Mapping[str, str] | None = None,
) -> VerificationReport:
    checks = [
        *validate_local_profile(),
        *scan_source_tree(),
        *validate_runtime_telemetry_env(env),
        egress_probe(),
    ]

    attestation: dict[str, object] | None = None
    if any(check.status == CheckStatus.FAIL for check in checks):
        result: Literal["PASS", "FAIL", "SKIPPED"] = "FAIL"
    elif checks[-1].status == CheckStatus.SKIP:
        result = "SKIPPED"
    else:
        key = signing_key_b64url
        if key is None and signing_key_loader is not None:
            key = signing_key_loader()
        if key is None:
            checks.append(
                _fail(
                    "attestation_signature",
                    "SHIELD_AIR_GAP_ATTESTATION_KEY is required after egress=0 proof",
                )
            )
            result = "FAIL"
        else:
            attestation = _sign_attestation(checks, key)
            result = "PASS"

    return VerificationReport(result=result, checks=tuple(checks), attestation=attestation)


def _sign_attestation(checks: Sequence[CheckResult], signing_key_b64url: str) -> dict[str, object]:
    issued_at = int(time.time() * 1000)
    payload: dict[str, object] = {
        "attestation_version": "air-gap-v1",
        "egress": 0,
        "issued_at": issued_at,
        "profile": "local",
        "checks": [
            {"name": check.name, "status": check.status.value, "message": check.message}
            for check in checks
        ],
    }
    signing_bytes = crypto.jcs_canonicalize(payload).encode("utf-8")
    payload["algorithm"] = "ed25519"
    payload["public_key"] = crypto.get_public_key_base64url(signing_key_b64url)
    payload["signature"] = crypto.sign_ed25519(signing_key_b64url, signing_bytes)
    return payload


def format_report(report: VerificationReport) -> str:
    lines = ["AIR_GAP_VERIFY_REPORT", f"RESULT: {report.result}"]
    for check in report.checks:
        if check.message.startswith("SKIP_HOST_UNSUPPORTED:"):
            lines.append(check.message)
        else:
            lines.append(f"{check.status.value}: {check.name}: {check.message}")
    if report.attestation is None:
        egress = next((check for check in report.checks if check.name == "host_egress_smoke"), None)
        if egress is not None and egress.status == CheckStatus.PASS:
            lines.append("ATTESTATION_SKIPPED: missing attestation signing key")
        else:
            lines.append("ATTESTATION_SKIPPED: egress=0 host smoke not run")
    else:
        lines.append(f"SIGNED_ATTESTATION: egress=0 signature={report.attestation['signature']}")
    return "\n".join(lines) + "\n"


def main(*, stdout: TextIO = sys.stdout) -> int:
    report = run_air_gap_verification(
        signing_key_loader=lambda: os.environ.get("SHIELD_AIR_GAP_ATTESTATION_KEY")
    )
    stdout.write(format_report(report))
    return 1 if report.result == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
