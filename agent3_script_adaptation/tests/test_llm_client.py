import pytest

from src import llm_client


class RetryableError(Exception):
    pass


class PermanentError(Exception):
    pass


def _fake_sleep(delays):
    def sleep(seconds):
        delays.append(seconds)
    return sleep


# ---- _with_retries ----

def test_with_retries_returns_immediately_on_first_success():
    delays = []
    calls = []

    def call():
        calls.append(1)
        return "ok"

    result = llm_client._with_retries(call, (RetryableError,), sleep=_fake_sleep(delays))

    assert result == "ok"
    assert len(calls) == 1
    assert delays == []


def test_with_retries_retries_on_a_retryable_exception_then_succeeds():
    delays = []
    attempts = {"n": 0}

    def call():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RetryableError("transient")
        return "recovered"

    result = llm_client._with_retries(call, (RetryableError,), sleep=_fake_sleep(delays))

    assert result == "recovered"
    assert attempts["n"] == 2
    assert delays == [1.0]  # one retry at base_delay * 2**0


def test_with_retries_uses_exponential_backoff_across_multiple_retries():
    delays = []

    def call():
        raise RetryableError("still failing")

    with pytest.raises(RetryableError):
        llm_client._with_retries(call, (RetryableError,), max_attempts=4, base_delay=1.0, sleep=_fake_sleep(delays))

    assert delays == [1.0, 2.0, 4.0]  # 3 retries before the 4th attempt gives up


def test_with_retries_gives_up_after_max_attempts_and_raises_the_last_error():
    calls = []

    def call():
        calls.append(1)
        raise RetryableError(f"attempt {len(calls)}")

    with pytest.raises(RetryableError, match="attempt 3"):
        llm_client._with_retries(call, (RetryableError,), max_attempts=3, sleep=_fake_sleep([]))

    assert len(calls) == 3


def test_with_retries_does_not_retry_a_non_retryable_exception():
    calls = []
    delays = []

    def call():
        calls.append(1)
        raise PermanentError("bad api key")

    with pytest.raises(PermanentError):
        llm_client._with_retries(call, (RetryableError,), sleep=_fake_sleep(delays))

    assert len(calls) == 1  # never retried
    assert delays == []


# ---- _generate_via_claude_cli's retry wiring (subprocess-based) ----

def test_claude_cli_retries_once_on_failure_then_succeeds(monkeypatch):
    calls = []

    class FailThenSucceed:
        def __call__(self, cmd, capture_output, text):
            calls.append(cmd)
            if len(calls) == 1:
                return type("R", (), {"returncode": 1, "stdout": "", "stderr": "temporary glitch"})()
            return type("R", (), {"returncode": 0, "stdout": "the answer", "stderr": ""})()

    monkeypatch.setattr(llm_client.subprocess, "run", FailThenSucceed())
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)

    result = llm_client._generate_via_claude_cli("system", "user", None)

    assert result == "the answer"
    assert len(calls) == 2


def test_claude_cli_gives_up_after_two_failures_with_the_clis_stderr(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text):
        calls.append(cmd)
        return type("R", (), {"returncode": 1, "stdout": "", "stderr": "still broken"})()

    monkeypatch.setattr(llm_client.subprocess, "run", fake_run)
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)

    with pytest.raises(RuntimeError, match="still broken"):
        llm_client._generate_via_claude_cli("system", "user", None)

    assert len(calls) == 2  # max_attempts=2 for the CLI path, not more
