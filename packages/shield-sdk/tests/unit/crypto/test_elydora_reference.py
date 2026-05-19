"""Live byte-exact cross-check against the upstream Elydora reference SDK.

Skips when the Elydora tree is not present (CI runners, public clones — the
design corpus & Related_Work live only on the maintainer's machine). When the
tree IS present it loads Elydora's reference ``crypto.py``/``utils.py`` by
file path (without executing ``elydora/__init__.py``) and asserts our port is
byte-identical — the §5b live evidence behind the frozen golden vectors.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from shield_sdk import crypto

_CANDIDATES = [
    os.environ.get("ELYDORA_PY", ""),
    "/Users/jiaweiyang/Desktop/COMPSCI703/Agent Shield/"
    "Related_Work/Elydora-Open-Source-main/sdks/python",
]


def _find_elydora() -> str | None:
    for c in _CANDIDATES:
        if c and (Path(c) / "elydora" / "crypto.py").is_file():
            return c
    return None


def _load_reference(elydora_py_dir: str) -> Any:
    pkg = types.ModuleType("elydora")
    pkg.__path__ = [str(Path(elydora_py_dir) / "elydora")]  # type: ignore[attr-defined]
    sys.modules["elydora"] = pkg

    def _load(name: str) -> Any:
        path = Path(elydora_py_dir) / "elydora" / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"elydora.{name}", path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"elydora.{name}"] = mod
        spec.loader.exec_module(mod)
        return mod

    _load("utils")
    return _load("crypto")


_DIR = _find_elydora()
pytestmark = pytest.mark.skipif(
    _DIR is None, reason="Elydora reference tree not present (expected off-machine)"
)


def test_port_is_byte_exact_with_elydora() -> None:
    assert _DIR is not None
    ec = _load_reference(_DIR)
    priv = crypto.base64url_encode(bytes(range(32)))

    assert crypto.get_public_key_base64url(priv) == ec.get_public_key_base64url(priv)

    samples: list[Any] = [
        {"b": 1, "a": 2, "n": None, "f": 10000.0},
        {"z": [3, 2, 1], "nested": {"d": True, "c": "café 漢字 🛡"}},
        [1, 2.5, -0.0, True, None, "x"],
        {"present_null": None, "kept": 0},
    ]
    for s in samples:
        assert crypto.jcs_canonicalize(s) == ec.jcs_canonicalize(s)
        assert crypto.compute_payload_hash(s) == ec.compute_payload_hash(s)

    assert crypto.compute_chain_hash(
        crypto.GENESIS_CHAIN_HASH, "ph", "op", 1747526400000
    ) == ec.compute_chain_hash(crypto.GENESIS_CHAIN_HASH, "ph", "op", 1747526400000)

    msg = b"frozen golden message \xf0\x9f\x9b\xa1"
    assert crypto.sign_ed25519(priv, msg) == ec.sign_ed25519(priv, msg)
    eor = {"operation_id": "op", "payload_hash": "ph", "signature": "IGN"}
    assert crypto.sign_eor(eor, priv) == ec.sign_eor(eor, priv)
