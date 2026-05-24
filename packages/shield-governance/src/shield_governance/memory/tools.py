"""LangChain guardian tools backed by incident memory."""

from __future__ import annotations

import time
from typing import Any, cast

from langchain_core.tools import tool
from shield_sdk.schema import ShieldActionRecord

from shield_governance.memory.incidents import (
    MemoryQueryResult,
    local_fallback_result,
    trace_safe_record_text,
)


def build_recall_similar_incidents_tool(
    *,
    record: ShieldActionRecord,
    memory: Any,
    tool_call_log: list[str] | None = None,
    memory_evidence_log: list[dict[str, object]] | None = None,
    name: str = "recall_similar_incidents",
) -> Any:
    """Build a trace-safe recall tool for Evaluator/Supervisor/Auditor agents."""

    @tool(name)
    def recall_similar_incidents(tool_name: str = "", recipient: str = "") -> dict[str, Any]:
        """Recall similar prior governance incidents from the configured memory backend.

        The deliverable backend is local persistent Chroma and returns only
        trace-safe references: hit IDs, scores/distances, collection name,
        latency, and backend label. Raw tool arguments and prompts are not
        returned.
        """
        if tool_call_log is not None:
            tool_call_log.append(name)
        result = _query_memory(
            memory,
            record=record,
            tool_name=tool_name or None,
            recipient=recipient or None,
        )
        evidence = result.to_evidence()
        if memory_evidence_log is not None:
            memory_evidence_log.append(evidence)
        return evidence

    return recall_similar_incidents


def _query_memory(
    memory: Any,
    *,
    record: ShieldActionRecord,
    tool_name: str | None,
    recipient: str | None,
) -> MemoryQueryResult:
    query_record = getattr(memory, "query_record", None)
    if callable(query_record):
        return cast(
            MemoryQueryResult,
            query_record(
                record,
                top_k=5,
                tool_name=tool_name,
                recipient=recipient,
            ),
        )

    started = time.perf_counter()
    recall = getattr(memory, "recall", None)
    if callable(recall):
        wanted_tool = tool_name or record.payload.tool_name or ""
        wanted_recipient = recipient or (
            str(record.payload.tool_args.get("recipient", "")) if record.payload.tool_args else ""
        )
        matches_raw = recall(
            tool_name=wanted_tool or None,
            recipient=wanted_recipient or None,
        )
        matches = [
            {
                "record_id": getattr(match, "record_id", ""),
                "tool_name": getattr(match, "tool_name", None),
                "recipient": getattr(match, "recipient", None),
                "amount": getattr(match, "amount", None),
            }
            for match in matches_raw
        ]
        return local_fallback_result(
            collection="process_local_short_window",
            query_text=trace_safe_record_text(record, tool_name=tool_name, recipient=recipient),
            matches=matches,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            missing_reason="chroma memory not configured; using explicit local fallback",
        )

    return local_fallback_result(
        collection="unavailable",
        query_text=trace_safe_record_text(record, tool_name=tool_name, recipient=recipient),
        matches=[],
        latency_ms=(time.perf_counter() - started) * 1000.0,
        missing_reason="memory backend has no query_record or recall method",
    )
