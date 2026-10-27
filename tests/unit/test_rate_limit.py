"""Tests for the distributed Redis rate limiter."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from redis.exceptions import RedisError

from src.core.rate_limit import RATE_LIMIT_LUA, RateLimiter


@pytest.fixture
def rate_limiter() -> RateLimiter:
    """Return a RateLimiter with a mocked Redis connection."""
    with patch("src.core.rate_limit.ConnectionPool.from_url"):
        with patch("src.core.rate_limit.Redis") as mock_redis_class:
            mock_redis = AsyncMock()
            mock_redis_class.return_value = mock_redis
            limiter = RateLimiter("redis://dummy")
            # Attach the mock explicitly for tests
            limiter.redis = mock_redis
            return limiter


@pytest.mark.asyncio
async def test_rate_limiter_allows_request(rate_limiter: RateLimiter) -> None:
    """Verify that the rate limiter allows a request when under the limit."""
    rate_limiter.redis.eval.return_value = 1  # type: ignore[attr-defined]

    allowed = await rate_limiter.is_allowed("test_key", 100, 60)

    assert allowed is True
    rate_limiter.redis.eval.assert_called_once_with(  # type: ignore[attr-defined]
        RATE_LIMIT_LUA, 1, "test_key", 100, 60
    )


@pytest.mark.asyncio
async def test_rate_limiter_blocks_request(rate_limiter: RateLimiter) -> None:
    """Verify that the rate limiter blocks a request when over the limit."""
    rate_limiter.redis.eval.return_value = 0  # type: ignore[attr-defined]

    allowed = await rate_limiter.is_allowed("test_key", 100, 60)

    assert allowed is False


@pytest.mark.asyncio
async def test_rate_limiter_fail_open_on_redis_error(rate_limiter: RateLimiter) -> None:
    """Verify the fail-open policy when Redis is unavailable."""
    rate_limiter.redis.eval.side_effect = RedisError("Connection refused")  # type: ignore[attr-defined]

    # Even though Redis failed, it should allow the request (fail-open)
    allowed = await rate_limiter.is_allowed("test_key", 100, 60)

    assert allowed is True
