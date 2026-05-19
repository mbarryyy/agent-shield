"""Generate + cross-verify the frozen crypto golden vectors against Elydora.

Run locally (§5b evidence — provenance is auditable, re-runnable):

    ELYDORA_PY="/Users/jiaweiyang/Desktop/COMPSCI703/Agent Shield/\
Related_Work/Elydora-Open-Source-main/sdks/python" \
    uv run python packages/shield-sdk/tests/_tools/gen_golden_vectors.py

It loads Elydora's reference ``crypto.py`` + ``utils.py`` *directly by file
path* (without executing ``elydora/__init__.py``, which pulls httpx/etc.),
asserts our port is byte-identical for every primitive, then writes the frozen
vectors used by the CI regression tests. Not collected by pytest (no ``test_``
prefix) and mypy-excluded (``/tests/``).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from typing import Any

# --- import our port -------------------------------------------------------
from shield_sdk import canonical, crypto
from shield_sdk.schema import (
    ActionPayload,
    ActionRef,
    Decision,
    GovernanceVerdict,
    Guardian,
    Obligations,
    Phase,
    ServedVia,
    ShieldActionRecord,
    VerdictReason,
)


def _load_elydora_reference(elydora_py_dir: str) -> tuple[Any, Any]:
    """Load elydora.utils + elydora.crypto by path, skipping __init__.py."""
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

    eu = _load("utils")
    ec = _load("crypto")
    return ec, eu


# Fixed, deterministic Ed25519 test seed (32 bytes). NOT a real key — frozen
# test material only, committed on purpose so vectors are reproducible.
_SEED = bytes(range(32))


def _b64url(data: bytes) -> str:
    return crypto.base64url_encode(data)


def main() -> int:
    elydora_py = os.environ.get("ELYDORA_PY")
    if not elydora_py or not Path(elydora_py).is_dir():
        print("ELYDORA_PY not set / not a dir — cannot cross-verify.", file=sys.stderr)
        return 2
    ec, eu = _load_elydora_reference(elydora_py)

    priv_b64 = _b64url(_SEED)
    pub_ours = crypto.get_public_key_base64url(priv_b64)
    pub_ref = ec.get_public_key_base64url(priv_b64)
    assert pub_ours == pub_ref, "pubkey derivation diverged from Elydora"

    # ---- JCS primitive vectors (Elydora is the oracle) -------------------
    jcs_inputs: list[Any] = [
        {"b": 1, "a": 2},
        {"z": [3, 2, 1], "a": {"d": True, "c": None}},
        {"unicode": "café — ñ — 漢字", "emoji": "🛡"},
        [1, 2.5, -0.0, 0.0, True, False, None, "x"],
        {"nested": {"k": {"deep": [1, {"q": "r"}]}}},
        {"num": 1747526400000, "f": 10000.0, "neg": -12.34},
        "bare-string",
        12345,
        {"present_null": None, "kept": 0},
    ]
    jcs_vectors = []
    for v in jcs_inputs:
        ours = crypto.jcs_canonicalize(v)
        ref = ec.jcs_canonicalize(v)
        assert ours == ref, f"JCS diverged for {v!r}: {ours!r} != {ref!r}"
        jcs_vectors.append({"input": v, "canonical": ours})

    # ---- payload_hash / chain_hash primitive vectors --------------------
    payloads: list[Any] = [
        {"tool_name": "send_money", "tool_args": {"amount": 10000.0, "recipient": "X"}},
        {"a": 1},
        {},
    ]
    payload_hash_vectors = []
    for p in payloads:
        ours = crypto.compute_payload_hash(p)
        ref = ec.compute_payload_hash(p)
        assert ours == ref, f"payload_hash diverged for {p!r}"
        payload_hash_vectors.append({"payload": p, "payload_hash": ours})

    chain_inputs = [
        (
            crypto.GENESIS_CHAIN_HASH,
            payload_hash_vectors[0]["payload_hash"],
            "0193aaaa-bbbb-7ccc-8ddd-eeeeeeeeeeee",
            1747526400000,
        ),
        ("someprevhash", "somepayloadhash", "op-2", 1747526400999),
    ]
    chain_hash_vectors = []
    for prev, ph, op, ts in chain_inputs:
        ours = crypto.compute_chain_hash(prev, ph, op, ts)
        ref = ec.compute_chain_hash(prev, ph, op, ts)
        assert ours == ref, "chain_hash diverged"
        chain_hash_vectors.append(
            {
                "prev": prev,
                "payload_hash": ph,
                "operation_id": op,
                "issued_at": ts,
                "chain_hash": ours,
            }
        )

    # ---- Ed25519 sign + sign_eor (Elydora oracle) -----------------------
    msg = b"agent-shield frozen golden message \xf0\x9f\x9b\xa1"
    sig_ours = crypto.sign_ed25519(priv_b64, msg)
    sig_ref = ec.sign_ed25519(priv_b64, msg)
    assert sig_ours == sig_ref, "Ed25519 signature diverged from Elydora"
    assert crypto.verify_ed25519(pub_ours, msg, sig_ours)
    assert not crypto.verify_ed25519(pub_ours, msg + b"!", sig_ours)

    eor = {
        "operation_id": "0193aaaa-bbbb-7ccc-8ddd-eeeeeeeeeeee",
        "agent_id": "agentdojo-banking-v1",
        "payload_hash": payload_hash_vectors[0]["payload_hash"],
        "prev_chain_hash": crypto.GENESIS_CHAIN_HASH,
        "issued_at": 1747526400000,
        "signature": "MUST-BE-IGNORED",
    }
    eor_sig_ours = crypto.sign_eor(eor, priv_b64)
    eor_sig_ref = ec.sign_eor(eor, priv_b64)
    assert eor_sig_ours == eor_sig_ref, "sign_eor diverged from Elydora"

    # ---- Shield §4 record/verdict vectors (our frozen projection) -------
    rec = ShieldActionRecord(
        record_id="0193aaaa-bbbb-7ccc-8ddd-000000000001",
        correlation_id="0193aaaa-bbbb-7ccc-8ddd-000000000002",
        run_id="run-0001",
        step_index=4,
        issued_at=1747526400000,
        ttl_ms=30000,
        nonce="AAAAAAAAAAAAAAAAAAAAAA",
        phase=Phase.PRE_EXEC,
        action=ActionRef(tool="send_money", args_digest="sha256:deadbeef"),
        payload=ActionPayload(
            tool_name="send_money",
            tool_args={
                "recipient": "ATTACKER-IBAN",
                "amount": 10000.0,
                "subject": "exfil",
                "date": "2026-05-18",
            },
        ),
        agent_pubkey_kid="agentdojo-banking-v1-key-v1",
    )
    rec = canonical.finalize_record(rec, priv_b64)
    assert canonical.verify_record(rec, pub_ours)
    chain_hash = canonical.derive_chain_hash(crypto.GENESIS_CHAIN_HASH, rec)

    verdict = GovernanceVerdict(
        verdict_id="0193aaaa-bbbb-7ccc-8ddd-000000000003",
        record_id=rec.record_id,
        correlation_id=rec.correlation_id,
        run_id="run-0001",
        decision=Decision.BLOCK,
        risk_score=0.93,
        reasons=[
            VerdictReason(
                agent=Guardian.DEFENDER,
                label="RECIPIENT_NOT_ALLOWLISTED",
                detail="IBAN never seen",
                score=0.9,
                model_id=None,
                served_via=ServedVia.LOCAL,
            ),
        ],
        obligations=Obligations(require_human=True, prevented_loss=10000.0),
        served_at=1747526400740,
        shield_kid="shield-server-key-v1",
    )
    verdict = canonical.finalize_verdict(verdict, priv_b64)
    assert canonical.verify_verdict(verdict, pub_ours)

    out = {
        "x-status": "FROZEN at W1 by sdk-builder. Primitive vectors are the "
        "Elydora reference SDK output (cross-verified byte-exact at generation "
        "time); Shield record/verdict vectors use the frozen §4 projection in "
        "shield_sdk.canonical. Regenerate via "
        "packages/shield-sdk/tests/_tools/gen_golden_vectors.py.",
        "x-genesis-chain-hash": crypto.GENESIS_CHAIN_HASH,
        "x-genesis-note": "43-char, NO trailing '=' — byte-identical in Elydora "
        "client.py and operation-service.ts; README trailing-'=' is wrong.",
        "x-signable-projection": "model_dump(mode='json', exclude_none=True) "
        "minus signature(+chain_hash for records); present-null == absent == "
        "omitted; see shield_sdk.canonical.",
        "keypair": {
            "alg": "Ed25519",
            "seed_hex": _SEED.hex(),
            "private_key_b64url": priv_b64,
            "public_key_b64url": pub_ours,
        },
        "jcs": jcs_vectors,
        "payload_hash": payload_hash_vectors,
        "chain_hash": chain_hash_vectors,
        "ed25519": {
            "message_b64url": _b64url(msg),
            "signature": sig_ours,
            "public_key_b64url": pub_ours,
        },
        "sign_eor": {"eor": eor, "signature": eor_sig_ours},
        "record": {
            "model": rec.model_dump(mode="json"),
            "signable_string": canonical.record_signing_string(rec),
            "payload_hash": rec.payload_hash,
            "signature": rec.signature,
            "derived_chain_hash": chain_hash,
        },
        "verdict": {
            "model": verdict.model_dump(mode="json"),
            "signable_string": canonical.verdict_signing_string(verdict),
            "signature_by_shield": verdict.signature_by_shield,
        },
    }

    repo = Path(__file__).resolve().parents[4]
    fixture = repo / "packages/shield-sdk/tests/unit/crypto/golden_vectors.json"
    contracts = repo / "contracts/golden/vectors.json"
    blob = json.dumps(out, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    fixture.write_text(blob)
    contracts.write_text(blob)
    print(f"wrote {fixture}")
    print(f"wrote {contracts}")
    print("ALL Elydora cross-checks PASSED — byte-exact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
