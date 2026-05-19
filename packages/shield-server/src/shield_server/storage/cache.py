"""Redis-backed Cache (REWRITE of Elydora adapters/redis-cache.ts).

Backs nonce replay-prevention (`nonce:{org}:{nonce}` SET NX EX = op TTL) and the
forward-looking `chain:{agent}:latest` hint. Network glue is `# pragma: no
cover` (integration job only). Channel-2 Redis Streams land at W2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from redis.asyncio import Redis


class RedisCache:  # pragma: no cover - integration-only network glue
    def __init__(self, client: Redis) -> None:
        self._client = client

    @classmethod
    async def connect(cls, url: str) -> RedisCache:
        from redis.asyncio import Redis

        return cls(Redis.from_url(url, decode_responses=True))

    async def close(self) -> None:
        await self._client.aclose()

    async def get(self, key: str) -> str | None:
        value = await self._client.get(key)
        return value if value is None else str(value)

    async def set_if_absent(self, key: str, value: str, ttl_seconds: int) -> bool:
        return bool(await self._client.set(key, value, nx=True, ex=ttl_seconds))

    async def set(self, key: str, value: str) -> None:
        await self._client.set(key, value)
