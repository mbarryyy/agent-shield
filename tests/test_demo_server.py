from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

_SCRIPT = Path(__file__).parents[1] / "scripts" / "demo" / "serve_finance_demo_backend.py"


def _load_server_module():
    assert _SCRIPT.exists(), "persistent finance demo backend script is missing"
    spec = importlib.util.spec_from_file_location("serve_finance_demo_backend", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seeded_demo_backend_exposes_dashboard_and_run_routes(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SHIELD_AUTH_MODE", raising=False)
    monkeypatch.delenv("SHIELD_CORS_ORIGINS", raising=False)
    module = _load_server_module()

    app, summary = module.build_seeded_demo_app(tmp_path)

    assert summary["scene_count"] == 5
    assert "http://127.0.0.1:3000" in app.state.settings.cors_origins
    assert "http://localhost:3000" in app.state.settings.cors_origins

    with TestClient(app) as client:
        dashboard = client.get("/v1/governance/dashboard/kpi")
        timeline = client.get("/v1/governance/runs/demo-shield-block/timeline")
        exports = client.get("/v1/exports")
        block_row = next(row for row in timeline.json()["rows"] if row["decision"] == "BLOCK")
        block_detail = client.get(f"/v1/governance/verdicts/{block_row['correlation_id']}")

    assert dashboard.status_code == 200, dashboard.text
    dashboard_body = dashboard.json()
    assert dashboard_body["prevented_loss_total"] >= 30_000.0
    assert dashboard_body["decision_mix"]["BLOCK"] >= 1

    assert timeline.status_code == 200, timeline.text
    timeline_body = timeline.json()
    assert timeline_body["total_count"] >= 1
    assert {row["decision"] for row in timeline_body["rows"]} >= {"PASS", "BLOCK"}

    assert block_detail.status_code == 200, block_detail.text
    reasons = block_detail.json()["verdict"]["reasons"]
    assert {reason["agent"] for reason in reasons} >= {
        "defender",
        "evaluator",
        "supervisor",
        "auditor",
    }

    assert exports.status_code == 200, exports.text
    assert len(exports.json()["exports"]) >= 2
