"""One JSON line per model API call -> ``worlds/<level>/logs/api_calls/SR<n>.jsonl``.

Feeds the run debugger (tools/run_debugger). ``agent_decisions.log`` only times the
decide call; wake-up, ask, chat and vision calls left no timing trace at all.

    with api_call_log.track("decide", agent_id, provider, model):
        raw = ...provider call...          # provider code may call note_usage(in, out)

Line: {"timestamp", "sim_run", "agent_id", "purpose", "provider", "model",
       "ms", "ok", "error", "input_tokens", "output_tokens"}
The timestamp is when the call STARTED. One file per run; when a new run's file is created,
only the newest KEEP_RUNS files are kept (older runs are deleted).
Logging never breaks a call: a write failure is reported once and then ignored.
"""
from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import sim_run

logger = logging.getLogger("AgentRuntime")

KEEP_RUNS = 50

_dir: Path | None = None
_lock = threading.Lock()
_write_failed = False
_current: contextvars.ContextVar[dict | None] = contextvars.ContextVar("api_call", default=None)
_agent: contextvars.ContextVar[str | None] = contextvars.ContextVar("api_call_agent", default=None)


def set_dir(logs_dir: Path) -> None:
    """Calls are written to ``<logs_dir>/api_calls/SR<n>.jsonl``."""
    global _dir
    _dir = Path(logs_dir) / "api_calls"


def note_usage(input_tokens, output_tokens) -> None:
    """Attach token counts to the call being tracked on this thread (no-op otherwise)."""
    rec = _current.get()
    if rec is not None:
        rec["input_tokens"] = input_tokens
        rec["output_tokens"] = output_tokens


@contextmanager
def for_agent(agent_id: str):
    """Name the agent for calls made inside this block that cannot name it (vision)."""
    token = _agent.set(agent_id)
    try:
        yield
    finally:
        _agent.reset(token)


@contextmanager
def track(purpose: str, agent_id: str | None, provider: str, model: str | None):
    rec = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sim_run": sim_run.active_run(),
        "agent_id": agent_id or _agent.get(),
        "purpose": purpose,
        "provider": provider,
        "model": model,
        "ok": True,
        "error": None,
        "input_tokens": None,
        "output_tokens": None,
    }
    token = _current.set(rec)
    t0 = time.monotonic()
    try:
        yield rec
    except BaseException as e:
        rec["ok"] = False
        rec["error"] = f"{type(e).__name__}: {e}"[:300]
        raise
    finally:
        rec["ms"] = round((time.monotonic() - t0) * 1000, 1)
        _current.reset(token)
        _write(rec)


def _run_num(path: Path) -> int:
    try:
        return int(path.stem[2:])
    except ValueError:
        return -1


def _prune() -> None:
    """Delete the oldest run files beyond KEEP_RUNS (by SR number)."""
    files = sorted(_dir.glob("SR*.jsonl"), key=_run_num)
    for old in files[:-KEEP_RUNS]:
        old.unlink(missing_ok=True)
        logger.info("api_calls: deleted %s (keeping the newest %d runs)", old.name, KEEP_RUNS)


def _write(rec: dict) -> None:
    global _write_failed
    if _dir is None:
        return
    path = _dir / f'{rec["sim_run"]}.jsonl'
    try:
        with _lock:
            new = not path.exists()
            _dir.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            if new:
                _prune()
    except OSError as e:
        if not _write_failed:
            _write_failed = True
            logger.error("API call log unavailable at %s: %s — API calls not logged", path, e)
