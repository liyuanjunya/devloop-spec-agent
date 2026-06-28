"""Tests for the strict sub-agent retry wrapper.

Per v7 plan: 5 attempts, exponential backoff [2, 5, 15, 30, 60]s,
halt-and-loud-error on final failure — NEVER silently skip.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable

import pytest

from devloop.llm.retry import (
    DEFAULT_BACKOFF_S,
    RetryAttempt,
    SubAgentFailedError,
    retry_with_backoff,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _FlakyCall:
    """Async callable that fails N times then succeeds with ``success_value``."""

    def __init__(
        self,
        fail_times: int,
        *,
        exc: Exception | None = None,
        success_value: object = "OK",
    ) -> None:
        self.fail_times = fail_times
        self.exc = exc or RuntimeError("boom")
        self.success_value = success_value
        self.calls = 0

    async def __call__(self) -> object:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return self.success_value


class _ResultCall:
    """Async callable returning values from an iterator on each call."""

    def __init__(self, values: list[object]) -> None:
        self.values = list(values)
        self.calls = 0

    async def __call__(self) -> object:
        self.calls += 1
        return self.values.pop(0)


@pytest.fixture(autouse=True)
def _patch_asyncio_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace asyncio.sleep with a record-only no-op so tests run instantly.

    The returned list captures every sleep duration in order, letting tests
    assert on the exact backoff schedule without ever wall-clock waiting.
    """
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("devloop.llm.retry.asyncio.sleep", fake_sleep)
    return sleeps


# ---------------------------------------------------------------------------
# 1. Success on the first attempt — no retries
# ---------------------------------------------------------------------------


async def test_success_on_first_attempt(_patch_asyncio_sleep: list[float]) -> None:
    call = _FlakyCall(fail_times=0, success_value="hello")
    result = await retry_with_backoff(call, max_attempts=5)
    assert result == "hello"
    assert call.calls == 1, "first-attempt success must not re-invoke"
    assert _patch_asyncio_sleep == [], "no sleeps on first-try success"


# ---------------------------------------------------------------------------
# 2. Success on the second attempt after one failure
# ---------------------------------------------------------------------------


async def test_success_on_second_attempt_after_one_failure(
    _patch_asyncio_sleep: list[float],
) -> None:
    call = _FlakyCall(fail_times=1, success_value=42)
    result = await retry_with_backoff(call, max_attempts=5)
    assert result == 42
    assert call.calls == 2
    # Exactly one sleep — the wait before attempt 2 — using the first backoff entry.
    assert _patch_asyncio_sleep == [float(DEFAULT_BACKOFF_S[0])]


# ---------------------------------------------------------------------------
# 3. Halt after max attempts — raises SubAgentFailedError
# ---------------------------------------------------------------------------


async def test_halt_after_max_attempts(_patch_asyncio_sleep: list[float]) -> None:
    call = _FlakyCall(fail_times=99, exc=ValueError("always fails"))
    with pytest.raises(SubAgentFailedError) as exc_info:
        await retry_with_backoff(call, max_attempts=5)

    err = exc_info.value
    assert call.calls == 5, "exactly max_attempts invocations"
    assert len(err.attempts) == 5
    assert isinstance(err.original_exception, ValueError)
    assert str(err.original_exception) == "always fails"
    # The error message must clearly state failure — no silent skip wording.
    assert "FAILED after 5 attempts" in str(err)


# ---------------------------------------------------------------------------
# 4. Backoff actually waits the v7 schedule
# ---------------------------------------------------------------------------


async def test_backoff_actually_waits(_patch_asyncio_sleep: list[float]) -> None:
    """All 5 attempts fail → 4 sleeps using DEFAULT_BACKOFF_S[0..3]."""
    call = _FlakyCall(fail_times=99)
    with pytest.raises(SubAgentFailedError):
        await retry_with_backoff(call, max_attempts=5)

    # 5 attempts → 4 sleeps between them (no sleep before attempt 1).
    expected = [float(s) for s in DEFAULT_BACKOFF_S[:4]]
    assert _patch_asyncio_sleep == expected, (
        f"backoff schedule deviated: expected {expected}, got {_patch_asyncio_sleep}"
    )
    # And the v7-mandated schedule is what we claim.
    assert expected == [2.0, 5.0, 15.0, 30.0]


# ---------------------------------------------------------------------------
# 5. Non-retryable exceptions bubble immediately
# ---------------------------------------------------------------------------


