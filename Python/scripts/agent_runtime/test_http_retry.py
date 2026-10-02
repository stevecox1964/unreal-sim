"""Offline tests for http_retry.post — the 429 / connection-drop retry (#113, SR66_P).

SR66_P lost both wake-up calls to one OpenRouter 429 at run start because
nothing retried. No network: ``requests`` and ``time.sleep`` are stubbed. Run:
    .venv\\Scripts\\python.exe scripts\\agent_runtime\\test_http_retry.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # Python/
sys.path.insert(0, str(ROOT))

import requests                                  # noqa: E402
from agent_runtime import http_retry             # noqa: E402


def check(label, cond):
    if not cond:
        print(f"FAIL: {label}")
        sys.exit(1)
    print(f"ok: {label}")


class _Resp:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}


class _FakeRequests:
    """Plays back a script of responses / exceptions, one per post()."""
    ConnectionError = requests.ConnectionError

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def post(self, url, **kwargs):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _run(script):
    fake = _FakeRequests(script)
    sleeps = []
    saved_req, saved_sleep = http_retry.requests, http_retry.time.sleep
    http_retry.requests, http_retry.time.sleep = fake, sleeps.append
    try:
        try:
            result = http_retry.post("https://example.test", json={})
        except Exception as e:      # noqa: BLE001 — the test inspects it
            result = e
    finally:
        http_retry.requests, http_retry.time.sleep = saved_req, saved_sleep
    return result, fake.calls, sleeps


def test_success_is_one_call():
    result, calls, sleeps = _run([_Resp(200)])
    check("a 200 returns at once", result.status_code == 200 and calls == 1 and not sleeps)


def test_429_then_200_retries():
    result, calls, sleeps = _run([_Resp(429), _Resp(200)])
    check("a 429 is retried and the 200 is returned", result.status_code == 200 and calls == 2)
    check("it waited the default 3 s plus at most 2 s jitter", 3.0 <= sleeps[0] <= 5.0)


def test_retry_after_is_honoured_and_capped():
    _, _, sleeps = _run([_Resp(429, {"Retry-After": "7"}), _Resp(200)])
    check("Retry-After 7 s -> waits 7..9 s", 7.0 <= sleeps[0] <= 9.0)
    _, _, sleeps = _run([_Resp(503, {"Retry-After": "600"}), _Resp(200)])
    check("Retry-After 600 s is capped at 15 s (+ jitter)", 15.0 <= sleeps[0] <= 17.0)


def test_gives_up_after_three_tries():
    result, calls, sleeps = _run([_Resp(429), _Resp(429), _Resp(429)])
    check("three 429s: the last response is returned for the caller to raise",
          result.status_code == 429 and calls == 3 and len(sleeps) == 2)


def test_client_errors_are_not_retried():
    result, calls, _ = _run([_Resp(400)])
    check("a 400 is the caller's problem, not retried", result.status_code == 400 and calls == 1)
    result, calls, _ = _run([_Resp(401)])
    check("a 401 (bad key) is not retried", result.status_code == 401 and calls == 1)


def test_connection_errors():
    result, calls, _ = _run([requests.ConnectionError("reset"), _Resp(200)])
    check("a dropped connection is retried", result.status_code == 200 and calls == 2)
    result, calls, _ = _run([requests.exceptions.SSLError("ssl")] * 3)
    check("three SSL errors re-raise the last one",
          isinstance(result, requests.exceptions.SSLError) and calls == 3)


def test_read_timeout_is_not_retried():
    result, calls, _ = _run([requests.ReadTimeout("slow")])
    check("a read timeout re-raises at once (it already cost the full timeout)",
          isinstance(result, requests.ReadTimeout) and calls == 1)


def main():
    test_success_is_one_call()
    test_429_then_200_retries()
    test_retry_after_is_honoured_and_capped()
    test_gives_up_after_three_tries()
    test_client_errors_are_not_retried()
    test_connection_errors()
    test_read_timeout_is_not_retried()
    print("\nAll http-retry checks passed.")


if __name__ == "__main__":
    main()
