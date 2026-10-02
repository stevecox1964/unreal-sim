"""Retry a model HTTP call the provider turned away for a moment.

A 429 (rate limit), a 5xx, or a dropped connection is the provider's problem,
not a decision: code retries, the model never sees it. SR66_P lost both wake-up
calls to one 429 at run start because nothing retried. The wait honours
``Retry-After`` (capped) plus a little jitter, so two APCs that collided once do
not collide again on the retry.
"""
from __future__ import annotations

import logging
import random
import time

import requests

logger = logging.getLogger("AgentRuntime")

RETRY_STATUS = {429, 500, 502, 503, 504}
ATTEMPTS = 3
_DEFAULT_WAIT_S = 3.0
_MAX_WAIT_S = 15.0


def _retry_after(response) -> float:
    try:
        return min(float(response.headers.get("Retry-After", _DEFAULT_WAIT_S)), _MAX_WAIT_S)
    except (TypeError, ValueError):
        return _DEFAULT_WAIT_S


def post(url: str, **kwargs):
    """``requests.post`` with up to ``ATTEMPTS`` tries on 429 / 5xx / connection
    errors. Returns the last response (callers keep their own error handling);
    re-raises the connection error when the last try also fails. A read timeout
    is not retried — it already cost the full timeout once."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            response = requests.post(url, **kwargs)
        except requests.ConnectionError as e:   # includes SSLError, connection reset
            if attempt == ATTEMPTS:
                raise
            wait, why = _DEFAULT_WAIT_S, type(e).__name__
        else:
            if response.status_code not in RETRY_STATUS or attempt == ATTEMPTS:
                return response
            wait, why = _retry_after(response), f"HTTP {response.status_code}"
        wait += random.uniform(0.0, 2.0)
        logger.warning("model call failed (%s) — retry %d/%d in %.1f s",
                       why, attempt, ATTEMPTS - 1, wait)
        time.sleep(wait)
    raise RuntimeError("unreachable")