async def test_retryable_exceptions_filter(
    _patch_asyncio_sleep: list[float],
) -> None:
    call = _FlakyCall(fail_times=99, exc=KeyError("nope"))
    # Only ValueError is retryable; KeyError must propagate untouched.
    with pytest.raises(KeyError):
        await retry_with_backoff(
            call,
            max_attempts=5,
            retryable_exceptions=(ValueError,),
        )
    assert call.calls == 1, "non-retryable exception must NOT retry"
    assert _patch_asyncio_sleep == [], "no sleeps for non-retryable failure"


# ---------------------------------------------------------------------------
# 6. is_retryable_result callback — falsy result triggers retry
# ---------------------------------------------------------------------------


async def test_is_retryable_result_callback(
    _patch_asyncio_sleep: list[float],
) -> None:
    # First two returns are "falsy" per our policy; third is the real answer.
    call = _ResultCall(values=["", "", "GOOD"])
    result = await retry_with_backoff(
        call,
        max_attempts=5,
        is_retryable_result=lambda v: not v,  # empty string ⇒ retry
    )
    assert result == "GOOD"
    assert call.calls == 3
    assert _patch_asyncio_sleep == [2.0, 5.0]


async def test_is_retryable_result_exhaustion_halts_loud(
    _patch_asyncio_sleep: list[float],
) -> None:
    call = _ResultCall(values=[None] * 5)
    with pytest.raises(SubAgentFailedError) as exc_info:
        await retry_with_backoff(
            call,
            max_attempts=5,
            is_retryable_result=lambda v: v is None,
        )
    # Final exception is None because no exception was raised — only bad results.
    assert exc_info.value.original_exception is None
    assert len(exc_info.value.attempts) == 5
    # Each recorded attempt should carry the retryable_result reason.
    for a in exc_info.value.attempts:
        assert a.error_type == "retryable_result"


# ---------------------------------------------------------------------------
# 7. SubAgentFailedError includes all attempt details in its message
# ---------------------------------------------------------------------------


async def test_subagent_failed_error_includes_all_attempts(
    _patch_asyncio_sleep: list[float],
) -> None:
    call = _FlakyCall(fail_times=99, exc=RuntimeError("kaboom"))
    with pytest.raises(SubAgentFailedError) as exc_info:
        await retry_with_backoff(call, max_attempts=5)

    msg = str(exc_info.value)
    # Header line
    assert "FAILED after 5 attempts" in msg
    # Each of the 5 attempts must appear in the formatted message.
    for i in range(1, 6):
        assert f"Attempt {i}: RuntimeError: kaboom" in msg, (
            f"missing attempt {i} in error message: {msg!r}"
        )
    # Final exception line
    assert "Final exception: RuntimeError: kaboom" in msg
    # And RetryAttempt entries themselves
    assert len(exc_info.value.attempts) == 5
    for idx, attempt in enumerate(exc_info.value.attempts):
        assert isinstance(attempt, RetryAttempt)
        assert attempt.attempt_index == idx
        assert attempt.error_type == "RuntimeError"
        assert attempt.error_message == "kaboom"


# ---------------------------------------------------------------------------
# 8. max_attempts=1 means no retry — single attempt only
# ---------------------------------------------------------------------------


async def test_max_attempts_1_means_no_retry(
    _patch_asyncio_sleep: list[float],
) -> None:
    call = _FlakyCall(fail_times=99, exc=RuntimeError("once"))
    with pytest.raises(SubAgentFailedError) as exc_info:
        await retry_with_backoff(call, max_attempts=1)

    assert call.calls == 1, "max_attempts=1 must invoke exactly once"
    assert _patch_asyncio_sleep == [], "max_attempts=1 must not sleep"
    assert len(exc_info.value.attempts) == 1


async def test_max_attempts_1_success_returns_value(
    _patch_asyncio_sleep: list[float],
) -> None:
    call = _FlakyCall(fail_times=0, success_value="single-shot OK")
    result = await retry_with_backoff(call, max_attempts=1)
    assert result == "single-shot OK"
    assert call.calls == 1


async def test_max_attempts_0_raises_value_error() -> None:
    """Guard: zero attempts is a programming error, not a silent no-op."""
    with pytest.raises(ValueError):
        await retry_with_backoff(_FlakyCall(fail_times=0), max_attempts=0)


# ---------------------------------------------------------------------------
# 9. Custom backoff list is honoured verbatim
# ---------------------------------------------------------------------------


async def test_custom_backoff_list_used(
    _patch_asyncio_sleep: list[float],
) -> None:
    call = _FlakyCall(fail_times=99)
    with pytest.raises(SubAgentFailedError):
        await retry_with_backoff(
            call,
            max_attempts=4,
            backoff_s=[0.1, 0.2, 0.3],
        )
    # 4 attempts → 3 sleeps using the 3 provided values verbatim.
    assert _patch_asyncio_sleep == [0.1, 0.2, 0.3]


