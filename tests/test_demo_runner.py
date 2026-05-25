from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPT = Path(__file__).parents[1] / "scripts" / "demo" / "run_finance_demo.py"
_SPEC = importlib.util.spec_from_file_location("run_finance_demo", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
run_demo = _MODULE.run_demo


def test_finance_demo_runner_populates_backend_scenes_and_pdf_export(tmp_path) -> None:
    summary = run_demo(tmp_path)

    assert summary["scene_count"] == 5
    assert [scene["scene"] for scene in summary["scenes"]] == [
        "normal_precheck",
        "unprotected_baseline",
        "shield_block",
        "hitl",
        "audit_export",
    ]
    assert summary["decision_counts"]["PASS"] >= 1
    assert summary["decision_counts"]["BLOCK"] >= 1
    assert summary["decision_counts"]["ESCALATE"] >= 1

    block_scene = next(scene for scene in summary["scenes"] if scene["scene"] == "shield_block")
    assert block_scene["final_decision"] == "BLOCK"
    assert block_scene["prevented_loss_usd"] == 30_000.0

    hitl_scene = next(scene for scene in summary["scenes"] if scene["scene"] == "hitl")
    assert hitl_scene["initial_decision"] == "ESCALATE"
    assert hitl_scene["resume_decision"] == "PASS"
    assert hitl_scene["incident_status_after_resume"] == "resolved"

    export_scene = next(scene for scene in summary["scenes"] if scene["scene"] == "audit_export")
    assert export_scene["pdf_download_url"].endswith("/download")
    assert export_scene["pdf_bytes_size"] > 5
    assert export_scene["pdf_magic"] is True
    assert export_scene["pdf_file"].endswith(".pdf")

    summary_path = tmp_path / "summary.json"
    assert summary_path.exists()
    persisted = json.loads(summary_path.read_text(encoding="utf-8"))
    assert persisted["scene_count"] == 5
