import asyncio
import time
from collections import deque
from contextlib import asynccontextmanager
from logger import setup_logger

logger = setup_logger(__name__)


class AsyncRateLimiter:
    """
    Async-safe rate limiter using sliding window approach.
    Enforces a maximum number of requests per time window for coroutines.
    """

    def __init__(self, max_requests: int = 7, time_window: float = 1.0):
        """
        Initialize async rate limiter.

        Args:
            max_requests: Maximum number of requests allowed in the time window
            time_window: Time window in seconds
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self._timestamps = deque()
        self._lock = asyncio.Lock()  # For async task synchronization

    async def acquire(self):
        """
        Acquire a request slot. Waits asynchronously until a slot is available.
        Async-safe for coroutines.
        """
        async with self._lock:
            now = time.time()

            # Remove timestamps older than the time window
            while self._timestamps and self._timestamps[0] < now - self.time_window:
                self._timestamps.popleft()

            # If we're at the limit, wait until the oldest timestamp expires
            if len(self._timestamps) >= self.max_requests:
                oldest_timestamp = self._timestamps[0]
                wait_time = (oldest_timestamp + self.time_window) - now
                if wait_time > 0:
                    logger.debug(
                        f"Rate limit reached. Waiting {wait_time:.3f}s before allowing request"
                    )
                    await asyncio.sleep(wait_time)  # Non-blocking async sleep
                    # Update now after sleep
                    now = time.time()
                    # Clean up expired timestamps again after sleep
                    while (
                        self._timestamps
                        and self._timestamps[0] < now - self.time_window
                    ):
                        self._timestamps.popleft()

            # Record this request timestamp
            self._timestamps.append(now)

    @asynccontextmanager
    async def limit(self):
        """
        Async context manager for rate limiting.
        Usage:
            async with rate_limiter.limit():
                # make async API call
        """
        await self.acquire()
        try:
            yield
        finally:
            # Timestamp already recorded in acquire()
            pass


# Global async rate limiter instance for AmoCRM API
async_amo_crm_rate_limiter = AsyncRateLimiter(max_requests=7, time_window=1.0)
