"""Strict retry wrapper for LLM gateway calls.

Per v7: 5 attempts, exponential backoff, halt-and-loud-error on final failure.
NEVER silently skip — if all retries fail, raise a descriptive exception.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# v7 schedule: pause BEFORE attempts 2..5 for 2s, 5s, 15s, 30s, 60s respectively.
# (The 5th value is reused for any further attempts if max_attempts is increased.)
DEFAULT_BACKOFF_S: list[float] = [2, 5, 15, 30, 60]


@dataclass(slots=True, frozen=True)
class RetryAttempt:
    """One recorded retry attempt — what failed and how long we waited beforehand."""

    attempt_index: int
    error_type: str
    error_message: str
    waited_s: float


@dataclass(slots=True)
class RetryResult:
    """Diagnostic record of a (possibly successful) retry loop."""

    success: bool
    value: object = None
    attempts: list[RetryAttempt] = field(default_factory=list)
    total_elapsed_s: float = 0.0


class SubAgentFailedError(Exception):
    """Raised when a sub-agent call fails after all retries.

    Per v7 ``no silent failures`` policy this is the LOUD, halting signal that
    callers can rely on: either ``retry_with_backoff`` returns a value or it
    raises this exception. There is no third "silently returned None" path.
    """

    def __init__(
        self,
        attempts: list[RetryAttempt],
        original_exception: Exception | None = None,
    ):
        self.attempts = attempts
        self.original_exception = original_exception
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        lines = [f"Sub-agent call FAILED after {len(self.attempts)} attempts."]
        for i, a in enumerate(self.attempts):
            lines.append(
                f"  Attempt {i + 1}: {a.error_type}: {a.error_message[:200]} "
                f"(waited {a.waited_s}s before)"
            )
        if self.original_exception:
            lines.append(
                f"  Final exception: {type(self.original_exception).__name__}: "
                f"{self.original_exception!s}"
            )
        return "\n".join(lines)


async def retry_with_backoff(
    call: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 5,
    backoff_s: list[float] | None = None,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    is_retryable_result: Callable[[T], bool] | None = None,
    operation_name: str = "sub-agent call",
) -> T:
    """Retry an async call with explicit backoff.

    Raises :class:`SubAgentFailedError` if all attempts fail. NEVER returns
    silently on failure — calling code can rely on either getting a result or
    an exception.

    Parameters
    ----------
    call : the awaitable factory (``call()`` returns a new awaitable each time)
    max_attempts : maximum total attempts including the first
    backoff_s : seconds to wait BEFORE each attempt after the first.
                If shorter than ``max_attempts - 1``, the last value is repeated.
    retryable_exceptions : which exception types trigger a retry.
                Non-matching exceptions propagate immediately without retry.
    is_retryable_result : optional callback; if it returns True for a result,
                treat that result as a failure and retry.
    operation_name : short string included in log messages.
    """
    if backoff_s is None:
        backoff_s = DEFAULT_BACKOFF_S
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1 (got {max_attempts})")

    attempts: list[RetryAttempt] = []
    last_exception: Exception | None = None
    start = time.monotonic()

    for attempt_idx in range(max_attempts):
        wait_s = 0.0
        if attempt_idx > 0:
            # backoff_s[i] is the wait BEFORE attempt index (i+1). If we run out
            # of explicit values, reuse the last one — guards against callers
            # passing a short list with a high max_attempts.
            wait_s = float(backoff_s[min(attempt_idx - 1, len(backoff_s) - 1)])
            logger.warning(
                "%s attempt %d/%d failed; sleeping %ds before retry",
                operation_name,
                attempt_idx,
                max_attempts,
                wait_s,
            )
            await asyncio.sleep(wait_s)
        try:
            result = await call()
            if is_retryable_result is not None and is_retryable_result(result):
                attempts.append(
                    RetryAttempt(
                        attempt_index=attempt_idx,
                        error_type="retryable_result",
                        error_message=(
                            f"is_retryable_result returned True for "
                            f"{type(result).__name__}"
                        ),
                        waited_s=wait_s,
                    )
                )
                continue
            return result
        except retryable_exceptions as e:
            last_exception = e
            attempts.append(
                RetryAttempt(
                    attempt_index=attempt_idx,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    waited_s=wait_s,
                )
            )
            logger.warning(
                "%s attempt %d/%d raised %s: %s",
                operation_name,
                attempt_idx + 1,
                max_attempts,
                type(e).__name__,
                e,
            )

    # All retries exhausted — halt and loud. NEVER return None silently.
    elapsed = time.monotonic() - start
    logger.error(
        "%s FAILED after %d attempts (elapsed %.1fs). "
        "NOT silently skipping. Raising SubAgentFailedError.",
        operation_name,
        max_attempts,
        elapsed,
    )
    raise SubAgentFailedError(attempts, last_exception)
