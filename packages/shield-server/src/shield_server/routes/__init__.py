"""HTTP routes — faithful to the Elydora console contract (`console/src/lib/api.ts`).

Endpoint paths/verbs/status codes mirror Elydora `src/routes/*.ts` so the
existing Next.js console boots unchanged against this FastAPI backend. The §4
governance surface (`POST /v1/governance/decide`, Channel-2 streams) lands at W2.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from shield_sdk.schema import GovernanceVerdict, ShieldActionRecord

from .. import agents as agent_svc
from .. import audit as audit_svc
from .. import governance as governance_svc
from .. import ingest as ingest_svc
from .. import reads as reads_svc
from .._crypto import CryptoProvider
from .._ids import generate_uuid7
from ..auth import AuthContext, auth_context
from ..config import ACTIONS_STREAM_PREFIX, VERDICTS_STREAM_PREFIX
from ..errors import AppError
from ..models import (
    AuditQueryRequest,
    CostRollup,
    CreateExportResponseModel,
    DashboardKpi,
    ExportModel,
    FreezeAgentRequest,
    GetExportResponseModel,
    IncidentsResponse,
    IssueTokenResponseModel,
    JWKSResponse,
    ListEpochsResponse,
    ListExportsResponse,
    OperationRecord,
    ProvenanceGraph,
    RegisterAgentRequest,
    RevokeAgentRequest,
    SubmitOperationResponse,
    TimelineResponse,
    UnfreezeAgentRequest,
    UpdateAgentRequest,
    VerdictView,
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


# --- governance (§4 Channel-1: sync decision gate; W3 = real gov via seam) --
@router.post("/v1/governance/decide")
async def governance_decide(request: Request, ctx: Ctx) -> GovernanceVerdict:
    """One round-trip: ingest the pre_exec ShieldActionRecord + return the
    server-signed GovernanceVerdict. The decision comes from the pre-warmed
    in-process governance app (app.state.governance); org_id bound from auth."""
    body = await request.json()
    if not isinstance(body, dict):
        raise AppError(400, "VALIDATION_ERROR", "Invalid record body.")
    try:
        rec = ShieldActionRecord.model_validate({**body, "org_id": ctx.org_id})
    except ValidationError as exc:
        raise AppError(400, "VALIDATION_ERROR", "Malformed ShieldActionRecord.") from exc
    return await governance_svc.decide(
        get_storage(request),
        rec,
        request.app.state.settings,
        request.app.state.governance,
    )


@router.post("/v1/governance/record", status_code=202)
async def governance_record(request: Request, ctx: Ctx) -> dict[str, object]:
    """Channel-2 ingest for the async post_exec ShieldActionRecord (the
    `record_path` ShieldRecorder targets). Chains + fans to shield:actions;
    NO verdict (async). org_id is bound from auth."""
    body = await request.json()
    if not isinstance(body, dict):
        raise AppError(400, "VALIDATION_ERROR", "Invalid record body.")
    try:
        rec = ShieldActionRecord.model_validate({**body, "org_id": ctx.org_id})
    except ValidationError as exc:
        raise AppError(400, "VALIDATION_ERROR", "Malformed ShieldActionRecord.") from exc
    return await governance_svc.record(get_storage(request), rec, request.app.state.settings)


# --- governance READ contract (W3 PR-S2; additive /v1/governance/*, ---------
#     console-pact typed, NOT a frozen-§4 contracts/*.schema.json change) -----
@router.get("/v1/governance/runs/{run_id}/timeline")
async def governance_timeline(
    run_id: str,
    request: Request,
    ctx: Ctx,
    cursor: str | None = None,
    limit: int | None = None,
) -> TimelineResponse:
    return await reads_svc.timeline(get_storage(request), ctx.org_id, run_id, cursor, limit)


@router.get("/v1/governance/verdicts/{correlation_id}")
async def governance_verdict(correlation_id: str, request: Request, ctx: Ctx) -> VerdictView:
    return await reads_svc.verdict_by_correlation(get_storage(request), ctx.org_id, correlation_id)


@router.get("/v1/governance/runs/{run_id}/provenance")
async def governance_provenance(run_id: str, request: Request, ctx: Ctx) -> ProvenanceGraph:
    return await reads_svc.provenance(get_storage(request), ctx.org_id, run_id)


@router.get("/v1/governance/runs/{run_id}/cost")
async def governance_cost(run_id: str, request: Request, ctx: Ctx) -> CostRollup:
    """hook#5 — LOCKED seam-4 /cost rollup (READ-agg of intervention_log SINK
    + stored §4 prevented_loss; zero server token re-count / $ synthesis)."""
    return await reads_svc.cost(get_storage(request), ctx.org_id, run_id)


@router.get("/v1/governance/dashboard/kpi")
async def governance_dashboard_kpi(request: Request, ctx: Ctx) -> DashboardKpi:
    """Task #31 (b) — org-wide dashboard KPI rollup.

    Org-scoped (NOT run-scoped, unlike ``/v1/governance/runs/{run_id}/cost``)
    so the console dashboard's "Total Prevented Loss" stat-card aggregates
    every signed verdict in the org. Pure READ over ``governance_verdicts``;
    zero server recompute of $ — the stored figure is the MEASURED env-diff
    gov / sdk placed on the §4 ``GovernanceVerdict.obligations.prevented_loss``
    at /decide time.
    """
    return await reads_svc.dashboard_kpi(get_storage(request), ctx.org_id)


@router.get("/v1/governance/incidents")
async def governance_incidents(
    request: Request,
    ctx: Ctx,
    run_id: str | None = None,
    status: str | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> IncidentsResponse:
    """Console U6 HITL view — list ESCALATE incidents + server-authoritative
    pending/resolved state. `incident_id` == the verdict_id consumed by
    POST /v1/governance/incidents/{incident_id}/resume."""
    return await reads_svc.incidents(
        get_storage(request), ctx.org_id, run_id, status, cursor, limit
    )


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


@router.get("/v1/governance/stream")
async def governance_stream(
    request: Request,
    ctx: Ctx,
    workflow_id: str = "banking",
) -> StreamingResponse:
    """SSE bridge Redis Channel-2 → browser (a browser cannot read Redis).
    Drains the current shield:actions/shield:verdicts snapshot for the
    workflow and closes — bounded + docker-free-testable; continuous tailing
    is the prod/CI path (real Redis XRANGE)."""
    storage = get_storage(request)
    actions = f"{ACTIONS_STREAM_PREFIX}:{workflow_id}"
    verdicts = f"{VERDICTS_STREAM_PREFIX}:{workflow_id}"

    async def _gen() -> AsyncIterator[str]:
        for _mid, fields in await storage.cache.xrange(actions):
            yield _sse("action", json.dumps(fields))
        for _mid, fields in await storage.cache.xrange(verdicts):
            yield _sse("verdict", json.dumps(fields))

    return StreamingResponse(_gen(), media_type="text/event-stream")


# --- governance HITL resume (W3 PR-S5; thin route+auth+validation, ---------
#     gov owns the LangGraph Command(resume=) semantics) ---------------------
@router.post("/v1/governance/incidents/{incident_id}/resume")
async def governance_resume(incident_id: str, request: Request, ctx: Ctx) -> GovernanceVerdict:
    """Act-2 HITL: re-enter a paused ESCALATE incident with the human
    decision. Server signs the post-resume verdict; gov owns the resume()
    semantics (Null default → honest stub until gov lands)."""
    body = await request.json()
    if not isinstance(body, dict):
        raise AppError(400, "VALIDATION_ERROR", "Invalid resume body.")
    decision = body.get("decision")
    if not isinstance(decision, str):
        raise AppError(400, "VALIDATION_ERROR", "Missing resume decision.")
    payload = body.get("payload")
    if payload is not None and not isinstance(payload, dict):
        raise AppError(400, "VALIDATION_ERROR", "resume payload must be an object.")
    return await governance_svc.resume(
        get_storage(request),
        request.app.state.settings,
        request.app.state.governance,
        incident_id,
        decision,
        payload,
    )


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
async def issue_token(request: Request, _ctx: Ctx) -> IssueTokenResponseModel:
    """ADR-0013 — legacy `/v1/auth/token` deprecation shim.

    Renamed at the protocol level to ``/v1/auth/api-keys`` in v1; this route
    stays mounted under all modes for one release window with the demo-static
    token shape so existing console/SDK build artefacts keep booting. Carries
    the ``Ctx`` auth dep so the §A2 ``test_every_route_declares_auth_dep``
    invariant holds across both ``open`` and ``enterprise`` modes (the dep
    auto-injects a synthetic admin in open mode; enterprise resolves the
    real session/api-key).
    """
    body = await request.json()
    ttl = body.get("ttl_seconds") if isinstance(body, dict) else None
    expires_at = None if ttl is None else int(time.time() * 1000) + int(ttl) * 1000
    return IssueTokenResponseModel(token="demo-static-token", expires_at=expires_at)


@router.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})
