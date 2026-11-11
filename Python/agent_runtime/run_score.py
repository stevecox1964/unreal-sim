"""Run scorecard (#119): one line of numbers per APC per run.

Code counts, no model judges. The numbers are read from the two files every run
already writes — ``logs/sim_runner.log`` (truncated per run) and
``logs/api_calls/<run>.jsonl`` — and appended to ``logs/scorecard.jsonl``, so a
later run (or Claude on a loop) can see whether a change made things better.

A number that was not measured is ``None``, never 0 (rule 12).

Score a log by hand:  ``uv run python -m agent_runtime.run_score <logs_dir>``
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path

_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),(\d{3}) \w+ \[([^\]]*)\] (.*)$")
_AGENT = re.compile(r"^\[(\w+)\] (.*)$")
_YAW = re.compile(r"yaw (\d+)")
_STOP = re.compile(r"=== SIMULATION STOP === ticks=(\d+) elapsed=([\d.]+)s")


def _turn(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _new_row() -> dict:
    return {
        "decisions": 0, "actions": {},
        "seconds_to_inside": None, "decisions_to_inside": None, "inside_at": None,
        "place_steps": 0, "place_step_m": 0.0, "steps_refused": 0,
        "named_place_walks": 0,
        "way_in_looks": 0, "eyes_saw_way_in": 0, "engine_saw_way_in": 0,
        "eyes_engine_gap_deg_median": None,
        "eyes_reused": 0, "eye_calls": 0, "eye_calls_failed": 0,
        "lost_answers": 0, "tasks_completed": [], "seconds_to_task": None,
        "api_calls": 0, "api_failed": 0, "cost_usd": 0.0,
    }


def score_run(log_path: Path, api_jsonl: Path | None = None) -> list[dict]:
    """One scorecard row per APC seen in ``log_path``."""
    rows: dict[str, dict] = {}
    gaps: dict[str, list[float]] = {}
    run_id = None
    first = None
    ticks = elapsed = None
    for raw in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _LINE.match(raw)
        if not m:
            continue
        when = datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S").timestamp() + int(m[2]) / 1000.0
        first = first if first is not None else when
        run_id = run_id or m[3]
        text = m[4]
        stop = _STOP.search(text)
        if stop:
            ticks, elapsed = int(stop[1]), float(stop[2])
            continue
        a = _AGENT.match(text)
        if not a:
            continue
        row = rows.setdefault(a[1], _new_row())
        msg = a[2]
        since = round(when - first, 1)
        if " decided: " in msg:
            row["decisions"] += 1
            action = msg.split(" decided: ", 1)[1].split(" ", 1)[0]
            row["actions"][action] = row["actions"].get(action, 0) + 1
        elif msg.startswith("body reads INSIDE") and row["seconds_to_inside"] is None:
            row["seconds_to_inside"] = since
            row["decisions_to_inside"] = row["decisions"]
            row["inside_at"] = msg[len("body reads INSIDE at "):]
        elif msg.startswith("place step "):
            if "no room" in msg or "staying put" in msg:
                row["steps_refused"] += 1
            else:
                step = re.search(r": ([\d.]+) m \(", msg)
                if step:
                    row["place_steps"] += 1
                    row["place_step_m"] = round(row["place_step_m"] + float(step[1]), 1)
        elif msg.startswith("approaching place "):
            row["named_place_walks"] += 1
        elif msg.startswith("ways in at "):
            eyes, _, engine = msg.partition("| ENGINE (log only):")
            eyes_yaws = [float(y) for y in _YAW.findall(eyes)]
            engine_yaws = [float(y) for y in _YAW.findall(engine)]
            row["way_in_looks"] += 1
            row["eyes_saw_way_in"] += bool(eyes_yaws)
            row["engine_saw_way_in"] += bool(engine_yaws)
            if eyes_yaws and engine_yaws:
                gaps.setdefault(a[1], []).append(
                    min(_turn(e, g) for e in eyes_yaws for g in engine_yaws))
        elif msg.startswith("eyes: reused"):
            row["eyes_reused"] += 1
        elif "returned invalid JSON" in msg:
            row["lost_answers"] += 1
        elif msg.startswith("agenda task ") and " completed" in msg:
            row["tasks_completed"].append(msg.split(" ")[2])
            if row["seconds_to_task"] is None:
                row["seconds_to_task"] = since

    if api_jsonl is not None and api_jsonl.exists():
        for raw in api_jsonl.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            row = rows.get(rec.get("agent_id"))
            if row is None:
                continue
            row["api_calls"] += 1
            row["api_failed"] += not rec.get("ok")
            if rec.get("purpose") == "vision":
                row["eye_calls"] += 1
                row["eye_calls_failed"] += not rec.get("ok")
            row["cost_usd"] = round(row["cost_usd"] + float(rec.get("cost_usd") or 0.0), 4)

    out = []
    for agent_id, row in sorted(rows.items()):
        if gaps.get(agent_id):
            row["eyes_engine_gap_deg_median"] = statistics.median(gaps[agent_id])
        out.append({"run": run_id, "agent": agent_id, "ticks": ticks,
                    "elapsed_s": elapsed, **row})
    return out


def write_scorecard(logs_dir: Path) -> list[dict]:
    """Score the run in ``logs_dir`` and append its rows to ``scorecard.jsonl``."""
    logs_dir = Path(logs_dir)
    log_path = logs_dir / "sim_runner.log"
    rows = score_run(log_path)
    if rows and rows[0]["run"]:
        rows = score_run(log_path, logs_dir / "api_calls" / f"{rows[0]['run']}.jsonl")
    with open(logs_dir / "scorecard.jsonl", "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return rows


if __name__ == "__main__":
    for scored in write_scorecard(Path(sys.argv[1])):
        print(json.dumps(scored))
