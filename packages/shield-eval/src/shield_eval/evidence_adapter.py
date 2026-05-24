"""Map server guardian evidence rows into eval-side trace rows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

_EVIDENCE_LABELS = {
    "FIXTURE",
    "SUPPLEMENTARY_FIXTURE",
    "MOCKED",
    "SKIPPED",
    "PROVIDER_BACKED",
    "MEASURED",
}

REQUIRED_AGENTIC_TRACE_FIELDS: tuple[str, ...] = (
    "trace_id",
    "case_id",
    "arm",
    "attack_succeeded",
    "expected_tools",
    "tools_called",
    "expected_decision",
    "supervisor_decision",
    "self_correction_state",
    "grounded_reason_count",
    "total_reason_count",
)


def adapt_guardian_evidence_rows(
    rows: Iterable[Mapping[str, Any] | object], *, evidence_label: str
) -> dict[str, Any]:
    """Return normalized rows plus honest agentic-metric readiness.

    Existing server evidence is enough for provider cost/latency/token display,
    but not enough to compute AGD/DRC/TSA/ARQ/SCE/RGF. Missing fields are listed
    explicitly instead of relabelling partial evidence as measured metrics.
    """

    if evidence_label not in _EVIDENCE_LABELS:
        raise ValueError(f"unsupported evidence_label: {evidence_label}")

    normalized = [_normalize_row(row) for row in rows]
    missing_fields = [
        field
        for field in REQUIRED_AGENTIC_TRACE_FIELDS
        if not normalized or any(row.get(field) is None for row in normalized)
    ]
    metric_label = (
        "MEASURED"
        if evidence_label == "PROVIDER_BACKED" and normalized and not missing_fields
        else "SKIPPED"
    )
    return {
        "schema_version": "guardian-evidence-adapter.v1",
        "source_evidence_label": evidence_label,
        "agentic_metric_label": metric_label,
        "measured_provider_evidence": evidence_label == "PROVIDER_BACKED",
        "missing_fields": missing_fields,
        "rows": normalized,
        "notes": [
            "PROVIDER_BACKED source rows do not imply measured agentic metrics until "
            "all trace fields needed for AGD/DRC/TSA/ARQ/SCE/RGF are present."
        ],
    }


def _normalize_row(row: Mapping[str, Any] | object) -> dict[str, Any]:
    data = _as_mapping(row)
    return {
        "record_id": _string_or_none(data.get("record_id")),
        "correlation_id": _string_or_none(data.get("correlation_id")),
        "guardian": _string_or_none(data.get("guardian")),
        "decision": _string_or_none(data.get("decision")),
        "reasons": list(data.get("reasons") or []),
        "model_id": _string_or_none(data.get("model_id")),
        "served_via": _string_or_none(data.get("served_via")),
        "prompt_tokens": _int(data.get("prompt_tokens")),
        "completion_tokens": _int(data.get("completion_tokens")),
        "latency_ms": _float(data.get("latency_ms")),
        "cost_usd": _float(data.get("cost_usd")),
        **{field: data.get(field) for field in REQUIRED_AGENTIC_TRACE_FIELDS},
    }


def _as_mapping(row: Mapping[str, Any] | object) -> Mapping[str, Any]:
    if isinstance(row, Mapping):
        return row
    if is_dataclass(row):
        return asdict(row)
    return {
        key: getattr(row, key)
        for key in dir(row)
        if not key.startswith("_") and not callable(getattr(row, key))
    }


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "value", value)
    return str(raw)


def _int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _float(value: object) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0
