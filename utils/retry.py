from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger("knou.retry")

F = TypeVar("F", bound=Callable[..., Any])

# Exceptions that indicate a transient API error worth retrying
_RETRYABLE: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)

try:
    import anthropic
    _RETRYABLE = _RETRYABLE + (
        anthropic.APIConnectionError,
        anthropic.RateLimitError,
        anthropic.APITimeoutError,
        anthropic.InternalServerError,
    )
except ImportError:
    pass

try:
    import openai
    _RETRYABLE = _RETRYABLE + (
        openai.APIConnectionError,
        openai.RateLimitError,
        openai.APITimeoutError,
        openai.InternalServerError,
    )
except ImportError:
    pass


def _log_retry(retry_state: RetryCallState) -> None:
    logger.warning(
        "Retrying %s (attempt %d) after error: %s",
        retry_state.fn.__name__ if retry_state.fn else "?",
        retry_state.attempt_number,
        retry_state.outcome.exception() if retry_state.outcome else "unknown",
    )


def llm_retry(
    max_attempts: int = 5,
    min_wait: float = 2.0,
    max_wait: float = 60.0,
) -> Callable[[F], F]:
    """Decorator: retry LLM API calls with exponential back-off."""
    return retry(
        reraise=True,
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type(_RETRYABLE),
        before_sleep=_log_retry,
    )
