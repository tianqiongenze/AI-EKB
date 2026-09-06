from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    reset_at: float


class TokenBucketRateLimiter:
    def __init__(self, tokens_per_minute: int) -> None:
        if tokens_per_minute <= 0:
            raise ValueError("tokens_per_minute must be positive")
        self.capacity = tokens_per_minute
        self.tokens = float(tokens_per_minute)
        self.refill_rate_per_sec = tokens_per_minute / 60.0
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def allow(self, tokens: int = 1) -> RateLimitResult:
        if tokens <= 0:
            raise ValueError("tokens must be positive")
        with self._lock:
            now = time.monotonic()
            elapsed = max(0.0, now - self.last_refill)
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate_per_sec)
            self.last_refill = now
            if self.tokens >= tokens:
                self.tokens -= tokens
                remaining = int(self.tokens)
                reset_at = now + (self.capacity - self.tokens) / self.refill_rate_per_sec
                return RateLimitResult(True, remaining, reset_at)
            remaining = int(self.tokens)
            reset_at = now + (tokens - self.tokens) / self.refill_rate_per_sec
            return RateLimitResult(False, remaining, reset_at)


class TenantRegionRateLimiter:
    def __init__(self, default_tokens_per_minute: int) -> None:
        self._default = default_tokens_per_minute
        self._limiters: dict[tuple[str, str], TokenBucketRateLimiter] = {}
        self._lock = threading.Lock()

    def allow(
        self,
        tenant_id: str,
        region_id: str,
        tokens: int = 1,
        override_tokens_per_minute: int | None = None,
    ) -> RateLimitResult:
        key = (tenant_id, region_id)
        with self._lock:
            limiter = self._limiters.get(key)
            target_capacity = override_tokens_per_minute or self._default
            if limiter is None or limiter.capacity != target_capacity:
                limiter = TokenBucketRateLimiter(target_capacity)
                self._limiters[key] = limiter
        return limiter.allow(tokens=tokens)
