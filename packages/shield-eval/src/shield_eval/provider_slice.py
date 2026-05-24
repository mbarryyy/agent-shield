"""Provider-slice profile helpers.

These helpers are eval-owned and do not mutate the default governance cloud
profile. They describe the first approved low-cost slice only.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

HAIKU_PROVIDER_SLICE_PROFILE = "provider-slice-haiku"
HAIKU_PROVIDER_SLICE_MODEL = "claude-haiku-4-5-20251001"
PROVIDER_SLICE_APPROVAL_THRESHOLD_USD = 3.0
CLOUD_PROVIDER_PROFILE = "cloud"


def build_haiku_provider_slice_profile(
    *, worker_model: str = HAIKU_PROVIDER_SLICE_MODEL
) -> dict[str, Any]:
    """Return the explicit eval-only Haiku profile for the first provider slice."""

    return {
        "model_router_profile": HAIKU_PROVIDER_SLICE_PROFILE,
        "worker_model": worker_model,
        "guardian_models": list(guardian_model_rows(HAIKU_PROVIDER_SLICE_PROFILE)),
    }


def guardian_model_rows(model_router_profile: str) -> tuple[dict[str, Any], ...]:
    if model_router_profile == HAIKU_PROVIDER_SLICE_PROFILE:
        return (
            {
                "guardian": "defender",
                "provider": "local",
                "model_id": "local-deterministic",
                "served_via": "local",
            },
            {
                "guardian": "evaluator",
                "provider": "anthropic",
                "model_id": HAIKU_PROVIDER_SLICE_MODEL,
                "served_via": "cloud",
            },
            {
                "guardian": "supervisor",
                "provider": "anthropic",
                "model_id": HAIKU_PROVIDER_SLICE_MODEL,
                "served_via": "cloud",
            },
            {
                "guardian": "auditor",
                "provider": "anthropic",
                "model_id": HAIKU_PROVIDER_SLICE_MODEL,
                "served_via": "cloud",
            },
        )
    if model_router_profile == CLOUD_PROVIDER_PROFILE:
        return (
            {
                "guardian": "defender",
                "provider": "local",
                "model_id": "local-deterministic",
                "served_via": "local",
            },
            {
                "guardian": "evaluator",
                "provider": "anthropic",
                "model_id": "claude-sonnet-4-20250514",
                "served_via": "cloud",
            },
            {
                "guardian": "supervisor",
                "provider": "anthropic",
                "model_id": "claude-opus-4-20250514",
                "served_via": "cloud",
            },
            {
                "guardian": "auditor",
                "provider": "anthropic",
                "model_id": "claude-haiku-4-5-20251001",
                "served_via": "cloud",
            },
        )
    return (
        {
            "guardian": "defender",
            "provider": "local",
            "model_id": "local-deterministic",
            "served_via": "local",
        },
        {
            "guardian": "evaluator",
            "provider": "model_router",
            "model_id": "from-model-router",
            "served_via": "cloud",
        },
        {
            "guardian": "supervisor",
            "provider": "model_router",
            "model_id": "from-model-router",
            "served_via": "cloud",
        },
        {
            "guardian": "auditor",
            "provider": "model_router",
            "model_id": "from-model-router",
            "served_via": "cloud",
        },
    )


def default_guardian_evidence_rows(model_router_profile: str) -> list[dict[str, Any]]:
    return [
        {
            "guardian": row["guardian"],
            "decision": "PASS",
            "model_id": row["model_id"],
            "served_via": row["served_via"],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "latency_ms": 0.0,
            "cost_usd": 0.0,
            "reasons": [],
        }
        for row in guardian_model_rows(model_router_profile)
    ]


def dotenv_value(key: str, *, start: Path | None = None) -> str | None:
    """Read one key from the nearest `.env` without logging or expanding it."""

    start_dir = (start or Path.cwd()).resolve()
    candidates = (start_dir, *start_dir.parents)
    for directory in candidates:
        path = directory / ".env"
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            name, sep, value = line.partition("=")
            if sep and name.strip() == key:
                parsed = value.strip().strip('"').strip("'")
                return parsed or None
    return None


def env_key_available(key: str) -> bool:
    return bool(os.environ.get(key) or dotenv_value(key))


def ensure_env_key_loaded(key: str) -> str | None:
    value = os.environ.get(key) or dotenv_value(key)
    if value and key not in os.environ:
        os.environ[key] = value
    return value
