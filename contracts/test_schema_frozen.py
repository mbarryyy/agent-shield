"""§4 boundary enforcement (FROZEN at v1.1 — C11 / ADR-0007).

The canonical example envelopes validate against the regenerated JSON-Schema
snapshots, and the snapshots stay aligned with the single pydantic source of
truth ``shield_sdk.schema``. CI diffs this on every PR (the FROZEN-contract
firewall). The snapshots are ``additionalProperties: false`` on every closed
object (O5) — that is why no ``x-note`` or stray key may live inside a
schema-validated example.

ESCALATE-degradation note (eval-builder-owned, documented here on purpose,
NOT in the envelope): in AgentDojo's non-interactive ``benchmark_suite()`` an
ESCALATE verdict degrades deterministically per runtime config (BLOCK |
auto-approve); the live demo keeps the real ``interrupt()`` HITL pause.
``examples/verdict_escalate.json`` is a pure, valid ESCALATE verdict.

This file is part of the ADR-0007 ritual branch and is green only against the
v1.1 ``shield_sdk.schema`` (it lands with / after the SDK feature freeze).
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from shield_sdk import schema as pyschema

_C = Path(__file__).parent


def _load(p: str) -> dict:
    return json.loads((_C / p).read_text())


def test_examples_validate_against_snapshots() -> None:
    sar = _load("shield_action_record.schema.json")
    gv = _load("governance_verdict.schema.json")
    jsonschema.validate(_load("examples/pre_exec.json"), sar)
    jsonschema.validate(_load("examples/post_exec.json"), sar)
    jsonschema.validate(_load("examples/verdict.json"), gv)
    jsonschema.validate(_load("examples/verdict_escalate.json"), gv)


def test_snapshots_are_strict_additionalproperties_false() -> None:
    """O5: the snapshot-diff firewall only bites if the contract is closed."""
    sar = _load("shield_action_record.schema.json")
    gv = _load("governance_verdict.schema.json")
    assert sar["additionalProperties"] is False
    assert gv["additionalProperties"] is False
    # Every closed nested model is closed too.
    for d in sar["$defs"].values():
        if d.get("type") == "object":
            assert d["additionalProperties"] is False
    for d in gv["$defs"].values():
        if d.get("type") == "object":
            assert d["additionalProperties"] is False


def test_decision_enum_matches_pydantic() -> None:
    gv = _load("governance_verdict.schema.json")
    snapshot_decisions = set(gv["$defs"]["Decision"]["enum"])
    pydantic_decisions = {d.value for d in pyschema.Decision}
    assert (
        snapshot_decisions
        == pydantic_decisions
        == {"PASS", "ALERT", "BLOCK", "ESCALATE", "ROLLBACK", "REWRITE"}
    )


def test_v11_cost_fields_in_snapshot() -> None:
    gv = _load("governance_verdict.schema.json")
    reason_props = gv["$defs"]["VerdictReason"]["properties"]
    assert "model_id" in reason_props and "served_via" in reason_props
    assert "prevented_loss" in gv["$defs"]["Obligations"]["properties"]
    assert gv["x-shield-version"] == "1.1"
    assert gv["properties"]["shield_version"]["default"] == "1.1"


def test_examples_use_v11_field_names() -> None:
    """§4.2 names, not the W0 stub's code/message/guardian."""
    v = _load("examples/verdict.json")
    r = v["reasons"][0]
    assert {"agent", "label"} <= set(r)
    assert "code" not in r and "guardian" not in r
    assert "confidence" not in v  # dropped at the v1.1 freeze (not in §4.2)


def test_snapshot_matches_live_pydantic() -> None:
    """The committed snapshot IS what shield_sdk.schema generates today."""
    live = pyschema.GovernanceVerdict.model_json_schema()
    snap = _load("governance_verdict.schema.json")
    assert snap["properties"] == live["properties"]
    assert snap["required"] == live["required"]
    assert snap["$defs"] == live["$defs"]
