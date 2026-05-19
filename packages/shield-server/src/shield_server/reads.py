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

import json
from typing import Any, cast

from .audit import decode_cursor, encode_cursor
from .config import DEFAULT_QUERY_LIMIT, MAX_QUERY_LIMIT
from .errors import AppError
from .models import (
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
    verdict = await _load_json(storage, str(matches[0]["r2_verdict_key"]))

    ops = await storage.db.fetch("SELECT * FROM operations")
    paired = [o for o in ops if o.get("correlation_id") == correlation_id and o["org_id"] == org_id]
    pre = next((o for o in paired if o.get("phase") == "pre_exec"), None)
    post = next((o for o in paired if o.get("phase") == "post_exec"), None)
    return VerdictView(
        correlation_id=correlation_id,
        verdict=verdict,
        pre_exec=await _load_json(storage, None if pre is None else str(pre["r2_payload_key"])),
        post_exec=await _load_json(storage, None if post is None else str(post["r2_payload_key"])),
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
