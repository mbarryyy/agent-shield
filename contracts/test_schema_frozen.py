"""§4 boundary enforcement: the canonical example envelopes validate against the
committed JSON-Schema snapshots, and the runtime pydantic models stay aligned
with the snapshots. CI diffs this on every PR (the FROZEN-contract firewall).

W0: the snapshots are stubs (sdk-builder freezes them at W1 v1.1 per
ADR-0007); this test still enforces example<->schema<->pydantic consistency now
so a drift the moment building starts is caught immediately.
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


def test_decision_enum_matches_pydantic() -> None:
    gv = _load("governance_verdict.schema.json")
    snapshot_decisions = set(gv["properties"]["decision"]["enum"])
    pydantic_decisions = {d.value for d in pyschema.Decision}
    assert (
        snapshot_decisions
        == pydantic_decisions
        == {"PASS", "ALERT", "BLOCK", "ESCALATE", "ROLLBACK", "REWRITE"}
    )


def test_v11_cost_fields_in_snapshot() -> None:
    gv = _load("governance_verdict.schema.json")
    reason_props = gv["properties"]["reasons"]["items"]["properties"]
    assert "model_id" in reason_props and "served_via" in reason_props
    assert "prevented_loss" in gv["properties"]["obligations"]["properties"]
    assert gv["x-shield-version"] == "1.1"
