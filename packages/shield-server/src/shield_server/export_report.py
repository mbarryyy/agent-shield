from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from textwrap import wrap
from typing import Any

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

_LEFT = 54
_TOP = 742
_BOTTOM = 54
_LINE = 13


def _ts(ms: object) -> str:
    if not isinstance(ms, int | float | str):
        return "not recorded"
    try:
        value = int(ms)
    except ValueError:
        return "not recorded"
    return datetime.fromtimestamp(value / 1000, UTC).isoformat()


def _s(value: object, default: str = "not recorded") -> str:
    if value is None:
        return default
    text = str(value)
    return text if text else default


def _jsonish(value: object, key: str) -> str:
    if not isinstance(value, dict):
        return "not recorded"
    return _s(value.get(key))


def _by_verdict_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {_s(row.get("verdict_id")): row for row in rows}


def _reasons(verdict: dict[str, Any] | None) -> str:
    if verdict is None:
        return "verdict envelope unavailable"
    reasons = verdict.get("reasons")
    if not isinstance(reasons, list) or not reasons:
        return "no evidence reasons recorded"
    labels: list[str] = []
    for reason in reasons:
        if isinstance(reason, dict):
            label = reason.get("label")
            if label:
                labels.append(str(label))
    return ", ".join(labels) if labels else "no evidence labels recorded"


def _tokens_for(verdict_id: str, intervention_rows: list[dict[str, Any]]) -> tuple[int, int]:
    prompt = 0
    completion = 0
    for row in intervention_rows:
        if _s(row.get("verdict_id")) != verdict_id:
            continue
        prompt += int(row.get("tokens_in") or 0)
        completion += int(row.get("tokens_out") or 0)
    return prompt, completion


class _PdfWriter:
    def __init__(self) -> None:
        self._buffer = BytesIO()
        self._canvas = canvas.Canvas(self._buffer, pagesize=letter, pageCompression=0)
        self._y = _TOP

    def _new_page_if_needed(self, needed: int = _LINE) -> None:
        if self._y - needed >= _BOTTOM:
            return
        self._canvas.showPage()
        self._y = _TOP

    def heading(self, text: str, size: int = 14) -> None:
        self._new_page_if_needed(_LINE * 2)
        self._canvas.setFont("Helvetica-Bold", size)
        self._canvas.drawString(_LEFT, self._y, text)
        self._y -= _LINE + 4

    def line(self, text: str = "", *, size: int = 9, indent: int = 0) -> None:
        self._canvas.setFont("Helvetica", size)
        width = max(42, 96 - int(indent / 5))
        chunks = wrap(text, width=width, break_long_words=False) or [""]
        for chunk in chunks:
            self._new_page_if_needed(_LINE)
            self._canvas.drawString(_LEFT + indent, self._y, chunk)
            self._y -= _LINE

    def finish(self) -> bytes:
        self._canvas.save()
        return self._buffer.getvalue()


