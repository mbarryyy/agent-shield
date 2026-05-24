"""Incident memory backends for guardian tools.

The deliverable backend is a local persistent Chroma collection. The local
fallback exists only for explicitly labelled degraded/development paths.
"""

from __future__ import annotations

import hashlib
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from shield_sdk.schema import Decision, ShieldActionRecord

MemoryBackendName = Literal["chroma", "local_fallback"]


class MemoryBackendUnavailable(RuntimeError):
    """Raised when a requested memory backend cannot be constructed."""


@dataclass(frozen=True, slots=True)
class ChromaMemoryConfig:
    persist_directory: str | Path | None
    collection_name: str = "agent_shield_incidents"
    embedding_dimensions: int = 64


@dataclass(frozen=True, slots=True)
class MemoryHit:
    id: str
    score: float
    distance: float
    metadata: dict[str, str | int | float | bool]

    def to_evidence(self) -> dict[str, object]:
        return {
            "id": self.id,
            "score": self.score,
            "distance": self.distance,
        }


@dataclass(frozen=True, slots=True)
class MemoryQueryResult:
    memory_backend: MemoryBackendName
    collection: str
    query_id: str
    hit_count: int
    hits: tuple[MemoryHit, ...]
    latency_ms: float
    missing_reason: str | None = None

    def to_evidence(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "memory_backend": self.memory_backend,
            "collection": self.collection,
            "query_id": self.query_id,
            "hit_count": self.hit_count,
            "top_hits": [hit.to_evidence() for hit in self.hits],
            "latency_ms": self.latency_ms,
        }
        if self.missing_reason:
            payload["missing_reason"] = self.missing_reason
        return payload


class DeterministicHashEmbedder:
    """Small local embedder used to keep Chroma fully offline in tests/dev."""

    def __init__(self, dimensions: int = 64) -> None:
        if dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        self._dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        tokens = _tokens(text)
        vector = [0.0] * self._dimensions
        for token in tokens or ["<empty>"]:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "big") % self._dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[idx] += sign * (1.0 + digest[5] / 255.0)
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            return vector
        return [v / norm for v in vector]


