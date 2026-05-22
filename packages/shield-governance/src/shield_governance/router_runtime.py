"""Small text-call adapter for ShieldModelRouter clients.

This module imports no provider SDKs. Provider construction remains centralized
in ``model_router.py``; this file only invokes the returned client object.
"""

from __future__ import annotations

import inspect
import time
from dataclasses import dataclass
from typing import Any

from shield_sdk.schema import ServedVia

from shield_governance.model_router import ResolvedModel, ShieldModelRouter


@dataclass(frozen=True, slots=True)
class RouterCallResult:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True, slots=True)
class RouterCallMeasurement:
    role: str
    model_id: str
    served_via: ServedVia
    result: RouterCallResult
    latency_ms: float


class RouterTextClient:
    """Invoke the client returned by ``ShieldModelRouter.model_factory``."""

    def __init__(self, router: ShieldModelRouter, role: str) -> None:
        self._router = router
        self._role = role

    async def acomplete(self, prompt: str) -> RouterCallMeasurement:
        started = time.perf_counter()
        resolved, client = self._resolved_client()
        raw = _invoke_text_client(client, resolved, prompt)
        if inspect.isawaitable(raw):
            raw = await raw
        return self._measurement(resolved, raw, started)

    def complete(self, prompt: str) -> RouterCallMeasurement:
        started = time.perf_counter()
        resolved, client = self._resolved_client()
        raw = _invoke_text_client(client, resolved, prompt)
        if inspect.isawaitable(raw):
            raise RuntimeError("router role returned an async client for a synchronous call")
        return self._measurement(resolved, raw, started)

    def _resolved_client(self) -> tuple[ResolvedModel, object]:
        resolved = self._router.for_role(self._role)
        client = self._router.model_factory(self._role)({}, object())
        return resolved, client

    def _measurement(
        self, resolved: ResolvedModel, raw: object, started: float
    ) -> RouterCallMeasurement:
        return RouterCallMeasurement(
            role=self._role,
            model_id=resolved.model,
            served_via=resolved.served_via,
            result=_coerce_result(raw),
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )


def _invoke_text_client(client: object, resolved: ResolvedModel, prompt: str) -> object:
    complete = getattr(client, "complete", None)
    if callable(complete):
        return complete(
            prompt,
            model=resolved.model,
            max_tokens=resolved.max_tokens,
            temperature=resolved.temperature,
        )

    messages = getattr(client, "messages", None)
    create = getattr(messages, "create", None)
    if callable(create):
        return create(
            model=resolved.model,
            max_tokens=resolved.max_tokens or 1024,
            temperature=resolved.temperature,
            messages=[{"role": "user", "content": prompt}],
        )

    chat = getattr(client, "chat", None)
    completions = getattr(chat, "completions", None)
    chat_create = getattr(completions, "create", None)
    if callable(chat_create):
        kwargs: dict[str, object] = {
            "model": resolved.model,
            "temperature": resolved.temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if resolved.max_tokens is not None:
            kwargs["max_tokens"] = resolved.max_tokens
        return chat_create(**kwargs)

    raise TypeError(
        f"router client for role {resolved.role!r} must expose complete(), "
        "messages.create(), or chat.completions.create()"
    )


def _coerce_result(raw: object) -> RouterCallResult:
    if isinstance(raw, RouterCallResult):
        return raw
    if isinstance(raw, str):
        return RouterCallResult(text=raw)
    if isinstance(raw, dict):
        return RouterCallResult(
            text=str(raw.get("text", raw.get("content", ""))),
            prompt_tokens=_int(raw.get("prompt_tokens", raw.get("input_tokens", 0))),
            completion_tokens=_int(raw.get("completion_tokens", raw.get("output_tokens", 0))),
            cost_usd=_float(raw.get("cost_usd", 0.0)),
        )

    text = _object_text(raw)
    usage = getattr(raw, "usage", None)
    return RouterCallResult(
        text=text,
        prompt_tokens=_int(
            getattr(usage, "prompt_tokens", getattr(usage, "input_tokens", 0))
            if usage is not None
            else 0
        ),
        completion_tokens=_int(
            getattr(usage, "completion_tokens", getattr(usage, "output_tokens", 0))
            if usage is not None
            else 0
        ),
    )


def _object_text(raw: object) -> str:
    content = getattr(raw, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list) and content:
        first = content[0]
        text = getattr(first, "text", None)
        if text is not None:
            return str(text)

    choices = getattr(raw, "choices", None)
    if isinstance(choices, list) and choices:
        message = getattr(choices[0], "message", None)
        text = getattr(message, "content", None)
        if text is not None:
            return str(text)

    return str(raw)


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0
