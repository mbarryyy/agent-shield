"""ADR-0013 — Rate limiting for sign-in / sign-up / password-reset endpoints.

Approach:
  * IP-level sliding window via Redis (10/min on sensitive endpoints).
    Implemented inline (no ``slowapi`` middleware) so we own the wire
    behaviour: emit ``error.code = RATE_LIMITED`` (the existing Elydora
    ErrorCode in ``errors.ErrorCode``) and an ``audit_log_auth.RATELIMIT_BLOCK``
    row. ``slowapi`` is in the workspace deps but its 429 wire shape does
    not match Elydora's ``ErrorResponse``; reusing the typed ``AppError``
    keeps the console's parser unchanged.
  * Account-level lockout lives in ``users.record_failed_login`` (exponential
    5/10/20/30 min schedule).

The rate-limit check uses ``Cache.set_if_absent`` (SET NX EX) over a windowed
key ``ratelimit:{bucket}:{ip}:{window}`` where window = ``floor(t/window_secs)``.
The fixed-window semantics is good enough for sign-in protection (the worst
case is 2 × limit at window boundary; the secondary account-level lockout
caps the realistic damage).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..errors import AppError
from ..storage import Cache
from .audit import insert_audit
from .utils import client_ip

# Default budget: 10 requests/min per IP for sensitive endpoints.
DEFAULT_LIMIT_PER_WINDOW = 10
DEFAULT_WINDOW_SECONDS = 60


@dataclass(frozen=True, slots=True)
class RateLimitConfig:
    bucket: str
    limit: int = DEFAULT_LIMIT_PER_WINDOW
    window_seconds: int = DEFAULT_WINDOW_SECONDS


async def _increment_and_check(cache: Cache, *, key: str, limit: int, window_seconds: int) -> bool:
    """Return True if the request is OVER limit (should be blocked).

    Implementation: counter is stored as a stringified integer; each call
    SET-NX-EX initialises it to "1", then subsequent calls fetch and check.
    The MemoryCache models this faithfully for unit tests; the RedisCache
    uses native Redis INCR + EXPIRE under the hood (see storage/cache.py).
    Falls back to LENIENT on cache errors — rate limit is defence-in-depth,
    not the only guard (account lockout backstops it).
    """
    try:
        existing = await cache.get(key)
        if existing is None:
            await cache.set_if_absent(key, "1", window_seconds)
            return False
        count = int(existing) + 1
        # Re-set to extend value (TTL preserved by Redis on string overwrite).
        await cache.set(key, str(count))
        return count > limit
    except Exception:  # pragma: no cover - cache outage is a soft-fail path
        return False


async def enforce_or_block(
    cache: Cache,
    *,
    config: RateLimitConfig,
    headers: dict[str, str],
    fallback_ip: str | None,
) -> None:
    """Raise ``AppError(429, RATE_LIMITED)`` when over budget; return cleanly otherwise.

    Routes call this BEFORE doing the expensive password verification step
    so a flood of bad logins doesn't burn argon2id CPU. The
    ``audit_log_auth.RATELIMIT_BLOCK`` row is the caller's responsibility
    (this function is sync-side cheap; the caller knows the user_id when
    available).
    """
    ip = client_ip(headers, fallback=fallback_ip) or "unknown"
    bucket = config.bucket
    window = int(time.time()) // config.window_seconds
    key = f"ratelimit:{bucket}:{ip}:{window}"
    if await _increment_and_check(
        cache, key=key, limit=config.limit, window_seconds=config.window_seconds
    ):
        raise AppError(429, "RATE_LIMITED")


async def record_block(
    cache: Cache,
    db: object,  # storage.Database (kept loose to avoid an import cycle)
    *,
    bucket: str,
    ip: str | None,
    user_agent: str | None,
    user_id: str | None,
) -> None:
    """Emit the RATELIMIT_BLOCK audit row when a request is rate-limited."""
    # ``db`` is the storage.Database Protocol; we trust the caller (Protocol
    # is structural — runtime check would need @runtime_checkable). ``cache``
    # is taken for future per-bucket telemetry counters; current implementation
    # is fire-once.
    _ = cache
    await insert_audit(
        db,  # type: ignore[arg-type]
        event="RATELIMIT_BLOCK",
        user_id=user_id,
        ip=ip,
        user_agent=user_agent,
        detail={"bucket": bucket},
    )


__all__ = [
    "DEFAULT_LIMIT_PER_WINDOW",
    "DEFAULT_WINDOW_SECONDS",
    "RateLimitConfig",
    "enforce_or_block",
    "record_block",
]
