"""Import surface + the W0 stubs that remain stubs until their owning week.

`metrics` (W4) and `changelog` (release) are intentionally still W0 stubs —
their assertions are unchanged. `run_ab` / `mock_llm` are W1-real and covered
behaviourally in `test_run_ab_offline.py`.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout

from shield_eval import arms, changelog, metrics, mock_llm, run_ab  # noqa: F401


def test_submodules_import() -> None:
    assert changelog and metrics and mock_llm and run_ab and arms


def test_mock_llm_is_pipeline_element() -> None:
    from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement

    m = mock_llm.MockedLLM(name="mocked-x")
    assert isinstance(m, BasePipelineElement)
    assert m.name == "mocked-x"


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
