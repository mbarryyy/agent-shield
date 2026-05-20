"""Elydora error model — 1:1 port of
Related_Work/Elydora-Open-Source-main/packages/server/src/shared/constants/errors.ts
+ middleware/error-handler.ts.

The console (`console/src/lib/api.ts`) parses `ErrorResponse.error.{code,message,
request_id,details}` and branches on `code`, so the wire shape is load-bearing
and must byte-match Elydora.
"""

from __future__ import annotations

from typing import Literal

from fastapi import Request
from fastapi.responses import JSONResponse

ErrorCode = Literal[
    "INVALID_SIGNATURE",
    "UNKNOWN_AGENT",
    "KEY_REVOKED",
    "AGENT_FROZEN",
    "TTL_EXPIRED",
    "REPLAY_DETECTED",
    "PREV_HASH_MISMATCH",
    "PAYLOAD_TOO_LARGE",
    "RATE_LIMITED",
    "INTERNAL_ERROR",
    "UNAUTHORIZED",
    "FORBIDDEN",
    "NOT_FOUND",
    "VALIDATION_ERROR",
    # ADR-0013 §A1.c — enterprise mode hard-disables self-service sign-up;
    # new users arrive via /v1/auth/admin/invite + /v1/auth/invites/accept.
    "ENTERPRISE_MODE_SIGNUP_DISABLED",
]

# Verbatim from shared/constants/errors.ts (plus the ADR-0013 §A1.c addition).
ERROR_CODES: dict[ErrorCode, str] = {
    "INVALID_SIGNATURE": "The operation signature is invalid.",
    "UNKNOWN_AGENT": "The specified agent does not exist.",
    "KEY_REVOKED": "The signing key has been revoked.",
    "AGENT_FROZEN": "The agent is frozen and cannot submit operations.",
    "TTL_EXPIRED": "The operation TTL has expired.",
    "REPLAY_DETECTED": "A duplicate nonce was detected (replay attack).",
    "PREV_HASH_MISMATCH": "The previous chain hash does not match.",
    "PAYLOAD_TOO_LARGE": "The operation payload exceeds the maximum allowed size.",
    "RATE_LIMITED": "Too many requests. Please retry later.",
    "INTERNAL_ERROR": "An internal server error occurred.",
    "UNAUTHORIZED": "Authentication is required.",
    "FORBIDDEN": "You do not have permission to perform this action.",
    "NOT_FOUND": "The requested resource was not found.",
    "VALIDATION_ERROR": "The request failed validation.",
    "ENTERPRISE_MODE_SIGNUP_DISABLED": (
        "Self-service sign-up is disabled in enterprise mode. "
        "New users must arrive via invite from an org admin."
    ),
}


class AppError(Exception):
    """Carries an HTTP status + Elydora error code (error-handler.ts:AppError)."""

    def __init__(
        self,
        status_code: int,
        error_code: ErrorCode,
        message: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message or ERROR_CODES[error_code])
        self.status_code = status_code
        self.error_code: ErrorCode = error_code
        self.message = message or ERROR_CODES[error_code]
        self.details = details


def build_error_response(
    code: ErrorCode,
    request_id: str,
    message: str | None = None,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    """Standardised body (error-handler.ts:buildErrorResponse)."""
    error: dict[str, object] = {
        "code": code,
        "message": message or ERROR_CODES[code],
        "request_id": request_id,
    }
    if details:
        error["details"] = details
    return {"error": error}


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    if isinstance(exc, AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_response(exc.error_code, request_id, exc.message, exc.details),
        )
    return JSONResponse(  # pragma: no cover - defensive: unhandled non-AppError
        status_code=500,
        content=build_error_response("INTERNAL_ERROR", request_id),
    )
