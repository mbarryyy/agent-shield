"""W0: import every shield-governance submodule so the stub surface is covered."""

from __future__ import annotations

import io
from contextlib import redirect_stdout

from shield_governance import agents, air_gap_verify, graph, memory, tools  # noqa: F401


def test_submodules_import() -> None:
    assert agents and graph and memory and tools


def test_air_gap_verify_stub_runs() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        air_gap_verify.main()
    assert "W0 stub" in buf.getvalue()
