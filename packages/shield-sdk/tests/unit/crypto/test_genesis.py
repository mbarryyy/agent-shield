"""Crypto-floor: genesis constant + full submodule import surface.

ci.yml runs ``packages/shield-sdk/tests/unit/crypto`` under
``--cov=shield_sdk --cov-fail-under=90``; importing every submodule here keeps
the non-crypto stub surface (sdk/defense/instrument) covered, and locks the
43-char no-pad genesis constant that gates all chain-hash work.
"""

from __future__ import annotations

import importlib

import pytest
import shield_sdk
import shield_sdk.crypto as crypto
import shield_sdk.defense  # noqa: F401
import shield_sdk.instrument  # noqa: F401
import shield_sdk.instrument.agentdojo  # noqa: F401
import shield_sdk.instrument.hooks  # noqa: F401
import shield_sdk.sdk as sdk
from shield_sdk import schema


def test_all_submodules_import() -> None:
    for name in ("schema", "crypto", "canonical", "sdk", "defense", "instrument"):
        assert importlib.import_module(f"shield_sdk.{name}") is not None
    assert shield_sdk.__all__ == ["canonical", "crypto", "schema"]


def test_genesis_chain_hash_frozen() -> None:
    assert crypto.GENESIS_CHAIN_HASH == "A" * 43
    assert len(crypto.GENESIS_CHAIN_HASH) == 43
    assert "=" not in crypto.GENESIS_CHAIN_HASH


def test_sdk_client_decide_is_w2() -> None:
    """crypto/canonical/schema are frozen at W1; the HTTP client is W2."""
    with pytest.raises(NotImplementedError):
        sdk.ShieldClient("http://x").decide(
            schema.ShieldActionRecord(phase=schema.Phase.PRE_EXEC, run_id="r")
        )
