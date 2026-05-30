"""P1a: AsyncVerdictWorker lifecycle wired into the app lifespan.

The Channel-2 async verdict worker (the boundary that signs + publishes the
late guardian verdicts) was reachable only via ``python -m
shield_server.async_verdict_worker`` — never started by the running server, so
the LLM guardians never fired end-to-end under ``uvicorn``. These tests pin the
deterministic wiring contract (NO real LLM, NO key, NO spend):

  * default OFF: the worker is NOT spawned unless ``SHIELD_ASYNC_WORKER=1``
    (so the rest of the suite + console-only deploys don't start a consumer);
  * when enabled, a background task is created at startup and cancelled at
    shutdown;
  * fail-loud: enabled + cloud router profile + no ``ANTHROPIC_API_KEY`` ⇒
    RuntimeError at boot, never a silent no-LLM worker.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from shield_server.app import create_app
from shield_server.config import Settings
from shield_server.storage import build_memory_storage


def _build_app(monkeypatch: pytest.MonkeyPatch, **env: str) -> object:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    storage = build_memory_storage()
    return create_app(storage=storage, settings=Settings.from_env())


def test_worker_not_started_when_flag_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHIELD_ASYNC_WORKER", raising=False)
    app = _build_app(monkeypatch)
    with TestClient(app):
        assert getattr(app.state, "async_worker_task", None) is None


def test_worker_started_and_cancelled_when_flag_set_local_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # local profile needs no key (air-gapped); with an empty stream the
    # guardians never fire, so this is fully deterministic + keyless.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = _build_app(monkeypatch, SHIELD_ASYNC_WORKER="1", SHIELD_ROUTER_PROFILE="local")
    with TestClient(app):
        task = getattr(app.state, "async_worker_task", None)
        assert task is not None
        assert not task.done()
    # lifespan shutdown must cancel the background task.
    assert app.state.async_worker_task.done()


def test_worker_fail_loud_cloud_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = _build_app(monkeypatch, SHIELD_ASYNC_WORKER="1", SHIELD_ROUTER_PROFILE="cloud")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"), TestClient(app):
        pass
