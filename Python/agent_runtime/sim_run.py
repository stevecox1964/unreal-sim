"""Per-world sim run counter (``SR<n>_<mode>``).

Every simulation run gets a monotonic id (first run = ``SR1_P``) so that
observation screenshots, the decision log, and general logs are all attributable
to a single run when debugging. The tag ends in the sim mode — ``_P`` for Play,
``_S`` for Survey — so a run's purpose shows in every file name and log line.
Runs from before the suffix (e.g. ``SR45``) keep their bare tag. One counter
serves both modes. The counter is **per-world** — each level counts
independently — and persists in a git-ignored ``sim_run.json`` next to the
world's other runtime state (``Python/worlds/<level>/sim_run.json``).

No Unreal, no network: pure counter I/O, fully offline-testable.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

_FILE = "sim_run.json"

# Sim mode (#102) -> the letter on the run tag.
MODE_LETTERS = {"play": "P", "survey": "S"}
_NUMBER_RE = re.compile(r"^SR(\d+)")


def _path(world_dir: Path) -> Path:
    return Path(world_dir) / _FILE


def format_run(n: int, mode: str | None = None) -> str:
    """Format a run number as its SR tag: ``(42, "play")`` -> ``'SR42_P'``,
    ``(42, "survey")`` -> ``'SR42_S'``; no/unknown mode -> ``'SR42'``."""
    letter = MODE_LETTERS.get(str(mode or "").strip().lower())
    return f"SR{n}_{letter}" if letter else f"SR{n}"


def run_number(tag: str) -> int:
    """The number in a run tag: ``'SR66_P'`` -> 66, ``'SR45'`` -> 45; -1 if none."""
    m = _NUMBER_RE.match(str(tag or ""))
    return int(m.group(1)) if m else -1


def current_number(world_dir: Path) -> int:
    """The last allocated run number for this world (``0`` if none/corrupt).

    Example: ``current_number(Path('Python/worlds/MCP_World'))`` -> ``7``.
    """
    p = _path(world_dir)
    if not p.exists():
        return 0
    try:
        return int(json.loads(p.read_text(encoding="utf-8")).get("run", 0))
    except (ValueError, TypeError, OSError, json.JSONDecodeError):
        return 0


def current_run(world_dir: Path) -> str:
    """The current SR tag for this world (``'SR0'`` when nothing allocated yet)."""
    mode = None
    p = _path(world_dir)
    if p.exists():
        try:
            mode = json.loads(p.read_text(encoding="utf-8")).get("mode")
        except (ValueError, TypeError, OSError, json.JSONDecodeError):
            mode = None
    return format_run(current_number(world_dir), mode)


def allocate_run(world_dir: Path, mode: str | None = None) -> str:
    """Increment and persist the per-world run counter; return the new SR tag.

    The first ever run for a world returns ``'SR1_P'`` in Play mode (``'SR1'``
    with no mode); a missing or corrupt counter file restarts from ``1``.
    Example: ``allocate_run(Path('Python/worlds/MCP_World'), "survey")`` ->
    ``'SR1_S'``.
    """
    world_dir = Path(world_dir)
    world_dir.mkdir(parents=True, exist_ok=True)
    n = current_number(world_dir) + 1
    _path(world_dir).write_text(json.dumps({"run": n, "mode": mode}), encoding="utf-8")
    return format_run(n, mode)


# ── In-process active run (for tagging general logs) ─────────────────────────────

_active_run: str = "SR0"


def set_active_run(tag: str) -> None:
    """Set the in-process active run tag; blank/``None`` is ignored (stays SR0)."""
    global _active_run
    if not tag:
        return
    _active_run = tag


def active_run() -> str:
    """The in-process active run tag (``'SR0'`` before any run allocates one)."""
    return _active_run


class SimRunFilter(logging.Filter):
    """Logging filter that stamps every record with the current SR tag.

    Attach to log handlers so the format string can reference ``%(sim_run)s``;
    records emitted before a run allocates are stamped ``SR0``.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.sim_run = active_run()
        return True
