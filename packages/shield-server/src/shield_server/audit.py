"""Audit query — keyset (cursor) pagination.

Port of Elydora audit-service.ts + pagination.ts. Cursor = opaque base64url
JSON `{created_at,id}` of the last row on the page; ordering is
(created_at DESC, operation_id DESC); `limit+1` is fetched to detect a next
page; `total_count` ignores the cursor filter (accurate total). The filter is
applied in-process for backend parity (MemoryDatabase + asyncpg run identical
logic); Postgres-side WHERE/LIMIT pushdown is a W4 hardening — semantics here
are byte-identical to Elydora's keyset scheme.
"""

from __future__ import annotations

import json

from ._b64 import b64url_decode, b64url_encode
from .config import DEFAULT_QUERY_LIMIT, MAX_QUERY_LIMIT
from .errors import AppError
from .models import AuditQueryRequest, AuditQueryResponse, Operation
from .storage import Storage


def encode_cursor(created_at: int, op_id: str) -> str:
    return b64url_encode(json.dumps({"created_at": created_at, "id": op_id}).encode("utf-8"))


def decode_cursor(cursor: str) -> tuple[int, str] | None:
    try:
        parsed = json.loads(b64url_decode(cursor))
    except (ValueError, TypeError):
        return None
    if (
        not isinstance(parsed, dict)
        or not isinstance(parsed.get("created_at"), int)
        or not isinstance(parsed.get("id"), str)
    ):
        return None
    return parsed["created_at"], parsed["id"]


async def query_audit(
    storage: Storage, params: AuditQueryRequest, org_id: str
) -> AuditQueryResponse:
    limit = min(max(params.limit or DEFAULT_QUERY_LIMIT, 1), MAX_QUERY_LIMIT)

    if params.start_time is not None and params.start_time < 0:
        raise AppError(400, "VALIDATION_ERROR", "Invalid start_time.")
    if params.end_time is not None and params.end_time < 0:
        raise AppError(400, "VALIDATION_ERROR", "Invalid end_time.")

    cursor_payload: tuple[int, str] | None = None
    if params.cursor:
        cursor_payload = decode_cursor(params.cursor)
        if cursor_payload is None:
            raise AppError(400, "VALIDATION_ERROR", "Invalid cursor.")

    rows = await storage.db.fetch("SELECT * FROM operations")
    ops = [Operation.model_validate(r) for r in rows]

    # Always scope to the caller's org, then optional filters (audit-service.ts).
    ops = [o for o in ops if o.org_id == org_id]
    if params.agent_id:
        ops = [o for o in ops if o.agent_id == params.agent_id]
    if params.operation_type:
        ops = [o for o in ops if o.operation_type == params.operation_type]
    if params.start_time is not None:
        ops = [o for o in ops if o.created_at >= params.start_time]
    if params.end_time is not None:
        ops = [o for o in ops if o.created_at <= params.end_time]

    total_count = len(ops)  # total ignores the cursor filter (accurate)

    ops.sort(key=lambda o: (o.created_at, o.operation_id), reverse=True)
    if cursor_payload is not None:
        c_created, c_id = cursor_payload
        ops = [
            o
            for o in ops
            if (o.created_at < c_created) or (o.created_at == c_created and o.operation_id < c_id)
        ]

    page = ops[: limit + 1]
    has_more = len(page) > limit
    operations = page[:limit] if has_more else page

    next_cursor: str | None = None
    if has_more and operations:
        last = operations[-1]
        next_cursor = encode_cursor(last.created_at, last.operation_id)

    return AuditQueryResponse(operations=operations, cursor=next_cursor, total_count=total_count)
