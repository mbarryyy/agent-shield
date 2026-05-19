"""Cost hook #1 — the per-decision token counter (the SOURCE).

master design §2.5 hook #1 ≡ eval §9 dep #5. Attributes prompt/completion
tokens (+ ``model_id`` / ``served_via`` resolved from
:class:`~shield_governance.model_router.ShieldModelRouter`, cost hook #2) to a
``record_id`` / ``correlation_id``.

Seam #7 boundary (LOCKED by team-lead, 2026-05-19):

* governance OWNS this SOURCE — the token-counting + the values keyed by
  ``record_id`` / ``correlation_id``.
* server OWNS the SINK — the ``intervention_log`` Postgres table + the write
  (hook #3). We DO NOT create a table, DO NOT write the sink, DO NOT add a
  server route. :meth:`TokenCounter.intervention_rows` emits the exact typed
  value contract that POPULATES server's columns; the write is server's.

W2 builds the counter + the population contract. Real population runs at W3
when the live Evaluator / Supervisor LLM calls happen. The Defender hot path is
model-free by design, so it contributes ZERO tokens (and that zero is itself a
correct, asserted data point for the eval Token-Overhead metric).
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from shield_sdk.schema import Guardian, ServedVia


@dataclass(frozen=True, slots=True)
class LLMUsageSample:
    """One ShieldModelRouter-mediated LLM call's token attribution."""

    record_id: str
    correlation_id: str
    agent: Guardian
    model_id: str | None
    served_via: ServedVia
    prompt_tokens: int
    completion_tokens: int
    step_index: int = 0


@dataclass(frozen=True, slots=True)
class InterventionTokenRow:
    """The exact value contract that POPULATES server's ``intervention_log``
    columns (server owns the table + the write — seam #7). Keyed by
    ``record_id`` / ``correlation_id`` so server joins it to its row."""

    record_id: str
    correlation_id: str
    step_index: int
    agent: str  # Guardian value
    model_id: str | None
    served_via: str  # ServedVia value
    tokens_in: int
    tokens_out: int


class TokenCounter:
    """Thread-safe per-process accumulator.

    One instance per governance process; each guardian node calls
    :meth:`record` (or :meth:`record_router_call`) after every
    ShieldModelRouter-mediated LLM call. ``record_router_call`` pulls
    ``model_id`` / ``served_via`` straight from the router so cost hook #1
    (tokens) and cost hook #2 (model/served_via) share ONE source of truth.
    """

    def __init__(self) -> None:
        self._samples: list[LLMUsageSample] = []
        self._lock = Lock()

    def record(self, sample: LLMUsageSample) -> None:
        with self._lock:
            self._samples.append(sample)

    def record_router_call(
        self,
        *,
        record_id: str,
        correlation_id: str,
        agent: Guardian,
        router: object,
        role: str,
        prompt_tokens: int,
        completion_tokens: int,
        step_index: int = 0,
    ) -> LLMUsageSample:
        """Attribute one LLM call, resolving model/served_via via the router.

        ``router`` is a :class:`ShieldModelRouter` (duck-typed to avoid a hard
        import cycle); it must expose ``model_id(role)`` and
        ``served_via(role)`` — the cost-hook-#2 single source of truth.
        """
        model_id = str(router.model_id(role))  # type: ignore[attr-defined]
        served_via = router.served_via(role)  # type: ignore[attr-defined]
        if not isinstance(served_via, ServedVia):
            served_via = ServedVia(str(served_via))
        sample = LLMUsageSample(
            record_id=record_id,
            correlation_id=correlation_id,
            agent=agent,
            model_id=model_id,
            served_via=served_via,
            prompt_tokens=max(0, prompt_tokens),
            completion_tokens=max(0, completion_tokens),
            step_index=step_index,
        )
        self.record(sample)
        return sample

    def samples_for(self, record_id: str) -> list[LLMUsageSample]:
        with self._lock:
            return [s for s in self._samples if s.record_id == record_id]

    def totals_for(self, record_id: str) -> tuple[int, int]:
        """(prompt_tokens, completion_tokens) summed for one record."""
        with self._lock:
            pin = sum(s.prompt_tokens for s in self._samples if s.record_id == record_id)
            pout = sum(s.completion_tokens for s in self._samples if s.record_id == record_id)
        return pin, pout

    def intervention_rows(self) -> list[InterventionTokenRow]:
        """The population contract for server's ``intervention_log`` sink.

        One row per LLM call (server aggregates/joins by
        ``record_id``/``correlation_id``). governance never writes these — it
        hands them to server, which owns the table + the write (seam #7).
        """
        with self._lock:
            return [
                InterventionTokenRow(
                    record_id=s.record_id,
                    correlation_id=s.correlation_id,
                    step_index=s.step_index,
                    agent=s.agent.value,
                    model_id=s.model_id,
                    served_via=s.served_via.value,
                    tokens_in=s.prompt_tokens,
                    tokens_out=s.completion_tokens,
                )
                for s in self._samples
            ]

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()
