"""ADR-0013 — Misc unit_auth coverage: utils, audit, email, tokens, csrf,
config refusals, ratelimit, app startup."""

from __future__ import annotations

import asyncio
import os
import sys

import pytest
from shield_server import app as app_module
from shield_server.auth import (
    AuthContext,
    _bearer,
    auth_context,
    resolve_auth,
)
from shield_server.auth import audit as audit_mod
from shield_server.auth import tokens as tokens_mod
from shield_server.auth.csrf import (
    csrf_token_from_header,
    is_state_changing,
    require_csrf,
)
from shield_server.auth.email import (
    ConsoleEmailSender,
    FileEmailSender,
    Message,
    build_email_sender,
    render_email_verify,
    render_invite,
    render_password_reset,
    with_sender_from,
)
from shield_server.auth.ratelimit import RateLimitConfig, enforce_or_block
from shield_server.auth.sessions import SessionRow, build_cookie_kwargs
from shield_server.auth.utils import (
    client_ip,
    constant_time_equal,
    generate_opaque_token,
    redact_argv,
    sha256_hex,
    uuidv7,
)
from shield_server.config import Settings, _parse_kid_list
from shield_server.errors import AppError
from shield_server.storage import build_memory_storage

pytestmark = pytest.mark.unit_auth


# --- utils ------------------------------------------------------------- #


def test_uuidv7_format_and_uniqueness() -> None:
    a = uuidv7()
    b = uuidv7()
    assert a != b
    assert len(a) == 36 and a.count("-") == 4


def test_sha256_hex_is_64chars() -> None:
    h = sha256_hex("hello")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_constant_time_equal_basic_and_types() -> None:
    assert constant_time_equal("abc", "abc")
    assert not constant_time_equal("abc", "abd")
    assert not constant_time_equal(None, "abc")  # type: ignore[arg-type]


def test_generate_opaque_token_length() -> None:
    t = generate_opaque_token()
    assert len(t) >= 60


