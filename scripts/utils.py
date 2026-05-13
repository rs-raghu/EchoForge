"""
utils.py

Shared utilities for the EchoForge pipeline.
"""

import time
import functools



from logger import get_logger
log = get_logger(__name__)

def retry(
    max_attempts: int = 3,
    delay: float = 5.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    is_retryable=None,
):
    """
    Decorator that retries a function on failure with exponential backoff.

    Args:
        max_attempts : Total number of attempts (first try + N-1 retries).
        delay        : Seconds to wait before the first retry.
        backoff      : Multiplier applied to the wait time after each retry.
                       With delay=5 and backoff=2: waits 5s, 10s, 20s, ...
        exceptions   : Tuple of exception types to catch and potentially retry.
                       Exceptions NOT in this tuple propagate immediately.
        is_retryable : Optional callable(exception) -> bool.
                       When provided, an exception is only retried if this
                       returns True.  Use it to skip retries for permanent
                       failures that retrying can never fix — e.g. a
                       geo-blocked video, a 403 Forbidden, a missing file.
                       If None, all caught exceptions are retried.

    Usage:
        @retry(max_attempts=3, delay=10, backoff=2)
        def fetch_something():
            ...

        # With a retryability guard:
        def _not_permanent(e):
            return "404" not in str(e)

        @retry(max_attempts=3, delay=5, is_retryable=_not_permanent)
        def fetch_with_guard():
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            wait = delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    # Permanent failure — don't retry regardless of attempt count
                    if is_retryable is not None and not is_retryable(exc):
                        raise

                    # Final attempt — re-raise so the caller sees the real error
                    if attempt == max_attempts:
                        log.info(
                            f"❌ [{func.__name__}] All {max_attempts} attempts "
                            f"exhausted. Last error: {exc}"
                        )
                        raise

                    log.info(
                        f"⚠️  [{func.__name__}] Attempt {attempt}/{max_attempts} "
                        f"failed: {exc}"
                    )
                    log.info(f"   Retrying in {wait:.0f}s...")
                    time.sleep(wait)
                    wait *= backoff

        return wrapper
    return decorator