def render_compliance_pdf(payload: dict[str, Any]) -> bytes:
    """Render a human-readable compliance export from server read-model data.

    The report intentionally summarizes record and verdict metadata instead of
    embedding raw action payloads or tool arguments.
    """
    operations = [dict(row) for row in payload.get("operations", []) if isinstance(row, dict)]
    verdict_rows = [
        dict(row) for row in payload.get("governance_verdicts", []) if isinstance(row, dict)
    ]
    verdict_bodies = [
        dict(row) for row in payload.get("verdict_bodies", []) if isinstance(row, dict)
    ]
    intervention_rows = [
        dict(row) for row in payload.get("intervention_log", []) if isinstance(row, dict)
    ]
    epochs = [dict(row) for row in payload.get("epochs", []) if isinstance(row, dict)]
    raw_query = payload.get("query")
    query: dict[str, Any] = raw_query if isinstance(raw_query, dict) else {}
    verdict_body_by_id = _by_verdict_id(verdict_bodies)

    run_ids = sorted(
        {_s(row.get("run_id")) for row in operations + verdict_rows if row.get("run_id")}
    )
    agent_ids = sorted(
        {_s(row.get("agent_id")) for row in operations + verdict_rows if row.get("agent_id")}
    )
    decisions: dict[str, int] = {}
    for row in verdict_rows:
        decision = _s(row.get("decision"))
        decisions[decision] = decisions.get(decision, 0) + 1
    prevented = sum(float(row.get("prevented_loss") or 0.0) for row in verdict_rows)
    total_prompt = sum(int(row.get("tokens_in") or 0) for row in intervention_rows)
    total_completion = sum(int(row.get("tokens_out") or 0) for row in intervention_rows)

    pdf = _PdfWriter()
    pdf.heading("Agent Shield Compliance Export", 16)
    pdf.line(f"Generated at: {_ts(payload.get('generated_at'))}")
    pdf.line(f"Export id: {_s(payload.get('export_id'))}")
    pdf.line(f"Organization: {_s(payload.get('org_id'))}")
    pdf.line(f"Query start_time: {_s(query.get('start_time'))}")
    pdf.line(f"Query end_time: {_s(query.get('end_time'))}")
    pdf.line(f"Query format: {_s(query.get('format'))}")
    pdf.line()

    pdf.heading("Workflow and run identifiers")
    if run_ids:
        for run_id in run_ids:
            pdf.line(f"Run: {run_id}")
    else:
        pdf.line("Run: no run identifiers found in the selected records")
    if agent_ids:
        for agent_id in agent_ids:
            pdf.line(f"Agent: {agent_id}")
    else:
        pdf.line("Agent: no agent identifiers found in the selected records")
    pdf.line()

    pdf.heading("Records timeline")
    if not operations:
        pdf.line("No action records matched the selected export window.")
    for row in sorted(operations, key=lambda item: int(item.get("created_at") or 0)):
        action = row.get("action")
        pdf.line(
            "Record: "
            f"{_s(row.get('operation_id'))} | phase={_s(row.get('phase'))} | "
            f"created={_ts(row.get('created_at'))}"
        )
        pdf.line(f"Run: {_s(row.get('run_id'))} | Agent: {_s(row.get('agent_id'))}", indent=12)
        pdf.line(
            "Tool: "
            f"{_jsonish(action, 'tool')} | args_digest={_jsonish(action, 'args_digest')} | "
            f"seq_no={_s(row.get('seq_no'))}",
            indent=12,
        )
        pdf.line(f"Correlation: {_s(row.get('correlation_id'))}", indent=12)
    pdf.line()

    pdf.heading("Verdicts, risk, evidence, cost, and latency")
    if not verdict_rows:
        pdf.line("No governance verdicts matched the selected export window.")
    for row in sorted(verdict_rows, key=lambda item: int(item.get("created_at") or 0)):
        verdict_id = _s(row.get("verdict_id"))
        prompt, completion = _tokens_for(verdict_id, intervention_rows)
        latency = row.get("latency_ms")
        latency_text = "not recorded" if latency is None else f"{float(latency):.3f} ms"
        pdf.line(
            f"Verdict: {verdict_id} | Record: {_s(row.get('record_id'))} | "
            f"Decision: {_s(row.get('decision'))}"
        )
        pdf.line(
            f"Risk score: {float(row.get('risk_score') or 0.0):.2f} | Latency: {latency_text}",
            indent=12,
        )
        pdf.line(f"Evidence: {_reasons(verdict_body_by_id.get(verdict_id))}", indent=12)
        pdf.line(
            "Cost: "
            f"prompt_tokens={prompt} completion_tokens={completion} "
            f"total_tokens={prompt + completion}",
            indent=12,
        )
    pdf.line()

    pdf.heading("Compliance summary")
    mix = ", ".join(f"{key}={value}" for key, value in sorted(decisions.items()))
    pdf.line(f"Records included: {len(operations)}")
    pdf.line(f"Verdicts included: {len(verdict_rows)}")
    pdf.line(f"Decision mix: {mix if mix else 'none'}")
    pdf.line(f"Epoch artifacts included: {len(epochs)}")
    pdf.line(
        "Stored prevented loss total: "
        f"{prevented:.2f} (stored governance field only; not an independent benchmark claim)"
    )
    pdf.line(
        "Cost: "
        f"prompt_tokens={total_prompt} completion_tokens={total_completion} "
        f"total_tokens={total_prompt + total_completion}"
    )
    pdf.line()

    pdf.heading("Limitations and verification labels")
    for label in (
        "GENERATED_FROM_SERVER_READ_MODEL",
        "PDF_GENERATED_WITH_REPORTLAB",
        "NOT_A_BENCHMARK",
        "ZERO_EGRESS_NOT_VERIFIED",
        "PRODUCTION_READINESS_NOT_ASSERTED",
    ):
        pdf.line(label)
    pdf.line("Raw tool arguments are excluded from this PDF report.")
    pdf.line("Missing or partial data is labelled as not recorded or unavailable.")
    return pdf.finish()