def test_redact_argv_redacts_long_token_shaped_args(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = ["shield-server", "--allow-open-auth", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"]
    monkeypatch.setattr(sys, "argv", fake)
    out = redact_argv()
    assert out[-1] == "***REDACTED***"
    assert out[1] == "--allow-open-auth"


def test_client_ip_from_x_forwarded_for() -> None:
    ip = client_ip({"x-forwarded-for": "1.2.3.4, 5.6.7.8"})
    assert ip == "1.2.3.4"
    assert client_ip(None, fallback="9.9.9.9") == "9.9.9.9"


# --- W3 byte-compat surface ------------------------------------------- #


def test_w3_resolve_auth_api_token_path() -> None:
    from types import SimpleNamespace

    settings = SimpleNamespace(api_token="s3cr3t", dev_auth_open=False)
    from starlette.requests import Request

    scope = {
        "type": "http",
        "headers": [(b"authorization", b"Bearer s3cr3t")],
    }
    ctx = resolve_auth(Request(scope), settings)  # type: ignore[arg-type]
    assert ctx == AuthContext(org_id="demo-org", actor="api-token")


def test_w3_resolve_auth_dev_open_path() -> None:
    from types import SimpleNamespace

    from starlette.requests import Request

    settings = SimpleNamespace(api_token=None, dev_auth_open=True)
    ctx = resolve_auth(Request({"type": "http", "headers": []}), settings)  # type: ignore[arg-type]
    assert ctx.org_id == "demo-org"


def test_w3_resolve_auth_unauthorized() -> None:
    from types import SimpleNamespace

    from starlette.requests import Request

    settings = SimpleNamespace(api_token="real", dev_auth_open=False)
    with pytest.raises(AppError) as exc:
        resolve_auth(
            Request({"type": "http", "headers": [(b"authorization", b"Bearer wrong")]}),  # type: ignore[arg-type]
            settings,
        )
    assert exc.value.status_code == 401


def test_w3_bearer_helpers() -> None:
    from starlette.requests import Request

    assert _bearer(Request({"type": "http", "headers": []})) is None
    req = Request({"type": "http", "headers": [(b"authorization", b"Bearer    xyz   ")]})
    assert _bearer(req) == "xyz"


# --- audit ------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_audit_insert() -> None:
    storage = build_memory_storage()
    audit_id = await audit_mod.insert_audit(
        storage.db,
        event="SIGN_IN_OK",
        user_id="u1",
        org_id="demo-org",
        ip="127.0.0.1",
        user_agent="test",
        detail={"foo": "bar"},
    )
    assert audit_id
    assert len(storage.db.audit_log_auth) == 1
    row = storage.db.audit_log_auth[0]
    assert row["event"] == "SIGN_IN_OK"
    assert '"foo"' in row["detail"]


# --- tokens ------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_tokens_issue_and_consume_password_reset() -> None:
    storage = build_memory_storage()
    issued = await tokens_mod.issue(storage.db, kind="password_reset", user_id="u1")
    assert issued.raw and issued.user_id == "u1"
    user = await tokens_mod.consume(storage.db, kind="password_reset", raw=issued.raw)
    assert user == "u1"
    # Single-use: second consume fails.
    again = await tokens_mod.consume(storage.db, kind="password_reset", raw=issued.raw)
    assert again is None


@pytest.mark.asyncio
async def test_tokens_consume_unknown_token_returns_none() -> None:
    storage = build_memory_storage()
    assert (await tokens_mod.consume(storage.db, kind="password_reset", raw="ghost")) is None


# --- email ------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_console_email_sender(capsys: pytest.CaptureFixture[str]) -> None:
    s = ConsoleEmailSender()
    await s.send(Message(to="a@x", subject="S", body="B", from_addr="f@x"))
    out = capsys.readouterr().out
    assert "Subject: S" in out and "To: a@x" in out


@pytest.mark.asyncio
async def test_file_email_sender(tmp_path) -> None:
    s = FileEmailSender(str(tmp_path / "mbox"))
    await s.send(Message(to="a@x", subject="S", body="B", from_addr="f@x"))
    files = list((tmp_path / "mbox").iterdir())
    assert len(files) == 1
    body = files[0].read_text()
    assert "Subject: S" in body and "\n\nB\n" in body


def test_email_factory_refuses_console_under_enterprise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHIELD_AUTH_MODE", "enterprise")
    monkeypatch.setenv("SHIELD_EMAIL_BACKEND", "console")
    monkeypatch.setenv(
        "SHIELD_SESSION_SECRETS",
        "k1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    )
    monkeypatch.setenv(
        "SHIELD_PASSWORD_PEPPERS",
        "p1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    )
    monkeypatch.setenv(
        "SHIELD_AUTH_FERNET_KEYS",
        "f1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )
    settings = Settings.from_env()
    with pytest.raises(RuntimeError, match="REFUSED.*console"):
        build_email_sender(settings)


def test_render_templates_are_text_first() -> None:
    msg = render_password_reset(recipient="a@x", reset_url="http://x/r", ttl_minutes=15)
    assert "password reset" in msg.body.lower() and "http://x/r" in msg.body
    msg = render_email_verify(recipient="a@x", verify_url="http://x/v", ttl_minutes=60)
    assert "Confirm" in msg.body and "http://x/v" in msg.body
    msg = render_invite(
        recipient="a@x",
        accept_url="http://x/a",
        org_name="org",
        role="org_owner",
        ttl_minutes=60,
    )
    assert "invited to join" in msg.body
    # Stamp.
    from shield_server.config import Settings as S

    s = S(
        database_url="x",
        redis_url="x",
        minio_endpoint="x",
        minio_access_key="x",
        minio_secret_key="x",
        minio_secure=False,
        minio_bucket="x",
        server_signing_key="x",
        api_token=None,
        cors_origins=(),
        dev_auth_open=True,
        smtp_from="no-reply@example.com",
    )
    stamped = with_sender_from(msg, s)
    assert stamped.from_addr == "no-reply@example.com"


# --- csrf -------------------------------------------------------------- #


def test_csrf_state_changing_detection() -> None:
    from starlette.requests import Request

    for method in ("POST", "PATCH", "PUT", "DELETE"):
        req = Request({"type": "http", "method": method, "headers": []})
        assert is_state_changing(req)
    for method in ("GET", "HEAD", "OPTIONS"):
        req = Request({"type": "http", "method": method, "headers": []})
        assert not is_state_changing(req)


def test_csrf_header_extraction() -> None:
    from starlette.requests import Request

    req = Request({"type": "http", "headers": [(b"x-csrf-token", b"the-csrf")]})
    assert csrf_token_from_header(req) == "the-csrf"


def test_require_csrf_passes_for_safe_methods() -> None:
    from starlette.requests import Request

    req = Request({"type": "http", "method": "GET", "headers": []})
    sess = SessionRow(
        session_id="s",
        user_id="u",
        csrf_token="x",
        created_at=0,
        last_used_at=0,
        expires_at=0,
        revoked_at=None,
    )
    require_csrf(req, sess)  # no raise


def test_require_csrf_raises_403_on_mismatch() -> None:
    from starlette.requests import Request

    req = Request(
        {
            "type": "http",
            "method": "POST",
            "headers": [(b"x-csrf-token", b"WRONG")],
        }
    )
    sess = SessionRow(
        session_id="s",
        user_id="u",
        csrf_token="RIGHT",
        created_at=0,
        last_used_at=0,
        expires_at=0,
        revoked_at=None,
    )
    with pytest.raises(AppError) as exc:
        require_csrf(req, sess)
    assert exc.value.status_code == 403


# --- ratelimit --------------------------------------------------------- #


@pytest.mark.asyncio
async def test_enforce_or_block_passes_under_limit_and_blocks_over() -> None:
    storage = build_memory_storage()
    cfg = RateLimitConfig(bucket="t", limit=3, window_seconds=10)
    for _ in range(3):
        await enforce_or_block(
            storage.cache,
            config=cfg,
            headers={"x-forwarded-for": "1.1.1.1"},
            fallback_ip="1.1.1.1",
        )
    with pytest.raises(AppError) as exc:
        await enforce_or_block(
            storage.cache,
            config=cfg,
            headers={"x-forwarded-for": "1.1.1.1"},
            fallback_ip="1.1.1.1",
        )
    assert exc.value.status_code == 429


# --- sessions cookie kwargs ------------------------------------------- #


def test_build_cookie_kwargs_includes_secure_under_enterprise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHIELD_AUTH_MODE", "enterprise")
    monkeypatch.setenv("SHIELD_EMAIL_BACKEND", "file")
    monkeypatch.setenv("SHIELD_SESSION_SECRETS", "k1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    monkeypatch.setenv("SHIELD_PASSWORD_PEPPERS", "p1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    monkeypatch.setenv("SHIELD_AUTH_FERNET_KEYS", "f1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    monkeypatch.delenv("SHIELD_ALLOW_INSECURE_COOKIES", raising=False)
    settings = Settings.from_env()
    kw = build_cookie_kwargs(settings)
    assert kw["secure"] is True
    assert kw["httponly"] is True
    assert kw["samesite"] == "lax"


# --- config kid-list parser ------------------------------------------- #


def test_parse_kid_list_basic() -> None:
    assert _parse_kid_list(None) == ()
    assert _parse_kid_list("") == ()
    assert _parse_kid_list("k1:secret-a,k2:secret-b") == (
        ("k1", "secret-a"),
        ("k2", "secret-b"),
    )


def test_parse_kid_list_rejects_malformed() -> None:
    with pytest.raises(ValueError, match="kid:secret"):
        _parse_kid_list("notpair")
    with pytest.raises(ValueError, match="empty"):
        _parse_kid_list(":secret")
    with pytest.raises(ValueError, match="duplicate kid"):
        _parse_kid_list("k1:a,k1:b")


# --- app startup refusals (§A3 / §A4) --------------------------------- #


def test_refuse_open_without_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHIELD_AUTH_MODE", "open")
    # The W3 314-test path uses default enforce_startup_refusals=False; this
    # test opts in to make the §A3 refusal explicit.
    with pytest.raises(SystemExit) as exc:
        app_module.create_app(enforce_startup_refusals=True)
    assert "REFUSED" in str(exc.value)
    assert "--allow-open-auth" in str(exc.value)


def test_refuse_enterprise_with_console_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHIELD_AUTH_MODE", "enterprise")
    monkeypatch.setenv("SHIELD_EMAIL_BACKEND", "console")
    monkeypatch.setenv("SHIELD_SESSION_SECRETS", "k1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    monkeypatch.setenv("SHIELD_PASSWORD_PEPPERS", "p1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    monkeypatch.setenv("SHIELD_AUTH_FERNET_KEYS", "f1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    with pytest.raises(SystemExit) as exc:
        app_module.create_app(enforce_startup_refusals=True)
    assert "REFUSED" in str(exc.value)
    assert "console" in str(exc.value)


def test_cli_main_seed_admin_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """``shield-server --seed-admin`` routes to the auth CLI."""
    monkeypatch.setattr(
        "shield_server.auth.cli.main",
        lambda argv: (_ for _ in ()).throw(RuntimeError(f"called with {argv!r}")),
    )
    with pytest.raises(RuntimeError, match="called with"):
        app_module.cli_main(["--seed-admin", "--email", "x@y"])


# --- auth_context async wrapper across modes ------------------------- #


@pytest.mark.asyncio
async def test_auth_context_open_mode_returns_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHIELD_AUTH_MODE", raising=False)
    monkeypatch.setenv("SHIELD_DEV_AUTH", "open")
    from types import SimpleNamespace

    from starlette.requests import Request

    settings = Settings.from_env()
    request = Request(
        {
            "type": "http",
            "headers": [],
            "app": SimpleNamespace(state=SimpleNamespace(settings=settings)),
            "state": {},
        }
    )
    ctx = await auth_context(request)
    assert ctx == AuthContext(org_id="demo-org", actor="demo")


@pytest.mark.asyncio
async def test_auth_context_api_token_only_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHIELD_AUTH_MODE", "api_token_only")
    monkeypatch.setenv("SHIELD_API_TOKEN", "tok-xyz")
    from types import SimpleNamespace

    from starlette.requests import Request

    settings = Settings.from_env()
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", b"Bearer tok-xyz")],
            "app": SimpleNamespace(state=SimpleNamespace(settings=settings)),
            "state": {},
        }
    )
    ctx = await auth_context(request)
    assert ctx.actor == "api-token"


# Suppress lone imports of `asyncio` / `os` — kept to document side-effect
# usage when extending these tests.
_ = asyncio
_ = os
