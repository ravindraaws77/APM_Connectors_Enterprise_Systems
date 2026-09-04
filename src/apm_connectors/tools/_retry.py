"""Retry-with-backoff for the real (network-calling) tool clients.

Transient connection failures talking to Google/Microsoft's APIs happen
in practice — observed directly: a `ConnectionAbortedError` from a live
Gmail API call, mid-response, caused by something on the local network
path (antivirus, a brief drop) rather than anything wrong with the
request itself.

Deliberately for READ methods only. A write/action call (send_email,
insert_event, update_range) must never be retried automatically: if the
connection drops after the server already processed the request but
before the success response arrives, a blind retry would send/create/
write a second time. That risk is unacceptable for this project's whole
premise (no unintended external side effects) — a write that fails
transiently should surface as a failure for a human to look at, not
silently retry into a duplicate.
"""

from __future__ import annotations

import functools
import time
from typing import Callable, TypeVar

T = TypeVar("T")

# Connection-level failures worth retrying: the request never got a
# response at all. OSError alone covers this -- ConnectionError,
# ConnectionAbortedError/ConnectionResetError, TimeoutError, and
# socket.timeout are all OSError subclasses in Python's standard
# exception hierarchy, as is requests.exceptions.ConnectionError
# (RequestException extends IOError, i.e. OSError). Deliberately does
# NOT include HTTP error status codes (e.g. 429/5xx) here -- those come
# back as exceptions from the specific client libraries
# (googleapiclient.errors.HttpError, requests.HTTPError) with response
# details a caller may want to inspect, and are out of scope for this
# first pass.
TRANSIENT_EXCEPTIONS = (OSError,)


def with_retry(attempts: int = 3, base_delay_seconds: float = 0.5) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator for a read-only network call: retry up to `attempts`
    times on a transient connection-level error, with linear backoff
    (base_delay_seconds, 2x, 3x, ...). Re-raises the last error once
    attempts are exhausted. Never retries a non-transient exception
    (e.g. an auth/scope error) -- retrying won't fix those.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: object, **kwargs: object) -> T:
            last_error: Exception | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)  # type: ignore[return-value]
                except TRANSIENT_EXCEPTIONS as exc:
                    last_error = exc
                    if attempt < attempts:
                        time.sleep(base_delay_seconds * attempt)
            assert last_error is not None
            raise last_error

        return wrapper

    return decorator
