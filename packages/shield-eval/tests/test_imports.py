"""W0: import every shield-eval submodule so the stub surface is covered."""

from __future__ import annotations

import io
from contextlib import redirect_stdout

from shield_eval import changelog, metrics, mock_llm, run_ab  # noqa: F401


def test_submodules_import() -> None:
    assert changelog and metrics and mock_llm and run_ab


def test_mock_llm_stub_constructs() -> None:
    assert mock_llm.MockedLLM("transcript").transcript == "transcript"


def test_run_ab_stub_runs() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = run_ab.main(["--suite", "banking", "--smoke"])
    assert rc == 0
    assert "W0 stub" in buf.getvalue()


def test_metrics_stub_runs() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = metrics.main(["--check", "asr<=0.10"])
    assert rc == 0
    assert "W0 stub" in buf.getvalue()


def test_changelog_stub_runs() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = changelog.main(["--since-last-tag"])
    assert rc == 0
    assert "W0 stub" in buf.getvalue()
