"""Distributed HTTP rate limiting using Redis."""

from __future__ import annotations

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import RedisError

from src.core.config import get_settings
from src.core.logging import get_logger

logger = get_logger(__name__)

# Atomic Lua script for rate limiting
# KEYS[1] = rate limit key
# ARGV[1] = max requests
# ARGV[2] = window seconds
# Returns 1 if allowed, 0 if rate limited.
RATE_LIMIT_LUA = """
local current
current = redis.call("incr", KEYS[1])
if current == 1 then
    redis.call("expire", KEYS[1], ARGV[2])
end
if current > tonumber(ARGV[1]) then
    return 0
end
return 1
"""


class RateLimiter:
    """Distributed rate limiter using Redis with a fail-open policy."""

    def __init__(self, redis_url: str):
        self._pool = ConnectionPool.from_url(redis_url, decode_responses=True)
        self.redis = Redis(connection_pool=self._pool)
        self._script_sha: str | None = None

    async def is_allowed(self, key: str, max_requests: int, window: int) -> bool:
        """Check if the request is allowed.

        If Redis is unavailable, this defaults to a FAIL-OPEN policy (returns True).
        This means rate limiting is temporarily unavailable during outages and
        should not be relied upon as a strict security boundary.
        """
        try:
            # We use eval directly or register_script.
            # Using eval avoids needing to track the script object across async contexts.
            result = await self.redis.eval(RATE_LIMIT_LUA, 1, key, max_requests, window)
            return bool(result)
        except RedisError as e:
            logger.error(
                "rate_limiter_redis_error",
                error=str(e),
                key=key,
                policy="fail-open",
            )
            return True

    async def close(self) -> None:
        """Close the Redis connection pool."""
        await self.redis.aclose()


# Global singleton
_limiter: RateLimiter | None = None


def init_rate_limiter(redis_url: str) -> None:
    """Initialize the global rate limiter."""
    global _limiter
    _limiter = RateLimiter(redis_url)


async def close_rate_limiter() -> None:
    """Close the global rate limiter."""
    global _limiter
    if _limiter:
        await _limiter.close()
        _limiter = None


async def get_rate_limiter() -> RateLimiter:
    """Dependency to get the rate limiter instance."""
    if not _limiter:
        settings = get_settings()
        return RateLimiter(settings.redis_url)
    return _limiter
