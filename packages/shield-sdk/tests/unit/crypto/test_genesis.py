"""W0 crypto-floor test (ci.yml runs this under --cov=shield_sdk --cov-fail-under=90).

Imports every shield_sdk submodule so the W0 stub surface is fully covered
(real logic bodies are `# pragma: no cover` until their build week), and locks
the 43-char no-pad genesis constant now (it gates all chain-hash work at W1).
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
import shield_sdk.schema as schema
import shield_sdk.sdk as sdk


def test_all_submodules_import() -> None:
    for name in ("schema", "crypto", "sdk", "defense", "instrument"):
        assert importlib.import_module(f"shield_sdk.{name}") is not None
    assert shield_sdk.__all__ == ["schema"]


def test_genesis_chain_hash_frozen() -> None:
    assert crypto.GENESIS_CHAIN_HASH == "A" * 43
    assert len(crypto.GENESIS_CHAIN_HASH) == 43
    assert "=" not in crypto.GENESIS_CHAIN_HASH


def test_w1_crypto_is_not_yet_implemented() -> None:
    with pytest.raises(NotImplementedError):
        crypto.compute_payload_hash({"a": 1})
    with pytest.raises(NotImplementedError):
        crypto.jcs_canonicalize({"a": 1})
    with pytest.raises(NotImplementedError):
        sdk.ShieldClient("http://x").decide(
            schema.ShieldActionRecord(
                phase=schema.Phase.PRE_EXEC, correlation_id="c", run_id="r", payload_hash="h"
            )
        )
