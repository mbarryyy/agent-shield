"""Serve a persistent local backend seeded with the Round 2 finance demo.

This is the browser-facing companion to ``run_finance_demo.py``. It first
populates an in-memory FastAPI app through the real backend routes, then serves
that same app with uvicorn so the console can render backend data.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import uvicorn
from shield_server.app import create_app
from shield_server.config import Settings
from shield_server.storage import build_memory_storage

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_finance_demo import DEFAULT_ARTIFACT_DIR, DemoGovernanceApp, DemoRunner  # noqa: E402

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_CONSOLE_ORIGINS = "http://127.0.0.1:3000,http://localhost:3000"


def _demo_settings() -> Settings:
    os.environ.setdefault("SHIELD_AUTH_MODE", "open")
    os.environ.setdefault("SHIELD_CORS_ORIGINS", DEFAULT_CONSOLE_ORIGINS)
    return Settings.from_env()


def build_seeded_demo_app(
    artifact_dir: str | Path = DEFAULT_ARTIFACT_DIR,
) -> tuple[Any, dict[str, Any]]:
    storage = build_memory_storage()
    governance = DemoGovernanceApp()
    app = create_app(
        storage=storage,
        settings=_demo_settings(),
        governance=governance,
    )
    summary = DemoRunner(
        Path(artifact_dir),
        storage=storage,
        governance=governance,
        app=app,
    ).run()
    app.state.demo_summary = summary
    return app, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Serve a local backend preloaded with the Round 2 finance demo flow."
    )
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    args = parser.parse_args(argv)

    app, summary = build_seeded_demo_app(args.artifact_dir)
    backend_url = f"http://{args.host}:{args.port}"
    print(
        json.dumps(
            {
                "backend_url": backend_url,
                "artifact_dir": str(Path(args.artifact_dir)),
                "scene_count": summary["scene_count"],
                "open_console_with": {
                    "NEXT_PUBLIC_API_BASE_URL": backend_url,
                    "NEXT_PUBLIC_SHIELD_AUTH_MODE": "open",
                    "NEXT_PUBLIC_GOV_WORKFLOW_ID": "banking",
                    "NEXT_PUBLIC_GOV_RUN_ID": "demo-shield-block",
                },
            },
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