# ---------------------------------------------------------------------------
# 10. Short backoff list extends by repeating the last value
# ---------------------------------------------------------------------------


async def test_short_backoff_list_extends_with_last_value(
    _patch_asyncio_sleep: list[float],
) -> None:
    """backoff=[1, 2] with max_attempts=5 → sleeps [1, 2, 2, 2]."""
    call = _FlakyCall(fail_times=99)
    with pytest.raises(SubAgentFailedError):
        await retry_with_backoff(
            call,
            max_attempts=5,
            backoff_s=[1.0, 2.0],
        )
    # 5 attempts → 4 sleeps; first two from the list, then last value repeats.
    assert _patch_asyncio_sleep == [1.0, 2.0, 2.0, 2.0], (
        f"short backoff list must extend with last value, got {_patch_asyncio_sleep}"
    )


# ---------------------------------------------------------------------------
# 11. Operation name appears in logs
# ---------------------------------------------------------------------------


async def test_operation_name_in_logs(
    caplog: pytest.LogCaptureFixture,
    _patch_asyncio_sleep: list[float],
) -> None:
    call = _FlakyCall(fail_times=99, exc=RuntimeError("logged"))
    with caplog.at_level(logging.WARNING, logger="devloop.llm.retry"):
        with pytest.raises(SubAgentFailedError):
            await retry_with_backoff(
                call,
                max_attempts=3,
                backoff_s=[0.01, 0.02],
                operation_name="spec_writer_call",
            )

    # The operation name must surface in retry warnings and the final error log.
    op_messages = [
        rec.getMessage() for rec in caplog.records if "spec_writer_call" in rec.getMessage()
    ]
    assert op_messages, (
        f"operation name 'spec_writer_call' missing from logs: "
        f"{[r.getMessage() for r in caplog.records]}"
    )
    # Loud-fail log must mention "NOT silently skipping" so ops can grep for it.
    final = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert final, "final exhaustion must log at ERROR level"
    assert any("NOT silently skipping" in r.getMessage() for r in final), (
        "the loud-error sentinel string must appear at ERROR level"
    )


async def test_operation_name_default_in_logs(
    caplog: pytest.LogCaptureFixture,
    _patch_asyncio_sleep: list[float],
) -> None:
    call = _FlakyCall(fail_times=99)
    with caplog.at_level(logging.WARNING, logger="devloop.llm.retry"):
        with pytest.raises(SubAgentFailedError):
            await retry_with_backoff(
                call,
                max_attempts=2,
                backoff_s=[0.01],
            )
    # The default operation name should appear somewhere.
    assert any("sub-agent call" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# 12. asyncio.sleep is actually invoked (verifies patching wiring)
# ---------------------------------------------------------------------------


async def test_async_sleep_called(_patch_asyncio_sleep: list[float]) -> None:
    """Each non-first attempt must await asyncio.sleep — caught via monkeypatch."""
    call = _FlakyCall(fail_times=2, success_value="done")
    result = await retry_with_backoff(
        call,
        max_attempts=5,
        backoff_s=[0.5, 1.5, 4.0],
    )
    assert result == "done"
    # Two sleeps for the two retries before the third (successful) attempt.
    assert _patch_asyncio_sleep == [0.5, 1.5]


async def test_async_sleep_uses_custom_implementation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wrapper must call asyncio.sleep — not time.sleep or a busy loop."""
    sleep_calls: list[float] = []
    original_sleep = asyncio.sleep

    async def spy(seconds: float) -> None:
        sleep_calls.append(seconds)
        # Yield control just like the real coroutine, but without waiting.
        await original_sleep(0)

    monkeypatch.setattr("devloop.llm.retry.asyncio.sleep", spy)
    call = _FlakyCall(fail_times=1, success_value="ok")
    result = await retry_with_backoff(call, max_attempts=3, backoff_s=[0.001])
    assert result == "ok"
    assert sleep_calls == [0.001]


# ---------------------------------------------------------------------------
# Extra: each call gets a FRESH awaitable (no awaiting an already-consumed one)
# ---------------------------------------------------------------------------


async def test_call_factory_pattern_each_attempt_is_fresh_awaitable(
    _patch_asyncio_sleep: list[float],
) -> None:
    """Regression guard: passing a coroutine-producing factory works across retries.

    If the wrapper accidentally awaited the same coroutine object twice it
    would raise ``RuntimeError: cannot reuse already awaited coroutine``.
    """
    call_count = {"n": 0}

    async def factory() -> Awaitable[str]:
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise TimeoutError("slow upstream")
        return "done"

    result = await retry_with_backoff(factory, max_attempts=5, backoff_s=[0.0, 0.0])
    assert result == "done"
    assert call_count["n"] == 3