class ChromaIncidentMemory:
    """Local persistent Chroma incident collection used by guardian tools."""

    memory_backend: MemoryBackendName = "chroma"

    def __init__(
        self,
        config: ChromaMemoryConfig,
        *,
        embedder: DeterministicHashEmbedder | None = None,
    ) -> None:
        if config.persist_directory is None:
            raise MemoryBackendUnavailable("chroma memory requires persist_directory")
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError as exc:  # pragma: no cover - exercised when dependency missing
            raise MemoryBackendUnavailable("chromadb is not installed") from exc

        self._config = config
        self._embedder = embedder or DeterministicHashEmbedder(config.embedding_dimensions)
        self._persist_directory = Path(config.persist_directory)
        self._persist_directory.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
        self._client = chromadb.PersistentClient(
            path=str(self._persist_directory),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=config.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def collection_name(self) -> str:
        return self._config.collection_name

    def remember_record(
        self,
        record: ShieldActionRecord,
        *,
        decision: Decision,
        reasons: tuple[str, ...] | list[str],
    ) -> None:
        document = trace_safe_record_text(record)
        self._collection.upsert(
            ids=[record.record_id],
            embeddings=cast(Any, [self._embedder.embed(document)]),
            documents=[document],
            metadatas=[_metadata(record, decision=decision, reasons=tuple(reasons))],
        )

    def query_record(
        self,
        record: ShieldActionRecord,
        *,
        top_k: int = 5,
        tool_name: str | None = None,
        recipient: str | None = None,
    ) -> MemoryQueryResult:
        started = time.perf_counter()
        document = trace_safe_record_text(record, tool_name=tool_name, recipient=recipient)
        result = self._collection.query(
            query_embeddings=cast(Any, [self._embedder.embed(document)]),
            n_results=max(1, int(top_k)),
            include=cast(Any, ["distances", "metadatas"]),
        )
        ids = _first_nested(result.get("ids"))
        distances = [float(value) for value in _first_nested(result.get("distances"))]
        metadatas = _first_nested(result.get("metadatas"))
        hits = tuple(
            MemoryHit(
                id=str(hit_id),
                distance=max(0.0, distance),
                score=_distance_to_score(distance),
                metadata=dict(metadata) if isinstance(metadata, dict) else {},
            )
            for hit_id, distance, metadata in zip(ids, distances, metadatas, strict=False)
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        return MemoryQueryResult(
            memory_backend="chroma",
            collection=self.collection_name,
            query_id=_query_id(document),
            hit_count=len(hits),
            hits=hits,
            latency_ms=latency_ms,
        )


def trace_safe_record_text(
    record: ShieldActionRecord,
    *,
    tool_name: str | None = None,
    recipient: str | None = None,
) -> str:
    args = dict(record.payload.tool_args or {})
    effective_tool = tool_name or record.payload.tool_name or "<unknown>"
    effective_recipient = recipient if recipient is not None else args.get("recipient")
    parts = [
        f"tool:{effective_tool}",
        f"phase:{record.phase.value}",
        f"org:{record.org_id}",
        f"agent:{record.agent_id}",
        f"workflow:{record.workflow_id}",
    ]
    if effective_recipient not in (None, ""):
        parts.append(f"recipient_hash:{_short_hash(str(effective_recipient))}")
    if "amount" in args:
        parts.append(f"amount_bucket:{_amount_bucket(args.get('amount'))}")
    parts.extend(f"arg_key:{key}" for key in sorted(args))
    return " ".join(parts)


def local_fallback_result(
    *,
    collection: str,
    query_text: str,
    matches: list[dict[str, object]],
    latency_ms: float,
    missing_reason: str | None = None,
) -> MemoryQueryResult:
    hits = tuple(
        MemoryHit(
            id=str(match["record_id"]),
            score=1.0,
            distance=0.0,
            metadata={},
        )
        for match in matches
        if "record_id" in match
    )
    return MemoryQueryResult(
        memory_backend="local_fallback",
        collection=collection,
        query_id=_query_id(query_text),
        hit_count=len(hits),
        hits=hits,
        latency_ms=latency_ms,
        missing_reason=missing_reason,
    )


def _metadata(
    record: ShieldActionRecord,
    *,
    decision: Decision,
    reasons: tuple[str, ...],
) -> dict[str, str | int | float | bool]:
    args = dict(record.payload.tool_args or {})
    metadata: dict[str, str | int | float | bool] = {
        "record_id": record.record_id,
        "correlation_id": record.correlation_id,
        "org_id": record.org_id,
        "agent_id": record.agent_id,
        "workflow_id": record.workflow_id,
        "run_id_hash": _short_hash(record.run_id),
        "phase": record.phase.value,
        "tool_name": record.payload.tool_name or "",
        "decision": decision.value,
        "reasons": ",".join(reasons),
    }
    if "recipient" in args:
        metadata["recipient_hash"] = _short_hash(str(args["recipient"]))
    if "amount" in args:
        metadata["amount_bucket"] = _amount_bucket(args.get("amount"))
    return metadata


def _tokens(text: str) -> list[str]:
    return [
        "".join(ch for ch in token.lower() if ch.isalnum() or ch in "_:-") for token in text.split()
    ]


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _query_id(text: str) -> str:
    return _short_hash(text)


def _amount_bucket(value: object) -> str:
    try:
        amount = abs(float(cast(Any, value)))
    except (TypeError, ValueError):
        return "unknown"
    if amount < 100:
        return "lt_100"
    if amount < 1_000:
        return "lt_1000"
    if amount < 10_000:
        return "lt_10000"
    return "gte_10000"


def _distance_to_score(distance: float) -> float:
    return max(0.0, min(1.0, 1.0 / (1.0 + max(0.0, distance))))


def _first_nested(value: object) -> list[Any]:
    if not isinstance(value, list) or not value:
        return []
    first = value[0]
    return first if isinstance(first, list) else []
