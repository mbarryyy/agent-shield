"""W3 PR-S2 — console governance READ service (additive /v1/governance/*).

Backs the console demo surface (master §3.4 / sdk §5): the live-monitor
timeline, the verdict tab (paired pre↔post + signed §4 GovernanceVerdict), and
the correlation_id-keyed intent↔outcome provenance DAG (the Auditor view).

READ-ONLY over the server-owned stores (the W3 PR-S2 `governance_verdicts`
index + the `operations` chain with the additive correlation/run/phase columns
+ the MinIO §4 envelopes). NOT a §4 schema change; the verdict/record bodies
are returned opaque (frozen §4 types, never redefined here). Filtering/sort is
done in-process so MemoryDatabase (unit) and asyncpg (integration) run the
identical logic (same discipline as `audit.query_audit`).
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any, cast

from shield_sdk.schema import Decision

from ._ids import generate_uuid7
from .audit import decode_cursor, encode_cursor
from .config import DEFAULT_QUERY_LIMIT, MAX_QUERY_LIMIT
from .errors import AppError
from .export_report import render_compliance_pdf
from .governance import guardian_evidence_key
from .merkle import epoch_artifact_bytes, epoch_from_operation_rows, sign_eer
from .models import (
    EER,
    CostRollup,
    CostTokens,
    CreateExportRequest,
    DashboardKpi,
    Epoch,
    ExportModel,
    GetEpochResponseModel,
    GetExportResponseModel,
    IncidentRow,
    IncidentsResponse,
    ListEpochsResponse,
    ListExportsResponse,
    ProvenanceEdge,
    ProvenanceGraph,
    ProvenanceNode,
    TimelineResponse,
    TimelineRow,
    VerdictView,
)
from .storage import Storage


def _i(x: object) -> int:
    return int(cast(int, x))


def _f(x: object) -> float:
    return float(cast(float, x))


def _pct(values: list[float], q: float) -> float:
    """Nearest-rank percentile (q in [0,1]); 0.0 for an empty sample."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return float(s[idx])


async def _persisted_epochs(storage: Storage, org_id: str) -> list[Epoch]:
    rows = await storage.db.fetch("SELECT * FROM epochs")
    persisted = [Epoch.model_validate(r) for r in rows if r.get("org_id") == org_id]
    persisted.sort(key=lambda e: e.created_at, reverse=True)
    return persisted


async def _computed_epochs(storage: Storage, org_id: str) -> list[Epoch]:
    persisted = await _persisted_epochs(storage, org_id)
    if persisted:
        return persisted

    ops = await storage.db.fetch("SELECT * FROM operations")
    epoch = epoch_from_operation_rows(org_id, ops)
    if epoch is None:
        return []
    return [epoch]


async def epochs(storage: Storage, org_id: str) -> ListEpochsResponse:
    return ListEpochsResponse(epochs=await _computed_epochs(storage, org_id))


async def epoch_detail(
    storage: Storage, org_id: str, epoch_id: str, signing_key: str
) -> GetEpochResponseModel:
    persisted = await _persisted_epochs(storage, org_id)
    candidates = persisted if persisted else await _computed_epochs(storage, org_id)
    matches = [epoch for epoch in candidates if epoch.epoch_id == epoch_id]
    if not matches:
        raise AppError(404, "NOT_FOUND", "Epoch not found.")
    epoch = matches[0]
    artifact = await _load_json(storage, epoch.r2_epoch_key)
    if persisted and artifact is not None and isinstance(artifact.get("eer"), dict):
        eer = EER.model_validate(artifact["eer"])
        if eer.epoch_id == epoch.epoch_id and eer.org_id == epoch.org_id:
            return GetEpochResponseModel(epoch=epoch, eer=eer)

    eer = sign_eer(epoch, signing_key)
    await storage.objects.put(
        epoch.r2_epoch_key,
        epoch_artifact_bytes(epoch, eer),
        "application/json",
    )
    return GetEpochResponseModel(epoch=epoch, eer=eer)


async def _export_rows(storage: Storage, org_id: str) -> list[ExportModel]:
    rows = await storage.db.fetch("SELECT * FROM exports")
    exports = [ExportModel.model_validate(r) for r in rows if r.get("org_id") == org_id]
    exports.sort(key=lambda e: e.created_at, reverse=True)
    return exports


