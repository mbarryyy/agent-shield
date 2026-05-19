"""Storage adapters: protocols + in-memory fakes (unit) + asyncpg/MinIO/Redis
(integration). W1 (server-builder) — replaces the W0 stub."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from .cache import RedisCache
from .interfaces import Cache, Database, ObjectStore, Tx
from .memory import MemoryCache, MemoryDatabase, MemoryObjectStore
from .objectstore import MinioObjectStore
from .postgres import PostgresDatabase

__all__ = [
    "Cache",
    "Database",
    "ObjectStore",
    "Tx",
    "Storage",
    "MemoryCache",
    "MemoryDatabase",
    "MemoryObjectStore",
    "RedisCache",
    "MinioObjectStore",
    "PostgresDatabase",
    "build_storage",
    "build_memory_storage",
]


@dataclass(slots=True)
class Storage:
    db: Database
    objects: ObjectStore
    cache: Cache


async def build_storage(settings: Settings) -> Storage:  # pragma: no cover - infra wiring
    """Wire the real asyncpg/MinIO/Redis adapters (integration / runtime)."""
    db = await PostgresDatabase.connect(settings.database_url)
    objects = await MinioObjectStore.connect(
        settings.minio_endpoint,
        settings.minio_access_key,
        settings.minio_secret_key,
        settings.minio_secure,
        settings.minio_bucket,
    )
    cache = await RedisCache.connect(settings.redis_url)
    return Storage(db=db, objects=objects, cache=cache)


def build_memory_storage() -> Storage:
    """In-memory storage (unit tests, and a docker-free demo of the API surface)."""
    return Storage(db=MemoryDatabase(), objects=MemoryObjectStore(), cache=MemoryCache())
