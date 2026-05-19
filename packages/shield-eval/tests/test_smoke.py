"""W0 smoke: the canonical runner name resolves and the stub CLIs exit 0."""

from __future__ import annotations

from shield_eval import changelog, metrics, run_ab
from shield_sdk.schema import ShieldActionRecord  # noqa: F401  (compile-against check)


def test_run_ab_smoke_exits_zero() -> None:
    assert run_ab.main(["--suite", "banking", "--smoke"]) == 0


def test_metrics_stub_exits_zero() -> None:
    assert metrics.main(["--check", "asr<=0.10"]) == 0


def test_changelog_stub_exits_zero() -> None:
    assert changelog.main(["--since-last-tag"]) == 0
