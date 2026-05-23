"""W0: import every shield-governance submodule so the stub surface is covered."""

from __future__ import annotations

import io

from shield_governance import agents, air_gap_verify, graph, memory, tools  # noqa: F401


def test_submodules_import() -> None:
    assert agents and graph and memory and tools


def test_air_gap_verify_main_prints_report(monkeypatch) -> None:
    monkeypatch.setattr(
        air_gap_verify,
        "detect_host_egress_smoke",
        lambda: air_gap_verify.CheckResult(
            name="host_egress_smoke",
            status=air_gap_verify.CheckStatus.SKIP,
            message="SKIP_HOST_UNSUPPORTED: egress-deny smoke unavailable on Darwin",
        ),
    )
    buf = io.StringIO()
    exit_code = air_gap_verify.main(stdout=buf)
    output = buf.getvalue()

    assert exit_code == 0
    assert "AIR_GAP_VERIFY_REPORT" in output
    assert "SKIP_HOST_UNSUPPORTED: egress-deny smoke unavailable on Darwin" in output
    assert "W0 stub" not in output
