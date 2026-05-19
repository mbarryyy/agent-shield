"""MinIO-backed ObjectStore (REWRITE of Elydora adapters/minio.ts).

Stores the full signed record envelope + EAR receipt exactly as Elydora stores
them in R2 (`{org}/{agent}/{op}` / `.../receipts/{op}`). The MinIO SDK is
synchronous, so calls are offloaded to a worker thread. Network glue is
`# pragma: no cover` (integration job only).
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import anyio.to_thread

if TYPE_CHECKING:  # pragma: no cover
    from minio import Minio


class MinioObjectStore:  # pragma: no cover - integration-only network glue
    def __init__(self, client: Minio, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @classmethod
    async def connect(
        cls,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool,
        bucket: str,
    ) -> MinioObjectStore:
        from minio import Minio

        client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)

        def _ensure() -> None:
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)

        await anyio.to_thread.run_sync(_ensure)
        return cls(client, bucket)

    async def put(self, key: str, body: bytes, content_type: str) -> None:
        def _put() -> None:
            self._client.put_object(
                self._bucket,
                key,
                io.BytesIO(body),
                length=len(body),
                content_type=content_type,
            )

        await anyio.to_thread.run_sync(_put)

    async def get(self, key: str) -> bytes | None:
        def _get() -> bytes | None:
            try:
                resp = self._client.get_object(self._bucket, key)
            except Exception:
                return None
            try:
                return resp.read()
            finally:
                resp.close()
                resp.release_conn()

        return await anyio.to_thread.run_sync(_get)