def _export_query(params: CreateExportRequest) -> str:
    return json.dumps(params.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


async def list_exports(storage: Storage, org_id: str) -> ListExportsResponse:
    return ListExportsResponse(exports=await _export_rows(storage, org_id))


async def create_export(
    storage: Storage, org_id: str, params: CreateExportRequest
) -> GetExportResponseModel:
    if params.start_time < 0 or params.end_time < 0 or params.start_time > params.end_time:
        raise AppError(400, "VALIDATION_ERROR", "Invalid export time range.")

    ops = await storage.db.fetch("SELECT * FROM operations")
    scoped_ops = [
        dict(o)
        for o in ops
        if o["org_id"] == org_id
        and params.start_time <= _i(o["created_at"]) <= params.end_time
        and (params.agent_id is None or o["agent_id"] == params.agent_id)
        and (params.operation_type is None or o["operation_type"] == params.operation_type)
    ]
    scoped_record_ids = {str(o["operation_id"]) for o in scoped_ops}

    verdicts = await storage.db.fetch("SELECT * FROM governance_verdicts")
    scoped_verdicts = [
        dict(v)
        for v in verdicts
        if v["org_id"] == org_id and str(v["record_id"]) in scoped_record_ids
    ]
    now = int(time.time() * 1000)
    export_id = generate_uuid7()
    extension = "pdf" if params.format == "pdf" else "json"
    key = f"{org_id}/exports/{export_id}.{extension}"
    query = _export_query(params)
    payload = {
        "export_id": export_id,
        "org_id": org_id,
        "query": json.loads(query),
        "generated_at": now,
        "operations": scoped_ops,
        "governance_verdicts": scoped_verdicts,
        "epochs": [e.model_dump(mode="json") for e in await _computed_epochs(storage, org_id)],
    }
    if params.format == "pdf":
        verdict_keys = [
            None if v.get("r2_verdict_key") is None else str(v["r2_verdict_key"])
            for v in scoped_verdicts
        ]
        verdict_bodies = [
            body
            for body in [await _load_json(storage, key) for key in verdict_keys]
            if body is not None
        ]
        verdict_ids = {str(v["verdict_id"]) for v in scoped_verdicts}
        intervention_log = await storage.db.fetch("SELECT * FROM intervention_log")
        pdf_payload = {
            **payload,
            "verdict_bodies": verdict_bodies,
            "intervention_log": [
                dict(r) for r in intervention_log if str(r.get("verdict_id")) in verdict_ids
            ],
        }
        await storage.objects.put(key, render_compliance_pdf(pdf_payload), "application/pdf")
    else:
        await storage.objects.put(
            key,
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            "application/json",
        )
    await storage.db.execute(
        "INSERT INTO exports (export_id, org_id, status, query_params, r2_export_key, "
        "created_at, completed_at) VALUES ($1,$2,$3,$4,$5,$6,$7)",
        export_id,
        org_id,
        "done",
        query,
        key,
        now,
        now,
    )
    export = ExportModel(
        export_id=export_id,
        org_id=org_id,
        status="done",
        query_params=query,
        r2_export_key=key,
        created_at=now,
        completed_at=now,
    )
    return GetExportResponseModel(export=export, download_url=f"/v1/exports/{export_id}/download")


async def get_export(storage: Storage, org_id: str, export_id: str) -> GetExportResponseModel:
    row = await storage.db.fetchrow(
        "SELECT * FROM exports WHERE export_id = $1 AND org_id = $2", export_id, org_id
    )
    if row is None:
        raise AppError(404, "NOT_FOUND", "Export not found.")
    export = ExportModel.model_validate(row)
    return GetExportResponseModel(export=export, download_url=f"/v1/exports/{export_id}/download")


async def download_export(storage: Storage, org_id: str, export_id: str) -> dict[str, Any]:
    export = (await get_export(storage, org_id, export_id)).export
    if export.status != "done" or not export.r2_export_key:
        raise AppError(400, "VALIDATION_ERROR", "Export not yet complete.")
    raw = await storage.objects.get(export.r2_export_key)
    if raw is None:
        raise AppError(404, "NOT_FOUND", "Export artifact not found.")
    if export.r2_export_key.endswith(".pdf"):
        return {
            "export_id": export.export_id,
            "content_type": "application/pdf",
            "filename": f"{export.export_id}.pdf",
            "body_base64": base64.b64encode(raw).decode("ascii"),
        }
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {"export": parsed}


async def _load_json(storage: Storage, key: str | None) -> dict[str, Any] | None:
    if not key:
        return None
    raw = await storage.objects.get(key)
    if raw is None:
        return None
    try:
        obj = json.loads(raw)
    except ValueError:  # pragma: no cover - defensive
        return None
    return obj if isinstance(obj, dict) else None


async def _load_guardian_evidence(
    storage: Storage, verdict_row: dict[str, object]
) -> list[dict[str, Any]]:
    key = verdict_row.get("r2_verdict_key")
    if not key:
        return []
    raw = await storage.objects.get(guardian_evidence_key(str(key)))
    if raw is None:
        return []
    try:
        obj = json.loads(raw)
    except ValueError:  # pragma: no cover - defensive
        return []
    if not isinstance(obj, list):
        return []
    return [dict(item) for item in obj if isinstance(item, dict)]


async def timeline(
    storage: Storage,
    org_id: str,
    run_id: str,
    cursor: str | None = None,
    limit: int | None = None,
) -> TimelineResponse:
    """Run live-monitor feed: gate decisions for {org_id, run_id}, newest
    first, keyset-paginated (same cursor scheme as the audit log)."""
    clamped = min(max(limit or DEFAULT_QUERY_LIMIT, 1), MAX_QUERY_LIMIT)
    rows = await storage.db.fetch("SELECT * FROM governance_verdicts")
    scoped = [r for r in rows if r["org_id"] == org_id and r.get("run_id") == run_id]
    total = len(scoped)
    scoped.sort(key=lambda r: (_i(r["created_at"]), str(r["verdict_id"])), reverse=True)

    cur = decode_cursor(cursor) if cursor else None
    if cursor and cur is None:
        raise AppError(400, "VALIDATION_ERROR", "Invalid cursor.")
    if cur is not None:
        c_created, c_id = cur
        scoped = [
            r
            for r in scoped
            if _i(r["created_at"]) < c_created
            or (_i(r["created_at"]) == c_created and str(r["verdict_id"]) < c_id)
        ]

    page = scoped[: clamped + 1]
    has_more = len(page) > clamped
    out = page[:clamped] if has_more else page
    next_cursor = (
        encode_cursor(_i(out[-1]["created_at"]), str(out[-1]["verdict_id"]))
        if has_more and out
        else None
    )
    return TimelineResponse(
        rows=[
            TimelineRow(
                verdict_id=str(r["verdict_id"]),
                record_id=str(r["record_id"]),
                correlation_id=str(r["correlation_id"]),
                run_id=r.get("run_id"),
                decision=str(r["decision"]),
                risk_score=_f(r["risk_score"]),
                latency_ms=(None if r.get("latency_ms") is None else _f(r["latency_ms"])),
                created_at=_i(r["created_at"]),
            )
            for r in out
        ],
        cursor=next_cursor,
        total_count=total,
    )


async def verdict_by_correlation(storage: Storage, org_id: str, correlation_id: str) -> VerdictView:
    """Verdict tab: the signed §4 GovernanceVerdict for a correlation_id +
    its paired pre_exec / post_exec §4 record envelopes."""
    gv_rows = await storage.db.fetch("SELECT * FROM governance_verdicts")
    matches = [
        r for r in gv_rows if r["correlation_id"] == correlation_id and r["org_id"] == org_id
    ]
    if not matches:
        raise AppError(404, "NOT_FOUND", "No verdict for that correlation_id.")
    matches.sort(key=lambda r: _i(r["created_at"]), reverse=True)
    latest = matches[0]
    verdict = await _load_json(storage, str(latest["r2_verdict_key"]))

    ops = await storage.db.fetch("SELECT * FROM operations")
    paired = [o for o in ops if o.get("correlation_id") == correlation_id and o["org_id"] == org_id]
    pre = next((o for o in paired if o.get("phase") == "pre_exec"), None)
    post = next((o for o in paired if o.get("phase") == "post_exec"), None)
    return VerdictView(
        correlation_id=correlation_id,
        verdict=verdict,
        pre_exec=await _load_json(storage, None if pre is None else str(pre["r2_payload_key"])),
        post_exec=await _load_json(storage, None if post is None else str(post["r2_payload_key"])),
        guardian_evidence=await _load_guardian_evidence(storage, latest),
    )


async def provenance(storage: Storage, org_id: str, run_id: str) -> ProvenanceGraph:
    """correlation_id-keyed intent↔outcome DAG for a run (the Auditor view —
    sdk §5 pt5 / master §3.4). Server returns graph DATA; console renders it."""
    ops = await storage.db.fetch("SELECT * FROM operations")
    scoped = [o for o in ops if o["org_id"] == org_id and o.get("run_id") == run_id]
    gv = await storage.db.fetch("SELECT * FROM governance_verdicts")
    decision_by_corr = {
        r["correlation_id"]: str(r["decision"])
        for r in gv
        if r["org_id"] == org_id and r.get("run_id") == run_id
    }

    nodes = [
        ProvenanceNode(
            record_id=str(o["operation_id"]),
            phase=o.get("phase"),
            correlation_id=o.get("correlation_id"),
            decision=(
                decision_by_corr.get(str(o["correlation_id"]))
                if o.get("phase") == "pre_exec"
                else None
            ),
            seq_no=_i(o["seq_no"]),
            chain_hash=str(o["chain_hash"]),
        )
        for o in scoped
    ]

    by_chain = {str(o["chain_hash"]): str(o["operation_id"]) for o in scoped}
    edges: list[ProvenanceEdge] = []
    for o in scoped:
        parent = by_chain.get(str(o["prev_chain_hash"]))
        if parent is not None:
            edges.append(ProvenanceEdge(src=parent, dst=str(o["operation_id"]), kind="chain"))
    by_corr: dict[str, dict[str, str]] = {}
    for o in scoped:
        cid = o.get("correlation_id")
        if cid:
            by_corr.setdefault(str(cid), {})[str(o.get("phase"))] = str(o["operation_id"])
    for pair in by_corr.values():
        if "pre_exec" in pair and "post_exec" in pair:
            edges.append(
                ProvenanceEdge(src=pair["pre_exec"], dst=pair["post_exec"], kind="correlation")
            )
    return ProvenanceGraph(run_id=run_id, nodes=nodes, edges=edges)


async def cost(storage: Storage, org_id: str, run_id: str) -> CostRollup:
    """W3 PR-S4 hook#5 — the LOCKED seam-4 /cost rollup. Pure READ-aggregation
    of server-owned stores: tokens/decision_mix/latency from the W2
    intervention_log SINK (gov-populated hook#1 counts — server NEVER
    re-counts), prevented_loss_total = Σ the stored §4
    obligations.prevented_loss (the MEASURED env-diff — NO server recompute).
    Org-safe scoping via governance_verdicts (org_id+run_id) → verdict_ids."""
    gv = await storage.db.fetch("SELECT * FROM governance_verdicts")
    scoped_gv = [r for r in gv if r["org_id"] == org_id and r.get("run_id") == run_id]
    verdict_ids = {str(r["verdict_id"]) for r in scoped_gv}

    il = await storage.db.fetch("SELECT * FROM intervention_log")
    rows = [r for r in il if str(r["verdict_id"]) in verdict_ids]

    prompt = sum(_i(r.get("tokens_in") or 0) for r in rows)
    completion = sum(_i(r.get("tokens_out") or 0) for r in rows)

    mix: dict[str, int] = {d.value: 0 for d in Decision}  # all 6 keys, 0 default
    for r in rows:
        key = str(r["decision"])
        if key in mix:
            mix[key] += 1

    latencies = [_f(r["latency_ms"]) for r in rows if r.get("latency_ms") is not None]
    prevented = sum(_f(r.get("prevented_loss") or 0.0) for r in scoped_gv)

    return CostRollup(
        tokens=CostTokens(prompt=prompt, completion=completion, total=prompt + completion),
        decision_mix=mix,
        prevented_loss_total=float(prevented),
        latency_p50_ms=_pct(latencies, 0.50),
        latency_p95_ms=_pct(latencies, 0.95),
    )


async def dashboard_kpi(storage: Storage, org_id: str) -> DashboardKpi:
    """Task #31 (b) — org-wide dashboard KPI rollup.

    Pure READ-aggregation across ``governance_verdicts`` for the given
    ``org_id``: ``prevented_loss_total`` = Σ stored ``prevented_loss`` (the
    MEASURED env-diff value gov / sdk placed on the §4
    ``GovernanceVerdict.obligations.prevented_loss`` field at /decide time;
    the server merely sums it — NO recompute). ``decision_mix`` always
    carries all 6 §4 ``Decision`` keys (zero default). Distinct from the
    run-scoped ``/cost`` endpoint by org-wide scoping (no run_id filter).

    seam#7 preserved: read-only; the source-of-truth for prevented_loss
    is gov's verdict, server-stored at verdict-sign time.
    """
    gv = await storage.db.fetch("SELECT * FROM governance_verdicts")
    scoped_gv = [r for r in gv if r["org_id"] == org_id]
    prevented = sum(_f(r.get("prevented_loss") or 0.0) for r in scoped_gv)
    mix: dict[str, int] = {d.value: 0 for d in Decision}
    for r in scoped_gv:
        key = str(r["decision"])
        if key in mix:
            mix[key] += 1
    return DashboardKpi(
        prevented_loss_total=float(prevented),
        decision_mix=mix,
        total_verdicts=len(scoped_gv),
    )


_RESOLUTIONS = {"accept", "edit", "response", "ignore"}


async def incidents(
    storage: Storage,
    org_id: str,
    run_id: str | None = None,
    status: str | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> IncidentsResponse:
    """W3 incidents-list (companion to S5 resume; console U6). An ESCALATE
    gate verdict IS an incident; status is server-authoritative ("resolved"
    once resume set governance_verdicts.resolution, else "pending").
    org-scoped, optional run_id/status filter, keyset like timeline.
    incident_id == the ESCALATE gate verdict_id (same id resume consumes)."""
    if status is not None and status not in ("pending", "resolved"):
        raise AppError(400, "VALIDATION_ERROR", "status must be pending|resolved.")
    clamped = min(max(limit or DEFAULT_QUERY_LIMIT, 1), MAX_QUERY_LIMIT)
    gv = await storage.db.fetch("SELECT * FROM governance_verdicts")
    rows = [
        r
        for r in gv
        if r["org_id"] == org_id
        and str(r["decision"]) == "ESCALATE"
        and (run_id is None or r.get("run_id") == run_id)
    ]

    def _status(r: dict[str, object]) -> str:
        return "resolved" if r.get("resolution") else "pending"

    if status is not None:
        rows = [r for r in rows if _status(r) == status]
    total = len(rows)
    rows.sort(key=lambda r: (_i(r["created_at"]), str(r["verdict_id"])), reverse=True)

    cur = decode_cursor(cursor) if cursor else None
    if cursor and cur is None:
        raise AppError(400, "VALIDATION_ERROR", "Invalid cursor.")
    if cur is not None:
        c_created, c_id = cur
        rows = [
            r
            for r in rows
            if _i(r["created_at"]) < c_created
            or (_i(r["created_at"]) == c_created and str(r["verdict_id"]) < c_id)
        ]

    page = rows[: clamped + 1]
    has_more = len(page) > clamped
    out = page[:clamped] if has_more else page
    next_cursor = (
        encode_cursor(_i(out[-1]["created_at"]), str(out[-1]["verdict_id"]))
        if has_more and out
        else None
    )
    return IncidentsResponse(
        incidents=[
            IncidentRow(
                incident_id=str(r["verdict_id"]),  # == the id resume consumes
                correlation_id=str(r["correlation_id"]),
                run_id=r.get("run_id"),
                decision=str(r["decision"]),
                risk_score=_f(r["risk_score"]),
                status="resolved" if r.get("resolution") else "pending",
                resolution=(str(r["resolution"]) if r.get("resolution") in _RESOLUTIONS else None),
                created_at=_i(r["created_at"]),
            )
            for r in out
        ],
        cursor=next_cursor,
        total_count=total,
    )
