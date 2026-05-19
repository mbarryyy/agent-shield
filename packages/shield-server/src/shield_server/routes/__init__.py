"""HTTP routes — faithful to the Elydora console contract (`console/src/lib/api.ts`).

Endpoint paths/verbs/status codes mirror Elydora `src/routes/*.ts` so the
existing Next.js console boots unchanged against this FastAPI backend. The §4
governance surface (`POST /v1/governance/decide`, Channel-2 streams) lands at W2.
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import agents as agent_svc
from .. import audit as audit_svc
from .. import ingest as ingest_svc
from .._crypto import CryptoProvider
from .._ids import generate_uuid7
from ..auth import AuthContext, auth_context
from ..errors import AppError
from ..models import (
    AuditQueryRequest,
    CreateExportResponseModel,
    ExportModel,
    FreezeAgentRequest,
    GetExportResponseModel,
    IssueTokenResponseModel,
    JWKSResponse,
    ListEpochsResponse,
    ListExportsResponse,
    OperationRecord,
    RegisterAgentRequest,
    RevokeAgentRequest,
    SubmitOperationResponse,
    UnfreezeAgentRequest,
    UpdateAgentRequest,
)
from ..storage import Storage

router = APIRouter()

Ctx = Annotated[AuthContext, Depends(auth_context)]


def get_storage(request: Request) -> Storage:
    return request.app.state.storage  # type: ignore[no-any-return]


def get_crypto(request: Request) -> CryptoProvider:
    return request.app.state.crypto  # type: ignore[no-any-return]


# --- operations -----------------------------------------------------------
@router.post("/v1/operations", status_code=202)
async def submit_operation(request: Request, ctx: Ctx) -> SubmitOperationResponse:
    body = await request.json()
    if not isinstance(body, dict) or not body.get("operation_id"):
        raise AppError(400, "VALIDATION_ERROR", "Invalid operation body.")
    # Elydora overrides org_id from the authenticated context (routes/operations.ts:29).
    rec = OperationRecord.model_validate({**body, "org_id": ctx.org_id})
    ear = await ingest_svc.submit_operation(
        get_storage(request),
        get_crypto(request),
        rec,
        request.app.state.settings.server_signing_key,
    )
    return SubmitOperationResponse(receipt=ear)


@router.get("/v1/operations/{operation_id}")
async def get_operation(operation_id: str, request: Request, ctx: Ctx) -> object:
    return await ingest_svc.get_operation(get_storage(request), operation_id, ctx.org_id)


@router.post("/v1/operations/{operation_id}/verify")
async def verify_operation(operation_id: str, request: Request, ctx: Ctx) -> dict[str, object]:
    valid, checks, errors = await ingest_svc.verify_operation(
        get_storage(request), get_crypto(request), operation_id, ctx.org_id
    )
    return {"valid": valid, "checks": checks, **({"errors": errors} if errors else {})}


# --- agents ---------------------------------------------------------------
@router.post("/v1/agents/register", status_code=201)
async def register_agent(req: RegisterAgentRequest, request: Request, ctx: Ctx) -> object:
    return await agent_svc.register_agent(get_storage(request), req, ctx.org_id)


@router.get("/v1/agents")
async def list_agents(request: Request, ctx: Ctx) -> object:
    return await agent_svc.list_agents(get_storage(request), ctx.org_id)


@router.get("/v1/agents/{agent_id}")
async def get_agent(agent_id: str, request: Request, ctx: Ctx) -> object:
    return await agent_svc.get_agent(get_storage(request), agent_id, ctx.org_id)


@router.patch("/v1/agents/{agent_id}")
async def update_agent(
    agent_id: str, req: UpdateAgentRequest, request: Request, ctx: Ctx
) -> dict[str, object]:
    agent = await agent_svc.update_integration_type(
        get_storage(request), agent_id, req.integration_type, ctx.org_id
    )
    return {"agent": agent}


@router.delete("/v1/agents/{agent_id}")
async def delete_agent(agent_id: str, request: Request, ctx: Ctx) -> dict[str, object]:
    await agent_svc.delete_agent(get_storage(request), agent_id, ctx.org_id)
    return {"deleted": True}


@router.post("/v1/agents/{agent_id}/freeze")
async def freeze_agent(
    agent_id: str, req: FreezeAgentRequest, request: Request, ctx: Ctx
) -> dict[str, object]:
    if not req.reason.strip():
        raise AppError(400, "VALIDATION_ERROR", "Missing reason.")
    agent = await agent_svc.set_agent_status(get_storage(request), agent_id, "frozen", ctx.org_id)
    return {"agent": agent}


@router.post("/v1/agents/{agent_id}/unfreeze")
async def unfreeze_agent(
    agent_id: str, req: UnfreezeAgentRequest, request: Request, ctx: Ctx
) -> dict[str, object]:
    if not req.reason.strip():
        raise AppError(400, "VALIDATION_ERROR", "Missing reason.")
    agent = await agent_svc.set_agent_status(get_storage(request), agent_id, "active", ctx.org_id)
    return {"agent": agent}


@router.post("/v1/agents/{agent_id}/revoke")
async def revoke_key(
    agent_id: str, req: RevokeAgentRequest, request: Request, ctx: Ctx
) -> dict[str, object]:
    if not req.kid or not req.reason.strip():
        raise AppError(400, "VALIDATION_ERROR", "Missing kid/reason.")
    await agent_svc.revoke_key(get_storage(request), agent_id, req.kid, ctx.org_id)
    return {"revoked": True}


# --- audit ----------------------------------------------------------------
@router.post("/v1/audit/query")
async def audit_query(req: AuditQueryRequest, request: Request, ctx: Ctx) -> object:
    return await audit_svc.query_audit(get_storage(request), req, ctx.org_id)


# --- epochs (W4 produces real epochs; W1 = empty list / not-found) ---------
@router.get("/v1/epochs")
async def list_epochs(request: Request, ctx: Ctx) -> ListEpochsResponse:
    return ListEpochsResponse(epochs=[])


@router.get("/v1/epochs/{epoch_id}")
async def get_epoch(epoch_id: str, request: Request, ctx: Ctx) -> object:
    raise AppError(404, "NOT_FOUND", "Epoch not found (epochs land at W4).")


# --- exports (W4 = full pipeline; W1 = console-compatible minimal) ---------
@router.get("/v1/exports")
async def list_exports(request: Request, ctx: Ctx) -> ListExportsResponse:
    return ListExportsResponse(exports=[])


@router.post("/v1/exports", status_code=201)
async def create_export(request: Request, ctx: Ctx) -> CreateExportResponseModel:
    now = int(time.time() * 1000)
    body = await request.json()
    exp = ExportModel(
        export_id=generate_uuid7(),
        org_id=ctx.org_id,
        status="queued",
        query_params=str(body),
        r2_export_key=None,
        created_at=now,
        completed_at=None,
    )
    return CreateExportResponseModel(export=exp)


@router.get("/v1/exports/{export_id}")
async def get_export(export_id: str, request: Request, ctx: Ctx) -> GetExportResponseModel:
    raise AppError(404, "NOT_FOUND", "Export not found (export pipeline lands at W4).")


@router.get("/v1/exports/{export_id}/download")
async def download_export(export_id: str, request: Request, ctx: Ctx) -> object:
    raise AppError(400, "VALIDATION_ERROR", "Export not yet complete.")


# --- jwks + auth (console settings/jwks pages) ----------------------------
@router.get("/.well-known/elydora/jwks.json")
async def jwks() -> JWKSResponse:
    # Server pubkey export is crypto-gated (shield_sdk.crypto, Task #2);
    # an empty keyset keeps the console JWKS page rendering until W1 rebase.
    return JWKSResponse(keys=[])


@router.post("/v1/auth/token")
async def issue_token(request: Request) -> IssueTokenResponseModel:
    body = await request.json()
    ttl = body.get("ttl_seconds") if isinstance(body, dict) else None
    expires_at = None if ttl is None else int(time.time() * 1000) + int(ttl) * 1000
    return IssueTokenResponseModel(token="demo-static-token", expires_at=expires_at)


@router.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})
