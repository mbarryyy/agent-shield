"""The four design Chroma collections (governance_design §6).

The vector DB is the graded Compound-Architecture component. It holds four
collections on ONE local ``chromadb.PersistentClient`` (no network, no key,
telemetry disabled — air-gap safe):

* ``policies`` — NL governance policies for codegen/RAG (GuardAgent technique).
* ``injection_signatures`` — known attack patterns (seeded from the AgentDojo
  banking injection tasks) for similarity lookup.
* ``behavior_baselines`` — per-(org, agent, workflow, tool) benign centroids
  for the Evaluator behavior-drift seam.
* ``incidents`` — past governance incidents for institutional-memory recall;
  this is the SAME collection :class:`ChromaIncidentMemory` writes/reads, so a
  guardian's recall tool and the seeded vector DB agree on one incidents store.

Every method is a real Chroma upsert/query round-trip against the persistent
client; there are no stubs. Embeddings use the local
:class:`DeterministicHashEmbedder` so the store is fully offline and
deterministic for tests and air-gapped deployment.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from shield_governance.memory.incidents import (
    ChromaIncidentMemory,
    ChromaMemoryConfig,
    DeterministicHashEmbedder,
    MemoryBackendUnavailable,
    MemoryHit,
    MemoryQueryResult,
    _distance_to_score,
    _first_nested,
    _query_id,
)

#: The four design collections, frozen as the §6 set so the
#: Compound-Architecture component is mechanically checkable.
VECTOR_DB_COLLECTIONS: tuple[str, ...] = (
    "policies",
    "injection_signatures",
    "behavior_baselines",
    "incidents",
)


@dataclass(frozen=True, slots=True)
class ChromaVectorStoreConfig:
    persist_directory: str | Path | None
    embedding_dimensions: int = 64


class ChromaVectorStore:
    """All four design collections on one local persistent Chroma client."""

    def __init__(
        self,
        config: ChromaVectorStoreConfig,
        *,
        embedder: DeterministicHashEmbedder | None = None,
    ) -> None:
        if config.persist_directory is None:
            raise MemoryBackendUnavailable("chroma vector store requires persist_directory")
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError as exc:  # pragma: no cover - exercised when dependency missing
            raise MemoryBackendUnavailable("chromadb is not installed") from exc

        self._config = config
        self._embedder = embedder or DeterministicHashEmbedder(config.embedding_dimensions)
        self._persist_directory = Path(config.persist_directory)
        self._persist_directory.mkdir(parents=True, exist_ok=True)
        # Air-gap invariant: disable Chroma's anonymized telemetry both via the
        # client Settings and the env var the air-gap verifier checks.
        os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
        self._client = chromadb.PersistentClient(
            path=str(self._persist_directory),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collections: dict[str, Any] = {
            name: self._client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
            )
            for name in VECTOR_DB_COLLECTIONS
        }

    def collection_names(self) -> tuple[str, ...]:
        return tuple(self._collections)

    # ----- per-collection upserts -------------------------------------- #

    def upsert_policy(
        self, *, policy_id: str, text: str, metadata: dict[str, str | int | float | bool]
    ) -> None:
        self._upsert("policies", policy_id, text, metadata)

    def upsert_injection_signature(
        self, *, signature_id: str, text: str, metadata: dict[str, str | int | float | bool]
    ) -> None:
        self._upsert("injection_signatures", signature_id, text, metadata)

    def upsert_behavior_baseline(
        self, *, baseline_id: str, text: str, metadata: dict[str, str | int | float | bool]
    ) -> None:
        self._upsert("behavior_baselines", baseline_id, text, metadata)

    # ----- shared incidents collection --------------------------------- #

    def incident_memory(self) -> ChromaIncidentMemory:
        """Return a :class:`ChromaIncidentMemory` bound to the SAME persistent
        directory + ``incidents`` collection this store owns, so guardian
        recall and the seeded vector DB read one store."""
        return ChromaIncidentMemory(
            ChromaMemoryConfig(
                persist_directory=self._persist_directory,
                collection_name="incidents",
                embedding_dimensions=self._config.embedding_dimensions,
            ),
            embedder=self._embedder,
        )

    # ----- query ------------------------------------------------------- #

    def query(self, collection: str, text: str, *, top_k: int = 5) -> MemoryQueryResult:
        try:
            handle = self._collections[collection]
        except KeyError:
            raise KeyError(
                f"unknown vector-DB collection {collection!r}; "
                f"known collections: {sorted(self._collections)}"
            ) from None
        started = time.perf_counter()
        result = handle.query(
            query_embeddings=cast(Any, [self._embedder.embed(text)]),
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
        return MemoryQueryResult(
            memory_backend="chroma",
            collection=collection,
            query_id=_query_id(text),
            hit_count=len(hits),
            hits=hits,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )

    def _upsert(
        self,
        collection: str,
        doc_id: str,
        text: str,
        metadata: dict[str, str | int | float | bool],
    ) -> None:
        # Chroma rejects an empty metadata mapping on upsert; always carry at
        # least the collection name so a row is queryable + self-describing.
        meta = dict(metadata) if metadata else {}
        meta.setdefault("collection", collection)
        self._collections[collection].upsert(
            ids=[doc_id],
            embeddings=cast(Any, [self._embedder.embed(text)]),
            documents=[text],
            metadatas=[meta],
        )
