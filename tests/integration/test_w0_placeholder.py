"""W0 integration placeholder so `pytest tests/integration -m integration`
collects ≥1 test. Real integration (12-step ingest, two-phase gate, Stream,
Merkle) lands W1->W4 (server-builder + eval-builder)."""

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_w0_integration_placeholder() -> None:
    assert True
