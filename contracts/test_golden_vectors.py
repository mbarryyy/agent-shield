"""Cross-impl crypto golden vectors vs Elydora's reference Python SDK.

W0: SKIPPED. sdk-builder freezes the real vectors at W1 (fixed Ed25519 keypair +
fixed records -> expected payload_hash/chain_hash/signature, captured from
Related_Work/Elydora-Open-Source-main/sdks/python/elydora), green on py3.11+3.12.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_VECTORS = json.loads((Path(__file__).parent / "golden" / "vectors.json").read_text())


def test_golden_vectors_present() -> None:
    if not _VECTORS.get("vectors"):
        pytest.skip("W0: golden vectors frozen at W1 by sdk-builder (C11/ADR-0007)")
    # W1: assert each vector's payload_hash/chain_hash/signature matches our crypto port.
