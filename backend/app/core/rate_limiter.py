import time
from collections import defaultdict
from typing import Dict, List, Optional
from fastapi import HTTPException, Request, status

from backend.app.core.config import settings


class InMemoryRateLimiter:
    """
    Sliding-window in-memory rate limiter per client IP and endpoint group.
    Provides protection against brute-force and resource exhaustion
    without external dependencies (like Redis).
    """

    def __init__(self):
        # Store: {bucket_key: [timestamp1, timestamp2, ...]}
        self._records: Dict[str, List[float]] = defaultdict(list)

    def _cleanup_old_records(self, bucket_key: str, window_seconds: float, now: float) -> List[float]:
        threshold = now - window_seconds
        records = [ts for ts in self._records[bucket_key] if ts > threshold]
        self._records[bucket_key] = records
        return records

    def is_rate_limited(
        self,
        key: str,
        max_requests: int,
        window_seconds: float = 60.0
    ) -> bool:
        """
        Returns True if the rate limit for this key has been exceeded.
        """
        if not getattr(settings, "RATE_LIMIT_ENABLED", True):
            return False

        now = time.time()
        records = self._cleanup_old_records(key, window_seconds, now)

        if len(records) >= max_requests:
            return True

        self._records[key].append(now)
        return False

    def check(
        self,
        request: Request,
        category: str = "general",
        max_requests: Optional[int] = None,
        window_seconds: float = 60.0
    ) -> None:
        """
        FastAPI dependency / helper to enforce rate limits.
        Raises HTTPException(429) if limit exceeded.
        """
        # Determine client identifier (IP or forwarded IP)
        forwarded = request.headers.get("x-forwarded-for")
        client_ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")

        # Determine limit by category
        if max_requests is None:
            if category == "auth":
                max_requests = getattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", 15)
            elif category == "indexing":
                max_requests = getattr(settings, "RATE_LIMIT_INDEXING_PER_MINUTE", 10)
            elif category == "assistant":
                max_requests = getattr(settings, "RATE_LIMIT_ASSISTANT_PER_MINUTE", 30)
            else:
                max_requests = getattr(settings, "RATE_LIMIT_DEFAULT_PER_MINUTE", 200)

        bucket_key = f"{client_ip}:{category}"
        if self.is_rate_limited(bucket_key, max_requests, window_seconds):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded for {category}. Please wait before making more requests.",
                headers={"Retry-After": str(int(window_seconds))}
            )

    def reset(self) -> None:
        """Resets all rate limit records (useful for testing)."""
        self._records.clear()


rate_limiter = InMemoryRateLimiter()
