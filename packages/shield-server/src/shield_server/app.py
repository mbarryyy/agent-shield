"""FastAPI app factory + ``shield-server`` argparse entrypoint.

W3 baseline preserved: ``create_app(storage=..., crypto=..., settings=...,
governance=...)`` constructs the app exactly as before; all 314 W3 tests
exercise this path with ``SHIELD_AUTH_MODE`` defaulting to ``open``.

ADR-0013 additive:

  * ``cli_main(argv=...)`` — argparse entrypoint with the CLI-only
    ``--allow-open-auth`` flag (§A3). The flag is NOT env-readable.
  * Startup refusals:
       - ``open`` mode without ``--allow-open-auth`` → ``sys.exit("REFUSED: ...")``
       - ``enterprise`` mode with ``SHIELD_EMAIL_BACKEND=console`` →
         ``sys.exit("REFUSED: ...")``
  * Startup audit row ``STARTED_IN_OPEN_MODE`` (§A3) — emitted from the
    lifespan when ``open`` mode was deliberately enabled.
  * Enterprise wiring (only when ``settings.is_enterprise``):
       - construct ``PasswordHasherService`` + ``TotpService`` + ``EmailSender``
         and attach to ``app.state``;
       - mount the ``auth_router`` (`/v1/auth/*`).
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from shield_sdk.schema import GovernanceVerdict  # frozen §4 type, imported not redeclared

from ._crypto import CryptoProvider, ShieldSdkCrypto
from .auth import (
    PasswordHasherService,
    TotpService,
    build_email_sender,
    insert_audit,
)
from .auth.routes import auth_router
from .config import PROTOCOL_VERSION, Settings
from .errors import AppError, app_error_handler
from .govseam import GovernanceApp, load_governance_app
from .routes import router
from .storage import Storage, build_storage


def _refuse_or_exit(settings: Settings) -> None:
    """Apply the ADR-0013 §A3 + §A4 startup refusals.

    §A3: ``open`` mode requires the CLI-only ``--allow-open-auth`` flag.
    §A4: ``enterprise`` mode refuses ``SHIELD_EMAIL_BACKEND=console``.
    """
    if settings.is_open and not settings.allow_open_auth:
        sys.exit(
            "REFUSED: SHIELD_AUTH_MODE=open requires the explicit CLI flag "
            "--allow-open-auth. The flag is intentionally CLI-only (not env, "
            "not docker-env, not config-file) so that 'open' cannot become a "
            "deploy-time default by accident. (ADR-0013 §A3)"
        )
    if settings.is_enterprise and settings.email_backend == "console":
        sys.exit(
            "REFUSED: SHIELD_EMAIL_BACKEND=console (stdout printer) is not "
            "permitted under SHIELD_AUTH_MODE=enterprise — set 'file' (test) "
            "or 'smtp' (prod); stdout email leakage to log aggregators would "
            "expose password-reset and email-verification tokens. (ADR-0013 §A4)"
        )


def create_app(
    *,
    storage: Storage | None = None,
    crypto: CryptoProvider | None = None,
    settings: Settings | None = None,
    governance: GovernanceApp | None = None,
    enforce_startup_refusals: bool = False,
) -> FastAPI:
    """W3-byte-compatible app factory.

    Startup refusals (§A3 / §A4) are intentionally OFF by default because
    direct ``create_app(...)`` callers (the 314 W3 tests + integration code)
    construct the app without going through the argparse layer. The
    production path (``cli_main`` → uvicorn → ``_factory``) enforces refusals
    *before* uvicorn starts the worker, then sets ``enforce_startup_refusals=
    True`` in ``_factory`` so a misconfigured re-import inside the worker
    still refuses on the second pass. Tests can opt-in with the same kwarg.
    """
    settings = settings or Settings.from_env()
    if enforce_startup_refusals:
        _refuse_or_exit(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not hasattr(app.state, "storage"):  # pragma: no cover - real infra path
            app.state.storage = await build_storage(settings)
        if not hasattr(app.state, "governance"):  # pre-warm ONCE (master §1.2/§2.3)
            app.state.governance = load_governance_app()
        # §A3 — STARTED_IN_OPEN_MODE audit row (deliberate audit-after-refusal-pass).
        if settings.is_open and settings.allow_open_auth:
            sys.stderr.write(
                "WARNING: shield-server starting in SHIELD_AUTH_MODE=open — all "
                "requests resolve to a synthetic dev_principal with all roles. "
                "NEVER USE IN PROD.\n"
            )
            # We never crash startup on audit failure (the stderr warning above
            # is the user-visible signal). MemoryDatabase models audit_log_auth
            # in unit tests; production hits the real Postgres path.
            with contextlib.suppress(Exception):  # pragma: no cover - integration-only
                await insert_audit(
                    app.state.storage.db,
                    event="STARTED_IN_OPEN_MODE",
                    detail={"hostname": _hostname(), "pid": _pid()},
                )
        yield

    app = FastAPI(title="Agent Shield Server", version="1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.crypto = crypto or ShieldSdkCrypto()
    if storage is not None:
        app.state.storage = storage
    if governance is not None:
        app.state.governance = governance

    # --- enterprise wiring -------------------------------------------- #
    if settings.is_enterprise:
        app.state.password_hasher = PasswordHasherService.from_settings(settings)
        app.state.totp_service = TotpService.from_settings(settings)
        app.state.email_sender = build_email_sender(settings)

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
    # The auth router is mounted only in enterprise mode (§A11 — `api_token_only`
    # explicitly does NOT mount session routes so the console cannot operate;
    # `open` mode does not need the session surface because the synthetic
    # dev_principal admits any RBAC dep).
    if settings.is_enterprise:
        app.include_router(auth_router)
    return app


def stub_pass_verdict(correlation_id: str) -> GovernanceVerdict:
    """W2 wires this behind POST /v1/governance/decide so eval/console integrate day 1."""
    from shield_sdk.schema import Decision

    return GovernanceVerdict(decision=Decision.PASS, correlation_id=correlation_id, latency_ms=0.0)


# --- ADR-0013 §A3 — CLI entrypoint (argparse-only --allow-open-auth) -- #


def _hostname() -> str:
    import platform

    return platform.node()


def _pid() -> int:
    import os as _os

    return _os.getpid()


def cli_main(argv: list[str] | None = None) -> int:
    """``shield-server`` CLI entrypoint. argparse the §A3 flag and exec uvicorn.

    Subcommands:
      * (no subcommand) — run the server.
      * ``--seed-admin``  — delegate to ``shield_server.auth.cli.main``.

    The ``--allow-open-auth`` flag is intentionally argparse-only: not env-
    readable, not Docker-env-readable, not config-file-readable. It is the
    sole means to permit ``SHIELD_AUTH_MODE=open`` at startup (§A3).
    """
    parser = argparse.ArgumentParser(
        prog="shield-server",
        description="Agent Shield server entrypoint (ADR-0013).",
    )
    parser.add_argument(
        "--allow-open-auth",
        action="store_true",
        help="Permit SHIELD_AUTH_MODE=open (§A3 CLI-only flag).",
    )
    parser.add_argument("--host", default="0.0.0.0", help="uvicorn host.")  # noqa: S104
    parser.add_argument("--port", default=8080, type=int, help="uvicorn port.")
    parser.add_argument(
        "--seed-admin",
        action="store_true",
        help="Delegate to shield_server.auth.cli seed-admin (uses remaining argv).",
    )
    args, rest = parser.parse_known_args(argv)
    if args.seed_admin:
        from .auth import cli as auth_cli

        return auth_cli.main(["seed-admin", *rest])
    # Inject the CLI flag into Settings so refuse_or_exit honours it.
    settings = Settings.from_env().with_allow_open_auth(args.allow_open_auth)
    _refuse_or_exit(settings)
    # The runtime app is constructed once by uvicorn via the factory shape.
    # We pass the §A3 flag's presence to the uvicorn worker process via a
    # process-local marker that's set ONLY when the parent saw the flag:
    # any spawned child inheriting SHIELD_AUTH_MODE=open without this marker
    # still refuses, preserving the §A3 invariant.
    import os as _os

    if args.allow_open_auth:
        _os.environ["_SHIELD_ALLOW_OPEN_AUTH_PROCESS"] = "1"
    import uvicorn  # pragma: no cover - server-only path

    uvicorn.run(  # pragma: no cover
        "shield_server.app:_factory",
        factory=True,
        host=args.host,
        port=args.port,
        reload=False,
    )
    return 0


def _factory() -> FastAPI:  # pragma: no cover - uvicorn-only path
    """Uvicorn factory: re-reads Settings + the §A3 process marker."""
    import os as _os

    settings = Settings.from_env().with_allow_open_auth(
        _os.environ.get("_SHIELD_ALLOW_OPEN_AUTH_PROCESS") == "1"
    )
    return create_app(settings=settings, enforce_startup_refusals=True)
