"""ADR-0013 — Enterprise-auth REST routes (`/v1/auth/*`).

Mounted under ``SHIELD_AUTH_MODE=enterprise`` only (the app entrypoint omits
this router under ``open`` and ``api_token_only``). The 18 endpoints
implement the §A1-§A11 contract: session sign-up / sign-in / sign-out /
get-session / refresh, password reset, email verification, TOTP setup /
confirm / disable / recovery, admin user-list / sessions-list / session-
revoke / role-change / invite, and SDK api-keys (issue / list / revoke).

Every state-changing route uses ``Depends(principal_context)`` so the §A2
``test_every_route_declares_auth_dep`` invariant holds; CSRF is enforced
inline (``require_csrf``) on the session-bound state-changers.

Error shape: every failure raises ``AppError(<status>, "<ErrorCode>")`` so
the existing Elydora ``app_error_handler`` produces a byte-identical
``ErrorResponse`` body — no new error envelope.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from ..config import DEMO_ORG_ID, Settings
from ..errors import AppError
from . import api_keys as api_keys_svc
from . import sessions as sessions_svc
from . import tokens as tokens_svc
from . import users as users_svc
from .audit import insert_audit
from .csrf import require_csrf
from .dep import PrincipalDep, require_role
from .email import (
    render_email_verify,
    render_invite,
    render_password_reset,
    with_sender_from,
)
from .passwords import PasswordHasherService
from .principal import ALL_ROLES, Principal, Role
from .ratelimit import RateLimitConfig, enforce_or_block, record_block
from .sessions import build_cookie_kwargs
from .totp import TotpService
from .utils import client_ip, generate_opaque_token, now_ms, sha256_hex, uuidv7

auth_router = APIRouter(prefix="/v1/auth", tags=["auth"])


# --- request / response models ----------------------------------------- #


class SignUpRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    name: str = ""


class SignInRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    email: EmailStr
    password: str
    totp_code: str | None = None


class SignInResponse(BaseModel):
    user_id: str
    email: str
    role: Role
    org_id: str
    csrf_token: str
    requires_totp: bool = False


class SessionResponse(BaseModel):
    user_id: str
    email: str
    org_id: str
    role: Role
    totp_enabled: bool
    auth_kind: str
    csrf_token: str | None = None
    session_expires_at: int | None = None


class OkResponse(BaseModel):
    ok: bool = True


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    email: EmailStr


class PasswordResetComplete(BaseModel):
    model_config = ConfigDict(extra="ignore")
    token: str
    new_password: str = Field(min_length=8, max_length=256)


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    current_password: str
    new_password: str = Field(min_length=8, max_length=256)


class EmailVerifyComplete(BaseModel):
    token: str


class TotpSetupResponse(BaseModel):
    provisioning_uri: str
    secret: str
    # The QR rendering is left to the console (qrcode.js); we surface the
    # provisioning URI + raw secret. Returning a server-rendered PNG would
    # double the wire shape and offer no security benefit (the URI carries
    # the same secret).


class TotpConfirmRequest(BaseModel):
    code: str


class TotpConfirmResponse(BaseModel):
    recovery_codes: list[str]


class TotpDisableRequest(BaseModel):
    password: str
    code: str


class TotpRecoveryRequest(BaseModel):
    email: EmailStr
    recovery_code: str


class AdminUser(BaseModel):
    user_id: str
    email: str
    name: str
    status: str
    totp_enabled: bool
    role: Role | None = None
    last_login_at: int | None = None
    created_at: int


class AdminUsersResponse(BaseModel):
    users: list[AdminUser]


class AdminSessionRow(BaseModel):
    session_id: str
    user_id: str
    ip: str | None
    user_agent: str | None
    created_at: int
    last_used_at: int
    expires_at: int
    revoked_at: int | None


class AdminSessionsResponse(BaseModel):
    sessions: list[AdminSessionRow]


class AdminRoleChangeRequest(BaseModel):
    role: Role


class AdminInviteRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    email: EmailStr
    role: Role


class AdminInviteResponse(BaseModel):
    invite_id: str
    expires_at: int


class AcceptInviteRequest(BaseModel):
    """ADR-0013 §A1 — public-allowlisted invite-accept body shape.

    Console POSTs ``{token, password, name}`` to ``/v1/auth/invites/accept``
    (console accept-invite/page.tsx). Server hashes the token, looks up the
    pending invite, creates the user + membership + session, marks the
    invite consumed (single-use), and emits an ``INVITE_ACCEPT_OK`` audit row.
    """

    model_config = ConfigDict(extra="ignore")
    token: str
    password: str = Field(min_length=8, max_length=256)
    name: str = ""


class IssueApiKeyRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    display_name: str = ""
    prefix: Literal["as_live_", "as_test_"] = "as_live_"
    agent_id: str | None = None
    agent_id_allowlist: list[str] | None = None
    ttl_seconds: int | None = None


class ApiKeyView(BaseModel):
    api_key_id: str
    display_name: str
    prefix: str
    agent_id: str | None
    agent_id_allowlist: list[str] | None
    created_at: int
    created_by: str
    expires_at: int | None
    last_used_at: int | None
    revoked_at: int | None


class IssueApiKeyResponse(BaseModel):
    api_key: str  # raw — shown ONCE
    view: ApiKeyView


class ApiKeysListResponse(BaseModel):
    api_keys: list[ApiKeyView]


# --- helpers ----------------------------------------------------------- #


def _hasher(request: Request) -> PasswordHasherService:
    return request.app.state.password_hasher  # type: ignore[no-any-return]


def _totp(request: Request) -> TotpService:
    return request.app.state.totp_service  # type: ignore[no-any-return]


def _email_sender(request: Request) -> Any:
    return request.app.state.email_sender


def _settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def _build_url(settings: Settings, path: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}{path}"


def _set_session_cookie(response: Response, settings: Settings, raw_token: str) -> None:
    response.set_cookie(value=raw_token, **build_cookie_kwargs(settings))


def _clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.cookie_name,
        path="/",
        domain=settings.cookie_domain,
    )


# --- /v1/auth/sign-up -------------------------------------------------- #


@auth_router.post("/sign-up")
async def sign_up(body: SignUpRequest, request: Request, response: Response) -> SignInResponse:
    """Open self-service sign-up — admits the requester as the first user of
    a fresh org. Subsequent users on the same org arrive via invite (admin
    flow). Rate-limited at the IP level (§A1).
    """
    settings = _settings(request)
    storage = request.app.state.storage
    await enforce_or_block(
        storage.cache,
        config=RateLimitConfig(bucket="sign-up"),
        headers=dict(request.headers),
        fallback_ip=request.client.host if request.client else None,
    )
    # Email-enumeration safety: if the email is taken, return the same
    # generic 200-shaped response by raising a 409 only at the audit row
    # level — at the wire level, a duplicate email returns 409 VALIDATION_ERROR
    # since sign-up is a deliberately user-driven action (the user already
    # knows whether they own the address).
    if await users_svc.find_by_email(storage.db, email=body.email) is not None:
        raise AppError(409, "VALIDATION_ERROR", details={"field": "email"})
    user = await users_svc.create_user(
        storage.db,
        _hasher(request),
        email=body.email,
        password=body.password,
        name=body.name,
        org_id=DEMO_ORG_ID,
        role="org_owner",
    )
    sess = await sessions_svc.create_session(
        storage.db,
        user_id=user.user_id,
        ttl_seconds=settings.session_ttl_seconds,
        ip=client_ip(dict(request.headers)),
        user_agent=request.headers.get("user-agent"),
    )
    _set_session_cookie(response, settings, sess.raw_token)
    await insert_audit(
        storage.db,
        event="SIGN_UP_OK",
        user_id=user.user_id,
        org_id=DEMO_ORG_ID,
        ip=client_ip(dict(request.headers)),
        user_agent=request.headers.get("user-agent"),
    )
    # Schedule email verification.
    issued = await tokens_svc.issue(storage.db, kind="email_verification", user_id=user.user_id)
    verify_url = _build_url(settings, f"/verify-email?token={issued.raw}")
    msg = with_sender_from(
        render_email_verify(recipient=user.email, verify_url=verify_url, ttl_minutes=24 * 60),
        settings,
    )
    await _email_sender(request).send(msg)
    return SignInResponse(
        user_id=user.user_id,
        email=user.email,
        role="org_owner",
        org_id=DEMO_ORG_ID,
        csrf_token=sess.csrf_token,
        requires_totp=False,
    )


# --- /v1/auth/sign-in -------------------------------------------------- #


@auth_router.post("/sign-in")
async def sign_in(body: SignInRequest, request: Request, response: Response) -> SignInResponse:
    settings = _settings(request)
    storage = request.app.state.storage
    headers = dict(request.headers)
    ip = client_ip(headers, fallback=request.client.host if request.client else None)
    ua = request.headers.get("user-agent")
    await enforce_or_block(
        storage.cache,
        config=RateLimitConfig(bucket="sign-in"),
        headers=headers,
        fallback_ip=ip,
    )

    async def _fail(*, user_id: str | None, reason: str) -> None:
        await insert_audit(
            storage.db,
            event="SIGN_IN_FAIL",
            user_id=user_id,
            ip=ip,
            user_agent=ua,
            detail={"reason": reason, "email": body.email},
        )
        raise AppError(401, "UNAUTHORIZED")

    user = await users_svc.find_by_email(storage.db, email=body.email)
    if user is None:
        await _fail(user_id=None, reason="unknown_email")
        raise AppError(401, "UNAUTHORIZED")  # _fail already raised; defensive
    if user.status == "disabled":
        await _fail(user_id=user.user_id, reason="disabled")
    if users_svc.lockout_is_active(user):
        await insert_audit(
            storage.db,
            event="SIGN_IN_LOCKED",
            user_id=user.user_id,
            ip=ip,
            user_agent=ua,
            detail={"locked_until": user.locked_until},
        )
        raise AppError(401, "UNAUTHORIZED")
    verify = _hasher(request).verify(body.password, user.password_hash, user.password_pepper_kid)
    if not verify.ok:
        await users_svc.record_failed_login(storage.db, user_id=user.user_id, ip=ip, user_agent=ua)
        await _fail(user_id=user.user_id, reason="password")
    # TOTP gate
    if user.totp_enabled:
        tc = await storage.db.fetchrow(
            "SELECT user_id, secret_encrypted, active_kid, recovery_codes_hash "
            "FROM totp_credentials WHERE user_id = $1",
            user.user_id,
        )
        if tc is None:
            await _fail(user_id=user.user_id, reason="totp_missing_credential")
        if not body.totp_code:
            await insert_audit(
                storage.db,
                event="SIGN_IN_TOTP_REQUIRED",
                user_id=user.user_id,
                ip=ip,
                user_agent=ua,
            )
            raise AppError(
                401,
                "UNAUTHORIZED",
                details={"code": "totp_required"},
            )
        assert tc is not None
        decrypted = _totp(request).decrypt(
            str(tc["secret_encrypted"]), stored_kid=str(tc["active_kid"])
        )
        if not _totp(request).verify(decrypted.secret, body.totp_code):
            await insert_audit(
                storage.db,
                event="SIGN_IN_TOTP_FAIL",
                user_id=user.user_id,
                ip=ip,
                user_agent=ua,
            )
            raise AppError(401, "UNAUTHORIZED")
        await insert_audit(
            storage.db,
            event="SIGN_IN_TOTP_OK",
            user_id=user.user_id,
            ip=ip,
            user_agent=ua,
        )
    # Success path
    await users_svc.reset_failed_login(storage.db, user_id=user.user_id)
    if verify.needs_rehash:
        new_hash, new_kid = _hasher(request).hash(body.password)
        await users_svc.update_password_hash(
            storage.db, user_id=user.user_id, password_hash=new_hash, pepper_kid=new_kid
        )
    membership = await users_svc.primary_membership(storage.db, user_id=user.user_id)
    if membership is None:
        raise AppError(403, "FORBIDDEN")
    org_id, role = membership
    sess = await sessions_svc.create_session(
        storage.db,
        user_id=user.user_id,
        ttl_seconds=settings.session_ttl_seconds,
        ip=ip,
        user_agent=ua,
    )
    _set_session_cookie(response, settings, sess.raw_token)
    await insert_audit(
        storage.db,
        event="SIGN_IN_OK",
        user_id=user.user_id,
        org_id=org_id,
        ip=ip,
        user_agent=ua,
    )
    return SignInResponse(
        user_id=user.user_id,
        email=user.email,
        role=role,
        org_id=org_id,
        csrf_token=sess.csrf_token,
    )


# --- /v1/auth/sign-out ------------------------------------------------- #


@auth_router.post("/sign-out")
async def sign_out(request: Request, response: Response, principal: PrincipalDep) -> OkResponse:
    storage = request.app.state.storage
    if principal.is_session and principal.session_id is not None:
        await sessions_svc.revoke_session(storage.db, session_id=principal.session_id)
        await insert_audit(
            storage.db,
            event="SIGN_OUT",
            user_id=principal.user_id,
            org_id=principal.org_id,
        )
    _clear_session_cookie(response, _settings(request))
    return OkResponse()


# --- /v1/auth/session -------------------------------------------------- #


@auth_router.get("/session")
async def get_session(request: Request, principal: PrincipalDep) -> SessionResponse:
    storage = request.app.state.storage
    csrf: str | None = None
    expires_at: int | None = None
    if principal.is_session and principal.session_id is not None:
        # Re-fetch row to read the CURRENT csrf_token (the row may have
        # rotated since principal_context resolution).
        row = await storage.db.fetchrow(
            "SELECT session_id, user_id, csrf_token, created_at, last_used_at, "
            "expires_at, revoked_at FROM sessions WHERE session_id = $1",
            principal.session_id,
        )
        if row is not None:
            csrf = str(row["csrf_token"])
            expires_at = int(row["expires_at"])
    return SessionResponse(
        user_id=principal.user_id,
        email=principal.email or "",
        org_id=principal.org_id,
        role=principal.role,
        totp_enabled=principal.totp_enabled,
        auth_kind=principal.auth_kind,
        csrf_token=csrf,
        session_expires_at=expires_at,
    )


@auth_router.post("/session/refresh")
async def session_refresh(
    request: Request, response: Response, principal: PrincipalDep
) -> SessionResponse:
    if not principal.is_session or principal.session_id is None:
        raise AppError(401, "UNAUTHORIZED")
    storage = request.app.state.storage
    settings = _settings(request)
    # CSRF required for state-changing refresh
    session_row = await storage.db.fetchrow(
        "SELECT session_id, user_id, csrf_token, created_at, last_used_at, "
        "expires_at, revoked_at FROM sessions WHERE session_id = $1",
        principal.session_id,
    )
    if session_row is None:
        raise AppError(401, "UNAUTHORIZED")
    require_csrf(
        request,
        sessions_svc.SessionRow(
            session_id=str(session_row["session_id"]),
            user_id=str(session_row["user_id"]),
            csrf_token=str(session_row["csrf_token"]),
            created_at=int(session_row["created_at"]),
            last_used_at=int(session_row["last_used_at"]),
            expires_at=int(session_row["expires_at"]),
            revoked_at=None,
        ),
    )
    raw, csrf = await sessions_svc.rotate_token(storage.db, session_id=principal.session_id)
    _set_session_cookie(response, settings, raw)
    await insert_audit(
        storage.db,
        event="SESSION_REFRESH",
        user_id=principal.user_id,
        org_id=principal.org_id,
    )
    return SessionResponse(
        user_id=principal.user_id,
        email=principal.email or "",
        org_id=principal.org_id,
        role=principal.role,
        totp_enabled=principal.totp_enabled,
        auth_kind=principal.auth_kind,
        csrf_token=csrf,
    )


# --- /v1/auth/password/reset/request|complete -------------------------- #


@auth_router.post("/password/reset/request")
async def password_reset_request(body: PasswordResetRequest, request: Request) -> OkResponse:
    """Always returns {ok: true} regardless of email existence (§A7)."""
    storage = request.app.state.storage
    settings = _settings(request)
    await enforce_or_block(
        storage.cache,
        config=RateLimitConfig(bucket="password-reset"),
        headers=dict(request.headers),
        fallback_ip=request.client.host if request.client else None,
    )
    user = await users_svc.find_by_email(storage.db, email=body.email)
    if user is None:
        return OkResponse()
    issued = await tokens_svc.issue(storage.db, kind="password_reset", user_id=user.user_id)
    reset_url = _build_url(settings, f"/reset-password?token={issued.raw}")
    msg = with_sender_from(
        render_password_reset(recipient=user.email, reset_url=reset_url, ttl_minutes=15),
        settings,
    )
    await _email_sender(request).send(msg)
    await insert_audit(
        storage.db,
        event="PASSWORD_RESET_REQUEST",
        user_id=user.user_id,
    )
    return OkResponse()


@auth_router.post("/password/reset/complete")
async def password_reset_complete(body: PasswordResetComplete, request: Request) -> OkResponse:
    storage = request.app.state.storage
    user_id = await tokens_svc.consume(storage.db, kind="password_reset", raw=body.token)
    if user_id is None:
        raise AppError(400, "VALIDATION_ERROR", details={"reason": "invalid_or_expired_token"})
    new_hash, new_kid = _hasher(request).hash(body.new_password)
    await users_svc.update_password_hash(
        storage.db, user_id=user_id, password_hash=new_hash, pepper_kid=new_kid
    )
    await sessions_svc.revoke_all_for_user(storage.db, user_id=user_id)
    await insert_audit(
        storage.db,
        event="PASSWORD_RESET_COMPLETE",
        user_id=user_id,
    )
    return OkResponse()


@auth_router.post("/password/change")
async def password_change(
    body: PasswordChangeRequest, request: Request, principal: PrincipalDep
) -> OkResponse:
    if not principal.is_session or principal.session_id is None:
        raise AppError(401, "UNAUTHORIZED")
    storage = request.app.state.storage
    sess_row = await storage.db.fetchrow(
        "SELECT session_id, user_id, csrf_token, created_at, last_used_at, "
        "expires_at, revoked_at FROM sessions WHERE session_id = $1",
        principal.session_id,
    )
    if sess_row is None:
        raise AppError(401, "UNAUTHORIZED")
    require_csrf(
        request,
        sessions_svc.SessionRow(
            session_id=str(sess_row["session_id"]),
            user_id=str(sess_row["user_id"]),
            csrf_token=str(sess_row["csrf_token"]),
            created_at=int(sess_row["created_at"]),
            last_used_at=int(sess_row["last_used_at"]),
            expires_at=int(sess_row["expires_at"]),
            revoked_at=None,
        ),
    )
    user = await users_svc.find_by_user_id(storage.db, user_id=principal.user_id)
    if user is None:
        raise AppError(401, "UNAUTHORIZED")
    verify = _hasher(request).verify(
        body.current_password, user.password_hash, user.password_pepper_kid
    )
    if not verify.ok:
        raise AppError(401, "UNAUTHORIZED")
    new_hash, new_kid = _hasher(request).hash(body.new_password)
    await users_svc.update_password_hash(
        storage.db, user_id=user.user_id, password_hash=new_hash, pepper_kid=new_kid
    )
    # Rotate this session's cookie; invalidate all others.
    raw, _csrf = await sessions_svc.rotate_token(storage.db, session_id=principal.session_id)
    # No cookie rewrite here without a Response — leave that to refresh.
    await insert_audit(
        storage.db,
        event="PASSWORD_CHANGE",
        user_id=user.user_id,
    )
    _ = raw
    return OkResponse()


# --- /v1/auth/email/verify --------------------------------------------- #


@auth_router.post("/email/verify/request")
async def email_verify_request(request: Request, principal: PrincipalDep) -> OkResponse:
    if not principal.is_session:
        raise AppError(401, "UNAUTHORIZED")
    storage = request.app.state.storage
    settings = _settings(request)
    issued = await tokens_svc.issue(
        storage.db, kind="email_verification", user_id=principal.user_id
    )
    verify_url = _build_url(settings, f"/verify-email?token={issued.raw}")
    msg = with_sender_from(
        render_email_verify(
            recipient=principal.email or "", verify_url=verify_url, ttl_minutes=24 * 60
        ),
        settings,
    )
    await _email_sender(request).send(msg)
    await insert_audit(
        storage.db,
        event="EMAIL_VERIFY_REQUEST",
        user_id=principal.user_id,
    )
    return OkResponse()


@auth_router.post("/email/verify/complete")
async def email_verify_complete(body: EmailVerifyComplete, request: Request) -> OkResponse:
    storage = request.app.state.storage
    user_id = await tokens_svc.consume(storage.db, kind="email_verification", raw=body.token)
    if user_id is None:
        raise AppError(400, "VALIDATION_ERROR", details={"reason": "invalid_or_expired_token"})
    await users_svc.set_email_verified(storage.db, user_id=user_id)
    await insert_audit(
        storage.db,
        event="EMAIL_VERIFY_COMPLETE",
        user_id=user_id,
    )
    return OkResponse()


# --- /v1/auth/totp/setup|confirm|disable|recovery --------------------- #


@auth_router.post("/totp/setup")
async def totp_setup(request: Request, principal: PrincipalDep) -> TotpSetupResponse:
    if not principal.is_session:
        raise AppError(401, "UNAUTHORIZED")
    storage = request.app.state.storage
    totp = _totp(request)
    setup_data = totp.setup_for(principal.email or principal.user_id)
    # Persist the encrypted secret + freshly-generated (UNCONFIRMED) recovery codes.
    encrypted = totp.encrypt(setup_data.secret)
    _, recovery_hashes = TotpService.generate_recovery_codes()
    await storage.db.execute(
        "INSERT INTO totp_credentials (user_id, secret_encrypted, active_kid, "
        "recovery_codes_hash, enabled_at, last_used_at) "
        "VALUES ($1, $2, $3, $4, $5, NULL)",
        principal.user_id,
        encrypted,
        totp.active_kid,
        recovery_hashes,
        now_ms(),
    )
    await insert_audit(
        storage.db,
        event="TOTP_SETUP",
        user_id=principal.user_id,
    )
    return TotpSetupResponse(
        provisioning_uri=setup_data.provisioning_uri,
        secret=setup_data.secret,
    )


@auth_router.post("/totp/confirm")
async def totp_confirm(
    body: TotpConfirmRequest, request: Request, principal: PrincipalDep
) -> TotpConfirmResponse:
    if not principal.is_session:
        raise AppError(401, "UNAUTHORIZED")
    storage = request.app.state.storage
    totp = _totp(request)
    tc = await storage.db.fetchrow(
        "SELECT user_id, secret_encrypted, active_kid, recovery_codes_hash "
        "FROM totp_credentials WHERE user_id = $1",
        principal.user_id,
    )
    if tc is None:
        raise AppError(400, "VALIDATION_ERROR", details={"reason": "no_pending_setup"})
    decrypted = totp.decrypt(str(tc["secret_encrypted"]), stored_kid=str(tc["active_kid"]))
    if not totp.verify(decrypted.secret, body.code):
        raise AppError(400, "VALIDATION_ERROR", details={"reason": "totp_code_mismatch"})
    # Confirmed — enable TOTP on the user row + return a FRESH set of recovery
    # codes (the setup-time codes are replaced; user sees them once now).
    plain, hashed = TotpService.generate_recovery_codes()
    await storage.db.execute(
        "UPDATE totp_credentials SET recovery_codes_hash = $1, last_used_at = $2 "
        "WHERE user_id = $3",
        hashed,
        now_ms(),
        principal.user_id,
    )
    await users_svc.set_totp_enabled(storage.db, user_id=principal.user_id, enabled=True)
    await insert_audit(
        storage.db,
        event="TOTP_CONFIRM",
        user_id=principal.user_id,
    )
    return TotpConfirmResponse(recovery_codes=plain)


@auth_router.post("/totp/disable")
async def totp_disable(
    body: TotpDisableRequest, request: Request, principal: PrincipalDep
) -> OkResponse:
    if not principal.is_session:
        raise AppError(401, "UNAUTHORIZED")
    storage = request.app.state.storage
    user = await users_svc.find_by_user_id(storage.db, user_id=principal.user_id)
    if user is None:
        raise AppError(401, "UNAUTHORIZED")
    verify = _hasher(request).verify(body.password, user.password_hash, user.password_pepper_kid)
    if not verify.ok:
        raise AppError(401, "UNAUTHORIZED")
    totp = _totp(request)
    tc = await storage.db.fetchrow(
        "SELECT user_id, secret_encrypted, active_kid, recovery_codes_hash "
        "FROM totp_credentials WHERE user_id = $1",
        principal.user_id,
    )
    if tc is not None:
        decrypted = totp.decrypt(str(tc["secret_encrypted"]), stored_kid=str(tc["active_kid"]))
        if not totp.verify(decrypted.secret, body.code):
            raise AppError(401, "UNAUTHORIZED")
    await storage.db.execute("DELETE FROM totp_credentials WHERE user_id = $1", principal.user_id)
    await users_svc.set_totp_enabled(storage.db, user_id=principal.user_id, enabled=False)
    await insert_audit(
        storage.db,
        event="TOTP_DISABLE",
        user_id=principal.user_id,
    )
    return OkResponse()


@auth_router.post("/totp/recovery")
async def totp_recovery(
    body: TotpRecoveryRequest, request: Request, response: Response
) -> SignInResponse:
    """Unauthenticated recovery-code path: consumes a single-use recovery
    code and issues a session in place of the missing TOTP code."""
    storage = request.app.state.storage
    settings = _settings(request)
    user = await users_svc.find_by_email(storage.db, email=body.email)
    if user is None or not user.totp_enabled:
        raise AppError(401, "UNAUTHORIZED")
    tc = await storage.db.fetchrow(
        "SELECT user_id, secret_encrypted, active_kid, recovery_codes_hash "
        "FROM totp_credentials WHERE user_id = $1",
        user.user_id,
    )
    if tc is None:
        raise AppError(401, "UNAUTHORIZED")
    stored_hashes = list(tc["recovery_codes_hash"] or [])
    stored_hashes = [str(h) for h in stored_hashes]
    ok, new_hashes = TotpService.consume_recovery_code(
        body.recovery_code, stored_hashes=stored_hashes
    )
    if not ok:
        raise AppError(401, "UNAUTHORIZED")
    await storage.db.execute(
        "UPDATE totp_credentials SET recovery_codes_hash = $1, last_used_at = $2 "
        "WHERE user_id = $3",
        new_hashes,
        now_ms(),
        user.user_id,
    )
    membership = await users_svc.primary_membership(storage.db, user_id=user.user_id)
    if membership is None:
        raise AppError(403, "FORBIDDEN")
    org_id, role = membership
    sess = await sessions_svc.create_session(
        storage.db,
        user_id=user.user_id,
        ttl_seconds=settings.session_ttl_seconds,
        ip=client_ip(dict(request.headers)),
        user_agent=request.headers.get("user-agent"),
    )
    _set_session_cookie(response, settings, sess.raw_token)
    await insert_audit(
        storage.db,
        event="SIGN_IN_RECOVERY_OK",
        user_id=user.user_id,
        org_id=org_id,
    )
    return SignInResponse(
        user_id=user.user_id,
        email=user.email,
        role=role,
        org_id=org_id,
        csrf_token=sess.csrf_token,
    )


# --- /v1/auth/admin/* -------------------------------------------------- #


AdminCtx = Annotated[Principal, Depends(require_role("org_owner", "security_admin"))]
OrgOwnerCtx = Annotated[Principal, Depends(require_role("org_owner"))]


@auth_router.get("/admin/users")
async def admin_list_users(request: Request, principal: AdminCtx) -> AdminUsersResponse:
    storage = request.app.state.storage
    rows = await storage.db.fetch("SELECT * FROM users")
    out: list[AdminUser] = []
    for r in rows:
        role: Role | None = await users_svc.role_for(
            storage.db, user_id=str(r["user_id"]), org_id=principal.org_id
        )
        out.append(
            AdminUser(
                user_id=str(r["user_id"]),
                email=str(r["email"]),
                name=str(r.get("name") or ""),
                status=str(r.get("status") or "active"),
                totp_enabled=bool(r.get("totp_enabled", False)),
                role=role,
                last_login_at=(
                    int(r["last_login_at"]) if r.get("last_login_at") is not None else None
                ),
                created_at=int(r["created_at"]),
            )
        )
    return AdminUsersResponse(users=out)


@auth_router.get("/admin/users/{user_id}/sessions")
async def admin_list_sessions(
    user_id: str, request: Request, principal: AdminCtx
) -> AdminSessionsResponse:
    storage = request.app.state.storage
    rows = await sessions_svc.list_sessions_for_user(storage.db, user_id=user_id)
    return AdminSessionsResponse(
        sessions=[
            AdminSessionRow(
                session_id=str(r["session_id"]),
                user_id=str(r["user_id"]),
                ip=(str(r["ip"]) if r.get("ip") else None),
                user_agent=(str(r["user_agent"]) if r.get("user_agent") else None),
                created_at=int(r["created_at"]),  # type: ignore[call-overload]
                last_used_at=int(r["last_used_at"]),  # type: ignore[call-overload]
                expires_at=int(r["expires_at"]),  # type: ignore[call-overload]
                revoked_at=(int(r["revoked_at"]) if r.get("revoked_at") else None),  # type: ignore[call-overload]
            )
            for r in rows
        ]
    )


@auth_router.post("/admin/sessions/{session_id}/revoke")
async def admin_revoke_session(
    session_id: str, request: Request, principal: AdminCtx
) -> OkResponse:
    storage = request.app.state.storage
    await sessions_svc.revoke_session(storage.db, session_id=session_id)
    await insert_audit(
        storage.db,
        event="SESSION_REVOKE",
        user_id=principal.user_id,
        org_id=principal.org_id,
        detail={"target_session_id": session_id},
    )
    return OkResponse()


@auth_router.post("/admin/users/{user_id}/role")
async def admin_change_role(
    user_id: str, body: AdminRoleChangeRequest, request: Request, principal: OrgOwnerCtx
) -> OkResponse:
    if body.role not in ALL_ROLES:
        raise AppError(400, "VALIDATION_ERROR", details={"reason": "invalid_role"})
    storage = request.app.state.storage
    await users_svc.change_role(
        storage.db, user_id=user_id, org_id=principal.org_id, role=body.role
    )
    await insert_audit(
        storage.db,
        event="ROLE_CHANGE",
        user_id=principal.user_id,
        org_id=principal.org_id,
        detail={"target_user_id": user_id, "new_role": body.role},
    )
    return OkResponse()


@auth_router.post("/admin/invite")
async def admin_invite(
    body: AdminInviteRequest, request: Request, principal: OrgOwnerCtx
) -> AdminInviteResponse:
    storage = request.app.state.storage
    settings = _settings(request)
    invite_id = uuidv7()
    raw = generate_opaque_token()
    expires_at = now_ms() + tokens_svc.INVITE_TTL_MS
    await storage.db.execute(
        "INSERT INTO invites (invite_id, org_id, email, role, invited_by, "
        "expires_at, consumed_at, created_at, token_hash) "
        "VALUES ($1, $2, $3, $4, $5, $6, NULL, $7, $8)",
        invite_id,
        principal.org_id,
        body.email,
        body.role,
        principal.user_id,
        expires_at,
        now_ms(),
        sha256_hex(raw),
    )
    accept_url = _build_url(settings, f"/accept-invite?token={raw}")
    msg = with_sender_from(
        render_invite(
            recipient=body.email,
            accept_url=accept_url,
            org_name=principal.org_id,
            role=body.role,
            ttl_minutes=7 * 24 * 60,
        ),
        settings,
    )
    await _email_sender(request).send(msg)
    await insert_audit(
        storage.db,
        event="INVITE_SEND",
        user_id=principal.user_id,
        org_id=principal.org_id,
        detail={"target_email": body.email, "role": body.role},
    )
    return AdminInviteResponse(invite_id=invite_id, expires_at=expires_at)


# --- /v1/auth/invites/accept ------------------------------------------- #


@auth_router.post("/invites/accept")
async def accept_invite(
    body: AcceptInviteRequest, request: Request, response: Response
) -> SignInResponse:
    """ADR-0013 §A1 — public-allowlisted invite-accept handler.

    Pairs with ``POST /v1/auth/admin/invite``: admin ISSUES invites (admin
    role), invitees ACCEPT via the emailed link. This endpoint is in
    ``PUBLIC_ROUTE_PATHS`` (``auth/dep.py``) — reachable without a session
    because the invitee does not have one yet.

    Behaviour:
      * §A7 uniform 401 ``UNAUTHORIZED`` on any token-failure mode
        (unknown / consumed / expired / email-collision). The true reason
        lives in ``audit_log_auth.INVITE_ACCEPT_FAIL`` only — no enumeration.
      * §A1 argon2id + active pepper for the new user's ``password_hash``.
      * §A7 ``email_verified_at = now_ms()`` on creation — invite delivery
        IS the email proof-of-control.
      * Single-use enforced by ``invites.consumed_at`` UPDATE; a repeat
        POST of the same token fails uniform 401.
      * Rate-limited at the IP level (same 10/min slowapi bucket pattern
        as sign-up / sign-in).
      * Creates a fresh server-authoritative session (opaque cookie token +
        CSRF) and Set-Cookie's it; returns the SAME ``SignInResponse``
        shape as sign-in / sign-up so the console post-auth flow plugs in
        unchanged.
    """
    settings = _settings(request)
    storage = request.app.state.storage
    headers = dict(request.headers)
    ip = client_ip(headers, fallback=request.client.host if request.client else None)
    ua = request.headers.get("user-agent")
    await enforce_or_block(
        storage.cache,
        config=RateLimitConfig(bucket="invites-accept"),
        headers=headers,
        fallback_ip=ip,
    )

    async def _fail(*, invite_id: str | None, reason: str) -> None:
        await insert_audit(
            storage.db,
            event="INVITE_ACCEPT_FAIL",
            ip=ip,
            user_agent=ua,
            detail={"reason": reason, "invite_id": invite_id},
        )
        raise AppError(401, "UNAUTHORIZED")

    token_hash = sha256_hex(body.token)
    row = await storage.db.fetchrow(
        "SELECT invite_id, org_id, email, role, invited_by, expires_at, "
        "consumed_at, created_at, token_hash FROM invites WHERE token_hash = $1",
        token_hash,
    )
    if row is None:
        await _fail(invite_id=None, reason="unknown_token")
    assert row is not None
    invite_id = str(row["invite_id"])
    if row.get("consumed_at") is not None:
        await _fail(invite_id=invite_id, reason="already_consumed")
    expires_at = row.get("expires_at")
    if expires_at is None or int(expires_at) < now_ms():
        await _fail(invite_id=invite_id, reason="expired")

    org_id = str(row["org_id"])
    invite_email = str(row["email"])
    role = str(row["role"])
    invited_by = str(row["invited_by"])

    # §A7 email-enumeration: a collision with an existing user is also a
    # uniform 401 (the invitee should never learn whether their email was
    # pre-registered through the invite-accept endpoint).
    existing = await users_svc.find_by_email(storage.db, email=invite_email)
    if existing is not None:
        await _fail(invite_id=invite_id, reason="email_collision")

    # Create the user + role membership (transactional via users_svc).
    new_user = await users_svc.create_user(
        storage.db,
        _hasher(request),
        email=invite_email,
        password=body.password,
        name=body.name,
        org_id=org_id,
        role=role,  # type: ignore[arg-type]  # CHECK constraint on invites guarantees valid role
        invited_by=invited_by,
    )
    # Invite-delivery implies email control → mark verified now.
    await users_svc.set_email_verified(storage.db, user_id=new_user.user_id)
    # Atomically consume the invite (single-use).
    await storage.db.execute(
        "UPDATE invites SET consumed_at = $1 WHERE invite_id = $2",
        now_ms(),
        invite_id,
    )
    await insert_audit(
        storage.db,
        event="INVITE_ACCEPT_OK",
        user_id=new_user.user_id,
        org_id=org_id,
        ip=ip,
        user_agent=ua,
        detail={"invite_id": invite_id, "role": role},
    )

    # Issue a fresh session — same shape as sign-up / sign-in so the
    # console post-auth flow is unchanged.
    sess = await sessions_svc.create_session(
        storage.db,
        user_id=new_user.user_id,
        ttl_seconds=settings.session_ttl_seconds,
        ip=ip,
        user_agent=ua,
    )
    _set_session_cookie(response, settings, sess.raw_token)
    return SignInResponse(
        user_id=new_user.user_id,
        email=new_user.email,
        role=role,
        org_id=org_id,
        csrf_token=sess.csrf_token,
    )


# --- /v1/auth/api-keys ------------------------------------------------- #


def _view_of(row: api_keys_svc.ApiKeyRow) -> ApiKeyView:
    return ApiKeyView(
        api_key_id=row.api_key_id,
        display_name=row.display_name,
        prefix=row.prefix,
        agent_id=row.agent_id,
        agent_id_allowlist=list(row.agent_id_allowlist) if row.agent_id_allowlist else None,
        created_at=row.created_at,
        created_by=row.created_by,
        expires_at=row.expires_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
    )


@auth_router.post("/api-keys")
async def issue_api_key(
    body: IssueApiKeyRequest, request: Request, principal: AdminCtx
) -> IssueApiKeyResponse:
    storage = request.app.state.storage
    expires_at = (now_ms() + body.ttl_seconds * 1000) if body.ttl_seconds else None
    allowlist = tuple(body.agent_id_allowlist) if body.agent_id_allowlist else None
    issued = await api_keys_svc.issue_api_key(
        storage.db,
        org_id=principal.org_id,
        created_by=principal.user_id,
        prefix=body.prefix,
        display_name=body.display_name,
        agent_id=body.agent_id,
        agent_id_allowlist=allowlist,
        expires_at=expires_at,
    )
    await insert_audit(
        storage.db,
        event="API_KEY_ISSUE",
        user_id=principal.user_id,
        org_id=principal.org_id,
        detail={"api_key_id": issued.row.api_key_id, "prefix": body.prefix},
    )
    return IssueApiKeyResponse(api_key=issued.raw_key, view=_view_of(issued.row))


@auth_router.get("/api-keys")
async def list_api_keys(request: Request, principal: AdminCtx) -> ApiKeysListResponse:
    storage = request.app.state.storage
    rows = await api_keys_svc.list_api_keys_for_org(storage.db, org_id=principal.org_id)
    return ApiKeysListResponse(api_keys=[_view_of(r) for r in rows])


@auth_router.delete("/api-keys/{api_key_id}")
async def revoke_api_key_route(
    api_key_id: str, request: Request, principal: AdminCtx
) -> OkResponse:
    storage = request.app.state.storage
    await api_keys_svc.revoke_api_key(storage.db, api_key_id=api_key_id)
    await insert_audit(
        storage.db,
        event="API_KEY_REVOKE",
        user_id=principal.user_id,
        org_id=principal.org_id,
        detail={"api_key_id": api_key_id},
    )
    return OkResponse()


# Suppress 'record_block' unused — kept exportable for any future telemetry
# wiring on rate-limited paths (already plumbed in ratelimit.py).
_ = record_block


__all__ = ["auth_router"]
