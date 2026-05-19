"""W0 smoke: shield-governance imports the frozen schema + config YAMLs parse."""

from __future__ import annotations

from pathlib import Path

import yaml
from shield_sdk.schema import GovernanceVerdict  # noqa: F401  (compile-against check)

_CFG = Path(__file__).parents[1] / "src" / "shield_governance" / "config"


def test_model_profiles_parse() -> None:
    cloud = yaml.safe_load((_CFG / "models.cloud.yaml").read_text())
    local = yaml.safe_load((_CFG / "models.local.yaml").read_text())
    assert cloud["profile"] == "cloud"
    assert local["profile"] == "local"
    assert set(cloud["guardians"]) == {"defender", "evaluator", "supervisor", "auditor"}
