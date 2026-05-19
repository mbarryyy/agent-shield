"""W2 HARD-GATE (reviewer-enforced): the §4 ShieldActionRecord / GovernanceVerdict
bytes are produced by the FROZEN shield_sdk.canonical projection VERBATIM —
`record_signable_dict` (model_dump(exclude_none) minus signature+chain_hash;
present-null ≡ absent), pinned to contracts/golden/vectors.json. The server
must NEVER re-derive this projection; `governance.decide` delegates to
shield_sdk.canonical.{verify_record,derive_chain_hash,finalize_verdict}. These
tests pin the bytes AND prove the delegation behaviorally (a canonical-signed
record is accepted; a record signed under any other projection is rejected).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import shield_sdk.canonical as canonical
import shield_sdk.crypto as crypto
from shield_sdk.schema import GovernanceVerdict, ShieldActionRecord
from shield_server import agents as agent_svc
from shield_server.config import Settings
from shield_server.errors import AppError
from shield_server.governance import decide
from shield_server.models import RegisterAgentRequest
from shield_server.storage import Storage, build_memory_storage

_V = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts" / "golden" / "vectors.json").read_text()
)
PRIV = _V["keypair"]["private_key_b64url"]
PUB = _V["keypair"]["public_key_b64url"]


def test_record_signable_string_matches_golden() -> None:
    rec = ShieldActionRecord.model_validate(_V["record"]["model"])
    assert canonical.record_signing_string(rec) == _V["record"]["signable_string"]
    assert canonical.compute_record_payload_hash(rec) == _V["record"]["payload_hash"]
    assert (
        canonical.derive_chain_hash(rec.prev_chain_hash, rec) == _V["record"]["derived_chain_hash"]
    )
    assert canonical.sign_record(rec, PRIV) == _V["record"]["signature"]
    assert canonical.verify_record(rec, PUB) is True


def test_verdict_signable_string_matches_golden() -> None:
    vd = GovernanceVerdict.model_validate(_V["verdict"]["model"])
    assert canonical.verdict_signing_string(vd) == _V["verdict"]["signable_string"]
    assert canonical.sign_verdict(vd, PRIV) == _V["verdict"]["signature_by_shield"]
    assert canonical.verify_verdict(vd, PUB) is True


def test_present_null_equals_absent_in_signable() -> None:
    """The FROZEN rule: exclude_none recursively + drop chain_hash/signature."""
    rec = ShieldActionRecord.model_validate(_V["record"]["model"])
    d = canonical.record_signable_dict(rec)
    assert "signature" not in d and "chain_hash" not in d
    assert "verdict_ref" not in d  # None -> omitted (present-null ≡ absent)
    assert d["context"] == {}  # all-None nested model collapses to {}


async def test_decide_delegates_to_canonical_not_a_re_derivation(
    settings_env: Settings,
) -> None:
    """Behavioral proof of no re-derivation: a record signed by the FROZEN
    canonical rule is ACCEPTED; the same record signed over a *different*
    projection (full JCS incl. None / incl. signature) is REJECTED."""
    storage: Storage = build_memory_storage()
    agent_priv = _V["keypair"]["private_key_b64url"]
    agent_pub = crypto.get_public_key_base64url(agent_priv)
    await agent_svc.register_agent(
        storage,
        RegisterAgentRequest(
            agent_id="agentdojo-banking-v1",
            keys=[{"kid": "k", "public_key": agent_pub}],  # type: ignore[list-item]
        ),
        "demo-org",
    )

    base = ShieldActionRecord(
        org_id="demo-org",
        agent_id="agentdojo-banking-v1",
        agent_pubkey_kid="k",
        phase="pre_exec",
        run_id="run-0001",
    )
    base.payload.tool_name = "send_money"

    # (a) FROZEN-rule signature -> accepted by the server's canonical.verify_record.
    good = canonical.finalize_record(base.model_copy(deep=True), agent_priv)
    v = await decide(storage, good, settings_env)
    assert v.decision.value == "PASS"

    # (b) WRONG projection (raw JCS of the *full* model incl. None + signature)
    #     -> server rejects (proves it verifies the canonical bytes, not these).
    bad = base.model_copy(deep=True)
    bad.payload_hash = canonical.compute_record_payload_hash(bad)
    bad.nonce = "different-nonce-xxxxxx"
    wrong_string = crypto.jcs_canonicalize(bad.model_dump(mode="json"))
    bad.signature = crypto.sign_ed25519(agent_priv, wrong_string.encode("utf-8"))
    with pytest.raises(AppError) as ei:
        await decide(storage, bad, settings_env)
    assert ei.value.error_code == "INVALID_SIGNATURE"


@pytest.fixture
def settings_env() -> Settings:
    return Settings.from_env()
