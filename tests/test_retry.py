import pytest

from apm_connectors.tools._retry import with_retry


def test_succeeds_immediately_without_retrying() -> None:
    calls = []

    @with_retry(attempts=3, base_delay_seconds=0)
    def flaky() -> str:
        calls.append(1)
        return "ok"

    assert flaky() == "ok"
    assert len(calls) == 1


def test_retries_transient_error_then_succeeds() -> None:
    calls = []

    @with_retry(attempts=3, base_delay_seconds=0)
    def flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("simulated transient network failure")
        return "ok"

    assert flaky() == "ok"
    assert len(calls) == 3


def test_raises_after_exhausting_attempts() -> None:
    calls = []

    @with_retry(attempts=3, base_delay_seconds=0)
    def always_fails() -> str:
        calls.append(1)
        raise ConnectionAbortedError("simulated: connection aborted by host")

    with pytest.raises(ConnectionAbortedError):
        always_fails()

    assert len(calls) == 3


def test_does_not_retry_non_transient_errors() -> None:
    calls = []

    @with_retry(attempts=3, base_delay_seconds=0)
    def bad_input() -> str:
        calls.append(1)
        raise ValueError("this is a real bug, not a network blip")

    with pytest.raises(ValueError):
        bad_input()

    assert len(calls) == 1  # never retried
