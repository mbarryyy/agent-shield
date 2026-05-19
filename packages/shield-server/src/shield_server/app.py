"""FastAPI app factory.

W1 (server-builder): the 12-step Elydora ingest + `/v1/{operations,agents,
audit,epochs,exports}` + JWKS/auth, preserving the Elydora console REST
contract so it boots unchanged. W2 adds the synchronous
`POST /v1/governance/decide` gate (stub -> PASS) + Channel-2 Redis Streams.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from shield_sdk.schema import GovernanceVerdict  # frozen §4 type, imported not redeclared

from ._crypto import CryptoProvider, ShieldSdkCrypto
from .config import PROTOCOL_VERSION, Settings
from .errors import AppError, app_error_handler
from .routes import router
from .storage import Storage, build_storage


def create_app(
    *,
    storage: Storage | None = None,
    crypto: CryptoProvider | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not hasattr(app.state, "storage"):  # pragma: no cover - real infra path
            app.state.storage = await build_storage(settings)
        yield

    app = FastAPI(title="Agent Shield Server", version="1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.crypto = crypto or ShieldSdkCrypto()
    if storage is not None:
        app.state.storage = storage

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Elydora-Protocol-Version"] = PROTOCOL_VERSION
        response.headers["X-Request-Id"] = request.state.request_id
        return response

    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(router)
    return app


def stub_pass_verdict(correlation_id: str) -> GovernanceVerdict:
    """W2 wires this behind POST /v1/governance/decide so eval/console integrate day 1."""
    from shield_sdk.schema import Decision

    return GovernanceVerdict(decision=Decision.PASS, correlation_id=correlation_id, latency_ms=0.0)
